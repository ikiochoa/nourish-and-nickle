"""One-off smoke test: run the pipeline for just 2 categories to verify wiring end-to-end."""
from __future__ import annotations

import httpx
from playwright.sync_api import sync_playwright

from swiss_pantry.matching.categorize import load_categories
from swiss_pantry.pipeline import enrich
from swiss_pantry.scrapers.aldi import AldiScraper
from swiss_pantry.scrapers.migros import MigrosScraper
from swiss_pantry.storage.db import get_connection, upsert_products

SCRAPERS = [MigrosScraper(), AldiScraper()]

categories = [c for c in load_categories() if c.id in ("soy_milk", "tofu")]
conn = get_connection()
off_cache: dict = {}

with sync_playwright() as pw, httpx.Client() as off_http:
    browser = pw.chromium.launch(headless=False)
    for category in categories:
        for scraper in SCRAPERS:
            print(f"--- {scraper.store_name} / {category.id} ---")
            raw = scraper.fetch(browser, category)
            print(f"{len(raw)} raw matches")
            for r in raw[:3]:
                print(" ", r)
            scored = [enrich(p, category, off_http, off_cache) for p in raw]
            if scored:
                upsert_products(conn, scored)
            for s in scored[:3]:
                print("  scored:", s.store, s.raw_name, s.price_chf, s.package_qty, s.package_unit, s.price_per_unit, s.health_score, s.health_grade)
    browser.close()

print("Rows in DB:", conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])
