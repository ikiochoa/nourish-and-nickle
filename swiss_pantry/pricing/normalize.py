from __future__ import annotations
import re
from typing import Optional

# Matches things like "500g", "1kg", "1l", "330ml", "6x9 rolls", "2x400g".
# The amount must start with a digit, or a stray "." before a word starting
# with g or l ("Nat. geräuchert") would read as a quantity.
_QTY_RE = re.compile(
    r"(?:(?P<multiplier>\d+)\s*x\s*)?(?P<amount>\d[\d.,]*)\s*(?P<unit>kg|g|l|ml|rolls?|stk\.?|st(?:ü|u)ck|pieces?)",
    re.IGNORECASE,
)

_UNIT_TO_GRAMS_OR_ML = {"kg": 1000, "g": 1, "l": 1000, "ml": 1}


# Countable units are kept distinct from rolls so a bottle of food colouring
# isn't displayed as "1 roll", while still being comparable in roll-priced
# categories like toilet paper (where a roll *is* the countable piece).
_COUNTABLE = {"roll", "piece"}


def parse_package_size(text: str) -> tuple[Optional[float], Optional[str]]:
    """Parse a pack-size string into (quantity, unit) where unit is
    'g', 'ml', 'roll', or 'piece'."""
    if not text:
        return None, None
    match = _QTY_RE.search(text.lower())
    if not match:
        return None, None

    amount = float(match.group("amount").replace(",", "."))
    multiplier = int(match.group("multiplier")) if match.group("multiplier") else 1
    unit = match.group("unit")

    if unit in ("roll", "rolls"):
        return amount * multiplier, "roll"
    if unit.startswith(("stk", "stü", "stu", "piece")):
        return amount * multiplier, "piece"

    grams_or_ml = amount * multiplier * _UNIT_TO_GRAMS_OR_ML[unit]
    canonical_unit = "ml" if unit in ("l", "ml") else "g"
    return grams_or_ml, canonical_unit


def units_compatible(parsed_unit: Optional[str], category_unit: str) -> bool:
    """Whether a parsed pack-size unit can be priced in the unit a category is
    compared in. Grams and millilitres are never interchangeable; rolls and
    loose pieces are the same thing for counting purposes."""
    if parsed_unit is None:
        return False
    if parsed_unit in _COUNTABLE and category_unit in _COUNTABLE:
        return True
    return parsed_unit == category_unit


def price_per_unit(price_chf: float, qty: Optional[float], unit: Optional[str]) -> Optional[float]:
    """CHF per 100g / 100ml, or CHF per countable item (roll / piece)."""
    if not qty or qty <= 0:
        return None
    if unit in _COUNTABLE:
        return round(price_chf / qty, 3)
    return round(price_chf / qty * 100, 3)
