"""Run the pipeline for a single category id, appending to the existing DB."""
import sys

import httpx
from playwright.sync_api import sync_playwright

from swiss_pantry.matching.categorize import load_categories
from swiss_pantry.pipeline import SCRAPERS, enrich, log
from swiss_pantry.storage.db import get_connection, upsert_products

category_id = sys.argv[1]
category = next(c for c in load_categories() if c.id == category_id)
conn = get_connection()
off_cache: dict = {}

with sync_playwright() as pw, httpx.Client() as off_http:
    browser = pw.chromium.launch(headless=False)
    try:
        for scraper in SCRAPERS:
            log.info("Scraping %s / %s", scraper.store_name, category.id)
            raw_products = scraper.fetch(browser, category)
            log.info("  -> %d matches", len(raw_products))
            scored = [enrich(p, category, off_http, off_cache) for p in raw_products]
            if scored:
                upsert_products(conn, scored)
    finally:
        browser.close()

conn.close()
log.info("Done.")
