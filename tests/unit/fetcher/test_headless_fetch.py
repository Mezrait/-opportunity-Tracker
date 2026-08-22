"""Tests for the Playwright-based headless fetch fallback. Drives a real headless
Chromium browser against local file:// fixtures -- never the live network. Requires
`uv run playwright install chromium` to have been run once (see Task 11 Step 4)."""
from pathlib import Path

from opportunity_tracker.fetcher.headless_fetch import fetch_headless

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def test_fetch_headless_flags_loading_placeholder_as_degraded():
    fixture_path = FIXTURES_DIR / "loading_placeholder.html"
    url = fixture_path.resolve().as_uri()

    result = fetch_headless(url)

    assert "Loading component..." in result.text
    assert result.is_degraded is True


def test_fetch_headless_real_content_is_not_degraded():
    fixture_path = FIXTURES_DIR / "real_content.html"
    url = fixture_path.resolve().as_uri()

    result = fetch_headless(url)

    assert len(result.text) >= 200
    assert result.is_degraded is False
