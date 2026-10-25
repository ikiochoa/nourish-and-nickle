from __future__ import annotations

from bs4 import BeautifulSoup

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import FetchContext, Scraper
from swiss_pantry.storage.models import RawProduct

# Lidl's server-rendered search results page (Magento). No bot protection
# observed, so a plain HTTP request is enough. The search box's JSON "suggest"
# endpoint is simpler but stops at 5 products.
SEARCH_URL = "https://sortiment.lidl.ch/de/catalogsearch/result/"
PAGE_SIZE = 36


def _pack_size_text(footer: str) -> str:
    """The price footer reads e.g. "pro 2x200g | 100g = 0.37 CHF": the pack
    size is the part before "|". Products sold in several sizes list them all
    ("pro 230g, 260g"); take the first, which the price belongs to."""
    size = footer.split("|")[0].strip()
    size = size.removeprefix("pro").strip()
    return size.split(",")[0]


class LidlScraper(Scraper):
    store_name = "Lidl"

    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        resp = ctx.http.get(SEARCH_URL, params={"q": category.search_de, "product_list_limit": PAGE_SIZE})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # With no exact match Lidl falls back to fuzzy results (a "tofu"
        # search also lists "Toffee & Nuts" and shower gel); the category
        # keyword filter below is what keeps those out.
        products: list[RawProduct] = []
        for tile in soup.select("li.product-item"):
            name_el = tile.select_one(".product-item-name")
            price_el = tile.select_one("strong.pricefield__price[content]")
            if not name_el or not price_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or not matches_category(name, category):
                continue
            footer_el = tile.select_one(".pricefield__footer")
            footer = footer_el.get_text(strip=True) if footer_el else ""
            qty, unit = parse_package_size(_pack_size_text(footer))
            link = tile.select_one("a.product-item-link[href]")
            price_box = tile.select_one(".price-box[data-product-id]")
            products.append(
                RawProduct(
                    store=self.store_name,
                    category=category.id,
                    raw_name=name,
                    brand=None,
                    price_chf=float(price_el["content"]),
                    package_qty=qty,
                    package_unit=unit,
                    url=link["href"] if link else None,
                    barcode=None,
                    raw_data={
                        "product_id": price_box["data-product-id"] if price_box else None,
                        "price_footer": footer,
                        "html": str(tile),
                    },
                )
            )
        return products
