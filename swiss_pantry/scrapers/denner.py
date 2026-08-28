from __future__ import annotations

from playwright.sync_api import Browser

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import Scraper
from swiss_pantry.storage.models import RawProduct

HOME_URL = "https://www.denner.ch/de"
AUTOCOMPLETE_ENDPOINT = "search-api/autoComplete"


def _attr(attribute_info: list[dict], name: str) -> str | None:
    for attr in attribute_info:
        if attr.get("attributeName") == name:
            vals = attr.get("vals") or []
            if vals:
                return vals[0].get("value")
    return None


def _flatten(attribute_info: list[dict]) -> dict:
    """attributeInfo is a list of {attributeName, vals: [{value}, ...]} - flatten
    to a plain dict so the full API record can be cached as-is for later use."""
    flat = {}
    for attr in attribute_info:
        key = attr.get("attributeName")
        vals = [v.get("value") for v in (attr.get("vals") or [])]
        if key:
            flat[key] = vals[0] if len(vals) == 1 else vals
    return flat


class DennerScraper(Scraper):
    store_name = "Denner"

    def fetch(self, browser: Browser, category: Category) -> list[RawProduct]:
        page = browser.new_page()
        captured: list[dict] = []

        def on_response(response):
            if AUTOCOMPLETE_ENDPOINT in response.url:
                try:
                    captured.append(response.json())
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(HOME_URL, wait_until="networkidle", timeout=30000)
        box = page.locator('input[type="text"], input[type="search"]').first
        box.click()
        box.type(category.search_de, delay=60)
        page.wait_for_timeout(1500)
        page.close()

        products: list[RawProduct] = []
        seen_skus = set()
        for batch in captured:
            for group in batch.get("items", []):
                if group.get("itemType") != "PRODUCT":
                    continue
                for match in group.get("matches", []):
                    sku = match.get("sku")
                    if sku in seen_skus:
                        continue
                    seen_skus.add(sku)
                    attrs = match.get("attributeInfo", [])
                    name = _attr(attrs, "name")
                    price = match.get("price")
                    if not name or price is None or not matches_category(name, category):
                        continue
                    # nameSubline (e.g. "nature, 310 g") is human-readable; content_size_text
                    # is normalized to kg in an odd "0.31 unit.g" format we don't need.
                    qty, unit = parse_package_size(_attr(attrs, "nameSubline") or "")
                    url = _attr(attrs, "itemUrl")
                    products.append(
                        RawProduct(
                            store=self.store_name,
                            category=category.id,
                            raw_name=name,
                            brand=None,
                            price_chf=float(price),
                            package_qty=qty,
                            package_unit=unit,
                            url=f"https://www.denner.ch{url}" if url and url.startswith("/") else url,
                            barcode=None,
                            raw_data=_flatten(attrs),
                        )
                    )
        return products
