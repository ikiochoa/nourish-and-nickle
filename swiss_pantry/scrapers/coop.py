from __future__ import annotations
import urllib.parse

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import FetchContext, Scraper
from swiss_pantry.storage.models import RawProduct

SEARCH_URL = "https://www.coop.ch/en/search/?text={query}"

EXTRACT_JS = """
(tiles) => tiles.map(tile => ({
    name: tile.querySelector('.productTile-details__name-value')?.textContent?.trim() || null,
    brand: tile.querySelector('.productTile__productMeta-value-item')?.textContent?.trim() || null,
    quantity: tile.querySelector('.productTile__quantity-text')?.textContent?.trim() || null,
    price: tile.querySelector('.productTile__price-value[data-udo-price]')?.getAttribute('data-udo-price') || null,
    url: tile.getAttribute('href'),
    html: tile.outerHTML,
}))
"""


class CoopScraper(Scraper):
    store_name = "Coop"

    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        page = ctx.browser().new_page()
        query = urllib.parse.quote(category.search_de)
        page.goto(SEARCH_URL.format(query=query), wait_until="networkidle", timeout=30000)
        tiles = page.eval_on_selector_all("a.productTile[data-productid]", EXTRACT_JS)
        page.close()

        products: list[RawProduct] = []
        for tile in tiles:
            name = tile.get("name")
            price = tile.get("price")
            if not name or not price or not matches_category(name, category):
                continue
            qty, unit = parse_package_size(tile.get("quantity") or "")
            url = tile.get("url")
            products.append(
                RawProduct(
                    store=self.store_name,
                    category=category.id,
                    raw_name=name,
                    brand=tile.get("brand"),
                    price_chf=float(price),
                    package_qty=qty,
                    package_unit=unit,
                    url=f"https://www.coop.ch{url}" if url and url.startswith("/") else url,
                    barcode=None,
                    raw_data={"html": tile.get("html")},
                )
            )
        return products
