# Opportunity Tracker — Local Web UI Design

## 0. Status and how this spec was approved

The user rejected the CLI as the primary interface ("no way i do it lie that, may be
make a websote for me and run it locally") and asked for a local website instead. Three
scoping decisions were made interactively: the website is a full end-to-end replacement
for the CLI (not a wrapper around it), runs show live progress, and the site is
localhost-only with no auth. Two visual mockups were then reviewed in the browser
(visual-companion tool): the overall page layout (sidebar nav, option A) was explicitly
approved by the user. The user then handed off the remaining decisions before going to
sleep: *"just pick please what ever you think is appropriate for this nd the other
coming, i am going bed now, i want it to be done when i wake up."* Every decision below
that has no recorded user answer was made unilaterally under that authorization, and is
called out in §11 (Decision Log) so it can be revisited on request.

## 1. Purpose

Replace the `optrack` CLI as the day-to-day interface. The user edits their profile and
search criteria through web forms, starts a search with one click, watches it run, and
browses ranked results — without touching YAML files or a terminal. The underlying
pipeline (discovery → fetch → extract → evaluate → rank), all 242 existing tests, and the
SQLite schema are unchanged and fully reused; this is a new presentation layer, not a
rewrite.

## 2. Non-goals

- No multi-user support, no accounts, no auth (single person, single machine).
- No deployment/hosting story — `localhost` only, started and stopped by hand.
- No new build toolchain (no npm/webpack/bundler) — plain Jinja2 templates, one CSS
  file, one small vanilla-JS file for polling.
- No websockets — polling is simple, sufficient at this scale, and easiest to keep
  correct under SQLite's single-writer constraints.
- The CLI (`optrack ...`) is not removed. It still works, and both interfaces converge
  on the same SQLite database and the same `profile.yaml`/`seeds.yaml` files — the web
  app is an additional, now-primary, way to drive the same system.

## 3. Architecture

A FastAPI app (`src/opportunity_tracker/webapp/`) that imports the existing pipeline
modules directly — no subprocess calls to the CLI, no duplicated business logic. Routes
render server-side Jinja2 templates; the one page that needs to move over time (the live
run screen) polls a small JSON status endpoint with `fetch()` every 1.5s and updates the
DOM directly, no framework.

**Why not shell out to the CLI:** the CLI's per-stage commands (`fetch-pending`,
`extract-pending`, ...) mix DB access with `typer.echo` for progress — there's no
structured signal to parse. The web app instead calls the same underlying functions the
CLI calls (`profile.sync_profile`, `filters.sync_filter`, `discovery_run.run_discovery`,
`fetcher.pipeline.fetch`, `extractor.run.extract_requirements`,
`evaluator.run.evaluate_award`, `reporter.markdown.sort_evaluations`) from its own
orchestration loop, so it can report structured progress as it goes.

**Why one process, one thread per run, not a job queue:** this is a single-user local
tool. A `threading.Thread` started by the "Run" button, writing into one in-memory
`RunState` object guarded by a lock, is enough — a real job queue (Celery/RQ/etc.) would
be solving a problem this tool doesn't have. Only one run may be active at a time; a
second "Run" click while one is active is rejected with a message rather than queued.

**Why polling, not websockets:** the only live-updating page is the run screen, refresh
cost is one small JSON payload every 1.5s, and polling needs no extra dependency, no
connection-lifecycle handling, and degrades trivially (a missed poll just tries again).

### 3.1 Progress tracking

`discovery_run.run_discovery` already commits progress into the `discovery_run` row
after every institution (`institutions_considered`, `institutions_with_candidates`,
`searches_used`) — the discovery phase's progress comes for free from a `SELECT * FROM
discovery_run WHERE id = ?` poll. The fetch/extract/evaluate stages have no such
persistence (the CLI just loops and prints); the web app's runner module reimplements
those three loops itself (same SQL, same per-row calls the CLI commands make — see
§3.2), writing progress into the same in-memory `RunState` after each row, so all four
phases report progress through one uniform mechanism from the browser's point of view.

### 3.2 The run orchestration module (`webapp/runner.py`)

One global `RunState` object (not per-request, not persisted — a run that's interrupted
by a server restart is simply lost, which is acceptable for a personal local tool with
no resume requirement). Shape:

```python
@dataclass
class RunState:
    active: bool = False
    filter_id: int | None = None
    filter_name: str | None = None
    phase: str = "idle"   # idle | discovering | fetching | extracting | evaluating | done | failed
    phase_current: int = 0
    phase_total: int = 0
    discovery_run_id: int | None = None
    candidates_found: int = 0
    log: list[str] = field(default_factory=list)   # capped at last 100 entries
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
```

`start_run(filter_id: int)`: under a lock, refuses if `active` is already `True`;
otherwise resets state and starts a daemon thread running `_run_pipeline(filter_id)`.

`_run_pipeline(filter_id)` — a straight-line reimplementation of `cli.py`'s `run`
command, opening its own `sqlite3.Connection` (SQLite connections aren't
thread-shared), with a progress write before/after each unit of work:

1. `profile.sync_profile(config.PROFILE_PATH, conn)` — phase `"discovering"` starts
   only after this; a missing/unsynced profile is a startup precondition, not a phase
   of its own.
2. Look up the `Filter` row by `filter_id` (`SELECT * FROM filter WHERE id = ?`) — the
   web app doesn't re-sync a `filter.yaml`; see §4.3 for why each saved search already
   has a stable DB row before "Run" is ever pressed.
3. `discovery_run.run_discovery(filter_row, conn, api_key, force_rediscover=False)` —
   phase `"discovering"`. `RunState.discovery_run_id` is set as soon as the row exists,
   and `phase_current`/`phase_total` are refreshed by polling that row's own columns
   (`institutions_considered` / `institutions_available`) inside a short sleep loop
   running alongside — simplest correct option: since `run_discovery` is itself a
   blocking call, the runner instead polls `discovery_run` from a second short-lived
   connection in a tight loop (every ~1s) *while* `run_discovery` runs on the first
   connection, until `run_discovery` returns. (SQLite allows concurrent readers.)
4. If `Path(config.SEEDS_PATH).exists()`: `discovery_run.ingest_manual_pins(...)`.
5. Fetch phase — the exact query and loop body from `cli.py`'s `fetch_pending_command`
   (replicated verbatim, see the task brief), updating `phase="fetching"`,
   `phase_current`/`phase_total` (`total` = row count from the same pending query, known
   up front unlike discovery).
6. Extract phase — `extract_pending_command`'s two queries and loop body, verbatim,
   `phase="extracting"`.
7. Evaluate phase — `evaluate_all_command`'s loop body, verbatim, `phase="evaluating"`.
8. `phase="done"`, `finished_at` set.

Any exception at any step: caught, `phase="failed"`, `error=str(exc)`, `finished_at`
set, thread exits. The run screen surfaces `error` verbatim — this is a personal tool
run by its own operator, not a public-facing service, so a raw exception message is
acceptable and more useful than a scrubbed one.

`RUN_STATE` is a module-level singleton in `webapp/runner.py`, imported by the route
handlers. This is safe under Uvicorn's default single-worker dev setup (the only
supported setup — see §3.3); a multi-worker deployment would break the singleton, which
is fine because a multi-worker deployment is out of scope (§2).

### 3.4 Dashboard's per-search bucket breakdown query

Referenced by §4.1. Awards aren't tied to a filter directly (only `discovery_run` is),
so a search's bucket counts are derived by joining through every `discovery_run` ever
run for that `filter_id` (not just the latest — a search's history accumulates, per the
"rank, never eliminate" principle, so a re-run's new candidates add to the picture
rather than replacing it):

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

### 3.3 Serving

A new Typer command, `optrack serve`, added to the existing `cli.py`:

```python
@app.command("serve")
def serve_command(
    port: int = typer.Option(8420, "--port", help="Local port to serve the web UI on."),
) -> None:
    """Start the local web UI (binds to 127.0.0.1 only)."""
    import uvicorn
    uvicorn.run("opportunity_tracker.webapp.app:app", host="127.0.0.1", port=port)
```

Bound to `127.0.0.1` explicitly (never `0.0.0.0`) — per the no-auth decision, the server
must be unreachable from anything but the local machine. Single Uvicorn worker (default)
— required by the `RUN_STATE` singleton design (§3.2).

## 4. Screens

Sidebar nav (approved mockup, option A): **Dashboard**, **Profile**, **Searches**,
**Pinned Links**, **Results**. "Run" has no permanent sidebar entry — a run is always
launched from a specific search's card on the Searches page, and immediately redirects
to the live run screen, which stays reachable at a fixed URL (`/run`) while a run is
active or has just finished, and is otherwise a "nothing running" placeholder.

### 4.1 Dashboard (`/`)

- Profile completeness: count of non-null attributes out of the total profile fields,
  shown as "9/11 fields set" with a link to `/profile` if incomplete.
- One card per saved search (`filter` row, latest per distinct `name`): name, country,
  degree levels, fields, last-run status/date (from the most recent `discovery_run` for
  that `filter_id`, if any — "never run" otherwise), and a bucket-count breakdown
  (ACT_NOW / ELIGIBLE_LATER / ... counts) scoped to that search's own discovery
  history (§3.4). A "Run" button per card.
- A link to `/results` for the full, unscoped ranked list.

### 4.2 Profile (`/profile`)

One form, fields exactly matching `profile.example.yaml`'s 11 attributes (full list in
the task brief) — text inputs for free text (`english_test_result`, `nationality`, ...),
a number input for `target_intake_year`, checkboxes for the two plain booleans
(`has_transcripts`, `supervisor_confirmed`; note `thesis_required` is a nullable
tri-state, not a plain bool — render as a "yes / no / unknown" radio group, not a
checkbox, matching its `null`-means-unknown semantics), a select for `degree_level`
(`phd` / `masters`, since those are the only two values ever compared against in the
evaluator per the domain). Every field can be left blank/unknown — the form must submit
`null` for an empty text field, never an empty string (an empty string is not the same
as "unknown" to the evaluator). On submit: write the same shape `profile.yaml` would
have, to `config.PROFILE_PATH`, then call `profile.sync_profile(config.PROFILE_PATH,
conn)`. No client-side framework — a plain HTML form, POST, redirect back to `/profile`
with the freshly-synced values shown.

### 4.3 Searches (`/searches`, `/searches/new`, `/searches/{id}/edit`)

List page: one card per distinct saved search (grouped by `name`, latest `content_hash`
row shown), matching the Dashboard's cards but with Edit/Run actions and no bucket
breakdown (that's the Dashboard's job).

New/Edit form: fields exactly matching `filter.example.yaml` — `name` (required, used as
both the display label and, slugified, the filename below), `country` (required, free
text — must match a country name in the vendored institution directory; the form does
not validate this against the directory synchronously, since the directory has ~150
distinct country strings and an exact-match text field with a mistyped country is
already how the CLI behaves — validation stays at existing zero, consistent behavior),
`degree_levels` (multi-select checkboxes: phd/masters), `fields` (free-text, comma
separated, e.g. "computer science, robotics" — split into the underlying list), plus the
optional `funding_type`, `deadline_after` (date input), `min_grade` (free text,
informational only per spec), `institution_cap` (number, default 50).

**Why each search gets its own YAML file, not one shared `filter.yaml`:** the DB's
`filter` table is already identity-based (keyed by `content_hash`, no "supersedes"
semantics, per `filters.py`'s own docstring) — it was already designed to hold many
distinct filters side by side, one CLI just only ever pointed `sync_filter` at a single
hardcoded path. The web app introduces a new directory, `web_filters/` (gitignored, new
webapp-local constant — `config.py`'s existing `FILTER_PATH` constant is untouched, so
the CLI's own single-filter workflow keeps working exactly as before), holding one YAML
file per saved search, named by a slug of `name`. Creating/editing a search writes that
file, then calls the real `filters.sync_filter(path, conn)` — so the resulting `Filter`
row, its `content_hash`, and discovery's staleness-window caching behavior are all
character-for-character identical to what the CLI itself would produce. A search's
identity from then on is its `filter_id` (`/searches/{id}/...`); renaming a search
creates a new saved search rather than mutating history in place, consistent with the
system's "append, never destroy" data model.

### 4.4 Pinned Links (`/pins`)

A list of already-ingested manual pins (`SELECT * FROM candidate WHERE
discovery_run_id IS NULL`, joined to `institution` for display) plus an "Add a link you
already know about" form: institution domain, URL, and optionally name/country (only
needed if the domain isn't already in the institution directory) and a declared-tier
override (1/2/3, with inline help text lifted from `seeds.example.yaml`'s comment
explaining when Tier 1 override is appropriate — this is a judgment call the operator
makes about a specific site, not a default anyone should reach for casually). On
submit: append to `seeds.yaml` (creating it from nothing if it doesn't exist yet), then
call `discovery_run.ingest_manual_pins(config.SEEDS_PATH, conn)` immediately, so a
pinned link doesn't have to wait for the next full "Run" to be picked up.

### 4.5 Run (`/run`, `+/api/run/status` JSON)

Implements the approved mockup option C: progress bar, live stat counters (phase
progress, candidates found, elapsed time), and a scrolling live-activity log — populated
by polling `/api/run/status` (JSON serialization of `RunState`) every 1.5s via
`fetch()`. When `phase == "done"`, the page stops polling and shows a "View results"
link to `/results`. When `phase == "failed"`, it shows `error` and a "back to Searches"
link. When no run has ever started this server session (`phase == "idle"`), the page
shows a simple "No search is running" placeholder with a link to `/searches`.

### 4.6 Results (`/results`)

Global, not scoped to one search — matches the CLI's own `report` command, which has
always reported across every award ever discovered, on the tool's core "rank, never
eliminate" principle. Rows come from exactly the CLI's `report` query (latest evaluation
per award) run through `reporter.markdown.sort_evaluations` for ordering, grouped into
`BUCKET_ORDER`'s five sections with `BUCKET_TITLES`' human labels as section headers —
this reuses the tested ranking/grouping logic directly rather than re-deriving it.
Each row: institution, country, days-until-deadline, a small pass/fail/unknown badge
per requirement kind (from `per_requirement_outcomes`), and a link to the award's
`canonical_url`. A plain client-side text filter (institution/country substring match,
pure JS over the already-rendered table, no new endpoint) — no server-side filtering,
since the whole point of this page is "everything, ranked," and the dataset size for one
person's job search is small enough that client-side filtering is instant.

## 5. Error handling

- **No profile synced yet, Run pressed:** the "Run" button itself is disabled with an
  inline note ("set up your profile first") when `/profile` has never been submitted —
  checked at page-render time (`SELECT 1 FROM profile LIMIT 1`), not deferred to a
  runtime failure.
- **`ANTHROPIC_API_KEY` unset:** `config.get_anthropic_api_key()` already raises
  `RuntimeError` with a clear message — the runner catches it like any other pipeline
  exception (§3.2) and the run screen shows it as the failure reason.
- **A run already active, Run pressed again:** `start_run` raises a dedicated
  `RunAlreadyActiveError`; the route catches it and redirects to `/run` with the
  existing run's live state rather than erroring.
- **Malformed form input** (e.g. `institution_cap` not a number): FastAPI/Pydantic's
  own validation on the route's request model returns a 422 with the field-level error;
  no custom validation layer.

## 6. Testing

- **Route tests** (`tests/unit/webapp/test_routes_*.py`): FastAPI's `TestClient`
  against a temp SQLite DB (same `tmp_path` + monkeypatched `config.DB_PATH` pattern
  the existing unit tests already use), one file per screen area (profile, searches,
  pins, results). Covers: form round-trip (submit → row appears in DB → shown on GET),
  validation errors, empty-state rendering (no profile yet, no searches yet, no results
  yet).
- **Runner tests** (`tests/unit/webapp/test_runner.py`): drive `_run_pipeline` directly
  against a temp DB with the same external-boundary mocks
  `tests/integration/test_full_pipeline.py` already established
  (`websearch.search_institution`, `httpx.get`, `urllib.request.urlopen`, `time.sleep`,
  `anthropic.Anthropic`) — this reuses that test's proven fixture rather than inventing
  a second one. Asserts `RunState` transitions through the expected phases in order and
  reaches `"done"` with the same DB end-state the CLI integration test already asserts
  on.
- **Manual smoke test:** since no human is available to click through the running app
  before this ships, the agent building it starts the server itself (`optrack serve`)
  and drives it end-to-end with the Chrome browser tool — create a profile, create a
  search, confirm nav/forms/empty-states all render correctly. A real network-backed
  run can't be driven this way (it needs the same mocked boundaries the runner tests
  use), so the runner tests are what actually cover a full run reaching "done"; the
  browser smoke test instead confirms the UI shell itself is correct.

## 7. File structure

```
src/opportunity_tracker/webapp/
  __init__.py
  app.py            # FastAPI app, route registration, Jinja2Templates setup
  routes_dashboard.py
  routes_profile.py
  routes_searches.py
  routes_pins.py
  routes_run.py
  routes_results.py
  runner.py         # RunState, start_run, _run_pipeline (§3.2)
  templates/
    base.html        # sidebar layout, nav, shared head/CSS link
    dashboard.html
    profile.html
    searches_list.html
    search_form.html
    pins.html
    run.html
    results.html
  static/
    style.css
    poll.js           # run-screen polling only
tests/unit/webapp/
  test_routes_dashboard.py
  test_routes_profile.py
  test_routes_searches.py
  test_routes_pins.py
  test_routes_results.py
  test_runner.py
web_filters/            # new, gitignored — one YAML per saved search (§4.3)
```

## 8. Dependencies

Add to `pyproject.toml`: `fastapi>=0.110`, `uvicorn>=0.30`, `jinja2>=3.1`,
`python-multipart>=0.0.9` (required by FastAPI/Starlette for parsing HTML form
`POST` bodies).

## 9. Milestones

Single milestone — this is additive to a complete, tested, merged system, not a phased
rollout. Done means: `optrack serve` starts a local server; every screen in §4 works
end-to-end against a real (even if empty) database; the full existing test suite plus
the new webapp tests pass; a live smoke-tested walkthrough (§6) confirms the UI itself
renders and navigates correctly.

## 10. Testing/failure-mode cross-check

Every screen in §4 has a corresponding error-handling note in §5 and a corresponding
test file in §6/§7 — Dashboard's empty states are covered by each of Profile/Searches/
Results' own empty-state tests (Dashboard renders nothing more than what those three
already assert exists-or-doesn't).

## 11. Decision Log

Decisions made unilaterally after the user handed off ("just pick... i want it done
when i wake up"), each reversible on request:

- **Sidebar nav** (option A) — user-approved via the visual-companion mockup before
  handoff.
- **Run screen: bar + stats + live log** (option C) — offered as the recommended option
  before handoff; picked unilaterally after handoff since no click/terminal answer was
  recorded for this specific screen.
- **Results page is global, not per-search** — matches the CLI's existing `report`
  command exactly; changing this would be a behavior change to already-tested code, not
  just a new UI, so it was not considered.
- **One saved-search-per-YAML-file, new `web_filters/` directory** — chosen to reuse
  `filters.sync_filter` verbatim (guaranteeing identical `content_hash`/caching
  behavior to the CLI) rather than duplicating its hashing/normalization logic.
- **Polling over websockets, single background thread over a job queue** — both sized to
  "one local user, one machine," per §2/§3.
- **Fixed port 8420** — arbitrary but memorable; the port is a `--port` flag so this
  costs nothing to change later.
- **No client-side JS framework, no bundler** — matches the user's own framing ("make a
  website for me and run it locally") as something simple to just run, not a build
  pipeline to maintain.
