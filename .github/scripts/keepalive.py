"""Open the deployed Streamlit dashboard in a real browser so it stays awake.

Streamlit Community Cloud hibernates an app after a stretch with no traffic, and
the next visitor gets a "This app has gone to sleep due to inactivity" screen
instead of the dashboard. A plain HTTP GET is not a reliable heartbeat: the app
server counts browser sessions, which means a WebSocket connection, so this
script drives headless Chromium instead. If the app is already asleep it also
clicks the wake-up button, so the job doubles as a self-healing ping.

Community Cloud serves the app itself in an iframe (``<app>.streamlit.app/~/+/``)
while the outer page only carries Streamlit's own chrome and the wake-up screen,
so every check below sweeps all frames rather than the main one.

Usage (CI does the same via .github/workflows/keepalive.yml):

    pip install playwright && playwright install --with-deps chromium
    APP_URL=https://<app>.streamlit.app python .github/scripts/keepalive.py

Exit code 0 means the dashboard was confirmed running; anything else means the
app could not be reached or woken, and the workflow fails loudly.
"""

from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

# The sleeping-app screen renders a single button; Streamlit has reworded it
# before ("Yes, get this app back up!"), so match loosely rather than exactly.
WAKE_BUTTON = re.compile(r"(back up|wake)", re.IGNORECASE)

# Present once the Streamlit frontend has connected to the server and rendered.
APP_READY = '[data-testid="stApp"]'

LOAD_TIMEOUT_MS = 120_000
READY_TIMEOUT_S = 240  # a cold restart reinstalls nothing but is still slow
POLL_INTERVAL_S = 3
SESSION_HOLD_MS = 20_000  # keep the WebSocket open so the visit counts as traffic
SCREENSHOT = os.environ.get("KEEPALIVE_SCREENSHOT", "keepalive.png")


def click_wake_button(page: Page) -> bool:
    """Click the "get this app back up" button if the sleep screen is showing."""
    for frame in page.frames:
        try:
            button = frame.get_by_role("button", name=WAKE_BUTTON)
            if button.count() and button.first.is_visible():
                button.first.click()
                return True
        except PlaywrightError:
            continue  # frame detached mid-sweep, or cross-origin noise
    return False


def app_is_rendered(page: Page) -> bool:
    for frame in page.frames:
        try:
            if frame.locator(APP_READY).count() and frame.locator(APP_READY).first.is_visible():
                return True
        except PlaywrightError:
            continue
    return False


def visible_text(page: Page) -> str:
    chunks = []
    for frame in page.frames:
        try:
            chunks.append(frame.locator("body").inner_text(timeout=5_000))
        except PlaywrightError:
            continue
    return "\n".join(chunks)


def main() -> int:
    url = os.environ.get("APP_URL", "").strip()
    if not url:
        print("APP_URL is not set: point it at the deployed app, e.g.", file=sys.stderr)
        print("  gh variable set APP_URL --body https://<app>.streamlit.app", file=sys.stderr)
        return 2

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)

            woken = False
            deadline = time.monotonic() + READY_TIMEOUT_S
            while time.monotonic() < deadline:
                if click_wake_button(page):
                    woken = True
                    print(f"{url} was asleep, clicked the wake-up button")
                if app_is_rendered(page):
                    break
                page.wait_for_timeout(POLL_INTERVAL_S * 1_000)
            else:
                print(
                    f"timed out after {READY_TIMEOUT_S}s waiting for the dashboard",
                    file=sys.stderr,
                )
                print(visible_text(page)[:2_000], file=sys.stderr)
                return 1

            if not woken:
                print(f"{url} was already awake")
            page.wait_for_timeout(SESSION_HOLD_MS)

            text = visible_text(page)
            if "Error running app" in text or "gone to sleep" in text:
                print("the page rendered but the app is not serving:", file=sys.stderr)
                print(text[:2_000], file=sys.stderr)
                return 1

            print(f"dashboard is up: {page.title()!r}")
            return 0
        finally:
            # Kept as a build artifact: the only way to see what CI actually saw.
            page.screenshot(path=SCREENSHOT, full_page=False)
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
