"""Playwright-based headless fetch -- fallback for JS-rendered pages that return a
near-empty shell to a plain GET. See spec §6.1."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from opportunity_tracker.fetcher.http_fetch import DEFAULT_LOADING_MARKERS, FetchResult


def fetch_headless(url: str, min_content_length: int = 200) -> FetchResult:
    """Render `url` with a headless Chromium browser and return its visible text.

    Reuses the same degraded-fetch heuristic as fetch_http: too-short body, or
    presence of a loading-placeholder marker -- a headless render can still be
    degraded (e.g. a page that never finishes loading its content component).
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            response = page.goto(url)
            text = page.inner_text("body")
            status_code = response.status if response is not None else 200
        finally:
            browser.close()

    is_degraded = len(text) < min_content_length or any(
        marker in text for marker in DEFAULT_LOADING_MARKERS
    )
    return FetchResult(text=text, status_code=status_code, is_degraded=is_degraded)
