from __future__ import annotations

import argparse
import logging
import shutil
from datetime import datetime, timezone
from typing import Optional

import httpx
from playwright.sync_api import sync_playwright

from swiss_pantry.health import off_client, scoring
from swiss_pantry.health.off_client import HealthFacts
from swiss_pantry.matching.categorize import Category, load_categories
from swiss_pantry.pricing.normalize import price_per_unit
from swiss_pantry.scrapers.aldi import AldiScraper
from swiss_pantry.scrapers.denner import DennerScraper
from swiss_pantry.scrapers.lidl import LidlScraper
from swiss_pantry.scrapers.migros import MigrosScraper
from swiss_pantry.storage.db import DB_PATH, get_connection, upsert_products
from swiss_pantry.storage.models import RawProduct, ScoredProduct

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")

# Coop is deliberately excluded: their site sits behind a DataDome CAPTCHA and,
# even after solving it by hand once, kept blocking on IP reputation. We will
# not attempt to automate past that - it needs Coop support to lift the block
# (see conversation), so Coop stays manual/phase-2 for now.
# Spar is excluded too: spar.ch has no online product catalog at all (just
# weekly-flyer marketing content), so there's nothing there to scrape.
SCRAPERS = [MigrosScraper(), AldiScraper(), DennerScraper(), LidlScraper()]


def enrich(raw: RawProduct, category: Category, off_http: httpx.Client, off_cache: dict) -> ScoredProduct:
    unit = price_per_unit(raw.price_chf, raw.package_qty, raw.package_unit)

    facts = None
    if category.fresh_produce:
        # Whole/loose fruit has essentially no OFF coverage (no barcode, no
        # generic "banana" entry worth trusting) - it's unprocessed by
        # definition, so score it as such rather than showing "unrated".
        facts = HealthFacts(nova_group=1, additives_tags=[], saturated_fat_per_100g=0.0)
    elif category.food:
        try:
            if raw.barcode:
                facts = off_client.by_barcode(off_http, raw.barcode)
            if facts is None:
                # No barcode (Aldi/Denner/Lidl) - search OFF by this product's
                # own name, not the generic category term (see search_for_product
                # docstring for why: a shared category-level search made every
                # non-barcode product in a category collapse onto one match).
                # Cache by exact name since the same product can appear at
                # multiple pack sizes within one run.
                if raw.raw_name not in off_cache:
                    off_cache[raw.raw_name] = off_client.search_for_product(
                        off_http, raw.raw_name, category
                    )
                facts = off_cache[raw.raw_name]
        except httpx.HTTPError as e:
            log.warning("OFF lookup failed for %s (%s): %s", raw.raw_name, raw.store, e)

    health_score, health_grade = scoring.score(facts) if category.food else (None, None)

    return ScoredProduct(
        store=raw.store,
        category=raw.category,
        raw_name=raw.raw_name,
        brand=raw.brand,
        price_chf=raw.price_chf,
        package_qty=raw.package_qty,
        package_unit=raw.package_unit,
        price_per_unit=unit,
        url=raw.url,
        barcode=raw.barcode,
        nova_group=facts.nova_group if facts else None,
        additives_tags=facts.additives_tags if facts else None,
        saturated_fat_per_100g=facts.saturated_fat_per_100g if facts else None,
        health_score=health_score,
        health_grade=health_grade,
        scraped_at=datetime.now(timezone.utc),
        store_raw=raw.raw_data,
        off_raw=facts.raw if facts else None,
        off_barcode=facts.off_barcode if facts else None,
    )


# If a store returns nothing this many categories in a row, treat it as the
# store having cut us off rather than as a genuine absence of products, and
# stop asking it. Migros once silently soft-blocked mid-run (page loads, its
# product API just stops answering) and the run quietly produced a fraction
# of the usual data - this makes that loud instead.
CONSECUTIVE_EMPTY_LIMIT = 5


def backup_db() -> None:
    """Snapshot the DB before a run, so a run that goes wrong (a store
    blocking us halfway through) can be rolled back instead of leaving a
    gutted dataset with no way back."""
    if not DB_PATH.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = DB_PATH.with_suffix(f".{stamp}.bak")
    shutil.copy2(DB_PATH, backup_path)
    log.info("Backed up existing DB to %s", backup_path.name)


def run(stores: Optional[list[str]] = None, category_ids: Optional[list[str]] = None) -> None:
    categories = load_categories()
    if category_ids:
        categories = [c for c in categories if c.id in category_ids]
    scrapers = SCRAPERS
    if stores:
        wanted = {s.lower() for s in stores}
        scrapers = [s for s in SCRAPERS if s.store_name.lower() in wanted]

    backup_db()
    conn = get_connection()
    off_cache: dict = {}
    consecutive_empty: dict[str, int] = {s.store_name: 0 for s in scrapers}
    cut_off: set[str] = set()

    with sync_playwright() as pw, httpx.Client() as off_http:
        # headless=False on purpose: Migros's bot-detection blocks plain
        # headless Chromium with a fake "maintenance" page. Aldi works either
        # way, so we just run everything headed for simplicity.
        browser = pw.chromium.launch(headless=False)
        try:
            for category in categories:
                for scraper in scrapers:
                    if scraper.store_name in cut_off:
                        continue
                    log.info("Scraping %s / %s", scraper.store_name, category.id)
                    try:
                        raw_products = scraper.fetch(browser, category)
                    except Exception as e:
                        log.error("Scrape failed for %s / %s: %s", scraper.store_name, category.id, e)
                        continue
                    raw_products = [p for p in raw_products if p.price_chf > 0]
                    log.info("  -> %d matches", len(raw_products))

                    if raw_products:
                        consecutive_empty[scraper.store_name] = 0
                    else:
                        consecutive_empty[scraper.store_name] += 1
                        if consecutive_empty[scraper.store_name] >= CONSECUTIVE_EMPTY_LIMIT:
                            cut_off.add(scraper.store_name)
                            log.error(
                                "%s returned nothing %d categories in a row - assuming it has "
                                "cut us off and skipping it for the rest of this run. Existing "
                                "%s rows are left untouched; re-run for this store later.",
                                scraper.store_name,
                                CONSECUTIVE_EMPTY_LIMIT,
                                scraper.store_name,
                            )
                            continue

                    scored = [enrich(p, category, off_http, off_cache) for p in raw_products]
                    if scored:
                        upsert_products(conn, scored)
        finally:
            browser.close()

    conn.close()
    if cut_off:
        log.warning("Run finished with incomplete data for: %s", ", ".join(sorted(cut_off)))
    log.info("Pipeline run complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Swiss supermarkets and score products.")
    parser.add_argument("--store", action="append", help="Limit to a store (repeatable), e.g. --store Migros")
    parser.add_argument("--category", action="append", help="Limit to a category id (repeatable)")
    args = parser.parse_args()
    run(stores=args.store, category_ids=args.category)
