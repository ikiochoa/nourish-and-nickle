from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "categories.yaml"


@dataclass
class Category:
    id: str
    name: str
    search_de: str
    search_en: str
    keywords_include: list[str]
    keywords_exclude: list[str]
    off_search_term: Optional[str]
    # Fragments of Open Food Facts' own category taxonomy that a name-searched
    # match must fall under (e.g. muesli accepts "breakfast-cereals"). OFF's
    # taxonomy words often differ from the words on the shelf, so this is kept
    # explicit rather than derived from keywords_include.
    off_category_tags: list[str]
    unit: str
    food: bool
    fresh_produce: bool = False


def load_categories() -> list[Category]:
    with open(CONFIG_PATH) as f:
        raw = yaml.safe_load(f)
    return [Category(**c) for c in raw]


def matches_category(raw_name: str, category: Category) -> bool:
    """A scraped product only counts as belonging to this category if its
    name contains one of the include keywords and none of the exclude ones -
    search results (esp. on Coop) mix in loosely related items otherwise."""
    name = raw_name.lower()
    if category.keywords_exclude and any(kw in name for kw in category.keywords_exclude):
        return False
    if not category.keywords_include:
        return True
    return any(kw in name for kw in category.keywords_include)
