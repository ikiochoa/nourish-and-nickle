from __future__ import annotations

import re

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import FetchContext, Scraper
from swiss_pantry.storage.models import RawProduct

# Aldi Suisse's product API, the one www.aldi-suisse.ch's own pages call. The
# old aldi-now.ch catalogue now redirects to aldi-suisse.ch, whose HTML pages
# refuse plain HTTP requests, but this API answers them.
SEARCH_URL = "https://asl.api.aldi-suisse.ch/commerce/v3/product-search"
PRODUCT_URL = "https://www.aldi-suisse.ch/de/produkt/{slug}-{sku}"
# The API asks for a store; E172 is the site's default (Winterthur). Aldi's
# shelf prices are taken to be national, so one store stands for all.
SERVICE_POINT = "E172"
PAGE_SIZE = 60

PRICE_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _price(record: dict) -> float | None:
    # amountRelevantDisplay is e.g. "CHF 1.09".
    display = (record.get("price") or {}).get("amountRelevantDisplay") or ""
    match = PRICE_RE.search(display.replace("\xa0", ""))
    return float(match.group().replace(",", ".")) if match else None


def _size_from_unit_price(record: dict, price: float) -> tuple[float | None, str | None]:
    """Some products have no sellingSize, but every price comes with Aldi's
    own unit price, e.g. "CHF 0.36/100 g". Work the pack size back out from
    it, so the unit price shown is exactly Aldi's. The result is approximate
    (the unit price is rounded to the centime), hence rounded to the gram."""
    display = ((record.get("price") or {}).get("comparisonDisplay") or "").replace("\xa0", " ")
    if "/" not in display:
        return None, None
    amount_text, per_text = display.split("/", 1)
    match = PRICE_RE.search(amount_text)
    per_text = per_text.strip()
    if not per_text[:1].isdigit():
        per_text = f"1 {per_text}"  # "CHF 2.90/kg"
    per_qty, unit = parse_package_size(per_text)
    if not match or not per_qty or unit not in ("g", "ml"):
        return None, None
    per_price = float(match.group().replace(",", "."))
    if per_price <= 0:
        return None, None
    return float(round(price / per_price * per_qty)), unit


class AldiScraper(Scraper):
    store_name = "Aldi"

    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        records: list[dict] = []
        offset = 0
        while True:
            resp = ctx.http.get(
                SEARCH_URL,
                params={
                    "currency": "CHF",
                    "serviceType": "walk-in",
                    "servicePoint": SERVICE_POINT,
                    "q": category.search_de,
                    "sort": "relevance",
                    "limit": PAGE_SIZE,
                    "offset": offset,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            records.extend(body.get("data") or [])
            total = ((body.get("meta") or {}).get("pagination") or {}).get("totalCount") or 0
            offset += PAGE_SIZE
            if offset >= min(total, 5 * PAGE_SIZE):
                break

        products: list[RawProduct] = []
        for record in records:
            name = record.get("name")
            brand = record.get("brandName")
            price = _price(record)
            if not name or not price:
                continue
            # Product names on the shelf (and in rows scraped before) lead with
            # the brand, e.g. "GOLDEN BRIDGE Porridge Apfel-Banane-Ananas".
            if brand and brand.lower() not in name.lower():
                name = f"{brand} {name}"
            if not matches_category(name, category):
                continue
            qty, unit = parse_package_size(record.get("sellingSize") or name)
            if qty is None:
                qty, unit = _size_from_unit_price(record, price)
            sku = record.get("sku")
            slug = record.get("urlSlugText")
            products.append(
                RawProduct(
                    store=self.store_name,
                    category=category.id,
                    raw_name=name,
                    brand=brand,
                    price_chf=price,
                    package_qty=qty,
                    package_unit=unit,
                    url=PRODUCT_URL.format(slug=slug, sku=sku) if slug and sku else None,
                    barcode=None,
                    raw_data=record,
                )
            )
        return products
