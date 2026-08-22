"""Tests for plain HTTP GET fetch and degraded-fetch detection. httpx.get is mocked
throughout -- this suite never makes a real HTTP request."""
from opportunity_tracker.fetcher.http_fetch import FetchResult, fetch_http


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_fetch_http_normal_content_is_not_degraded(mocker):
    real_text = "Scholarship details and eligibility criteria. " * 10  # well over 200 chars
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(real_text, 200),
    )

    result = fetch_http("https://uwa.edu.au/scholarships/rtp")

    assert isinstance(result, FetchResult)
    assert result.status_code == 200
    assert result.text == real_text
    assert result.is_degraded is False


def test_fetch_http_short_loading_body_is_degraded(mocker):
    short_text = "Loading component..."
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(short_text, 200),
    )

    result = fetch_http("https://uwa.edu.au/hdr-application")

    assert result.status_code == 200
    assert result.text == short_text
    assert result.is_degraded is True
