from __future__ import annotations
from abc import ABC, abstractmethod

import httpx

from swiss_pantry.matching.categorize import Category
from swiss_pantry.storage.models import RawProduct

# A normal desktop browser's headers. The stores serve their public search
# pages and feeds to these; we identify as a browser rather than as a bot
# library, but make no attempt to get past any bot protection.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
}


def new_http_client() -> httpx.Client:
    return httpx.Client(headers=DEFAULT_HEADERS, timeout=20, follow_redirects=True)


class BrowserUnavailable(RuntimeError):
    """A scraper needed a real browser but this run was started without one
    (e.g. the scheduled cloud run)."""


class FetchContext:
    """What a scraper may use to talk to a store: a shared HTTP client, and a
    real browser that is only started if some scraper actually asks for it.
    Most stores serve plain JSON or server-rendered HTML, so a typical run
    never launches Chromium."""

    def __init__(self, http: httpx.Client, allow_browser: bool = True):
        self.http = http
        self.allow_browser = allow_browser
        self._playwright = None
        self._browser = None

    def browser(self):
        if not self.allow_browser:
            raise BrowserUnavailable("this run has no browser (--no-browser)")
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            # headless=False on purpose: Migros's bot detection serves plain
            # headless Chromium a fake "maintenance" page.
            self._browser = self._playwright.chromium.launch(headless=False)
        return self._browser

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._playwright.stop()
            self._browser = self._playwright = None


class Scraper(ABC):
    store_name: str
    # True for a store that only stocks a few of our categories, so coming
    # back empty is normal and only failed requests count toward the
    # pipeline's "this store has cut us off" check.
    sparse_range: bool = False

    @abstractmethod
    def fetch(self, ctx: FetchContext, category: Category) -> list[RawProduct]:
        """Search the store for `category` and return raw listings."""
        raise NotImplementedError
