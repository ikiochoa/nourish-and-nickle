from __future__ import annotations
import json
from pathlib import Path
from typing import NamedTuple

_DATA_PATH = Path(__file__).resolve().parents[2] / "config" / "additives_risk.json"
_DATA: dict = json.loads(_DATA_PATH.read_text())


class AdditiveInfo(NamedTuple):
    tag: str
    name: str
    risk: str  # "high", "moderate", or "low"


def lookup(tag: str) -> AdditiveInfo:
    """Look up risk tier for an OFF additive tag (e.g. "en:e250"). Additives
    with no EFSA/ANSES flag in the taxonomy - the large majority - default
    to "low", since an unflagged, long-established additive (citric acid,
    lecithin) isn't the same concern as sodium nitrite or MSG."""
    entry = _DATA.get(tag)
    if entry is None:
        short = tag[3:] if tag.startswith("en:") else tag
        return AdditiveInfo(tag=tag, name=short.upper(), risk="low")
    return AdditiveInfo(tag=tag, name=entry["name"], risk=entry["risk"])


def classify_all(tags: list[str]) -> list[AdditiveInfo]:
    return [lookup(t) for t in tags]
