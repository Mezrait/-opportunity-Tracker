"""Claude web_search wrapper, domain-scoped per institution. Spec section 6.0.

Discovery never fetches full page content itself -- the web_search tool returns
URL/title/snippet metadata only, not full text (confirmed against current API docs,
spec section 12). Candidate URLs are handed to the existing fetcher pipeline unchanged
(fetcher/pipeline.py, Task 13) -- this module never does its own HTTP fetching.
"""
from __future__ import annotations

import anthropic

from opportunity_tracker.models import Filter, Institution

# GA (non-beta) web_search tool type -- confirmed against current API docs at spec
# time (2026-08-22). Do not swap for a newer tool-type string without also
# reconfirming compatibility with the anthropic>=0.34 SDK pin in pyproject.toml.
_WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
_MODEL = "claude-opus-5"
_MAX_TOKENS = 1024


class SearchResults(list):
    """The list of {"url", "title"} dicts, carrying how many searches it actually cost.

    Both search functions are called with max_uses > 1, so "one call == one search" is
    wrong: a single messages.create can bill up to max_uses server-side web_search
    requests. The real number lives on the response as
    `usage.server_tool_use.web_search_requests`, and the cost audit trail (spec §4.3) is
    only honest if it records that rather than a flat +1.

    A plain `list` subclass rather than a new return type on purpose: every existing caller
    and test that treats the result as a list of dicts keeps working unchanged, and
    `searches_used_by` reads the count back with a safe fallback.
    """

    searches_used: int = 1


def searches_used_by(results) -> int:
    """Number of server-side web_search requests `results` cost.

    Falls back to 1 for anything that is not a SearchResults -- a stubbed search in a test,
    or the empty list a caller substitutes when the call raised. Never raises.
    """
    try:
        return max(0, int(getattr(results, "searches_used", 1)))
    except (TypeError, ValueError):
        return 1


def _searches_used_from_response(response) -> int:
    """Read usage.server_tool_use.web_search_requests off an SDK response.

    Defensive at every hop: usage, server_tool_use and the counter are each optional in
    the SDK's types, and a mocked response may carry none of them. Falls back to 1 -- the
    old flat-count behaviour -- rather than letting a missing field break discovery.
    """
    usage = getattr(response, "usage", None)
    server_tool_use = getattr(usage, "server_tool_use", None)
    count = getattr(server_tool_use, "web_search_requests", None)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return 1
    return count


def build_query(filter_obj: Filter, institution: Institution) -> str:
    """Build the discovery search query for one institution, from the filter's
    first degree level and first field (spec section 6.0's worked example)."""
    degree_level = filter_obj.degree_levels[0]
    field = filter_obj.fields[0]
    return (
        f"{degree_level} {field} scholarship international students site info "
        f"for {institution.name}"
    )


def search_institution(
    institution: Institution,
    filter_obj: Filter,
    api_key: str,
    max_uses: int = 3,
) -> list[dict]:
    """Run one domain-scoped Claude web_search against a single institution.

    Returns a list of {"url": str, "title": str} dicts, deduplicated by URL and
    in the order results were returned. Never fetches full page content -- only
    URL/title metadata read from the web_search_tool_result content block.

    A server-tool error (HTTP 200 with an error object in place of a result
    list, per the Anthropic API's server-tool error contract) degrades to an
    empty list rather than raising -- consistent with "every error degrades
    toward UNKNOWN-GATED, never toward deletion" (spec principle 4). The
    caller (discovery/run.py) still counts the institution as considered; it
    simply gets zero candidates from it.

    The returned list is a `SearchResults`, carrying `searches_used` read from the
    response's usage block -- this call can bill up to `max_uses` server-side searches, so
    the caller must not assume one.
    """
    client = anthropic.Anthropic(api_key=api_key)
    query = build_query(filter_obj, institution)

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": query}],
        tools=[
            {
                "type": _WEB_SEARCH_TOOL_TYPE,
                "name": "web_search",
                "max_uses": max_uses,
                "allowed_domains": [institution.domain],
            }
        ],
    )

    results = SearchResults()
    results.searches_used = _searches_used_from_response(response)
    seen_urls: set[str] = set()

    for block in response.content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        content = block.content
        if not isinstance(content, list):
            # Error shape: content is a single object, e.g.
            # {"error_code": "max_uses_exceeded"}. Skip, don't raise.
            continue
        for item in content:
            url = getattr(item, "url", None)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = getattr(item, "title", None) or ""
            results.append({"url": url, "title": title})

    return results


def search_domain(domain: str, query: str, api_key: str, max_uses: int = 1) -> list[dict]:
    """Run one domain-scoped Claude web_search against a bare registrable domain.

    Sibling to search_institution, for a caller (the digger) that has a
    registrable domain and a free-text query but no Institution/Filter pair to
    build one from via build_query(). Same URL/title-only, deduplicated,
    error-degrades-to-[] contract as search_institution, including the `searches_used`
    count carried on the returned SearchResults.
    """
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": query}],
        tools=[
            {
                "type": _WEB_SEARCH_TOOL_TYPE,
                "name": "web_search",
                "max_uses": max_uses,
                "allowed_domains": [domain],
            }
        ],
    )

    results = SearchResults()
    results.searches_used = _searches_used_from_response(response)
    seen_urls: set[str] = set()

    for block in response.content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        content = block.content
        if not isinstance(content, list):
            continue
        for item in content:
            url = getattr(item, "url", None)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = getattr(item, "title", None) or ""
            results.append({"url": url, "title": title})

    return results
