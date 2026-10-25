from __future__ import annotations

import re
import urllib.parse

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import FetchContext, Scraper
from swiss_pantry.storage.models import RawProduct

# aldi-now.ch is Aldi Suisse's actual online grocery/delivery catalog and
# reflects real in-store assortment (own-brand "MY VAY" etc). The older
# aldi-suisse.ch site scraped earlier turned out to show different, seemingly
# unrelated private-label products - not what's actually on the shelf.
SEARCH_URL = "https://www.aldi-now.ch/de/search?q={query}"

PRICE_RE = re.compile(r"[\d]+[.,]?[\d]*")


class AldiScraper(Scraper):
    store_name = "Aldi"

    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        page = ctx.browser().new_page()
        query = urllib.parse.quote(category.search_de)
        page.goto(SEARCH_URL.format(query=query), wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(500)

        tiles = page.eval_on_selector_all(
            "product-item",
            """
            (tiles) => tiles.map(tile => ({
                name: tile.querySelector('.product-item__name')?.textContent?.trim() || null,
                volume: tile.querySelector('.product-item__sale-volume')?.textContent?.trim() || null,
                price: tile.querySelector('.money-price__amount')?.textContent?.trim() || null,
                url: tile.querySelector('a.product-item__overlay')?.getAttribute('href') || null,
                // Catch-all: badges/labels/eco-flags we don't parse individually
                // today, kept for later instead of re-scraping when we need them.
                html: tile.outerHTML,
            }))
            """,
        )
        page.close()

        products: list[RawProduct] = []
        for tile in tiles:
            name = tile.get("name")
            price_text = tile.get("price")
            if not name or not price_text or not matches_category(name, category):
                continue
            price_match = PRICE_RE.search(price_text.replace("\xa0", ""))
            if not price_match:
                continue
            price = float(price_match.group().replace(",", "."))
            qty, unit = parse_package_size(tile.get("volume") or "")
            url = tile.get("url")
            products.append(
                RawProduct(
                    store=self.store_name,
                    category=category.id,
                    raw_name=name,
                    brand=None,
                    price_chf=price,
                    package_qty=qty,
                    package_unit=unit,
                    url=f"https://www.aldi-now.ch{url}" if url and url.startswith("/") else url,
                    barcode=None,
                    raw_data={"html": tile.get("html")},
                )
            )
        return products
