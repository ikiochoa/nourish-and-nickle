from __future__ import annotations

import re
import urllib.parse

from playwright.sync_api import Browser

from swiss_pantry.matching.categorize import Category, matches_category
from swiss_pantry.pricing.normalize import parse_package_size
from swiss_pantry.scrapers.base import Scraper
from swiss_pantry.storage.models import RawProduct

# Plain, unauthenticated JSON endpoint (Magento/Elasticsuite "suggest" AJAX) -
# no bot protection observed, so a lightweight HTTP request context is enough;
# no need to render a page.
SUGGEST_URL = "https://sortiment.lidl.ch/de/search/ajax/suggest/?q={query}"

PRICE_RE = re.compile(r'content="([\d.]+)"')
FOOTER_RE = re.compile(r'pricefield__footer">([^<]+)<')


class LidlScraper(Scraper):
    store_name = "Lidl"

    def fetch(self, browser: Browser, category: Category) -> list[RawProduct]:
        context = browser.new_context()
        query = urllib.parse.quote(category.search_de)
        resp = context.request.get(SUGGEST_URL.format(query=query), timeout=15000)
        items = resp.json() if resp.ok else []
        context.close()

        products: list[RawProduct] = []
        for item in items:
            if item.get("type") != "product":
                continue
            name = item.get("title")
            price_html = item.get("price") or ""
            price_match = PRICE_RE.search(price_html)
            if not name or not price_match or not matches_category(name, category):
                continue
            footer_match = FOOTER_RE.search(price_html)
            size_text = footer_match.group(1).split("|")[0] if footer_match else ""
            qty, unit = parse_package_size(size_text)
            products.append(
                RawProduct(
                    store=self.store_name,
                    category=category.id,
                    raw_name=name,
                    brand=None,
                    price_chf=float(price_match.group(1)),
                    package_qty=qty,
                    package_unit=unit,
                    url=item.get("url"),
                    barcode=None,
                    raw_data=item,
                )
            )
        return products
