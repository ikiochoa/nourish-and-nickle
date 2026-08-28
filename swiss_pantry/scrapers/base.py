from __future__ import annotations
from abc import ABC, abstractmethod

from playwright.sync_api import Browser

from swiss_pantry.matching.categorize import Category
from swiss_pantry.storage.models import RawProduct


class Scraper(ABC):
    store_name: str

    @abstractmethod
    def fetch(self, browser: Browser, category: Category) -> list[RawProduct]:
        """Search the store for `category` and return raw listings."""
        raise NotImplementedError
