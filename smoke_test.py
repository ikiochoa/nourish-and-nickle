"""One-off smoke test: run the scrapers for just 2 categories and print what
comes back, without writing to the DB. Pass --no-browser to check that the
plain-HTTP stores work on their own."""
from __future__ import annotations

import sys

from swiss_pantry.matching.categorize import load_categories
from swiss_pantry.pipeline import SCRAPERS
from swiss_pantry.scrapers.base import BrowserUnavailable, FetchContext, new_http_client

categories = [c for c in load_categories() if c.id in ("soy_milk", "tofu")]

with new_http_client() as http:
    ctx = FetchContext(http, allow_browser="--no-browser" not in sys.argv)
    try:
        for category in categories:
            for scraper in SCRAPERS:
                print(f"--- {scraper.store_name} / {category.id} ---")
                try:
                    raw = scraper.fetch(ctx, category)
                except BrowserUnavailable:
                    print("needs a browser, skipped")
                    continue
                print(f"{len(raw)} matches")
                for r in raw[:3]:
                    print(" ", r.raw_name, r.price_chf, r.package_qty, r.package_unit, r.barcode)
    finally:
        ctx.close()
