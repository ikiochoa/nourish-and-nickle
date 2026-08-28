from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RawProduct:
    """A single product listing as scraped from one store."""

    store: str
    category: str
    raw_name: str
    brand: Optional[str]
    price_chf: float
    package_qty: Optional[float]
    package_unit: Optional[str]  # "g", "ml", "roll"
    url: Optional[str]
    barcode: Optional[str] = None
    # Whatever the store's own API/DOM exposed for this listing, kept as-is
    # (badges, eco-labels, category breadcrumbs, promo info, ...) so a future
    # feature can be read from cached data instead of a fresh scrape.
    raw_data: Optional[dict] = None


@dataclass
class ScoredProduct:
    store: str
    category: str
    raw_name: str
    brand: Optional[str]
    price_chf: float
    package_qty: Optional[float]
    package_unit: Optional[str]
    price_per_unit: Optional[float]  # CHF per 100g / 100ml / roll
    url: Optional[str]
    barcode: Optional[str]
    nova_group: Optional[int]
    # None = no OFF data at all; [] = OFF confirms zero additives; else the actual tags (e.g. "en:e250")
    additives_tags: Optional[list[str]]
    saturated_fat_per_100g: Optional[float]
    health_score: Optional[float]
    health_grade: Optional[str]
    scraped_at: datetime
    store_raw: Optional[dict] = None
    off_raw: Optional[dict] = None
    off_barcode: Optional[str] = None
