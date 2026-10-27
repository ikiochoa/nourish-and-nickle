"""Scrapers against canned responses shaped like the stores' real ones, so a
parsing change can be checked without hitting the stores."""
import json

import httpx

from swiss_pantry.matching.categorize import Category
from swiss_pantry.scrapers.aldi import AldiScraper
from swiss_pantry.scrapers.base import FetchContext
from swiss_pantry.scrapers.denner import DennerScraper
from swiss_pantry.scrapers.lidl import LidlScraper
from swiss_pantry.scrapers.ottos import OttosScraper

TOFU = Category(
    id="tofu",
    name="Tofu",
    search_de="Tofu",
    search_en="Tofu",
    keywords_include=["tofu"],
    keywords_exclude=["wurst"],
    off_search_term="tofu",
    off_category_tags=["tofu"],
    unit="g",
    food=True,
)


def ctx_for(handler) -> FetchContext:
    return FetchContext(httpx.Client(transport=httpx.MockTransport(handler)), allow_browser=False)


LIDL_TILE = """
<li class="item product product-item"><div class="product-item-info">
 <div class="product details product-item-details">
  <a href="https://sortiment.lidl.ch/de/catalog/product/view/id/{id}/s/x/" class="product-item-link">
   <strong class="product name product-item-name"> {name} </strong></a>
  <div class="price-box price-final_price" data-role="priceBox" data-product-id="{id}">
   <span class="pricefield"><span class="pricefield__body">
    <strong class="pricefield__price" itemprop="price" content="{price}">1<span>.</span><span>49</span></strong>
   </span><span class="pricefield__footer">{footer}</span></span>
  </div>
 </div>
</div></li>
"""


def test_lidl():
    tiles = [
        LIDL_TILE.format(id=1, name="Bio Tofu Classic", price="1.49", footer="pro 2x200g | 100g = 0.37 CHF"),
        LIDL_TILE.format(id=2, name="Its vegic Bio Tofu", price="3.65", footer="pro 230g, 260g | 100g = 1.59 CHF"),
        # Lidl's fuzzy fallback for "tofu"; the keyword filter drops it.
        LIDL_TILE.format(id=3, name="Toffee & Nuts", price="1.59", footer="pro 125g | 100g = 1.27 CHF"),
    ]
    page = f'<ol class="products list items product-items">{"".join(tiles)}</ol>'

    def handler(req):
        assert req.url.params["q"] == "Tofu"
        return httpx.Response(200, text=page)

    products = LidlScraper().fetch(ctx_for(handler), TOFU)
    assert [(p.raw_name, p.price_chf, p.package_qty, p.package_unit) for p in products] == [
        ("Bio Tofu Classic", 1.49, 400.0, "g"),
        ("Its vegic Bio Tofu", 3.65, 230.0, "g"),
    ]
    assert products[0].url == "https://sortiment.lidl.ch/de/catalog/product/view/id/1/s/x/"


def _denner_record(name, subline, price, url):
    attrs = {"name": name, "nameSubline": subline, "price": price, "itemUrl": url, "articleId": url}
    return {"attributeInfo": [{"attributeName": k, "vals": [{"value": v}]} for k, v in attrs.items()]}


def test_denner_reads_both_search_modes_and_dedupes():
    tofu = _denner_record("Denner Tofu bio", "nature, 310 g", "2.95", "/de/tofu-bio")
    tofu_autocomplete = {**tofu, "sku": "12345"}
    smoked = _denner_record("Räuchertofu", "200 g", "3.50", "/de/raeuchertofu")
    sausage = _denner_record("Tofuwurst", "200 g", "3.95", "/de/tofuwurst")
    responses = {
        "autocomplete": {"items": [tofu_autocomplete, sausage]},
        "overview": {"blocks": {"searches": [{"blockName": "products", "slots": [{"item": tofu}, {"item": smoked}]}]}},
    }
    modes = []

    def handler(req):
        body = json.loads(req.content)
        modes.append(body["mode"])
        assert body["q"] == "Tofu"
        return httpx.Response(200, json=responses[body["mode"]])

    products = DennerScraper().fetch(ctx_for(handler), TOFU)
    assert modes == ["autocomplete", "overview"]
    assert [(p.raw_name, p.price_chf, p.package_qty) for p in products] == [
        ("Denner Tofu bio", 2.95, 310.0),
        ("Räuchertofu", 3.5, 200.0),
    ]
    assert products[0].url == "https://www.denner.ch/de/tofu-bio"


def test_aldi():
    data = [
        {
            "name": "Tofu Natur",
            "brandName": "MY VAY",
            "sellingSize": "500 g",
            "price": {"amountRelevantDisplay": "CHF 1.09"},
            "sku": "000000000000123456",
            "urlSlugText": "my-vay-tofu-natur",
        },
        {
            "name": "BIO Tofu, geräuchert",
            "brandName": "BIO",
            "sellingSize": None,
            "price": {"amountRelevantDisplay": "CHF 1.45", "comparisonDisplay": "CHF 0.40/100 g"},
        },
        {"name": "Sojasauce", "brandName": "ASIA", "sellingSize": "150 ml", "price": {"amountRelevantDisplay": "CHF 1.99"}},
        # sellingSize with the wrong unit: the unit price shows it's 750 g.
        {
            "name": "Tofu Würfel",
            "brandName": "MY VAY",
            "sellingSize": "750 kg",
            "price": {"amountRelevantDisplay": "CHF 3.29", "comparisonDisplay": "CHF 0.44/100 g"},
        },
        # sellingSize that matches nothing: Aldi's unit price wins.
        {
            "name": "Tofu Rosso",
            "brandName": "MY VAY",
            "sellingSize": "50 g",
            "price": {"amountRelevantDisplay": "CHF 2.00", "comparisonDisplay": "CHF 1.00/100 g"},
        },
    ]

    def handler(req):
        assert req.url.params["q"] == "Tofu"
        return httpx.Response(200, json={"data": data, "meta": {"pagination": {"totalCount": 5}}})

    p, smoked, cubes, rosso = AldiScraper().fetch(ctx_for(handler), TOFU)
    assert (cubes.package_qty, cubes.package_unit) == (750.0, "g")
    assert (rosso.package_qty, rosso.package_unit) == (200.0, "g")
    assert (p.raw_name, p.brand, p.price_chf, p.package_qty, p.package_unit) == (
        "MY VAY Tofu Natur", "MY VAY", 1.09, 500.0, "g"
    )
    # No sellingSize: the pack size is worked out from Aldi's unit price.
    assert (smoked.raw_name, smoked.package_qty, smoked.package_unit) == ("BIO Tofu, geräuchert", 362.0, "g")
    assert p.url == "https://www.aldi-suisse.ch/de/produkt/my-vay-tofu-natur-000000000000123456"


def test_aldi_pages_through_results():
    offsets = []

    def handler(req):
        offset = int(req.url.params["offset"])
        offsets.append(offset)
        record = {"name": f"Tofu {offset}", "price": {"amountRelevantDisplay": "CHF 2.00"}, "sellingSize": "200 g"}
        return httpx.Response(200, json={"data": [record], "meta": {"pagination": {"totalCount": 100}}})

    products = AldiScraper().fetch(ctx_for(handler), TOFU)
    assert offsets == [0, 60]
    assert len(products) == 2


def test_ottos():
    products = [
        {"name": "<em>Tofu</em> nature 250 g", "price": {"value": 2.75, "formattedValue": "CHF 2.75"}, "url": "/p/1"},
        {"name": "Kaffeemaschine", "price": {"value": 99.0}, "url": "/p/2"},
    ]
    ctx = ctx_for(lambda req: httpx.Response(200, json={"products": products}))
    [p] = OttosScraper().fetch(ctx, TOFU)
    assert (p.raw_name, p.price_chf, p.package_qty, p.url) == ("Tofu nature 250 g", 2.75, 250.0, "https://www.ottos.ch/p/1")
