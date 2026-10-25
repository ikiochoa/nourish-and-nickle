from __future__ import annotations

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import FetchContext, Scraper
from swiss_pantry.storage.models import RawProduct

# The JSON search API denner.ch's own search box calls. It answers plain HTTP
# requests, so there is no need to open the page and type into it. "overview"
# is the full results page; "autocomplete" is the drop-down, which is what the
# browser-based scraper used to capture.
SEARCH_URL = "https://www.denner.ch/nuxt-api/search"
SEARCH_MODES = ("autocomplete", "overview")


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


def _product_records(node) -> list[dict]:
    """Every product record in a search response, wherever it sits. The two
    modes nest products differently (autocomplete: items[]; overview:
    blocks.searches[].slots[].item), and both have moved before, so look for
    the shape of a product record instead of following one exact path."""
    if isinstance(node, dict):
        if "attributeInfo" in node:
            return [node]
        return [r for v in node.values() for r in _product_records(v)]
    if isinstance(node, list):
        return [r for v in node for r in _product_records(v)]
    return []


def _price(record: dict, attrs: list[dict]) -> float | None:
    value = record.get("price")
    if value is None:
        value = _attr(attrs, "price")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class DennerScraper(Scraper):
    store_name = "Denner"

    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        records: list[dict] = []
        for mode in SEARCH_MODES:
            resp = ctx.http.post(
                SEARCH_URL,
                json={"mode": mode, "lang": "de", "q": category.search_de, "appCategory": None},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            records.extend(_product_records(resp.json()))

        products: list[RawProduct] = []
        seen = set()
        for record in records:
            attrs = record.get("attributeInfo") or []
            key = record.get("sku") or _attr(attrs, "articleId") or _attr(attrs, "itemUrl")
            if key in seen:
                continue
            seen.add(key)
            name = _attr(attrs, "name")
            price = _price(record, attrs)
            if not name or price is None or not matches_category(name, category):
                continue
            # nameSubline (e.g. "nature, 310 g") is human-readable; content_size_text
            # is normalized to kg in an odd "0.31 unit.g" format we don't need.
            qty, unit = parse_package_size(_attr(attrs, "nameSubline") or "")
            url = _attr(attrs, "itemUrl") or _attr(attrs, "canonical")
            products.append(
                RawProduct(
                    store=self.store_name,
                    category=category.id,
                    raw_name=name,
                    brand=None,
                    price_chf=price,
                    package_qty=qty,
                    package_unit=unit,
                    url=f"https://www.denner.ch{url}" if url and url.startswith("/") else url,
                    barcode=None,
                    raw_data=_flatten(attrs),
                )
            )
        return products
