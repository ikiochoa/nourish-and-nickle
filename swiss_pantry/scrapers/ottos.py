from __future__ import annotations

import re

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import FetchContext, Scraper
from swiss_pantry.storage.models import RawProduct

# Otto's online shop runs on SAP Commerce, whose standard "OCC" REST API the
# site's own pages call; it answers plain HTTP requests. Otto's sells mostly
# non-food, and its grocery range is small and shelf-stable (coffee, drinks,
# pantry staples), so many categories will simply come back empty.
SEARCH_URL = "https://api.ottos.ch/occ/v2/ottos/products/search"
SITE_URL = "https://www.ottos.ch"
PAGE_SIZE = 50

TAG_RE = re.compile(r"<[^>]+>")
PRICE_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _price(record: dict) -> float | None:
    price = record.get("price") or {}
    if isinstance(price.get("value"), (int, float)):
        return float(price["value"])
    match = PRICE_RE.search(price.get("formattedValue") or "")
    return float(match.group().replace(",", ".")) if match else None


class OttosScraper(Scraper):
    store_name = "Otto's"
    sparse_range = True

    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        resp = ctx.http.get(
            SEARCH_URL,
            params={
                "query": category.search_de,
                "fields": "FULL",
                "pageSize": PAGE_SIZE,
                "lang": "de",
                "curr": "CHF",
            },
        )
        resp.raise_for_status()

        products: list[RawProduct] = []
        for record in resp.json().get("products") or []:
            # Search hits come back with the matched words wrapped in <em>.
            name = TAG_RE.sub("", record.get("name") or "").strip()
            price = _price(record)
            if not name or not price or not matches_category(name, category):
                continue
            # No separate pack-size field: it is only in the name ("... 1 l").
            qty, unit = parse_package_size(name)
            url = record.get("url")
            products.append(
                RawProduct(
                    store=self.store_name,
                    category=category.id,
                    raw_name=name,
                    brand=(record.get("manufacturer") or None),
                    price_chf=price,
                    package_qty=qty,
                    package_unit=unit,
                    url=f"{SITE_URL}{url}" if url and url.startswith("/") else url,
                    barcode=None,
                    raw_data=record,
                )
            )
        return products
