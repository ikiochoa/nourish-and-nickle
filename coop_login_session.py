"""Interactive Coop session bootstrap.

Opens a real Chrome window at the Coop homepage (not a deep search link).
Log in with your account, then use the site's own search box to look up
something (not "tofu" - try a different term). Once real product tiles are
visible, this script detects it and saves the session cookies so the
automated scraper can reuse them.
"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SESSION_PATH = Path(__file__).resolve().parent / "data" / "coop_session.json"
SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False, channel="chrome")
    context = browser.new_context(viewport={"width": 1280, "height": 800}, locale="de-CH")
    page = context.new_page()
    page.goto("https://www.coop.ch/en/", timeout=30000)

    print("A Chrome window has opened at the Coop homepage.")
    print("1. Log in with your account (top right).")
    print("2. Use the search box to look up something other than tofu.")
    print("Waiting up to 6 minutes for product results to appear...")

    deadline = time.monotonic() + 360
    solved = False
    count = 0
    while time.monotonic() < deadline:
        count = page.locator("a.productTile[data-productid]").count()
        if count > 0:
            solved = True
            break
        time.sleep(2)

    if solved:
        context.storage_state(path=str(SESSION_PATH))
        print(f"Success - {count} products visible. Session saved to {SESSION_PATH}")
    else:
        print("Timed out waiting for product results. Session NOT saved.")

    browser.close()
