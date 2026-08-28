from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

import httpx

BASE_URL = "https://world.openfoodfacts.org"
SEARCH_URL = "https://search.openfoodfacts.org/search"
# Broad on purpose: store everything plausibly useful later (ingredients,
# labels, scores, full nutriments) so a future scoring/display change can be
# made from what's already cached in our DB, without a fresh OFF query.
FIELDS = (
    "product_name,brands,quantity,nova_group,additives_tags,nutriments,"
    "ingredients_text,nutriscore_grade,ecoscore_grade,labels_tags,"
    "allergens_tags,traces_tags,categories_tags,packaging_tags"
)
HEADERS = {"User-Agent": "swiss-pantry-personal-use/1.0 (+local script)"}

# Open Food Facts asks integrators to stay well under their fair-use limits.
# A simple shared min-interval between calls keeps us polite without needing
# a real backoff/retry system for what is a low-volume personal script.
_BARCODE_MIN_INTERVAL = 0.6
_SEARCH_MIN_INTERVAL = 1.0
_lock = threading.Lock()
_last_call: dict[str, float] = {"barcode": 0.0, "search": 0.0}


def _throttle(kind: str, min_interval: float) -> None:
    with _lock:
        wait = _last_call[kind] + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[kind] = time.monotonic()


@dataclass
class HealthFacts:
    nova_group: Optional[int]
    additives_tags: list[str]
    saturated_fat_per_100g: Optional[float]
    brands: str = ""
    # The full OFF product record for this FIELDS selection - kept as-is so a
    # later feature (sugar, Nutri-Score, ingredients text, ...) can be read
    # straight out of what's already stored instead of re-querying OFF.
    raw: Optional[dict] = None
    # The OFF barcode this was matched to - lets the app link back to
    # world.openfoodfacts.org/product/<code> so the source is checkable.
    off_barcode: Optional[str] = None

    @property
    def additives_count(self) -> int:
        return len(self.additives_tags)


def _parse(product: dict) -> HealthFacts:
    nutriments = product.get("nutriments", {})
    sat_fat = nutriments.get("saturated-fat_100g")
    return HealthFacts(
        nova_group=product.get("nova_group"),
        additives_tags=product.get("additives_tags") or [],
        saturated_fat_per_100g=float(sat_fat) if sat_fat is not None else None,
        brands=product.get("brands") or "",
        raw=product,
    )


def by_barcode(client: httpx.Client, barcode: str) -> Optional[HealthFacts]:
    _throttle("barcode", _BARCODE_MIN_INTERVAL)
    resp = client.get(
        f"{BASE_URL}/api/v2/product/{barcode}.json",
        params={"fields": FIELDS},
        headers=HEADERS,
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("status") != 1:
        return None
    facts = _parse(data["product"])
    facts.off_barcode = barcode
    return facts


def _search_codes(client: httpx.Client, search_term: str, page_size: int) -> list[tuple[str, str]]:
    """Find candidate barcodes for a free-text term via OFF's current search
    service (the older cgi/search.pl endpoint has been unreliable - frequent
    503s in testing). Returns (code, brands) pairs; caller fetches full
    nutrient data per-barcode via the stable v2 product API."""
    _throttle("search", _SEARCH_MIN_INTERVAL)
    resp = client.get(
        SEARCH_URL,
        params={"q": search_term, "page_size": page_size, "fields": "code,brands"},
        headers=HEADERS,
        timeout=15,
    )
    if resp.status_code != 200:
        return []
    hits = resp.json().get("hits", [])
    results = []
    for hit in hits:
        code = hit.get("code")
        if not code:
            continue
        brands = hit.get("brands")
        brands_str = ", ".join(brands) if isinstance(brands, list) else (brands or "")
        results.append((code, brands_str))
    return results


def search_candidates(client: httpx.Client, search_term: str, page_size: int = 10) -> list[HealthFacts]:
    """Fetch a batch of OFF results for a free-text category term once, so
    callers can match many store products against it without one HTTP call
    per product.

    Order matters here: OFF's own search relevance is what makes a query like
    "vegan kebab" rank actual vegan products first. Previously this dropped
    any candidate missing a NOVA classification - which silently reordered
    results, since incomplete-but-correct matches (a small vegan brand OFF
    hasn't fully classified) got skipped in favor of a complete-but-wrong one
    further down the list (a real meat kebab that happened to have NOVA set).
    That's how "MY VAY Kebab vegan" once got scored using a chicken/turkey/
    veal product's ingredients. Now we only drop a candidate OFF has no
    record of at all; compute_breakdown() already copes with partial data.
    """
    candidates = []
    for code, brands in _search_codes(client, search_term, page_size):
        facts = by_barcode(client, code)
        if facts is not None:
            facts.brands = facts.brands or brands
            candidates.append(facts)
    return candidates


def match_candidate(candidates: list[HealthFacts], brand_hint: Optional[str]) -> Optional[HealthFacts]:
    if not candidates:
        return None
    if brand_hint:
        brand_hint = brand_hint.lower()
        for c in candidates:
            if brand_hint in c.brands.lower():
                return c
    return candidates[0]


def _normalize(text: str) -> str:
    """Lowercase, strip accents/umlauts, collapse punctuation to spaces, so
    'Müesli'/'Muesli'/'MÜSLI' and 'Golden Bridge'/'GOLDEN BRIDGE' compare equal."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ss", "s")  # Müsli/Müesli vs Muessli style variants
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _brand_matches(off_brands: str, store_product_name: str) -> bool:
    """True if any OFF brand token actually appears in the store's product
    name. Aldi/Denner/Lidl don't expose a brand field at all - the brand is
    embedded in the name ('GOLDEN BRIDGE Cluster Granola Müesli'), so this is
    the only brand signal available for them."""
    name_norm = f" {_normalize(store_product_name)} "
    for brand in off_brands.split(","):
        brand_norm = _normalize(brand)
        # Single short tokens ("rea", "aro") match by accident far too easily.
        if len(brand_norm) >= 4 and f" {brand_norm} " in name_norm:
            return True
    return False


def _identifies_a_variant(off_product_name: str, off_brands: str) -> bool:
    """Reject OFF records whose product name is nothing but the brand.

    Own-brand ranges are the trap here: OFF often holds one stub entry named
    just "Golden bridge", and every Golden Bridge muesli variant (Cluster
    Granola, Triple Choco, Honig & Nuss, ...) matches it equally well on brand
    and category - so eight distinct products would all show one product's
    nutrition. A record has to name something beyond the brand to be usable."""
    name_tokens = set(_normalize(off_product_name).split())
    brand_tokens: set[str] = set()
    for brand in off_brands.split(","):
        brand_tokens |= set(_normalize(brand).split())
    if not brand_tokens:
        # With no brand recorded we can't tell brand words from variant words,
        # so we can't establish this record is the specific variant we want.
        return False
    return bool(name_tokens - brand_tokens)


def _is_same_kind(facts: HealthFacts, category) -> bool:
    """Reject a candidate that isn't even the right kind of product.

    OFF's full-text search always returns *something*: searching "Alnatura ·
    Fruit muesli · Bio, no added sugar" happily returned pineapple juice,
    because the token "Fruit" matched. Reusing the category's own
    keywords_include/keywords_exclude here means a muesli match has to look
    like a muesli - either by product name or by OFF's category taxonomy."""
    from swiss_pantry.matching.categorize import matches_category

    raw = facts.raw or {}
    if matches_category(raw.get("product_name") or "", category):
        return True
    # Taxonomy tags look like "en:mueslis" / "en:breakfast-cereals". Match on
    # the configured allowlist, since OFF's wording rarely equals the shelf's.
    tags = " ".join(raw.get("categories_tags") or []).lower()
    return any(tag in tags for tag in category.off_category_tags)


def search_for_product(
    client: httpx.Client,
    product_name: str,
    category,
    max_candidates: int = 5,
) -> Optional[HealthFacts]:
    """Match a single scraped product to OFF by searching its own name, for
    products whose barcode lookup found nothing (all of Aldi/Denner/Lidl, plus
    any Migros item OFF doesn't carry under its GTIN).

    A candidate is only accepted when it is BOTH the same kind of product
    (see _is_same_kind) AND from a brand that actually appears in the store's
    product name. Without both checks this quietly produced badly wrong data -
    an Alnatura muesli scored and linked as Eckes-Granini pineapple juice.
    Returning None here is deliberate: an honest "No data" beats a confident
    wrong answer, and the app surfaces unmatched rows as "Unrated"."""
    for code, brands in _search_codes(client, product_name, max_candidates):
        try:
            facts = by_barcode(client, code)
        except httpx.HTTPError:
            # One slow/failed record shouldn't cost us a good match further
            # down the candidate list.
            continue
        if facts is None:
            continue
        facts.brands = facts.brands or brands
        off_name = (facts.raw or {}).get("product_name") or ""
        if (
            _is_same_kind(facts, category)
            and _brand_matches(facts.brands, product_name)
            and _identifies_a_variant(off_name, facts.brands)
        ):
            return facts
    return None
