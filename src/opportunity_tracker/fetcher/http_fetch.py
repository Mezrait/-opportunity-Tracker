"""Plain HTTP GET fetch with degraded-fetch detection. See spec §6.1.

UWA's HDR page renders "Loading component..." to a plain GET -- a naive pipeline
would accept that as real content. Degraded-fetch detection here is minimum content
length plus expected-keyword (loading-placeholder) presence, exactly as the spec
requires; it is deliberately cheap and heuristic, not a full JS-awareness check --
that's what fetcher/headless_fetch.py is for.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class FetchResult:
    text: str
    status_code: int
    is_degraded: bool


DEFAULT_LOADING_MARKERS: tuple[str, ...] = (
    "Loading component...",
    "Please enable JavaScript",
)


def fetch_http(
    url: str,
    min_content_length: int = 200,
    loading_markers: tuple[str, ...] = DEFAULT_LOADING_MARKERS,
) -> FetchResult:
    """Fetch `url` via a plain HTTP GET and flag degraded fetches.

    A fetch is degraded if the response text is shorter than
    `min_content_length` OR contains any of `loading_markers`.
    """
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    text = response.text
    is_degraded = len(text) < min_content_length or any(
        marker in text for marker in loading_markers
    )
    return FetchResult(text=text, status_code=response.status_code, is_degraded=is_degraded)
