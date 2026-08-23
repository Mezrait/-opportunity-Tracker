# Opportunity Tracker Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI website (`optrack serve`) that replaces the CLI as the
day-to-day interface: edit profile/search criteria through web forms, run the pipeline
with one click and watch live progress, browse ranked results — all against the same
SQLite DB and pipeline modules the CLI already uses, untouched.

**Architecture:** A new `src/opportunity_tracker/webapp/` package. FastAPI + Jinja2
server-rendered templates, one small vanilla-JS file for progress polling, no build
step. A background `threading.Thread` runs the pipeline for a "Run" click; a
module-level `RunState` singleton tracks its progress; the browser polls a JSON status
endpoint every 1.5s. Six screens: Dashboard, Profile, Searches, Pinned Links, Run,
Results — each its own route module + template, isolated from the others behind a
shared `base.html` layout and a shared `webapp/deps.py` (DB connection + Jinja2
environment).

**Tech Stack:** FastAPI, Uvicorn, Jinja2, python-multipart (form parsing) — added to the
existing Python 3.12 / SQLite / pytest stack. No new frontend framework, no bundler.

**Spec:** `docs/superpowers/specs/2026-08-23-opportunity-tracker-web-ui-design.md`

## Global Constraints

- Python `>=3.12` (existing floor, unchanged).
- The server binds to `127.0.0.1` only, never `0.0.0.0` — no auth, must never be
  reachable off the local machine (spec §2, §3.3).
- Every DB access goes through `db.get_connection(config.DB_PATH)` +
  `db.init_db(conn)` — the same pattern every existing module uses. Route handlers get
  a connection via the `get_db` FastAPI dependency in `webapp/deps.py` (Task 1), never
  by opening one directly.
- The CLI (`cli.py`, `config.py`'s existing constants `PROFILE_PATH`/`FILTER_PATH`/
  `SEEDS_PATH`/`DB_PATH`) is not modified except by the single additive `serve` command
  in Task 1. No existing CLI command's behavior changes.
- No new top-level dependency beyond `fastapi`, `uvicorn`, `jinja2`,
  `python-multipart` (Task 1). No JS framework, no CSS framework, no bundler (spec §2).
- Reuse existing tested logic, never re-derive it: ranking/grouping always goes through
  `reporter.markdown.sort_evaluations` / `BUCKET_ORDER` / `BUCKET_TITLES`; a saved
  search's DB row is always produced by the real `filters.sync_filter`; the profile row
  is always produced by the real `profile.sync_profile`; manual pins always go through
  the real `discovery_run.ingest_manual_pins`.
- Every route module exposes `router = APIRouter()`. Route modules NEVER import the
  shared `app` object from `webapp/app.py` (that would be circular) — they import only
  from `webapp/deps.py` and the core `opportunity_tracker` package.
- Every route module's tests build their OWN minimal `FastAPI()` test app
  (`app = FastAPI(); app.include_router(the_module.router)`) rather than importing the
  real `webapp/app.py` — this keeps each task's tests fully independent of every other
  task's route module, so tasks can be implemented and reviewed in any order, including
  in parallel. Task 9 (wiring) is the only task that touches the real `app.py`.
- DB tests use `db.get_connection(":memory:")` + `db.init_db(conn)`, matching
  `tests/unit/test_db.py`'s existing pattern — no `tmp_path` fixture needed for an
  in-memory DB. Tests that also need `config.PROFILE_PATH`/`FILTER_PATH`/`SEEDS_PATH`
  to point somewhere writable DO use `tmp_path` + `monkeypatch.setattr(config, "...",
  str(tmp_path / "..."))`, one `monkeypatch` call per constant touched.

## File Structure

```
src/opportunity_tracker/webapp/
  __init__.py
  app.py                 # Task 1 (scaffold) + Task 9 (final router wiring)
  deps.py                 # Task 1 — get_db dependency, shared Jinja2Templates
  runner.py                # Task 2 — RunState, start_run, _run_pipeline
  routes_dashboard.py       # Task 3
  routes_profile.py          # Task 4
  routes_searches.py          # Task 5
  routes_pins.py                # Task 6
  routes_run.py                  # Task 7
  routes_results.py                # Task 8
  templates/
    base.html               # Task 1
    dashboard.html            # Task 3
    profile.html                # Task 4
    searches_list.html            # Task 5
    search_form.html                # Task 5
    pins.html                         # Task 6
    run.html                           # Task 7
    results.html                        # Task 8
  static/
    style.css              # Task 1
    poll.js                  # Task 7
tests/unit/webapp/
  __init__.py
  test_runner.py           # Task 2
  test_routes_dashboard.py   # Task 3
  test_routes_profile.py       # Task 4
  test_routes_searches.py        # Task 5
  test_routes_pins.py              # Task 6
  test_routes_run.py                 # Task 7
  test_routes_results.py               # Task 8
web_filters/                # new, gitignored, created at runtime by Task 5's routes
```

---

### Task 1: Web app scaffold — package, dependencies, base layout, serve command

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/opportunity_tracker/cli.py` (add `serve` command)
- Modify: `.gitignore` (add `web_filters/`)
- Create: `src/opportunity_tracker/webapp/__init__.py`
- Create: `src/opportunity_tracker/webapp/app.py`
- Create: `src/opportunity_tracker/webapp/deps.py`
- Create: `src/opportunity_tracker/webapp/templates/base.html`
- Create: `src/opportunity_tracker/webapp/static/style.css`
- Test: `tests/unit/webapp/__init__.py` (empty)
- Test: `tests/unit/webapp/test_app_scaffold.py`

**Interfaces:**
- Produces: `webapp.deps.get_db` (FastAPI dependency, `Iterator[sqlite3.Connection]`),
  `webapp.deps.templates` (a `fastapi.templating.Jinja2Templates` instance), the
  `base.html` template with blocks `{% block title %}` and `{% block content %}` and a
  render-context variable `active_nav` (one of `"dashboard"`, `"profile"`,
  `"searches"`, `"pins"`, `"run"`, `"results"`) used to highlight the current sidebar
  link. Every later task's templates `{% extends "base.html" %}`.
- Consumes: nothing from other tasks (this is the foundation task).

- [ ] **Step 1: Add web dependencies to `pyproject.toml`**

Edit the `dependencies` list (currently ends `"tldextract>=5.1",`) to also include, in
this order, right after `"tldextract>=5.1",`:

```toml
    "fastapi>=0.110",
    "uvicorn>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
```

- [ ] **Step 2: Install and verify**

Run: `uv sync`
Expected: resolves and installs `fastapi`, `uvicorn`, `jinja2`, `python-multipart`
alongside the existing dependencies, no errors.

- [ ] **Step 3: Add `web_filters/` to `.gitignore`**

Append, as its own new section at the end of the existing `.gitignore`:

```gitignore

# Web UI's per-saved-search filter files (spec §4.3) — same reasoning as
# profile.yaml/filter.yaml/seeds.yaml above: operator-specific, not committed.
web_filters/
```

- [ ] **Step 4: Create the webapp package skeleton**

Create `src/opportunity_tracker/webapp/__init__.py` (empty file).

Create `src/opportunity_tracker/webapp/deps.py`:

```python
"""Shared FastAPI dependencies for the web UI: DB connections and the Jinja2
environment. Every route module imports from here, never from app.py (circular)."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi.templating import Jinja2Templates

from opportunity_tracker import config, db

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 5: Create `app.py`**

```python
"""FastAPI app for the Opportunity Tracker web UI. Route modules are wired in by
Task 9 (`app.include_router(...)`) once every screen's router exists; until then this
file serves only the static assets and is not itself the app under test — each route
module's tests build their own minimal app (Global Constraints)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

_BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Opportunity Tracker")
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

# Task 9 adds one `app.include_router(...)` line per screen here, once every route
# module (Tasks 3-8) exists:
#   from opportunity_tracker.webapp import (
#       routes_dashboard, routes_pins, routes_profile, routes_results, routes_run,
#       routes_searches,
#   )
#   app.include_router(routes_dashboard.router)
#   app.include_router(routes_profile.router)
#   app.include_router(routes_searches.router)
#   app.include_router(routes_pins.router)
#   app.include_router(routes_run.router)
#   app.include_router(routes_results.router)
```

- [ ] **Step 6: Create `base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Opportunity Tracker{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div class="layout">
    <nav class="sidebar">
      <div class="brand">Opportunity<br>Tracker</div>
      <a href="/" class="nav-link{% if active_nav == 'dashboard' %} active{% endif %}">Dashboard</a>
      <a href="/profile" class="nav-link{% if active_nav == 'profile' %} active{% endif %}">Profile</a>
      <a href="/searches" class="nav-link{% if active_nav == 'searches' %} active{% endif %}">Searches</a>
      <a href="/pins" class="nav-link{% if active_nav == 'pins' %} active{% endif %}">Pinned Links</a>
      <a href="/results" class="nav-link{% if active_nav == 'results' %} active{% endif %}">Results</a>
    </nav>
    <main class="content">
      {% block content %}{% endblock %}
    </main>
  </div>
</body>
</html>
```

- [ ] **Step 7: Create `style.css`**

A single small stylesheet — clean, light, readable, no framework. Must define, at
minimum, the selectors every later task's templates rely on:
`.layout` (flex container, sidebar + content), `.sidebar` (fixed-width left rail,
`.brand`, `.nav-link`, `.nav-link.active`), `.content` (flexible main area, padded),
`.card` / `.card-grid` (used by Dashboard and Searches for the search cards), `.form-row`
/ `.form-group` / `label` / `input` / `select` / `textarea` (consistent form field
spacing), `.btn` / `.btn-primary` (buttons), `.badge` / `.badge-pass` / `.badge-fail` /
`.badge-unknown` (small colored pills, used by Results), `.bucket-section` /
`.bucket-header` (used by Results to group rows), `.progress-bar` / `.progress-fill`
(used by Run), `.empty-state` (centered muted placeholder text, used by every screen's
empty case), `.flash` / `.flash-error` (a dismissible message banner, used for error
states). Implement with plain CSS custom properties for the few colors used (a neutral
background, one accent color, and one color each for pass/fail/unknown/error) so later
tasks don't need to invent new colors.

- [ ] **Step 8: Add the `serve` command to `cli.py`**

Add this import near the top of `cli.py`, alongside the existing
`from opportunity_tracker import config, db, directory, filters, profile, urls` line
(add to that same line, don't duplicate the import statement) — no change needed there
since `serve_command` only needs `typer` and a deferred `uvicorn` import. Add this new
command, placed after `review_unclassified_command` and before `run_command`:

```python
@app.command("serve")
def serve_command(
    port: int = typer.Option(8420, "--port", help="Local port to serve the web UI on."),
) -> None:
    """Start the local web UI (binds to 127.0.0.1 only, no auth)."""
    import uvicorn

    typer.echo(f"Starting Opportunity Tracker web UI at http://127.0.0.1:{port}")
    uvicorn.run("opportunity_tracker.webapp.app:app", host="127.0.0.1", port=port)
```

- [ ] **Step 9: Write the scaffold test**

`tests/unit/webapp/__init__.py` — empty file (makes the directory a package so pytest
discovers it consistently with the rest of `tests/unit/`).

`tests/unit/webapp/test_app_scaffold.py`:

```python
from fastapi.testclient import TestClient

from opportunity_tracker.webapp.app import app


def test_static_files_are_mounted():
    client = TestClient(app)
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_base_template_renders_sidebar_links():
    from opportunity_tracker.webapp.deps import templates

    # Jinja2Templates exposes the underlying jinja2.Environment as .env
    rendered = templates.env.get_template("base.html").render(active_nav="dashboard")
    assert 'href="/profile"' in rendered
    assert 'href="/searches"' in rendered
    assert 'href="/pins"' in rendered
    assert 'href="/results"' in rendered
    assert "active" in rendered  # dashboard link carries the active class
```

- [ ] **Step 10: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/ -v`
Expected: both tests PASS.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src/opportunity_tracker/cli.py \
  src/opportunity_tracker/webapp/ tests/unit/webapp/
git commit -m "feat(webapp): scaffold FastAPI app, base layout, serve command"
```

---

### Task 2: Run orchestration module (`runner.py`)

**Files:**
- Create: `src/opportunity_tracker/webapp/runner.py`
- Test: `tests/unit/webapp/test_runner.py`

**Interfaces:**
- Consumes: `db.get_connection`, `config.DB_PATH`/`PROFILE_PATH`/`SEEDS_PATH`/
  `get_anthropic_api_key`, `profile.sync_profile`, `discovery_run.run_discovery`,
  `discovery_run.ingest_manual_pins`, `fetcher_pipeline.fetch`,
  `extractor_run.extract_requirements`, `evaluator_run.evaluate_award`,
  `_latest_profile`-equivalent query (inline, same SQL as `cli.py`'s `_latest_profile`),
  `_load_gold_set_recall`-equivalent (inline, same as `cli.py`'s, reading
  `data/gold_set_recall.json` if present else `{}`).
- Produces: `RunState` (dataclass), `RUN_STATE` (module-level singleton instance),
  `start_run(filter_id: int) -> None`, `RunAlreadyActiveError` (exception class). Task 7
  imports all four of these directly: `from opportunity_tracker.webapp.runner import
  RUN_STATE, RunAlreadyActiveError, RunState, start_run`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/webapp/test_runner.py` — mirrors the external-boundary mocking pattern
already proven in `tests/integration/test_full_pipeline.py` (mock only
`opportunity_tracker.discovery.websearch.search_institution`, `httpx.get`,
`urllib.request.urlopen`, `time.sleep`, and `anthropic.Anthropic` — everything else is
real code against a real temp SQLite file, since `_run_pipeline` opens its own
connection by path and an in-memory `:memory:` DB would not be visible across threads/
connections).

```python
import json
import threading
import time
from pathlib import Path

import pytest

from opportunity_tracker import config, db, filters
from opportunity_tracker.webapp import runner


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "PROFILE_PATH", str(tmp_path / "profile.yaml"))
    monkeypatch.setattr(config, "SEEDS_PATH", str(tmp_path / "seeds.yaml"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    Path(config.PROFILE_PATH).write_text(
        "degree_level: phd\nnationality: Testland\n", encoding="utf-8"
    )
    # Reset the module-level singleton between tests -- it is process-global.
    runner.RUN_STATE.__dict__.update(runner.RunState().__dict__)
    yield


@pytest.fixture
def seeded_filter_id(tmp_path):
    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    filter_yaml = tmp_path / "one_filter.yaml"
    filter_yaml.write_text(
        "name: test-search\ncountry: Testland\ndegree_levels: [phd]\n"
        "fields: [computer science]\ninstitution_cap: 1\n",
        encoding="utf-8",
    )
    row = filters.sync_filter(str(filter_yaml), conn)
    conn.close()
    return row.id


def test_start_run_rejects_a_second_concurrent_run(seeded_filter_id):
    # Simulate an in-progress run directly -- start_run's lock check happens before
    # it ever touches the pipeline, so no mocking of the pipeline itself is needed.
    runner.RUN_STATE.active = True
    with pytest.raises(runner.RunAlreadyActiveError):
        runner.start_run(seeded_filter_id)


def test_run_pipeline_reaches_done_with_mocked_network(seeded_filter_id, monkeypatch):
    from opportunity_tracker.discovery import websearch as websearch_module

    def fake_search_institution(institution, filter_obj, api_key, max_uses=3):
        return []  # no candidates found -- still a complete, valid run

    monkeypatch.setattr(
        websearch_module, "search_institution", fake_search_institution
    )

    runner.start_run(seeded_filter_id)

    deadline = time.time() + 10
    while runner.RUN_STATE.phase not in ("done", "failed") and time.time() < deadline:
        time.sleep(0.1)

    assert runner.RUN_STATE.phase == "done", runner.RUN_STATE.error
    assert runner.RUN_STATE.active is False
    assert runner.RUN_STATE.finished_at is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/webapp/test_runner.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'opportunity_tracker.webapp.runner'`)

- [ ] **Step 3: Implement `runner.py`**

```python
"""Background pipeline orchestration for the web UI's "Run" button. Reimplements
cli.py's `run` command as a non-blocking, progress-reporting background thread --
see spec §3.2 for why this can't just call cli.py's Typer command functions."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from opportunity_tracker import config, db, profile as profile_module
from opportunity_tracker.discovery import run as discovery_run
from opportunity_tracker.evaluator import run as evaluator_run
from opportunity_tracker.extractor import run as extractor_run
from opportunity_tracker.fetcher import pipeline as fetcher_pipeline
from opportunity_tracker.models import Document, FetchMethod, Filter, Profile, SourceTier

_GOLD_SET_RECALL_PATH = "data/gold_set_recall.json"
_MAX_LOG_ENTRIES = 100


class RunAlreadyActiveError(Exception):
    """Raised by start_run() when a run is already in progress."""


@dataclass
class RunState:
    active: bool = False
    filter_id: int | None = None
    filter_name: str | None = None
    phase: str = "idle"  # idle|discovering|fetching|extracting|evaluating|done|failed
    phase_current: int = 0
    phase_total: int = 0
    discovery_run_id: int | None = None
    candidates_found: int = 0
    log: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def add_log(self, message: str) -> None:
        self.log.append(message)
        if len(self.log) > _MAX_LOG_ENTRIES:
            del self.log[: len(self.log) - _MAX_LOG_ENTRIES]


RUN_STATE = RunState()
_LOCK = threading.Lock()


def start_run(filter_id: int) -> None:
    with _LOCK:
        if RUN_STATE.active:
            raise RunAlreadyActiveError("A run is already in progress.")
        RUN_STATE.__dict__.update(RunState().__dict__)
        RUN_STATE.active = True
        RUN_STATE.filter_id = filter_id
        RUN_STATE.started_at = datetime.now(timezone.utc).isoformat()
    thread = threading.Thread(target=_run_pipeline, args=(filter_id,), daemon=True)
    thread.start()


def _load_gold_set_recall() -> dict[str, float]:
    path = Path(_GOLD_SET_RECALL_PATH)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_profile(conn: sqlite3.Connection) -> Profile | None:
    row = conn.execute(
        "SELECT id, version, created_at, attributes FROM profile ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return Profile(
        id=row["id"], version=row["version"], created_at=row["created_at"],
        attributes=json.loads(row["attributes"]),
    )


def _row_to_filter(row: sqlite3.Row) -> Filter:
    return Filter(
        id=row["id"], name=row["name"], country=row["country"],
        degree_levels=json.loads(row["degree_levels"]), fields=json.loads(row["fields"]),
        funding_type=row["funding_type"], deadline_after=row["deadline_after"],
        min_grade=row["min_grade"], institution_cap=row["institution_cap"],
        content_hash=row["content_hash"], created_at=row["created_at"],
    )


def _run_pipeline(filter_id: int) -> None:
    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    try:
        api_key = config.get_anthropic_api_key()

        profile_module.sync_profile(config.PROFILE_PATH, conn)

        filter_row = conn.execute(
            "SELECT * FROM filter WHERE id = ?", (filter_id,)
        ).fetchone()
        if filter_row is None:
            raise ValueError(f"No saved search with id {filter_id}.")
        filter_obj = _row_to_filter(filter_row)
        RUN_STATE.filter_name = filter_obj.name

        RUN_STATE.phase = "discovering"
        RUN_STATE.add_log(f"Starting discovery for '{filter_obj.name}'...")
        _run_discovery_with_polling(filter_obj, conn, api_key)

        if Path(config.SEEDS_PATH).exists():
            pinned = discovery_run.ingest_manual_pins(config.SEEDS_PATH, conn)
            RUN_STATE.add_log(f"Ingested {len(pinned)} manual pin(s).")

        _run_fetch_phase(conn)
        _run_extract_phase(conn, api_key)
        _run_evaluate_phase(conn)

        RUN_STATE.phase = "done"
        RUN_STATE.finished_at = datetime.now(timezone.utc).isoformat()
    except Exception as exc:  # the run screen surfaces this verbatim -- spec §3.2
        RUN_STATE.phase = "failed"
        RUN_STATE.error = str(exc)
        RUN_STATE.finished_at = datetime.now(timezone.utc).isoformat()
    finally:
        RUN_STATE.active = False
        conn.close()


def _run_discovery_with_polling(filter_obj: Filter, conn: sqlite3.Connection, api_key: str) -> None:
    # `conn` was created in THIS thread (by _run_pipeline) and sqlite3 connections are
    # thread-affine by default (db.get_connection does not pass check_same_thread=False,
    # confirmed in db.py) -- so run_discovery(..., conn, ...) must stay on this thread.
    # The poller instead gets its OWN thread with its OWN fresh connection, so neither
    # connection ever crosses a thread boundary.
    stop_event = threading.Event()

    def _poll_loop() -> None:
        poll_conn = db.get_connection(config.DB_PATH)
        try:
            while not stop_event.is_set():
                _poll_discovery_progress(poll_conn, filter_obj.id)
                stop_event.wait(1.0)
        finally:
            poll_conn.close()

    poller = threading.Thread(target=_poll_loop, daemon=True)
    poller.start()
    try:
        run_row = discovery_run.run_discovery(filter_obj, conn, api_key, force_rediscover=False)
    finally:
        stop_event.set()
        poller.join()

    RUN_STATE.discovery_run_id = run_row.id
    RUN_STATE.candidates_found = run_row.institutions_with_candidates
    RUN_STATE.add_log(
        f"Discovery complete: {run_row.institutions_considered} institution(s) "
        f"considered, {run_row.institutions_with_candidates} with candidates."
    )


def _poll_discovery_progress(poll_conn: sqlite3.Connection, filter_id: int) -> None:
    row = poll_conn.execute(
        "SELECT id, institutions_considered, institutions_available, "
        "institutions_with_candidates FROM discovery_run WHERE filter_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (filter_id,),
    ).fetchone()
    if row is None:
        return
    RUN_STATE.discovery_run_id = row["id"]
    RUN_STATE.phase_current = row["institutions_considered"]
    RUN_STATE.phase_total = row["institutions_available"]
    RUN_STATE.candidates_found = row["institutions_with_candidates"]


def _run_fetch_phase(conn: sqlite3.Connection) -> None:
    RUN_STATE.phase = "fetching"
    pending = conn.execute(
        "SELECT candidate.id AS candidate_id, candidate.url AS url, "
        "candidate.declared_tier AS declared_tier, "
        "institution.name AS institution, institution.country AS country "
        "FROM candidate JOIN institution ON candidate.institution_id = institution.id "
        "WHERE candidate.promoted_to_award_id IS NULL"
    ).fetchall()
    RUN_STATE.phase_current = 0
    RUN_STATE.phase_total = len(pending)
    for row in pending:
        document = fetcher_pipeline.fetch(row["url"], conn, declared_tier=row["declared_tier"])
        conn.execute(
            "INSERT INTO award (scheme_id, institution, country, degree_levels, "
            "intake_year, canonical_url) VALUES (NULL, ?, ?, '[]', NULL, ?) "
            "ON CONFLICT(canonical_url) DO NOTHING",
            (row["institution"], row["country"], row["url"]),
        )
        award_row = conn.execute(
            "SELECT id FROM award WHERE canonical_url = ?", (row["url"],)
        ).fetchone()
        conn.execute(
            "UPDATE candidate SET promoted_to_award_id = ? WHERE id = ?",
            (award_row["id"], row["candidate_id"]),
        )
        conn.commit()
        RUN_STATE.phase_current += 1
        RUN_STATE.add_log(
            f"Fetched {row['institution']} (document {document.id})"
        )
    RUN_STATE.add_log(f"Fetch complete: {len(pending)} candidate(s) promoted.")


def _run_extract_phase(conn: sqlite3.Connection, api_key: str) -> None:
    RUN_STATE.phase = "extracting"
    pending = conn.execute(
        "SELECT award.id AS award_id, latest.document_id AS document_id "
        "FROM award "
        "JOIN (SELECT url, MAX(id) AS document_id FROM document "
        "      WHERE text_path IS NOT NULL GROUP BY url) AS latest "
        "  ON latest.url = award.canonical_url "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM requirement WHERE requirement.document_id = latest.document_id"
        ")"
    ).fetchall()
    RUN_STATE.phase_current = 0
    RUN_STATE.phase_total = len(pending)
    for row in pending:
        doc_row = conn.execute(
            "SELECT id, url, source_tier, fetch_method, content_hash, text_path, "
            "retrieved_at, fetch_status, degraded FROM document WHERE id = ?",
            (row["document_id"],),
        ).fetchone()
        document = Document(
            id=doc_row["id"], url=doc_row["url"], source_tier=SourceTier(doc_row["source_tier"]),
            fetch_method=FetchMethod(doc_row["fetch_method"]), content_hash=doc_row["content_hash"],
            text_path=doc_row["text_path"], retrieved_at=doc_row["retrieved_at"],
            fetch_status=doc_row["fetch_status"], degraded=bool(doc_row["degraded"]),
        )
        requirements, extraction_failed = extractor_run.extract_requirements(
            document, row["award_id"], conn, api_key
        )
        RUN_STATE.phase_current += 1
        if extraction_failed:
            RUN_STATE.add_log(f"Award {row['award_id']}: extraction FAILED.")
        else:
            RUN_STATE.add_log(
                f"Award {row['award_id']}: extracted {len(requirements)} requirement(s)."
            )
    RUN_STATE.add_log(f"Extraction complete: {len(pending)} award(s) processed.")


def _run_evaluate_phase(conn: sqlite3.Connection) -> None:
    RUN_STATE.phase = "evaluating"
    profile_row = _latest_profile(conn)
    if profile_row is None:
        raise RuntimeError("No profile synced yet.")
    gold_set_recall = _load_gold_set_recall()
    award_ids = [row["id"] for row in conn.execute("SELECT id FROM award")]
    RUN_STATE.phase_current = 0
    RUN_STATE.phase_total = len(award_ids)
    for award_id in award_ids:
        evaluation = evaluator_run.evaluate_award(award_id, profile_row, conn, gold_set_recall)
        RUN_STATE.phase_current += 1
        RUN_STATE.add_log(f"Award {award_id}: {evaluation.bucket.value}")
    RUN_STATE.add_log(f"Evaluation complete: {len(award_ids)} award(s) evaluated.")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/test_runner.py -v`
Expected: both tests PASS. (`test_run_pipeline_reaches_done_with_mocked_network` may
take a few seconds — it runs the real discovery/fetch/extract/evaluate loops against a
real temp SQLite file, only the true external boundary (`search_institution`) is
mocked, exactly like `tests/integration/test_full_pipeline.py`.)

- [ ] **Step 5: Run the full existing suite to confirm no regression**

Run: `uv run pytest -v`
Expected: all previously-passing tests still PASS (242+ before this task, plus the new
runner tests).

- [ ] **Step 6: Commit**

```bash
git add src/opportunity_tracker/webapp/runner.py tests/unit/webapp/test_runner.py
git commit -m "feat(webapp): add background run orchestration module"
```

---

### Task 3: Dashboard screen

**Files:**
- Create: `src/opportunity_tracker/webapp/routes_dashboard.py`
- Create: `src/opportunity_tracker/webapp/templates/dashboard.html`
- Test: `tests/unit/webapp/test_routes_dashboard.py`

**Interfaces:**
- Consumes: `webapp.deps.get_db`, `webapp.deps.templates` (Task 1). Reads `profile`,
  `filter`, `discovery_run`, `evaluation`, `award`, `candidate` tables directly via SQL
  (no new shared query helpers needed for this task alone).
- Produces: `router = APIRouter()` with `GET /` (name it `dashboard_home` — Task 9
  includes this router with no prefix).

- [ ] **Step 1: Write the failing tests**

`tests/unit/webapp/test_routes_dashboard.py` — build a local test app
(`app = FastAPI(); app.include_router(routes_dashboard.router)`), override
`webapp.deps.get_db` via `app.dependency_overrides[get_db] = ...` returning a
`:memory:` connection seeded per-test with `db.init_db`. Test cases:
1. Empty DB → GET `/` returns 200, response body contains an empty-state message
   (e.g. "No searches yet") and a link to `/searches`, and shows "0/11 fields set" (or
   the exact total field count used in Step 3) for profile completeness.
2. Seed one `profile` row (via `INSERT INTO profile ...` with a JSON `attributes` blob
   with some non-null fields) → GET `/` shows the correct "N/11 fields set" count.
3. Seed one `filter` row and one `discovery_run` row for it (`status='completed'`) →
   GET `/` shows that search's name and last-run status in the response body.
4. Seed a `filter` + `discovery_run` + `candidate` (linked to that `discovery_run_id`)
   + `award` (matching the candidate's promoted url) + `evaluation` row with
   `bucket='act_now'` → GET `/` shows a non-zero ACT_NOW count for that search's card.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/webapp/test_routes_dashboard.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `routes_dashboard.py`**

Total profile field count is **11** (the exact attribute keys in
`profile.example.yaml`: `research_project_fraction_held`, `english_test_result`,
`target_intake_year`, `has_transcripts`, `supervisor_confirmed`, `thesis_required`,
`degree_level`, `nationality`, `prior_scholarship_exclusion`, `return_obligation`,
`funding_component`). "Set" means the JSON value for that key is not `null`/missing
(booleans `false` still count as "set" — they are a real answer, not "unknown").

Query for each saved search's bucket breakdown (spec §3.4):

```sql
SELECT e.bucket, COUNT(*) AS n
FROM evaluation e
JOIN award a ON a.id = e.award_id
JOIN candidate c ON c.promoted_to_award_id = a.id
JOIN discovery_run dr ON dr.id = c.discovery_run_id
WHERE dr.filter_id = ?
  AND e.id IN (SELECT MAX(id) FROM evaluation GROUP BY award_id)
GROUP BY e.bucket
```

Query for the distinct list of saved searches (latest row per `name`):

```sql
SELECT * FROM filter WHERE id IN (
  SELECT MAX(id) FROM filter GROUP BY name
) ORDER BY name
```

Query for a search's most recent discovery run:

```sql
SELECT * FROM discovery_run WHERE filter_id = ? ORDER BY id DESC LIMIT 1
```

```python
"""Dashboard screen: profile completeness + one card per saved search."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request

from opportunity_tracker.webapp.deps import get_db, templates

router = APIRouter()

_PROFILE_FIELDS = (
    "research_project_fraction_held", "english_test_result", "target_intake_year",
    "has_transcripts", "supervisor_confirmed", "thesis_required", "degree_level",
    "nationality", "prior_scholarship_exclusion", "return_obligation", "funding_component",
)


@router.get("/", name="dashboard_home")
def dashboard_home(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    profile_row = conn.execute(
        "SELECT attributes FROM profile ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if profile_row is None:
        fields_set = 0
    else:
        attrs = json.loads(profile_row["attributes"])
        fields_set = sum(1 for key in _PROFILE_FIELDS if attrs.get(key) is not None)

    searches = []
    for row in conn.execute(
        "SELECT * FROM filter WHERE id IN (SELECT MAX(id) FROM filter GROUP BY name) "
        "ORDER BY name"
    ):
        last_run = conn.execute(
            "SELECT * FROM discovery_run WHERE filter_id = ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        buckets = {
            b["bucket"]: b["n"]
            for b in conn.execute(
                "SELECT e.bucket, COUNT(*) AS n FROM evaluation e "
                "JOIN award a ON a.id = e.award_id "
                "JOIN candidate c ON c.promoted_to_award_id = a.id "
                "JOIN discovery_run dr ON dr.id = c.discovery_run_id "
                "WHERE dr.filter_id = ? "
                "AND e.id IN (SELECT MAX(id) FROM evaluation GROUP BY award_id) "
                "GROUP BY e.bucket",
                (row["id"],),
            )
        }
        searches.append({
            "id": row["id"], "name": row["name"], "country": row["country"],
            "last_run_status": last_run["status"] if last_run else None,
            "last_run_at": last_run["started_at"] if last_run else None,
            "buckets": buckets,
        })

    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "active_nav": "dashboard",
            "fields_set": fields_set,
            "fields_total": len(_PROFILE_FIELDS),
            "searches": searches,
        },
    )
```

- [ ] **Step 4: Implement `dashboard.html`**

Extends `base.html`. Shows the "N/11 fields set" line (linking to `/profile` when
`fields_set < fields_total`), a `.card-grid` of `.card` elements (one per `searches`
entry: name, country, last-run status/date or "Never run", the bucket counts, a "Run"
button posting to `/searches/{id}/run`, an empty-state message "No searches yet — link
to /searches" when `searches` is empty), and a link to `/results`.

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/test_routes_dashboard.py -v`
Expected: all 4 cases PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opportunity_tracker/webapp/routes_dashboard.py \
  src/opportunity_tracker/webapp/templates/dashboard.html \
  tests/unit/webapp/test_routes_dashboard.py
git commit -m "feat(webapp): add dashboard screen"
```

---

### Task 4: Profile screen

**Files:**
- Create: `src/opportunity_tracker/webapp/routes_profile.py`
- Create: `src/opportunity_tracker/webapp/templates/profile.html`
- Test: `tests/unit/webapp/test_routes_profile.py`

**Interfaces:**
- Consumes: `webapp.deps.get_db`, `webapp.deps.templates`, `config.PROFILE_PATH`,
  `profile.sync_profile`.
- Produces: `router = APIRouter()` with `GET /profile` and `POST /profile`.

The 11 fields, their exact form input `name` attribute, HTML control, and YAML
type (this table is the literal contract — do not add, drop, or rename a field):

| YAML key | form field name | control | value type |
|---|---|---|---|
| `research_project_fraction_held` | `research_project_fraction_held` | `<input type="number" step="0.01" min="0" max="1">` | float or null |
| `english_test_result` | `english_test_result` | `<input type="text">` | string or null |
| `target_intake_year` | `target_intake_year` | `<input type="number" step="1">` | int or null |
| `has_transcripts` | `has_transcripts` | `<input type="checkbox">` | bool, default false (never null) |
| `supervisor_confirmed` | `supervisor_confirmed` | `<input type="checkbox">` | bool, default false (never null) |
| `thesis_required` | `thesis_required` | 3-way radio group, values `true`/`false`/`` (unknown) | bool or null |
| `degree_level` | `degree_level` | `<select>`: blank, `phd`, `masters` | string or null |
| `nationality` | `nationality` | `<input type="text">` | string or null |
| `prior_scholarship_exclusion` | `prior_scholarship_exclusion` | 3-way radio group, values `true`/`false`/`` | bool or null |
| `return_obligation` | `return_obligation` | `<input type="text">` | string or null |
| `funding_component` | `funding_component` | `<input type="text">` | string or null |

- [ ] **Step 1: Write the failing tests**

`tests/unit/webapp/test_routes_profile.py` — local test app pattern as Task 3. Cases:
1. GET `/profile` with no profile row yet → 200, form renders with every field blank/
   unchecked.
2. POST `/profile` with a full set of values (including `thesis_required=true`,
   `has_transcripts` checkbox present) → 303 redirect to `/profile`; a `profile` row
   now exists in the DB with `version=1` and the posted values under the right keys;
   the file at the monkeypatched `config.PROFILE_PATH` exists and parses back to the
   same dict via `yaml.safe_load`.
3. POST `/profile` leaving `english_test_result` and `nationality` blank → the stored
   `attributes` JSON has `"english_test_result": null` and `"nationality": null`, NOT
   empty strings.
4. POST `/profile` twice with identical values → still only one `profile` row (version
   stays 1) — `sync_profile`'s own no-op-on-unchanged-content behavior, already tested
   in `tests/unit/test_profile.py`, just needs to not be broken by the route.
5. GET `/profile` after a POST → the form's fields are pre-filled from the latest
   synced values (checkbox checked, select has the right option selected, etc).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/webapp/test_routes_profile.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `routes_profile.py`**

On POST: read each form field via FastAPI's `Form(default=...)` parameters (a
`checkbox` field is present in form data only when checked — use `Form(False)` for the
two plain booleans; the two tri-state radios use `Form("")` with `""` meaning null,
`"true"`/`"false"` mapping to `True`/`False`); build the attributes dict with `None`
for every blank text/number field and every `""` tri-state radio; `yaml.safe_dump` it
to `config.PROFILE_PATH` (create parent dirs if needed — they already exist, this file
lives at the repo root); call `profile.sync_profile(config.PROFILE_PATH, conn)`;
redirect (`RedirectResponse("/profile", status_code=303)`).

On GET: load the latest synced `attributes` dict (empty dict if no profile row yet)
and pass it to the template for pre-filling.

- [ ] **Step 4: Implement `profile.html`**

Extends `base.html`. One `<form method="post">` with the 11 fields per the table
above, a submit `.btn.btn-primary` labeled "Save Profile".

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/test_routes_profile.py -v`
Expected: all 5 cases PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opportunity_tracker/webapp/routes_profile.py \
  src/opportunity_tracker/webapp/templates/profile.html \
  tests/unit/webapp/test_routes_profile.py
git commit -m "feat(webapp): add profile screen"
```

---

### Task 5: Searches screens (list, new, edit)

**Files:**
- Create: `src/opportunity_tracker/webapp/routes_searches.py`
- Create: `src/opportunity_tracker/webapp/templates/searches_list.html`
- Create: `src/opportunity_tracker/webapp/templates/search_form.html`
- Test: `tests/unit/webapp/test_routes_searches.py`

**Interfaces:**
- Consumes: `webapp.deps.get_db`, `webapp.deps.templates`, `filters.sync_filter`,
  `webapp.runner.start_run`, `webapp.runner.RunAlreadyActiveError`.
- Produces: `router = APIRouter()` with `GET /searches`, `GET /searches/new`,
  `POST /searches/new`, `GET /searches/{filter_id}/edit`, `POST /searches/{filter_id}/edit`,
  `POST /searches/{filter_id}/run`.

Field table (same field-name-is-the-contract rule as Task 4), matching
`filter.example.yaml`:

| YAML key | form field name | control | required | value type |
|---|---|---|---|---|
| `name` | `name` | text | yes | string |
| `country` | `country` | text | yes | string |
| `degree_levels` | `degree_levels` (repeated, checkboxes) | checkboxes `phd`/`masters` | at least one | list[str] |
| `fields` | `fields` | text, comma-separated | yes | list[str] (split on `,`, strip, drop empties) |
| `funding_type` | `funding_type` | text | no | string or null |
| `deadline_after` | `deadline_after` | `<input type="date">` | no | ISO date string or null |
| `min_grade` | `min_grade` | text | no | string or null |
| `institution_cap` | `institution_cap` | number | no, default 50 | int |

**Why `POST /searches/new` writes a YAML file:** per spec §4.3, each saved search gets
its own file under a new `web_filters/` directory (create it with `Path(...).mkdir(
parents=True, exist_ok=True)` if missing — this directory is git-ignored, Task 1). The
filename is a filesystem-safe slug of `name`: lowercase, spaces/non-alphanumerics
replaced with `-`, e.g. "Canada CS PhD" → `web_filters/canada-cs-phd.yaml`. Write the
YAML (same shape as `filter.example.yaml`'s real fields, `_normalize`'d shape not
required — `filters.sync_filter` does its own normalization on read), then call
`filters.sync_filter(path, conn)` and redirect to `/searches`. Editing an existing
search overwrites that same slug's file and re-syncs — if the content changed, this
naturally creates a NEW `filter` row (different `content_hash`) per `sync_filter`'s own
identity-based semantics (spec §4.3) rather than mutating the old row; the route does
not need to do anything special for this, it's `sync_filter`'s existing, already-tested
behavior.

`POST /searches/{filter_id}/run`: call `runner.start_run(filter_id)`; on
`RunAlreadyActiveError`, redirect to `/run` anyway (the existing run's page is still the
right place to be); otherwise redirect to `/run`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/webapp/test_routes_searches.py` — local test app pattern, PLUS
monkeypatch a `web_filters/` path into `tmp_path` (the route module needs its own
constant for this directory — define `_WEB_FILTERS_DIR = Path("web_filters")` at
module level in `routes_searches.py` and have tests `monkeypatch.chdir(tmp_path)` so
the relative path lands in the temp dir, matching how `config.PROFILE_PATH` etc. are
already relative-path constants resolved against the process CWD). Cases:
1. GET `/searches` on an empty DB → 200, empty-state message, link to `/searches/new`.
2. POST `/searches/new` with a full valid payload → 303 redirect to `/searches`; a
   `filter` row exists with the right `name`/`country`/etc; `web_filters/<slug>.yaml`
   exists on disk and parses back to matching values.
3. GET `/searches` after Step 2's POST → 200, response body contains the search's name
   and country.
4. GET `/searches/{id}/edit` for an existing search → 200, form pre-filled with its
   current values.
5. POST `/searches/{id}/edit` with changed `country` → a new `filter` row is created
   (different `content_hash` than the original); `GET /searches` shows the updated
   country.
6. POST `/searches/{id}/run` → 303 redirect to `/run`; assert (via monkeypatching
   `opportunity_tracker.webapp.runner.start_run` with a stub that records its argument)
   that `start_run` was called with the right `filter_id`.
7. POST `/searches/{id}/run` when `runner.start_run` is monkeypatched to raise
   `RunAlreadyActiveError` → still redirects to `/run` (not a 500).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/webapp/test_routes_searches.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `routes_searches.py`** per the contract above.

- [ ] **Step 4: Implement `searches_list.html`** — extends `base.html`, a `.card-grid`
  of `.card` per distinct saved search (same "latest row per name" query as Task 3's
  dashboard — duplicate the query here too, it's a two-line `SELECT`, not worth a
  shared helper for one query used by two of eight route modules), each card with
  Edit/Run actions; a "+ New Search" button/link to `/searches/new`; empty-state when
  none exist.

- [ ] **Step 5: Implement `search_form.html`** — extends `base.html`, shared by both
  `/searches/new` and `/searches/{id}/edit` (the route passes an `existing` dict,
  `None` for `/new`, to pre-fill fields), fields per the table above, submit button
  labeled "Save Search".

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/test_routes_searches.py -v`
Expected: all 7 cases PASS.

- [ ] **Step 7: Commit**

```bash
git add src/opportunity_tracker/webapp/routes_searches.py \
  src/opportunity_tracker/webapp/templates/searches_list.html \
  src/opportunity_tracker/webapp/templates/search_form.html \
  tests/unit/webapp/test_routes_searches.py
git commit -m "feat(webapp): add searches list/new/edit/run screens"
```

---

### Task 6: Pinned Links screen

**Files:**
- Create: `src/opportunity_tracker/webapp/routes_pins.py`
- Create: `src/opportunity_tracker/webapp/templates/pins.html`
- Test: `tests/unit/webapp/test_routes_pins.py`

**Interfaces:**
- Consumes: `webapp.deps.get_db`, `webapp.deps.templates`, `config.SEEDS_PATH`,
  `discovery_run.ingest_manual_pins`.
- Produces: `router = APIRouter()` with `GET /pins`, `POST /pins/add`.

Form fields, matching `seeds.example.yaml`'s per-entry shape: `institution_domain`
(text, required), `url` (text, required), `name` (text, optional), `country` (text,
optional), `declared_tier` (`<select>`: blank, `1`, `2`, `3`, optional). Inline help
text next to `declared_tier`, taken from `seeds.example.yaml`'s comment: "Only set this
for a site you've personally verified is the awarding body's own — it lets that page
write fields even if the tool wouldn't otherwise trust it."

On `POST /pins/add`: load existing YAML list from `config.SEEDS_PATH` (empty list if
the file doesn't exist yet), append a new entry dict with only the non-blank keys set
(never write a `null` field for the optional ones — the example file's own entries omit
absent optional keys rather than setting them null; match that shape), `yaml.safe_dump`
the full list back, then call `discovery_run.ingest_manual_pins(config.SEEDS_PATH,
conn)`, then redirect to `/pins`.

On `GET /pins`: query `SELECT candidate.*, institution.name AS institution_name,
institution.country FROM candidate JOIN institution ON candidate.institution_id =
institution.id WHERE candidate.discovery_run_id IS NULL ORDER BY candidate.found_at
DESC` for the "already pinned" list.

- [ ] **Step 1: Write the failing tests**

`tests/unit/webapp/test_routes_pins.py` — local test app pattern, `tmp_path`-backed
`config.SEEDS_PATH`. Cases:
1. GET `/pins` with no pins yet → 200, empty-state message.
2. POST `/pins/add` with `institution_domain`/`url` only (domain matches a
   pre-seeded `institution` row in the test DB) → 303 redirect to `/pins`;
   `seeds.yaml` now exists and contains one entry with just those two keys; a
   `candidate` row now exists with `discovery_run_id IS NULL` for that institution.
3. GET `/pins` after Step 2 → 200, response body shows the pinned URL.
4. POST `/pins/add` twice with the identical domain+url → still only one `candidate`
   row (dedup is `ingest_manual_pins`'s own existing, already-tested behavior — this
   test just confirms the route doesn't break it).
5. POST `/pins/add` with `declared_tier=1` and a domain NOT in any existing
   `institution` row, plus `name`/`country` provided → succeeds (this is the
   Erasmus-Mundus-style worked example from `seeds.example.yaml` — a domain matching no
   institution still ingests correctly when `name`/`country` are supplied).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/webapp/test_routes_pins.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `routes_pins.py`** per the contract above.

- [ ] **Step 4: Implement `pins.html`** — extends `base.html`, a list/table of existing
  pins, an "Add a link" form below it per the field table above.

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/test_routes_pins.py -v`
Expected: all 5 cases PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opportunity_tracker/webapp/routes_pins.py \
  src/opportunity_tracker/webapp/templates/pins.html \
  tests/unit/webapp/test_routes_pins.py
git commit -m "feat(webapp): add pinned links screen"
```

---

### Task 7: Run screen (live progress + status API)

**Files:**
- Create: `src/opportunity_tracker/webapp/routes_run.py`
- Create: `src/opportunity_tracker/webapp/templates/run.html`
- Create: `src/opportunity_tracker/webapp/static/poll.js`
- Test: `tests/unit/webapp/test_routes_run.py`

**Interfaces:**
- Consumes: `webapp.deps.templates`, `webapp.runner.RUN_STATE` (Task 2 — read-only from
  this route; the route never calls `start_run` itself, that's Task 5's job).
- Produces: `router = APIRouter()` with `GET /run` (renders the page shell) and
  `GET /api/run/status` (returns `RUN_STATE` as JSON).

- [ ] **Step 1: Write the failing tests**

`tests/unit/webapp/test_routes_run.py` — local test app pattern. Since `RUN_STATE` is a
process-global singleton (Task 2), tests mutate `runner.RUN_STATE`'s fields directly
(no DB needed for this task) and restore it via an `autouse` fixture that resets it to
`RunState()` after each test. Cases:
1. `RUN_STATE.phase = "idle"` → GET `/run` → 200, body shows "No search is running"
   and a link to `/searches`.
2. `RUN_STATE.phase = "discovering"`, `phase_current=3`, `phase_total=10`,
   `filter_name="test-search"` → GET `/run` → 200, body includes `test-search`, and a
   `<script src="/static/poll.js">` tag (or equivalent inline bootstrap) so the browser
   starts polling.
3. GET `/api/run/status` with the same state as case 2 → 200, JSON body's `phase`,
   `phase_current`, `phase_total`, `filter_name` fields match exactly.
4. `RUN_STATE.phase = "done"`, `discovery_run_id=5` → GET `/run` → body contains a link
   to `/results`.
5. `RUN_STATE.phase = "failed"`, `RUN_STATE.error = "boom"` → GET `/run` → body
   contains the literal string `boom` and a link back to `/searches`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/webapp/test_routes_run.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `routes_run.py`**

```python
"""Live run-progress screen: a page shell plus the JSON status endpoint it polls."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from opportunity_tracker.webapp import runner
from opportunity_tracker.webapp.deps import templates

router = APIRouter()


@router.get("/run", name="run_page")
def run_page(request: Request):
    return templates.TemplateResponse(
        request, "run.html", {"active_nav": "run", "state": runner.RUN_STATE}
    )


@router.get("/api/run/status", name="run_status")
def run_status():
    return asdict(runner.RUN_STATE)
```

- [ ] **Step 4: Implement `run.html`**

Extends `base.html`. Server-rendered initial state from `state` (so the page is
correct even before JS runs a first poll) matching the mockup approved in the design
session (progress bar, phase/current/total counters, candidates-found counter, a
scrolling `<div id="run-log">` of `state.log` entries), plus `<script src="/static/
poll.js"></script>` at the end of the block. When `state.phase == "idle"`: skip all of
the above, show only "No search is running — go to /searches to start one." When
`state.phase == "failed"`: show `state.error` in a `.flash.flash-error` and a link back
to `/searches`. When `state.phase == "done"`: show a "View results" link to `/results`
in addition to the final stats.

- [ ] **Step 5: Implement `poll.js`**

```javascript
(function () {
  var pollInterval = null;

  function render(state) {
    var bar = document.getElementById("progress-fill");
    var pct = state.phase_total > 0
      ? Math.round((state.phase_current / state.phase_total) * 100)
      : 0;
    if (bar) bar.style.width = pct + "%";

    var phaseEl = document.getElementById("run-phase");
    if (phaseEl) phaseEl.textContent = state.phase;

    var progressEl = document.getElementById("run-progress-text");
    if (progressEl) progressEl.textContent = state.phase_current + " / " + state.phase_total;

    var candidatesEl = document.getElementById("run-candidates");
    if (candidatesEl) candidatesEl.textContent = state.candidates_found;

    var logEl = document.getElementById("run-log");
    if (logEl) {
      logEl.innerHTML = state.log.map(function (line) {
        return "<div>" + line.replace(/</g, "&lt;") + "</div>";
      }).join("");
    }

    if (state.phase === "done" || state.phase === "failed") {
      window.clearInterval(pollInterval);
      window.location.reload();
    }
  }

  function poll() {
    fetch("/api/run/status")
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () { /* transient network hiccup -- next poll retries */ });
  }

  var runContainer = document.getElementById("run-live");
  if (runContainer) {
    poll();
    pollInterval = window.setInterval(poll, 1500);
  }
})();
```

`run.html`'s live-state elements (progress bar fill, phase text, progress text,
candidates counter, log container) must use exactly the element ids `poll.js`
references: `#run-live` (wrapping container, only present when `state.phase` is one of
`discovering`/`fetching`/`extracting`/`evaluating`), `#progress-fill`, `#run-phase`,
`#run-progress-text`, `#run-candidates`, `#run-log`.

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/test_routes_run.py -v`
Expected: all 5 cases PASS.

- [ ] **Step 7: Commit**

```bash
git add src/opportunity_tracker/webapp/routes_run.py \
  src/opportunity_tracker/webapp/templates/run.html \
  src/opportunity_tracker/webapp/static/poll.js \
  tests/unit/webapp/test_routes_run.py
git commit -m "feat(webapp): add live run-progress screen"
```

---

### Task 8: Results screen

**Files:**
- Create: `src/opportunity_tracker/webapp/routes_results.py`
- Create: `src/opportunity_tracker/webapp/templates/results.html`
- Test: `tests/unit/webapp/test_routes_results.py`

**Interfaces:**
- Consumes: `webapp.deps.get_db`, `webapp.deps.templates`,
  `reporter.markdown.sort_evaluations`, `reporter.markdown.BUCKET_ORDER`,
  `reporter.markdown.BUCKET_TITLES`.
- Produces: `router = APIRouter()` with `GET /results`.

Data assembly is exactly `cli.py`'s `report_command`'s evaluation/award query pair
(latest evaluation per award, all awards) — same two `SELECT`s, same `Evaluation`/
`Award` object construction — then `sort_evaluations(evaluations)` for order, grouped
by `bucket` into `BUCKET_ORDER`'s five sections for rendering (do not re-derive the
sort or the bucket order — import and call the real functions).

- [ ] **Step 1: Write the failing tests**

`tests/unit/webapp/test_routes_results.py` — local test app pattern. Cases:
1. Empty DB → GET `/results` → 200, empty-state message ("No results yet — run a
   search first", link to `/searches`).
2. Seed one `award` + one `evaluation` row (`bucket='act_now'`,
   `per_requirement_outcomes='{"deadline": "pass"}'`, valid `sort_keys` JSON matching
   the shape in `tests/unit/evaluator/test_bucket.py` or `test_run.py`) → GET
   `/results` → 200, body contains the institution name, the bucket's human title ("Act
   Now"), and a `pass` badge for the `deadline` requirement.
3. Seed two awards/evaluations with different buckets (`act_now` and `coverage_gap`) →
   GET `/results` → the ACT_NOW section's heading appears before the COVERAGE_GAP
   section's heading in the response body text (byte-offset comparison, confirming
   `BUCKET_ORDER` drove the grouping, not insertion order).
4. Seed two evaluation rows for the SAME `award_id` (an older and a newer one,
   different `id`s) → GET `/results` shows that award exactly once, using the
   newer (higher-`id`) evaluation's bucket — confirms the "latest per award_id" query
   from `cli.py` was reproduced correctly, not just copied incorrectly.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/webapp/test_routes_results.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `routes_results.py`**, reusing the exact query from
  `cli.py`'s `report_command` (§9 of the design spec / lines ~291-328 of `cli.py`) for
  `evaluation_rows` and `awards_by_id`, then:

```python
from opportunity_tracker.reporter.markdown import BUCKET_ORDER, BUCKET_TITLES, sort_evaluations
# ...
ordered = sort_evaluations(evaluations)
by_bucket = {bucket: [] for bucket in BUCKET_ORDER}
for evaluation in ordered:
    by_bucket[evaluation.bucket].append(evaluation)
```

Pass `by_bucket`, `BUCKET_TITLES`, and `awards_by_id` (keyed by `award_id`, so the
template can look up institution/url/country per row) to the template.

- [ ] **Step 4: Implement `results.html`**

Extends `base.html`. One `.bucket-section` per non-empty `BUCKET_ORDER` entry (skip
empty buckets entirely — an empty COVERAGE_GAP section is noise, not a signal), each
with a `.bucket-header` (the human title) and a row per evaluation: institution,
country, days-until-deadline (from `sort_keys.days_until_deadline`, or "—" if `null`),
a `.badge` per `per_requirement_outcomes` entry (`.badge-pass`/`.badge-fail`/
`.badge-unknown` per its value), and a link to the award's `canonical_url`. A plain
`<input>` text box above the table with a small inline `<script>` that filters
`.result-row` elements by institution/country substring on `input` events (client-side
only, per spec §4.6 — no new endpoint).

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/unit/webapp/test_routes_results.py -v`
Expected: all 4 cases PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opportunity_tracker/webapp/routes_results.py \
  src/opportunity_tracker/webapp/templates/results.html \
  tests/unit/webapp/test_routes_results.py
git commit -m "feat(webapp): add results screen"
```

---

### Task 9: Final wiring, full-suite verification, live smoke test

**Files:**
- Modify: `src/opportunity_tracker/webapp/app.py`
- Test: `tests/unit/webapp/test_app_wiring.py`

This task is coordinator-executed (not dispatched to a subagent) — it is small,
mechanical, and touches the one file every other task deliberately avoided (Global
Constraints), so there is no benefit to the isolation a subagent would add.

**Interfaces:**
- Consumes: `routes_dashboard.router`, `routes_profile.router`,
  `routes_searches.router`, `routes_pins.router`, `routes_run.router`,
  `routes_results.router` (Tasks 3-8).

- [ ] **Step 1: Wire every router into `app.py`**

Replace the placeholder comment block at the bottom of `app.py` (Task 1, Step 5) with:

```python
from opportunity_tracker.webapp import (
    routes_dashboard, routes_pins, routes_profile, routes_results, routes_run,
    routes_searches,
)

app.include_router(routes_dashboard.router)
app.include_router(routes_profile.router)
app.include_router(routes_searches.router)
app.include_router(routes_pins.router)
app.include_router(routes_run.router)
app.include_router(routes_results.router)
```

- [ ] **Step 2: Write `test_app_wiring.py`**

```python
from fastapi.testclient import TestClient

from opportunity_tracker.webapp.app import app


def test_every_screen_is_reachable():
    client = TestClient(app)
    for path in ("/", "/profile", "/searches", "/pins", "/run", "/results"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"
```

Run: `uv run pytest tests/unit/webapp/test_app_wiring.py -v`
Expected: PASS (this exercises the real `app.py`, unlike every other task's tests —
first true end-to-end check that all six routers coexist without route-path
collisions or import errors).

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -v`
Expected: every test passes — the pre-existing 242+ CLI/pipeline tests, unchanged, plus
all new `tests/unit/webapp/*` tests from Tasks 1-9.

- [ ] **Step 4: Live smoke test**

Start the server (`uv run optrack serve`, background), then use the Chrome browser
tool to: load `http://127.0.0.1:8420/`, confirm the Dashboard renders with the
sidebar's five links; navigate to `/profile`, fill and submit the form, confirm it
redirects back with values pre-filled; navigate to `/searches`, create one search,
confirm it appears on both `/searches` and `/` (Dashboard); navigate to `/pins`, add
one pinned link, confirm it appears in the list; navigate to `/run` with no run active,
confirm the "No search is running" placeholder; navigate to `/results` with no data,
confirm the empty state. Stop the server afterward. Note any visual or navigation
defect found and fix it directly (this is verification, not a new task — small fixes
found here don't need their own task/review cycle, per `writing-plans`' task-review
guidance that a task's own review is the gate; this step exists precisely to catch what
route-level tests can't: real rendering, real navigation, real cross-screen links).

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/webapp/app.py tests/unit/webapp/test_app_wiring.py
git commit -m "feat(webapp): wire all screens into the app; verify end-to-end"
```
