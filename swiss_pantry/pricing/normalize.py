from __future__ import annotations
import re
from typing import Optional

# Matches things like "500g", "1kg", "1l", "330ml", "6x9 rolls", "2x400g"
_QTY_RE = re.compile(
    r"(?:(?P<multiplier>\d+)\s*x\s*)?(?P<amount>[\d.,]+)\s*(?P<unit>kg|g|l|ml|rolls?|stk\.?|st(?:ü|u)ck|pieces?)",
    re.IGNORECASE,
)

_UNIT_TO_GRAMS_OR_ML = {"kg": 1000, "g": 1, "l": 1000, "ml": 1}


def parse_package_size(text: str) -> tuple[Optional[float], Optional[str]]:
    """Parse a pack-size string into (quantity, unit) where unit is 'g', 'ml', or 'roll'."""
    if not text:
        return None, None
    match = _QTY_RE.search(text.lower())
    if not match:
        return None, None

    amount = float(match.group("amount").replace(",", "."))
    multiplier = int(match.group("multiplier")) if match.group("multiplier") else 1
    unit = match.group("unit")

    if unit in ("roll", "rolls") or unit.startswith(("stk", "stü", "stu", "piece")):
        return amount * multiplier, "roll"

    grams_or_ml = amount * multiplier * _UNIT_TO_GRAMS_OR_ML[unit]
    canonical_unit = "ml" if unit in ("l", "ml") else "g"
    return grams_or_ml, canonical_unit


def price_per_unit(price_chf: float, qty: Optional[float], unit: Optional[str]) -> Optional[float]:
    """CHF per 100g / 100ml, or CHF per roll."""
    if not qty or qty <= 0:
        return None
    if unit == "roll":
        return round(price_chf / qty, 3)
    return round(price_chf / qty * 100, 3)
