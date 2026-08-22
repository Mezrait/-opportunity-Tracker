"""Playwright-based headless fetch -- fallback for JS-rendered pages that return a
near-empty shell to a plain GET. See spec §6.1."""
from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import sync_playwright


# TODO: Once Task 10 (http_fetch.py) is merged, replace this with:
# from opportunity_tracker.fetcher.http_fetch import DEFAULT_LOADING_MARKERS, FetchResult
@dataclass
class FetchResult:
    """Result of a fetch operation.

    Fields:
        text: The extracted text content from the page
        status_code: HTTP status code (or 200 for file:// URLs)
        is_degraded: True if content appears incomplete or shows loading markers
    """
    text: str
    status_code: int
    is_degraded: bool


# Marker strings that indicate a page is still loading its content component
DEFAULT_LOADING_MARKERS = [
    "Loading component...",
    "Loading...",
    "loading",
]


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
