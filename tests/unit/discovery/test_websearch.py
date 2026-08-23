"""Tests for the Tavily web-search wrapper. tavily.TavilyClient is mocked entirely --
this suite never calls the real Tavily API."""
import pytest

from opportunity_tracker.discovery.websearch import (
    build_query,
    search_domain,
    search_institution,
    searches_used_by,
)
from opportunity_tracker.models import Filter, Institution, InstitutionSource


def _make_institution() -> Institution:
    return Institution(
        id=1,
        name="University of Western Australia",
        country="Australia",
        country_code="AU",
        domain="uwa.edu.au",
        source=InstitutionSource.HIPO_DIRECTORY,
        directory_version="2026.1",
        added_at="2026-08-22T00:00:00+00:00",
    )


def _make_filter() -> Filter:
    return Filter(
        id=1,
        name="AU PhD CS",
        country="Australia",
        degree_levels=["PhD"],
        fields=["Computer Science"],
        funding_type=None,
        deadline_after=None,
        min_grade=None,
        institution_cap=50,
        content_hash="hash-1",
        created_at="2026-08-22T00:00:00+00:00",
    )


def test_build_query_uses_first_degree_level_and_field():
    query = build_query(_make_filter(), _make_institution())
    assert query == (
        "PhD Computer Science scholarship international students site info "
        "for University of Western Australia"
    )


def test_search_institution_extracts_and_dedupes_results(mocker):
    fake_client = mocker.MagicMock()
    fake_client.search.return_value = {
        "results": [
            {"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP Scholarship"},
            {"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP Scholarship (dup)"},
            {"url": "https://uwa.edu.au/scholarships/other", "title": "Other Scholarship"},
        ]
    }
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    results = search_institution(_make_institution(), _make_filter(), api_key="tvly-test")

    assert results == [
        {"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP Scholarship"},
        {"url": "https://uwa.edu.au/scholarships/other", "title": "Other Scholarship"},
    ]


def test_search_institution_scopes_to_institution_domain_and_widens_max_results(mocker):
    fake_client = mocker.MagicMock()
    fake_client.search.return_value = {"results": []}
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    search_institution(_make_institution(), _make_filter(), api_key="tvly-test", max_uses=5)

    _, kwargs = fake_client.search.call_args
    assert kwargs["include_domains"] == ["uwa.edu.au"]
    assert kwargs["max_results"] == 15  # max_uses(5) * 3 results-per-use
    assert kwargs["query"] == (
        "PhD Computer Science scholarship international students site info "
        "for University of Western Australia"
    )


def test_search_institution_caps_max_results_at_tavilys_ceiling(mocker):
    fake_client = mocker.MagicMock()
    fake_client.search.return_value = {"results": []}
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    search_institution(_make_institution(), _make_filter(), api_key="tvly-test", max_uses=50)

    _, kwargs = fake_client.search.call_args
    assert kwargs["max_results"] == 20  # Tavily's own per-call ceiling, not 150


def test_search_institution_propagates_a_real_api_failure(mocker):
    # Unlike the in-band "error object instead of a result list" shape the old
    # Anthropic version degraded internally, a genuine API failure (network, auth,
    # rate limit) is NOT swallowed here -- the caller (discovery/run.py) already
    # catches this and degrades to "no candidate found" for the one institution.
    fake_client = mocker.MagicMock()
    fake_client.search.side_effect = RuntimeError("rate limited")
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    with pytest.raises(RuntimeError, match="rate limited"):
        search_institution(_make_institution(), _make_filter(), api_key="tvly-test")


def test_search_institution_reports_one_search_credit_used(mocker):
    fake_client = mocker.MagicMock()
    fake_client.search.return_value = {
        "results": [{"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP Scholarship"}]
    }
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    results = search_institution(_make_institution(), _make_filter(), api_key="tvly-test")

    # Tavily bills a flat 1 credit per basic-depth call, unlike Claude's web_search
    # tool which could bill up to max_uses depending on how many rounds it spent.
    assert searches_used_by(results) == 1


def test_searches_used_by_falls_back_to_one_for_a_plain_list():
    assert searches_used_by([]) == 1
    assert searches_used_by([{"url": "https://x.example", "title": "x"}]) == 1


def test_search_domain_scopes_to_bare_domain_and_returns_results(mocker):
    fake_client = mocker.MagicMock()
    fake_client.search.return_value = {
        "results": [{"url": "https://uwa.edu.au/rules/deadline", "title": "Deadline"}]
    }
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    results = search_domain("uwa.edu.au", "application deadline", api_key="tvly-test", max_uses=1)

    assert results == [{"url": "https://uwa.edu.au/rules/deadline", "title": "Deadline"}]
    _, kwargs = fake_client.search.call_args
    assert kwargs["include_domains"] == ["uwa.edu.au"]
    assert kwargs["max_results"] == 3  # max_uses(1) * 3 results-per-use
    assert kwargs["query"] == "application deadline"


def test_search_domain_reports_one_search_credit_used(mocker):
    fake_client = mocker.MagicMock()
    fake_client.search.return_value = {
        "results": [{"url": "https://uwa.edu.au/rules/deadline", "title": "Deadline"}]
    }
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    results = search_domain("uwa.edu.au", "application deadline", api_key="tvly-test")

    assert searches_used_by(results) == 1


def test_search_domain_handles_a_response_with_no_results_key(mocker):
    fake_client = mocker.MagicMock()
    fake_client.search.return_value = {}
    mocker.patch(
        "opportunity_tracker.discovery.websearch.TavilyClient", return_value=fake_client
    )

    results = search_domain("uwa.edu.au", "application deadline", api_key="tvly-test")

    assert results == []
