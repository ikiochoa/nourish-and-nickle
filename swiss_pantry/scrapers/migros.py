from __future__ import annotations
import json
import urllib.parse

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import FetchContext, Scraper
from swiss_pantry.storage.models import RawProduct

SEARCH_URL = "https://www.migros.ch/en/search?query={query}"
CARDS_ENDPOINT = "product-display/public/v4/product-cards"


class MigrosScraper(Scraper):
    store_name = "Migros"

    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        page = ctx.browser().new_page()
        captured: list[dict] = []

        def on_response(response):
            if CARDS_ENDPOINT in response.url and response.request.method == "POST":
                try:
                    captured.append(response.json())
                except Exception:
                    pass

        page.on("response", on_response)
        query = urllib.parse.quote(category.search_en)

        # The product-cards POST occasionally lands just after networkidle
        # resolves (first navigation in a fresh browser is slower to warm up);
        # retry once rather than silently returning zero results.
        for attempt in range(2):
            captured.clear()
            page.goto(SEARCH_URL.format(query=query), wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1200)
            if captured:
                break
        page.close()

        products: list[RawProduct] = []
        seen_ids = set()
        for batch in captured:
            for card in batch:
                uid = card.get("uid")
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                products.append(self._to_raw_product(card, category))
        return [p for p in products if p is not None]

    def _to_raw_product(self, card: dict, category: Category) -> RawProduct | None:
        title = card.get("title") or card.get("name")
        if not title or not matches_category(title, category):
            return None

        offer = card.get("offer", {})
        price = offer.get("price", {}).get("effectiveValue")
        if price is None:
            return None

        qty_text = offer.get("quantity", "")
        qty, unit = parse_package_size(qty_text)

        gtins = card.get("gtins") or []
        barcode = gtins[0] if gtins else None

        return RawProduct(
            store=self.store_name,
            category=category.id,
            raw_name=title,
            brand=card.get("brand"),
            price_chf=float(price),
            package_qty=qty,
            package_unit=unit,
            url=card.get("productUrls"),
            barcode=barcode,
            raw_data=card,
        )
