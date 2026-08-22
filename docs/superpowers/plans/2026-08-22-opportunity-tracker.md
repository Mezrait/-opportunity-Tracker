# Opportunity Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-user Python CLI that discovers scholarship/research-degree
opportunities across every institution in an operator-specified country matching a filter,
extracts their requirements with provenance, evaluates them against the operator's profile,
and produces a ranked report — without ever silently hiding a record or fabricating a value.

**Architecture:** A linear pipeline (`filter → discovery → fetcher → extractor → evaluator →
reporter`, with a `digger` gap-filler after extraction) backed by a single SQLite file.
Every stage is append-only and provenance-tracked. Deterministic stages (evaluator,
tiering, discovery caching) are pure functions with no network/LLM access, unit-tested with
TDD. Non-deterministic stages (fetcher, discovery search, extractor, digger) wrap a single
external call each behind a narrow interface, tested with mocked transports/clients.

**Tech Stack:** Python 3.12 managed by `uv` · SQLite (stdlib `sqlite3`) · Typer (CLI) ·
httpx (HTTP fetch) · Playwright (headless fetch) · pdfplumber (PDF text) · `anthropic` SDK
(extractor LLM calls + `web_search` tool for discovery) · PyYAML · python-dotenv · pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md`

## Global Constraints

Copied verbatim from the spec — every task's work implicitly includes these:

- Only Tier 1 sources may write to `requirement` fields; Tier 2/3 never write, only inform. (§5)
- Three-valued logic throughout: pass / fail / unknown. `unknown` never collapses to pass or fail, at any layer. (§3.3)
- Every error degrades toward UNKNOWN-GATED — never toward ELIGIBLE, never toward silent deletion. (§3.4)
- No record is ever hidden or deleted from the report. (§3.1)
- An institution considered by discovery with no candidate found is recorded as `NO_CANDIDATE_FOUND`, never silently absent. (§3.7)
- The extractor never receives the operator's profile in its prompt. (§6.2)
- The evaluator makes no network calls and no LLM calls. (§6.5)
- Re-extraction inserts new `requirement` rows; it never updates existing ones. (§4.4)
- Grade comparison (GPA→WAM) is never automated — an unconverted grade threshold yields `unknown`. (§6.5)
- Default trust threshold: 0.85 recall, per requirement kind, before that kind may produce a LIKELY BLOCKED verdict. (§9.3)
- Default staleness threshold: 30 days — a `requirement` older than this cannot contribute to an ACT NOW bucket. (§7, §11)
- Default `institution_cap`: 50 institutions per discovery run, configurable per filter. (§6.0)
- Discovery only ever searches within a single institution's own domain (`allowed_domains` scoped) — never the open web. (§2, §6.0)
- Digger's budget: 5 fetches, depth 2, same registrable domain, one target field per invocation. (§6.3)

---

## File Structure

```
pyproject.toml, .gitignore, .env.example, README.md
profile.example.yaml, filter.example.yaml, seeds.example.yaml
data/university_directory.json          # vendored Hipo dataset (committed)
src/opportunity_tracker/
    __init__.py
    models.py            # dataclasses + enums, zero I/O — the shared vocabulary
    config.py             # env loading, tunable constants
    db.py                  # schema DDL + connection helper
    tiering.py              # domain -> SourceTier classification
    profile.py               # profile.yaml <-> `profile` table sync
    filters.py                # filter.yaml <-> `filter` table sync
    directory.py                # Hipo JSON -> `institution` table loader
    fetcher/
        __init__.py
        robots.py                 # robots.txt compliance + per-host rate limiting
        http_fetch.py               # plain HTTP GET + degraded-fetch heuristic
        headless_fetch.py             # Playwright-based fetch
        pdf_fetch.py                    # PDF text extraction
        pipeline.py                       # orchestrates fetch strategy, hashing, `document` writes
    discovery/
        __init__.py
        websearch.py                       # Claude web_search wrapper, domain-scoped
        run.py                               # discovery_run orchestration + caching + manual pins
    extractor/
        __init__.py
        schema.py                             # requirement JSON schema (closed kind enum)
        prompts.py                              # extractor prompt template
        evidence.py                               # fuzzy evidence-span validator
        run.py                                      # single LLM call, retry-once, writes `requirement`
    digger/
        __init__.py
        run.py                                        # bounded gap-filler sub-agent
    evaluator/
        __init__.py
        rules.py                                        # per-kind three-valued pass/fail/unknown
        feasibility.py                                    # lead-time estimate
        trust.py                                            # gold-set recall gating
        bucket.py                                            # bucket assignment + sort keys
        run.py                                                # orchestrates one award's evaluation
    reporter/
        __init__.py
        markdown.py                                            # markdown report + discovery coverage
        csv_report.py                                            # CSV export
    cli.py                                                        # Typer app wiring every command
tests/
    unit/                 # one test file per module above, TDD
    fixtures/              # sample YAML/JSON/PDF/robots.txt fixtures, gold_set/ (populated later)
scripts/
    eval_gold_set.py        # per-kind recall/precision report against tests/fixtures/gold_set/
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/opportunity_tracker/__init__.py`
- Create: `README.md`

**Interfaces:**
- Produces: an importable `opportunity_tracker` package under a `uv`-managed venv; `uv run pytest` and `uv run optrack` both resolve.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "opportunity-tracker"
version = "0.1.0"
description = "Single-user CLI that discovers, verifies, and ranks scholarship/research-degree opportunities."
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12",
    "httpx>=0.27",
    "playwright>=1.45",
    "pdfplumber>=0.11",
    "anthropic>=0.34",
    "python-dotenv>=1.0",
    "pyyaml>=6.0",
]

[project.scripts]
optrack = "opportunity_tracker.cli:app"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-mock>=3.14",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/opportunity_tracker"]
```

- [ ] **Step 2: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
*.db
data/*.db
.pytest_cache/
*.egg-info/
```

- [ ] **Step 3: Create `.env.example`**

```
ANTHROPIC_API_KEY=
```

- [ ] **Step 4: Create `src/opportunity_tracker/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: Create minimal `README.md`**

```markdown
# Opportunity Tracker

Single-user CLI that discovers scholarship/research-degree opportunities matching a
filter (country, degree level, field), verifies their requirements against primary
sources, and ranks them against your profile.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) if you don't have it.
2. `uv sync` — provisions Python 3.12 and installs all dependencies.
3. `cp .env.example .env` and fill in `ANTHROPIC_API_KEY`.
4. `cp profile.example.yaml profile.yaml` and fill in your details.
5. `cp filter.example.yaml filter.yaml` and set your target country/degree/field.
6. `uv run optrack init-db` — creates `opportunity_tracker.db`.
7. `uv run optrack run` — runs the full pipeline: discover, fetch, extract, evaluate, report.

See `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md` for the full design.
```

- [ ] **Step 6: Provision the environment**

Run: `uv sync`
Expected: creates `.venv/`, installs all dependencies, no errors. `uv` provisions its own
Python 3.12 — no separate interpreter install needed.

- [ ] **Step 7: Verify the package imports**

Run: `uv run python -c "import opportunity_tracker; print(opportunity_tracker.__version__)"`
Expected: prints `0.1.0`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore .env.example README.md src/opportunity_tracker/__init__.py uv.lock
git commit -m "chore: project scaffolding with uv"
```

---

### Task 2: Core data structures (`models.py`)

**Files:**
- Create: `src/opportunity_tracker/models.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `RequirementKind`, `REQUIRED_KINDS`, `INFORMATIONAL_KINDS`, `FetchMethod`,
  `SourceTier`, `InstitutionSource`, `Bucket`, `Outcome`, `DiscoveryRunStatus` enums; and
  frozen dataclasses `Scheme`, `Award`, `Document`, `Requirement`, `Profile`, `Evaluation`,
  `UnclassifiedRule`, `Institution`, `Filter`, `DiscoveryRun`, `Candidate` — the exact field
  names/types every later task constructs and consumes. This module has zero I/O and zero
  dependencies on any other project module.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_models.py
from opportunity_tracker.models import RequirementKind, REQUIRED_KINDS, INFORMATIONAL_KINDS


def test_required_and_informational_kinds_partition_the_enum():
    assert REQUIRED_KINDS | INFORMATIONAL_KINDS == set(RequirementKind)
    assert REQUIRED_KINDS & INFORMATIONAL_KINDS == set()


def test_research_project_fraction_is_required():
    assert RequirementKind.RESEARCH_PROJECT_FRACTION in REQUIRED_KINDS


def test_supervisor_required_is_informational():
    assert RequirementKind.SUPERVISOR_REQUIRED in INFORMATIONAL_KINDS
    assert RequirementKind.SUPERVISOR_REQUIRED not in REQUIRED_KINDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.models'`

- [ ] **Step 3: Write `src/opportunity_tracker/models.py`**

```python
"""Core data structures shared across the pipeline. No I/O in this module."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RequirementKind(str, Enum):
    MIN_GRADE = "min_grade"
    RESEARCH_PROJECT_FRACTION = "research_project_fraction"
    THESIS_REQUIRED = "thesis_required"
    ENGLISH_TEST = "english_test"
    NATIONALITY = "nationality"
    DEADLINE = "deadline"
    DEGREE_LEVEL = "degree_level"
    SUPERVISOR_REQUIRED = "supervisor_required"
    PRIOR_SCHOLARSHIP_EXCLUSION = "prior_scholarship_exclusion"
    RETURN_OBLIGATION = "return_obligation"
    FUNDING_COMPONENT = "funding_component"
    INTAKE_YEAR = "intake_year"


REQUIRED_KINDS: frozenset[RequirementKind] = frozenset({
    RequirementKind.DEADLINE,
    RequirementKind.DEGREE_LEVEL,
    RequirementKind.INTAKE_YEAR,
    RequirementKind.THESIS_REQUIRED,
    RequirementKind.RESEARCH_PROJECT_FRACTION,
    RequirementKind.MIN_GRADE,
    RequirementKind.ENGLISH_TEST,
    RequirementKind.NATIONALITY,
})

INFORMATIONAL_KINDS: frozenset[RequirementKind] = frozenset({
    RequirementKind.SUPERVISOR_REQUIRED,
    RequirementKind.PRIOR_SCHOLARSHIP_EXCLUSION,
    RequirementKind.RETURN_OBLIGATION,
    RequirementKind.FUNDING_COMPONENT,
})


class FetchMethod(str, Enum):
    HTTP = "http"
    HEADLESS = "headless"
    PDF = "pdf"


class SourceTier(int, Enum):
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class InstitutionSource(str, Enum):
    HIPO_DIRECTORY = "hipo_directory"
    MANUAL = "manual"


class Bucket(str, Enum):
    ACT_NOW = "ACT_NOW"
    ELIGIBLE_LATER = "ELIGIBLE_LATER"
    UNKNOWN_GATED = "UNKNOWN_GATED"
    LIKELY_BLOCKED = "LIKELY_BLOCKED"


class Outcome(str, Enum):
    """Three-valued logic result for a single requirement."""
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class DiscoveryRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Scheme:
    id: int
    name: str
    funder: str | None
    jurisdiction: str | None


@dataclass(frozen=True)
class Award:
    id: int
    scheme_id: int | None
    institution: str
    country: str
    degree_levels: list[str]
    intake_year: int | None
    canonical_url: str


@dataclass(frozen=True)
class Document:
    id: int
    url: str
    source_tier: SourceTier
    fetch_method: FetchMethod
    content_hash: str
    text_path: str | None
    retrieved_at: str
    fetch_status: str
    degraded: bool


@dataclass(frozen=True)
class Requirement:
    id: int
    award_id: int
    document_id: int
    kind: RequirementKind
    operator: str | None
    value: str | None
    unit: str | None
    raw_text: str
    evidence: str
    confidence: float | None
    extracted_at: str
    human_verified: bool


@dataclass(frozen=True)
class Profile:
    id: int
    version: int
    created_at: str
    attributes: dict


@dataclass(frozen=True)
class Evaluation:
    id: int
    award_id: int
    profile_version: int
    evaluated_at: str
    bucket: Bucket
    sort_keys: dict
    per_requirement_outcomes: dict


@dataclass(frozen=True)
class UnclassifiedRule:
    id: int
    document_id: int
    raw_text: str
    logged_at: str
    reviewed: bool


@dataclass(frozen=True)
class Institution:
    id: int
    name: str
    country: str
    country_code: str
    domain: str
    source: InstitutionSource
    directory_version: str | None
    added_at: str


@dataclass(frozen=True)
class Filter:
    id: int
    name: str
    country: str
    degree_levels: list[str]
    fields: list[str]
    funding_type: str | None
    deadline_after: str | None
    min_grade: str | None
    institution_cap: int
    content_hash: str
    created_at: str


@dataclass(frozen=True)
class DiscoveryRun:
    id: int
    filter_id: int
    filter_content_hash: str
    started_at: str
    completed_at: str | None
    institutions_considered: int
    institutions_with_candidates: int
    searches_used: int
    status: DiscoveryRunStatus


@dataclass(frozen=True)
class Candidate:
    id: int
    discovery_run_id: int | None
    institution_id: int
    url: str
    query_used: str
    found_at: str
    promoted_to_award_id: int | None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/models.py tests/unit/test_models.py
git commit -m "feat: core data structures (models.py)"
```

---

### Task 3: Configuration (`config.py`)

**Files:**
- Create: `src/opportunity_tracker/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nothing (reads environment only).
- Produces: `STALENESS_DAYS = 30`, `TRUST_THRESHOLD_DEFAULT = 0.85`,
  `INSTITUTION_CAP_DEFAULT = 50`, `FEASIBILITY_LEAD_DAYS: dict[str, int | tuple[int, int]]`,
  `DB_PATH = "opportunity_tracker.db"`, `UNIVERSITY_DIRECTORY_PATH =
  "data/university_directory.json"`, and `get_anthropic_api_key() -> str` (reads
  `ANTHROPIC_API_KEY` from the environment via `python-dotenv`, raises `RuntimeError` with a
  clear message if unset).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
import pytest

from opportunity_tracker import config


def test_default_constants():
    assert config.STALENESS_DAYS == 30
    assert config.TRUST_THRESHOLD_DEFAULT == 0.85
    assert config.INSTITUTION_CAP_DEFAULT == 50


def test_get_anthropic_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert config.get_anthropic_api_key() == "sk-test-123"


def test_get_anthropic_api_key_raises_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        config.get_anthropic_api_key()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.config'`

- [ ] **Step 3: Write `src/opportunity_tracker/config.py`**

```python
"""Environment loading and tunable constants. Values here are the spec's defaults —
see docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md §9.3, §11, §6.0."""
import os

from dotenv import load_dotenv

load_dotenv()

STALENESS_DAYS = 30
TRUST_THRESHOLD_DEFAULT = 0.85
INSTITUTION_CAP_DEFAULT = 50

# Lead time added per missing prerequisite, in days (§6.4). A tuple is a (min, max) range.
FEASIBILITY_LEAD_DAYS: dict[str, int | tuple[int, int]] = {
    "english_test_result": 21,
    "supervisor_agreement": (28, 42),
    "transcripts": 7,
}

DB_PATH = "opportunity_tracker.db"
UNIVERSITY_DIRECTORY_PATH = "data/university_directory.json"
PROFILE_PATH = "profile.yaml"
FILTER_PATH = "filter.yaml"
SEEDS_PATH = "seeds.yaml"
DENY_LIST_PATH = "data/tier3_deny_list.yaml"


def get_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/config.py tests/unit/test_config.py
git commit -m "feat: environment config and tunable constants"
```

---

### Task 4: Database schema (`db.py`)

**Files:**
- Create: `src/opportunity_tracker/db.py`
- Test: `tests/unit/test_db.py`

**Interfaces:**
- Consumes: `config.DB_PATH`; `models.RequirementKind`, `FetchMethod`, `SourceTier`,
  `Bucket`, `InstitutionSource`, `DiscoveryRunStatus` (for building `CHECK` constraints from
  the single source of truth in `models.py`, never a duplicated literal list).
- Produces: `get_connection(db_path: str) -> sqlite3.Connection` (row_factory set to
  `sqlite3.Row`, foreign keys pragma on) and `init_db(conn: sqlite3.Connection) -> None`
  (idempotent — safe to call on an existing database). Every later task that touches
  storage calls `init_db` once and then executes raw SQL against the returned connection;
  no ORM.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_db.py
import sqlite3

import pytest

from opportunity_tracker.db import get_connection, init_db


def test_init_db_creates_all_tables():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "scheme", "award", "document", "requirement", "profile", "evaluation",
        "unclassified_rule", "institution", "filter", "discovery_run", "candidate",
    }
    assert expected <= tables


def test_init_db_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    init_db(conn)  # must not raise


def test_requirement_roundtrip_and_kind_constraint():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO scheme (name, funder, jurisdiction) VALUES ('S', 'F', 'AU')"
    )
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, 'UWA', 'AU', '[\"phd\"]', 2027, "
        "'https://uwa.edu.au/award')"
    )
    conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES "
        "('https://uwa.edu.au/rules', 1, 'http', 'abc123', 'docs/1.txt', "
        "'2026-08-22T00:00:00', 'ok', 0)"
    )
    conn.execute(
        "INSERT INTO requirement (award_id, document_id, kind, operator, value, "
        "unit, raw_text, evidence, confidence, extracted_at, human_verified) VALUES "
        "(1, 1, 'research_project_fraction', '>=', '0.25', 'fraction', "
        "'at least 25 percent FTE', 'the project must be at least 25 percent FTE', "
        "0.9, '2026-08-22T00:00:00', 0)"
    )
    conn.commit()
    row = conn.execute("SELECT kind, value FROM requirement").fetchone()
    assert row["kind"] == "research_project_fraction"
    assert row["value"] == "0.25"

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO requirement (award_id, document_id, kind, operator, "
            "value, unit, raw_text, evidence, extracted_at, human_verified) VALUES "
            "(1, 1, 'not_a_real_kind', null, null, null, 'x', 'x', "
            "'2026-08-22T00:00:00', 0)"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.db'`

- [ ] **Step 3: Write `src/opportunity_tracker/db.py`**

```python
"""SQLite schema and connection management. Raw SQL, no ORM — see spec §4."""
import sqlite3

from opportunity_tracker.models import (
    Bucket,
    DiscoveryRunStatus,
    FetchMethod,
    InstitutionSource,
    RequirementKind,
)


def _sql_list(values) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS scheme (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        funder TEXT,
        jurisdiction TEXT
    );

    CREATE TABLE IF NOT EXISTS award (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id INTEGER REFERENCES scheme(id),
        institution TEXT NOT NULL,
        country TEXT NOT NULL,
        degree_levels TEXT NOT NULL,
        intake_year INTEGER,
        canonical_url TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS document (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        source_tier INTEGER NOT NULL CHECK (source_tier IN (1, 2, 3)),
        fetch_method TEXT NOT NULL CHECK (fetch_method IN ({_sql_list(FetchMethod)})),
        content_hash TEXT NOT NULL,
        text_path TEXT,
        retrieved_at TEXT NOT NULL,
        fetch_status TEXT NOT NULL,
        degraded INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS requirement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        award_id INTEGER NOT NULL REFERENCES award(id),
        document_id INTEGER NOT NULL REFERENCES document(id),
        kind TEXT NOT NULL CHECK (kind IN ({_sql_list(RequirementKind)})),
        operator TEXT,
        value TEXT,
        unit TEXT,
        raw_text TEXT NOT NULL,
        evidence TEXT NOT NULL,
        confidence REAL,
        extracted_at TEXT NOT NULL,
        human_verified INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        attributes TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS evaluation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        award_id INTEGER NOT NULL REFERENCES award(id),
        profile_version INTEGER NOT NULL REFERENCES profile(version),
        evaluated_at TEXT NOT NULL,
        bucket TEXT NOT NULL CHECK (bucket IN ({_sql_list(Bucket)})),
        sort_keys TEXT NOT NULL,
        per_requirement_outcomes TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS unclassified_rule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER NOT NULL REFERENCES document(id),
        raw_text TEXT NOT NULL,
        logged_at TEXT NOT NULL,
        reviewed INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS institution (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        country TEXT NOT NULL,
        country_code TEXT NOT NULL,
        domain TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL CHECK (source IN ({_sql_list(InstitutionSource)})),
        directory_version TEXT,
        added_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS filter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        country TEXT NOT NULL,
        degree_levels TEXT NOT NULL,
        fields TEXT NOT NULL,
        funding_type TEXT,
        deadline_after TEXT,
        min_grade TEXT,
        institution_cap INTEGER NOT NULL DEFAULT 50,
        content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS discovery_run (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filter_id INTEGER NOT NULL REFERENCES filter(id),
        filter_content_hash TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        institutions_considered INTEGER NOT NULL DEFAULT 0,
        institutions_with_candidates INTEGER NOT NULL DEFAULT 0,
        searches_used INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK (status IN ({_sql_list(DiscoveryRunStatus)}))
    );

    CREATE TABLE IF NOT EXISTS candidate (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discovery_run_id INTEGER REFERENCES discovery_run(id),
        institution_id INTEGER NOT NULL REFERENCES institution(id),
        url TEXT NOT NULL,
        query_used TEXT NOT NULL,
        found_at TEXT NOT NULL,
        promoted_to_award_id INTEGER REFERENCES award(id)
    );
    """)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/db.py tests/unit/test_db.py
git commit -m "feat: SQLite schema for all 11 entities"
```

---

## Remaining tasks (5–27)

Tasks 5 onward (source tiering, profile/filter sync, institution directory loading, the
fetcher, discovery, extractor, digger, evaluator, and reporter/CLI/gold-set harness) are
specified in companion plan-part files, each written against the exact contract fixed in
Tasks 1–4 above (this file's `models.py`, `config.py`, and `db.py` content, byte-for-byte —
no other file may redefine or diverge from these). Task numbering continues across files
with no gaps or overlaps:

- Tasks 5–8 — Config & sync layer (tiering, profile sync, filter sync, institution directory loader): `docs/superpowers/plans/2026-08-22-opportunity-tracker-part-b-sync.md`
- Tasks 9–13 — Fetcher (robots, http, headless, pdf, pipeline): `docs/superpowers/plans/2026-08-22-opportunity-tracker-part-c-fetcher.md`
- Tasks 14–15 — Discovery (websearch wrapper, discovery run orchestration): `docs/superpowers/plans/2026-08-22-opportunity-tracker-part-d-discovery.md`
- Tasks 16–19 — Extractor & digger (schema/prompts, evidence validator, extractor run, digger run): `docs/superpowers/plans/2026-08-22-opportunity-tracker-part-e-extractor.md`
- Tasks 20–23 — Evaluator (rules, feasibility, trust gate, evaluator run): `docs/superpowers/plans/2026-08-22-opportunity-tracker-part-f-evaluator.md`
- Tasks 24–27 — Reporter, CLI, gold-set harness: `docs/superpowers/plans/2026-08-22-opportunity-tracker-part-g-reporter-cli.md`

Executors: complete Tasks 1–4 in this file first (they gate everything else). Then B, C and
D can run in parallel with each other (the sync layer, fetcher, and discovery don't depend
on one another). E depends on C (extractor calls the fetcher pipeline) and on D (digger
reuses discovery's `websearch` module). F depends on B and E (evaluator reads requirements
and profile). G depends on all of the above.
