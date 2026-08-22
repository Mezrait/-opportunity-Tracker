"""Plain HTTP GET fetch with degraded-fetch detection. See spec §6.1.

UWA's HDR page renders "Loading component..." to a plain GET -- a naive pipeline
would accept that as real content. Degraded-fetch detection here is minimum content
length plus expected-keyword (loading-placeholder) presence, exactly as the spec
requires; it is deliberately cheap and heuristic, not a full JS-awareness check --
that's what fetcher/headless_fetch.py is for.

What this module returns is EXTRACTED VISIBLE TEXT, not raw HTML -- the same shape
headless_fetch (Playwright `inner_text`) and pdf_fetch (plain text) return, so every
document in the store is comparable regardless of which path fetched it. Returning raw
markup broke three things at once: the `min_content_length` degraded heuristic was
meaningless (any HTML page trivially exceeds 200 characters of tags alone), the extractor
paid token cost for script/style/nav markup, and evidence spans were fuzzy-matched against
raw markup rather than against the text a human reads on the page.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

# Stripped before text extraction: these carry no reader-visible content, only code.
# <noscript> is deliberately NOT stripped -- "Please enable JavaScript" usually lives
# there, and it is one of the loading markers that triggers the headless fallback.
_NON_CONTENT_TAGS: tuple[str, ...] = ("script", "style", "template")


@dataclass(frozen=True)
class FetchResult:
    text: str
    status_code: int
    is_degraded: bool


DEFAULT_LOADING_MARKERS: tuple[str, ...] = (
    "Loading component...",
    "Please enable JavaScript",
)


def extract_visible_text(html: str) -> str:
    """Strip script/style/template markup from `html` and return its visible text.

    Blank lines are dropped and each line is stripped, which keeps the output close to
    what Playwright's `inner_text` produces for the same page -- the point being that a
    document's stored text should not depend on which fetch path happened to retrieve it.
    Plain (non-HTML) input passes through essentially unchanged, so a text/plain response
    is not mangled.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_NON_CONTENT_TAGS)):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text(separator="\n").splitlines())
    return "\n".join(line for line in lines if line)


def fetch_http(
    url: str,
    min_content_length: int = 200,
    loading_markers: tuple[str, ...] = DEFAULT_LOADING_MARKERS,
) -> FetchResult:
    """Fetch `url` via a plain HTTP GET, extract its visible text, and flag degraded fetches.

    A fetch is degraded if the extracted text is shorter than `min_content_length` OR
    contains any of `loading_markers`. Measuring that against extracted text rather than
    raw HTML is what makes the length half of the heuristic mean anything at all.
    """
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    text = extract_visible_text(response.text)
    is_degraded = len(text) < min_content_length or any(
        marker in text for marker in loading_markers
    )
    return FetchResult(text=text, status_code=response.status_code, is_degraded=is_degraded)
