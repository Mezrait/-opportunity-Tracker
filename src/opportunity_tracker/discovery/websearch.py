"""Tavily web-search wrapper, domain-scoped per institution. Spec section 6.0.

Originally built against Claude's web_search tool; migrated to Tavily 2026-08-23 for
cost (see the web-UI design spec's decision log) -- the domain-scoping and URL/title-only
contract are unchanged, only the provider underneath is different.

Discovery never fetches full page content itself -- Tavily's search endpoint returns
URL/title/content-snippet metadata only, not full page text. Candidate URLs are handed to
the existing fetcher pipeline unchanged (fetcher/pipeline.py) -- this module never does
its own HTTP fetching.
"""
from __future__ import annotations

from tavily import TavilyClient

from opportunity_tracker.models import Filter, Institution

# Tavily has no equivalent to Claude's max_uses (a budget for the model's own iterative
# search-and-refine loop, spent server-side across up to max_uses rounds) -- one Tavily
# call always returns up to max_results in a single round. max_uses is instead used to
# widen max_results, so a caller asking for a bigger search budget still gets
# proportionally more candidate URLs back. Tavily's own ceiling is 20 results/call.
_RESULTS_PER_USE = 3
_MAX_RESULTS_CEILING = 20


class SearchResults(list):
    """The list of {"url", "title"} dicts, carrying how many search credits it cost.

    Tavily bills a fixed 1 credit per basic-depth search call (unlike Claude's
    web_search tool, which could bill up to max_uses per call depending on how many
    rounds the model actually spent) -- so `searches_used` is always 1 here, set
    directly rather than read off a response field.

    A plain `list` subclass rather than a new return type on purpose: every existing
    caller and test that treats the result as a list of dicts keeps working unchanged,
    and `searches_used_by` reads the count back with a safe fallback.
    """

    searches_used: int = 1


def searches_used_by(results) -> int:
    """Number of Tavily search credits `results` cost.

    Falls back to 1 for anything that is not a SearchResults -- a stubbed search in a
    test, or the empty list a caller substitutes when the call raised. Never raises.
    """
    try:
        return max(0, int(getattr(results, "searches_used", 1)))
    except (TypeError, ValueError):
        return 1


def build_query(filter_obj: Filter, institution: Institution) -> str:
    """Build the discovery search query for one institution, from the filter's
    first degree level and first field (spec section 6.0's worked example)."""
    degree_level = filter_obj.degree_levels[0]
    field = filter_obj.fields[0]
    return (
        f"{degree_level} {field} scholarship international students site info "
        f"for {institution.name}"
    )


def _results_from_response(response) -> SearchResults:
    results = SearchResults()
    results.searches_used = 1
    seen_urls: set[str] = set()
    for item in (response or {}).get("results") or []:
        url = item.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        results.append({"url": url, "title": item.get("title") or ""})
    return results


def search_institution(
    institution: Institution,
    filter_obj: Filter,
    api_key: str,
    max_uses: int = 3,
) -> list[dict]:
    """Run one domain-scoped Tavily search against a single institution.

    Returns a list of {"url": str, "title": str} dicts, deduplicated by URL and in
    the order results were returned. Never fetches full page content -- only the
    URL/title Tavily's search endpoint itself returns.

    Raises on a genuine API failure (network, auth, rate limit) -- the caller
    (discovery/run.py) already catches this and degrades to "no candidate found" for
    the one institution, per spec principle 4 ("every error degrades toward
    UNKNOWN-GATED, never toward deletion"); this function does not swallow errors
    itself, matching the same division of responsibility the Anthropic-based version
    had.
    """
    client = TavilyClient(api_key=api_key)
    query = build_query(filter_obj, institution)
    response = client.search(
        query=query,
        include_domains=[institution.domain],
        max_results=min(_MAX_RESULTS_CEILING, max_uses * _RESULTS_PER_USE),
        search_depth="basic",
    )
    return _results_from_response(response)


def search_domain(domain: str, query: str, api_key: str, max_uses: int = 1) -> list[dict]:
    """Run one domain-scoped Tavily search against a bare registrable domain.

    Sibling to search_institution, for a caller (the digger) that has a registrable
    domain and a free-text query but no Institution/Filter pair to build one from via
    build_query(). Same URL/title-only, deduplicated contract as search_institution,
    including the `searches_used` count carried on the returned SearchResults, and the
    same "raises on a real API failure, caller's job to catch it" contract.
    """
    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=query,
        include_domains=[domain],
        max_results=min(_MAX_RESULTS_CEILING, max_uses * _RESULTS_PER_USE),
        search_depth="basic",
    )
    return _results_from_response(response)
