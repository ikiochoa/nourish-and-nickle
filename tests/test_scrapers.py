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


def test_lidl():
    item = {
        "type": "product",
        "title": "Tofu natur",
        "url": "https://sortiment.lidl.ch/de/tofu-natur",
        "price": '<strong class="pricefield__price" content="1.49">1.49</strong>'
        '<span class="pricefield__footer">pro 2x200g | 100g = 0.37 CHF</span>',
    }
    other = {"type": "category", "title": "Tofu"}
    ctx = ctx_for(lambda req: httpx.Response(200, json=[item, other]))
    [p] = LidlScraper().fetch(ctx, TOFU)
    assert (p.raw_name, p.price_chf, p.package_qty, p.package_unit) == ("Tofu natur", 1.49, 400.0, "g")


def _denner_record(name, subline, price, url):
    attrs = {"name": name, "nameSubline": subline, "price": price, "itemUrl": url, "articleId": url}
    return {"attributeInfo": [{"attributeName": k, "vals": [{"value": v}]} for k, v in attrs.items()]}


def test_denner_reads_both_search_modes_and_dedupes():
    tofu = _denner_record("Denner Tofu bio", "nature, 310 g", "2.95", "/de/tofu-bio")
    smoked = _denner_record("Räuchertofu", "200 g", "3.50", "/de/raeuchertofu")
    sausage = _denner_record("Tofuwurst", "200 g", "3.95", "/de/tofuwurst")
    responses = {
        "autocomplete": {"items": [tofu, sausage]},
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
        {"name": "Sojasauce", "brandName": "ASIA", "sellingSize": "150 ml", "price": {"amountRelevantDisplay": "CHF 1.99"}},
    ]

    def handler(req):
        assert req.url.params["q"] == "Tofu"
        return httpx.Response(200, json={"data": data, "meta": {"pagination": {"totalCount": 2}}})

    [p] = AldiScraper().fetch(ctx_for(handler), TOFU)
    assert (p.raw_name, p.brand, p.price_chf, p.package_qty, p.package_unit) == (
        "MY VAY Tofu Natur", "MY VAY", 1.09, 500.0, "g"
    )
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
