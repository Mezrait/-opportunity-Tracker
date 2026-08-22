# Opportunity Tracker Implementation Plan — Part D: Discovery (Tasks 14–15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

This file covers Tasks 14–15 of the Opportunity Tracker implementation plan. It builds on
Tasks 1–4 (`docs/superpowers/plans/2026-08-22-opportunity-tracker.md`), which define
`src/opportunity_tracker/models.py`, `config.py`, and `db.py` exactly as they exist in that
file — nothing here redefines any dataclass, enum, or table from those modules.

**Spec:** `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md` — primarily §6.0
(discovery), §4.3 (why `institution`/`filter`/`discovery_run`/`candidate` exist), principle 7
(discovery misses are logged, never silent), and §12's decision log entries on `web_search`
and discovery caching.

**Dependency note:** Task 15 (`discovery/run.py`) imports `directory.list_institutions` from
Task 8 (`src/opportunity_tracker/directory.py`, specified in
`docs/superpowers/plans/2026-08-22-opportunity-tracker-part-b-sync.md`). Task 8's assumed
contract, as consumed here, is `list_institutions(conn: sqlite3.Connection, country: str) ->
list[Institution]` — institutions already loaded into the `institution` table, filtered by
country. Task 15 cannot be run against a real database until Task 8 exists; its own tests
mock `directory.list_institutions` directly, so they do not require Task 8 to be implemented
first, only importable-or-mocked at the module-attribute level Task 15's code references.

---

### Task 14: Claude web_search wrapper (`discovery/websearch.py`)

**Files:**
- Create: `src/opportunity_tracker/discovery/__init__.py`
- Create: `src/opportunity_tracker/discovery/websearch.py`
- Create: `tests/unit/discovery/__init__.py` (empty — makes `tests/unit/discovery` a proper
  package so pytest imports its test modules under a qualified name; several other
  components in this plan are also named `run.py`, and an unqualified `test_run.py` in two
  different test directories would otherwise collide under pytest's rootless import mode)
- Test: `tests/unit/discovery/test_websearch.py`

**Interfaces:**
- Consumes: `opportunity_tracker.models.Institution` (fields: `id`, `name`, `country`,
  `country_code`, `domain`, `source`, `directory_version`, `added_at`),
  `opportunity_tracker.models.Filter` (fields: `id`, `name`, `country`, `degree_levels:
  list[str]`, `fields: list[str]`, `funding_type`, `deadline_after`, `min_grade`,
  `institution_cap`, `content_hash`, `created_at`) — both from Task 2's `models.py`,
  unmodified. Also the third-party `anthropic.Anthropic` client class.
- Produces: `search_institution(institution: Institution, filter_obj: Filter, api_key: str,
  max_uses: int = 3) -> list[dict]` — the function Task 15 (`discovery/run.py`) calls once
  per institution. Also `build_query(filter_obj: Filter, institution: Institution) -> str` —
  a small discoverable helper factored out so Task 15 can compute the identical query string
  to store as `candidate.query_used`, instead of duplicating the query-building logic.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/discovery/test_websearch.py
"""Tests for the Claude web_search wrapper. anthropic.Anthropic is mocked entirely --
this suite never calls the real Anthropic API."""
from opportunity_tracker.discovery.websearch import build_query, search_institution
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


class _FakeResultItem:
    """Shaped like the SDK's web_search_result content items: .url, .title."""

    def __init__(self, url, title):
        self.url = url
        self.title = title


class _FakeContentBlock:
    """Shaped like a Message.content entry: .type, .content."""

    def __init__(self, block_type, content):
        self.type = block_type
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def test_build_query_uses_first_degree_level_and_field():
    query = build_query(_make_filter(), _make_institution())
    assert query == (
        "PhD Computer Science scholarship international students site info "
        "for University of Western Australia"
    )


def test_search_institution_extracts_and_dedupes_results(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(content=[
        _FakeContentBlock("text", "some preamble"),
        _FakeContentBlock("web_search_tool_result", [
            _FakeResultItem("https://uwa.edu.au/scholarships/rtp", "RTP Scholarship"),
            _FakeResultItem("https://uwa.edu.au/scholarships/rtp", "RTP Scholarship (dup)"),
            _FakeResultItem("https://uwa.edu.au/scholarships/other", "Other Scholarship"),
        ]),
    ])
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    results = search_institution(_make_institution(), _make_filter(), api_key="sk-test")

    assert results == [
        {"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP Scholarship"},
        {"url": "https://uwa.edu.au/scholarships/other", "title": "Other Scholarship"},
    ]


def test_search_institution_scopes_tools_argument_to_institution_domain(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(content=[])
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    search_institution(_make_institution(), _make_filter(), api_key="sk-test", max_uses=5)

    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "allowed_domains": ["uwa.edu.au"],
        }
    ]
    assert kwargs["messages"][0]["content"] == (
        "PhD Computer Science scholarship international students site info "
        "for University of Western Australia"
    )


def test_search_institution_handles_server_tool_error_block(mocker):
    # Server-tool errors return HTTP 200 with content as a single error object
    # instead of a list -- must degrade to [] rather than raise or index-crash.
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(content=[
        _FakeContentBlock("web_search_tool_result", {"error_code": "max_uses_exceeded"}),
    ])
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    results = search_institution(_make_institution(), _make_filter(), api_key="sk-test")

    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/discovery/test_websearch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.discovery'`

- [ ] **Step 3: Write `src/opportunity_tracker/discovery/__init__.py`**

```python
```

(empty — marks `discovery` as a package)

- [ ] **Step 3b: Write `tests/unit/discovery/__init__.py`**

```python
```

(empty)

- [ ] **Step 3c: Write `src/opportunity_tracker/discovery/websearch.py`**

```python
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

    results: list[dict] = []
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/discovery/test_websearch.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/discovery/__init__.py \
        src/opportunity_tracker/discovery/websearch.py \
        tests/unit/discovery/__init__.py \
        tests/unit/discovery/test_websearch.py
git commit -m "feat: domain-scoped Claude web_search wrapper for discovery"
```

---

### Task 15: Discovery run orchestration (`discovery/run.py`)

**Files:**
- Create: `src/opportunity_tracker/discovery/run.py`
- Test: `tests/unit/discovery/test_run.py`

**Interfaces:**
- Consumes:
  - `opportunity_tracker.config.STALENESS_DAYS` (Task 3, `= 30`).
  - `opportunity_tracker.models.DiscoveryRun`, `DiscoveryRunStatus`, `Filter`,
    `InstitutionSource` (Task 2, unmodified).
  - `opportunity_tracker.db` schema tables `discovery_run`, `candidate`, `institution`,
    `filter` (Task 4) — accessed via raw SQL against the `sqlite3.Connection` passed in, no
    ORM.
  - `opportunity_tracker.directory.list_institutions(conn: sqlite3.Connection, country: str)
    -> list[Institution]` (Task 8 — see the dependency note at the top of this file for the
    assumed contract).
  - `opportunity_tracker.discovery.websearch.search_institution(institution, filter_obj,
    api_key, max_uses=3) -> list[dict]` and `websearch.build_query(filter_obj, institution)
    -> str` (Task 14, this file, above). Both are called as `websearch.search_institution(...)`
    / `websearch.build_query(...)` (module-qualified, not `from ... import ...`) so tests can
    mock them at `opportunity_tracker.discovery.websearch.search_institution`.
- Produces:
  - `run_discovery(filter_obj: Filter, conn: sqlite3.Connection, api_key: str,
    force_rediscover: bool = False) -> DiscoveryRun` — the entry point later called by the
    CLI (`optrack run` / `optrack discover`, a later task).
  - `ingest_manual_pins(seeds_yaml_path: str, conn: sqlite3.Connection) -> list[int]` — the
    entry point later called by the CLI for `seeds.yaml` ingestion.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/discovery/test_run.py
"""Tests for discovery run orchestration: caching, institution_cap enforcement,
principle-7 counting, and manual pin ingestion. websearch.search_institution and
directory.list_institutions are always mocked -- this suite never calls the real
Anthropic API or a real database file (uses in-memory sqlite)."""
import json

import pytest
import yaml

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.discovery.run import ingest_manual_pins, run_discovery
from opportunity_tracker.models import DiscoveryRunStatus, Filter, Institution, InstitutionSource


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    return c


def _insert_filter(conn, content_hash="hash-1", institution_cap=50, country="Australia"):
    cursor = conn.execute(
        "INSERT INTO filter (name, country, degree_levels, fields, funding_type, "
        "deadline_after, min_grade, institution_cap, content_hash, created_at) "
        "VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
        (
            "AU PhD CS",
            country,
            json.dumps(["PhD"]),
            json.dumps(["Computer Science"]),
            institution_cap,
            content_hash,
            "2026-08-22T00:00:00+00:00",
        ),
    )
    conn.commit()
    return Filter(
        id=cursor.lastrowid,
        name="AU PhD CS",
        country=country,
        degree_levels=["PhD"],
        fields=["Computer Science"],
        funding_type=None,
        deadline_after=None,
        min_grade=None,
        institution_cap=institution_cap,
        content_hash=content_hash,
        created_at="2026-08-22T00:00:00+00:00",
    )


def _insert_institution(conn, domain, name=None, country="Australia", country_code="AU"):
    name = name or domain
    cursor = conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, country, country_code, domain, InstitutionSource.HIPO_DIRECTORY.value,
         "2026.1", "2026-08-22T00:00:00+00:00"),
    )
    conn.commit()
    return Institution(
        id=cursor.lastrowid,
        name=name,
        country=country,
        country_code=country_code,
        domain=domain,
        source=InstitutionSource.HIPO_DIRECTORY,
        directory_version="2026.1",
        added_at="2026-08-22T00:00:00+00:00",
    )


def test_run_discovery_caches_within_staleness_window(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "uwa.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    search_mock = mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        return_value=[{"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP"}],
    )

    first = run_discovery(filter_obj, conn, api_key="sk-test")
    assert first.status == DiscoveryRunStatus.COMPLETED
    assert search_mock.call_count == 1

    second = run_discovery(filter_obj, conn, api_key="sk-test")
    assert second.id == first.id
    assert search_mock.call_count == 1  # not called again -- cache hit


def test_force_rediscover_bypasses_cache(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "uwa.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    search_mock = mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        return_value=[{"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP"}],
    )

    first = run_discovery(filter_obj, conn, api_key="sk-test")
    second = run_discovery(filter_obj, conn, api_key="sk-test", force_rediscover=True)

    assert second.id != first.id
    assert search_mock.call_count == 2


def test_institution_with_no_results_still_counted_considered(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "empty.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    mocker.patch("opportunity_tracker.discovery.websearch.search_institution", return_value=[])

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.institutions_considered == 1
    assert run.institutions_with_candidates == 0
    assert run.status == DiscoveryRunStatus.COMPLETED


def test_institution_cap_is_respected(mocker, conn):
    filter_obj = _insert_filter(conn, institution_cap=2)
    institutions = [
        _insert_institution(conn, f"uni{i}.edu.au", name=f"Uni {i}") for i in range(5)
    ]
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=institutions)
    search_mock = mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution", return_value=[]
    )

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert search_mock.call_count == 2
    assert run.institutions_considered == 2


def test_search_failure_for_one_institution_does_not_abort_run(mocker, conn):
    filter_obj = _insert_filter(conn)
    bad = _insert_institution(conn, "bad.edu.au", name="Bad Uni")
    good = _insert_institution(conn, "good.edu.au", name="Good Uni")
    mocker.patch(
        "opportunity_tracker.directory.list_institutions", return_value=[bad, good]
    )

    def _side_effect(institution, filter_obj_arg, api_key, max_uses=3):
        if institution.domain == "bad.edu.au":
            raise RuntimeError("network exploded")
        return [{"url": "https://good.edu.au/scholarships/rtp", "title": "RTP"}]

    mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution", side_effect=_side_effect
    )

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.status == DiscoveryRunStatus.COMPLETED
    assert run.institutions_considered == 2
    assert run.institutions_with_candidates == 1


def test_ingest_manual_pins_creates_candidate_with_null_discovery_run(tmp_path, conn):
    seeds_path = tmp_path / "seeds.yaml"
    seeds_path.write_text(
        yaml.safe_dump([
            {
                "institution_domain": "pinned.edu.au",
                "url": "https://pinned.edu.au/scholarships/manual",
                "name": "Pinned University",
                "country": "Australia",
                "country_code": "AU",
            }
        ]),
        encoding="utf-8",
    )

    new_ids = ingest_manual_pins(str(seeds_path), conn)

    assert len(new_ids) == 1
    row = conn.execute(
        "SELECT discovery_run_id, query_used, url FROM candidate WHERE id = ?",
        (new_ids[0],),
    ).fetchone()
    assert row["discovery_run_id"] is None
    assert row["query_used"] == "manual_pin"
    assert row["url"] == "https://pinned.edu.au/scholarships/manual"

    institution_row = conn.execute(
        "SELECT source FROM institution WHERE domain = ?", ("pinned.edu.au",)
    ).fetchone()
    assert institution_row["source"] == InstitutionSource.MANUAL.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/discovery/test_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.discovery.run'`

- [ ] **Step 3: Write `src/opportunity_tracker/discovery/run.py`**

```python
"""Discovery run orchestration: filter -> candidate rows, with caching and manual
pin ingestion. Spec sections 6.0, 4.3, and principle 7 (NO_CANDIDATE_FOUND, never
silent)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import yaml

from opportunity_tracker import config, directory
from opportunity_tracker.discovery import websearch
from opportunity_tracker.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    Filter,
    InstitutionSource,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_discovery_run(row: sqlite3.Row) -> DiscoveryRun:
    return DiscoveryRun(
        id=row["id"],
        filter_id=row["filter_id"],
        filter_content_hash=row["filter_content_hash"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        institutions_considered=row["institutions_considered"],
        institutions_with_candidates=row["institutions_with_candidates"],
        searches_used=row["searches_used"],
        status=DiscoveryRunStatus(row["status"]),
    )


def _find_reusable_run(conn: sqlite3.Connection, filter_obj: Filter) -> DiscoveryRun | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.STALENESS_DAYS)).isoformat()
    row = conn.execute(
        "SELECT * FROM discovery_run WHERE filter_content_hash = ? AND status = ? "
        "AND started_at >= ? ORDER BY started_at DESC LIMIT 1",
        (filter_obj.content_hash, DiscoveryRunStatus.COMPLETED.value, cutoff),
    ).fetchone()
    return None if row is None else _row_to_discovery_run(row)


def run_discovery(
    filter_obj: Filter,
    conn: sqlite3.Connection,
    api_key: str,
    force_rediscover: bool = False,
) -> DiscoveryRun:
    """Run (or reuse) a discovery pass for `filter_obj`.

    Unless `force_rediscover`, a completed discovery_run with the same
    filter_content_hash started within config.STALENESS_DAYS is returned
    unchanged -- no new searches are spent (spec section 6.0 caching, section
    12 decision log: mirrors the fetcher's "unchanged hash => no downstream
    work" rule).

    Otherwise a new discovery_run row is inserted with status='running', and
    every institution the directory lists for `filter_obj.country` (capped at
    `filter_obj.institution_cap`) is searched via websearch.search_institution.
    An institution that yields zero results, or whose search call raises, is
    still counted in `institutions_considered` -- principle 7: discovery
    misses are logged, not silent. It is simply excluded from
    `institutions_with_candidates`. The row is updated to status='completed'
    once every institution has been processed.
    """
    if not force_rediscover:
        reusable = _find_reusable_run(conn, filter_obj)
        if reusable is not None:
            return reusable

    started_at = _now_iso()
    cursor = conn.execute(
        "INSERT INTO discovery_run (filter_id, filter_content_hash, started_at, "
        "completed_at, institutions_considered, institutions_with_candidates, "
        "searches_used, status) VALUES (?, ?, ?, NULL, 0, 0, 0, ?)",
        (filter_obj.id, filter_obj.content_hash, started_at, DiscoveryRunStatus.RUNNING.value),
    )
    conn.commit()
    run_id = cursor.lastrowid

    institutions = directory.list_institutions(conn, filter_obj.country)
    institutions = institutions[: filter_obj.institution_cap]

    institutions_considered = 0
    institutions_with_candidates = 0
    searches_used = 0

    for institution in institutions:
        institutions_considered += 1
        query_used = websearch.build_query(filter_obj, institution)

        try:
            results = websearch.search_institution(institution, filter_obj, api_key)
        except Exception:
            # A search failure degrades to "no candidate found" for this one
            # institution rather than aborting the whole run -- principle 4:
            # every error degrades toward UNKNOWN-GATED, never toward
            # deletion. The institution is still counted above; it's simply
            # excluded from institutions_with_candidates below.
            results = []
        searches_used += 1

        if results:
            institutions_with_candidates += 1
            for result in results:
                conn.execute(
                    "INSERT INTO candidate (discovery_run_id, institution_id, url, "
                    "query_used, found_at, promoted_to_award_id) VALUES "
                    "(?, ?, ?, ?, ?, NULL)",
                    (run_id, institution.id, result["url"], query_used, _now_iso()),
                )

        conn.execute(
            "UPDATE discovery_run SET institutions_considered = ?, "
            "institutions_with_candidates = ?, searches_used = ? WHERE id = ?",
            (institutions_considered, institutions_with_candidates, searches_used, run_id),
        )
        conn.commit()

    conn.execute(
        "UPDATE discovery_run SET completed_at = ?, status = ? WHERE id = ?",
        (_now_iso(), DiscoveryRunStatus.COMPLETED.value, run_id),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM discovery_run WHERE id = ?", (run_id,)).fetchone()
    return _row_to_discovery_run(row)


def ingest_manual_pins(seeds_yaml_path: str, conn: sqlite3.Connection) -> list[int]:
    """Ingest operator-curated seeds.yaml pins as `candidate` rows.

    Each seed is a mapping with at least `institution_domain` and `url`; it may
    optionally carry `name`, `country`, `country_code` to fill in a new
    institution row. The institution is looked up by domain; if missing, it's
    created with source=InstitutionSource.MANUAL, defaulting `name` to the
    domain and `country`/`country_code` to "Unknown"/"XX" when not given in
    the seed. Every inserted candidate has discovery_run_id=NULL and
    query_used='manual_pin', and is never deduplicated against discovery
    results -- a pin always represents explicit operator intent (spec section
    4.3). Returns the list of newly-inserted candidate ids, in seed order.
    """
    with open(seeds_yaml_path, "r", encoding="utf-8") as f:
        seeds = yaml.safe_load(f) or []

    new_candidate_ids: list[int] = []

    for seed in seeds:
        domain = seed["institution_domain"]
        url = seed["url"]

        institution_row = conn.execute(
            "SELECT id FROM institution WHERE domain = ?", (domain,)
        ).fetchone()

        if institution_row is None:
            cursor = conn.execute(
                "INSERT INTO institution (name, country, country_code, domain, "
                "source, directory_version, added_at) VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (
                    seed.get("name", domain),
                    seed.get("country", "Unknown"),
                    seed.get("country_code", "XX"),
                    domain,
                    InstitutionSource.MANUAL.value,
                    _now_iso(),
                ),
            )
            institution_id = cursor.lastrowid
        else:
            institution_id = institution_row["id"]

        cursor = conn.execute(
            "INSERT INTO candidate (discovery_run_id, institution_id, url, "
            "query_used, found_at, promoted_to_award_id) VALUES "
            "(NULL, ?, ?, 'manual_pin', ?, NULL)",
            (institution_id, url, _now_iso()),
        )
        new_candidate_ids.append(cursor.lastrowid)
        conn.commit()

    return new_candidate_ids
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/discovery/test_run.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/discovery/run.py tests/unit/discovery/test_run.py
git commit -m "feat: discovery run orchestration with caching and manual pin ingestion"
```
