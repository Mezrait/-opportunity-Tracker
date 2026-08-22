### Task 24: Markdown reporter (`reporter/markdown.py`)

**Files:**
- Create: `src/opportunity_tracker/reporter/__init__.py`
- Create: `src/opportunity_tracker/reporter/markdown.py`
- Test: `tests/unit/reporter/test_markdown.py`

**Interfaces:**
- Consumes: `models.Bucket` (spec §7 bucket order `ACT_NOW, ELIGIBLE_LATER, UNKNOWN_GATED,
  LIKELY_BLOCKED` plus `COVERAGE_GAP` — added to this exact enum by Task 23's
  `evaluator/run.py`; this task imports `Bucket` from `models.py` as-is and never redefines
  or re-declares any of its members); `models.Evaluation` (`id, award_id, profile_version,
  evaluated_at, bucket, sort_keys, per_requirement_outcomes` — all fields exactly as defined
  in Task 2); `models.Award` (`id, scheme_id, institution, country, degree_levels,
  intake_year, canonical_url`); `models.DiscoveryRun` (`id, filter_id,
  filter_content_hash, started_at, completed_at, institutions_considered,
  institutions_with_candidates, searches_used, status`) — all from Task 2's `models.py`.
  `evaluator.run.resolve_requirements_by_kind(conn: sqlite3.Connection, award_id: int) ->
  dict[RequirementKind, Requirement]` (Task 23) — the source of the `requirement`/`document`
  join this module needs to render each field's source URL and `retrieved_at`; call this
  once per award rather than querying `requirement`/`document` directly, so the "effective
  value per kind" resolution logic (spec §4.4) lives in exactly one place. Contract this
  task relies on for `Evaluation.sort_keys` (produced by Task 23's `evaluator/run.py`, part
  F): a `dict` with numeric keys `"unknown_count"`, `"days_until_deadline"`,
  `"funding_completeness"`. Contract relied on for `Evaluation.per_requirement_outcomes`
  (also Task 23): a **flat** `dict[str, str]` keyed by `RequirementKind.value` mapping
  directly to `Outcome.value` — e.g. `{"deadline": "pass", "research_project_fraction":
  "fail"}`. It carries no `requirement_id` or source data; source info for a given kind
  comes from `resolve_requirements_by_kind`, not from this dict.
- Produces: `render_report(evaluations: list[Evaluation], awards_by_id: dict[int, Award],
  discovery_runs: list[DiscoveryRun], conn: sqlite3.Connection) -> str` — the full markdown
  report, called by Task 26's `report` CLI command. `sort_evaluations(evaluations:
  list[Evaluation]) -> list[Evaluation]` — the shared bucket-then-sort-keys ordering used by
  both this module and Task 25's `reporter/csv_report.py` (Task 25 imports this function
  rather than duplicating the sort logic).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/reporter/test_markdown.py
from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.models import (
    Award,
    Bucket,
    DiscoveryRun,
    DiscoveryRunStatus,
    Evaluation,
)
from opportunity_tracker.reporter.markdown import render_report, sort_evaluations


def _make_award(award_id: int, institution: str) -> Award:
    return Award(
        id=award_id,
        scheme_id=None,
        institution=institution,
        country="AU",
        degree_levels=["phd"],
        intake_year=2027,
        canonical_url=f"https://example.edu/{award_id}",
    )


def _make_evaluation(
    eval_id: int,
    award_id: int,
    bucket: Bucket,
    unknown_count: int,
    days_until_deadline: int,
    funding_completeness: float,
    per_requirement_outcomes: dict | None = None,
) -> Evaluation:
    return Evaluation(
        id=eval_id,
        award_id=award_id,
        profile_version=1,
        evaluated_at="2026-08-22T00:00:00",
        bucket=bucket,
        sort_keys={
            "unknown_count": unknown_count,
            "days_until_deadline": days_until_deadline,
            "funding_completeness": funding_completeness,
        },
        per_requirement_outcomes=per_requirement_outcomes or {},
    )


# (eval_id, award_id, bucket, unknown_count, days_until_deadline, funding_completeness, institution)
CASES = [
    (1, 1, Bucket.LIKELY_BLOCKED, 0, 40, 0.5, "Zeta University"),
    (2, 2, Bucket.ACT_NOW, 0, 10, 1.0, "Alpha University"),
    (3, 3, Bucket.UNKNOWN_GATED, 1, 20, 0.5, "Beta University"),
    (4, 4, Bucket.ACT_NOW, 0, 5, 0.8, "Gamma University"),
    (5, 5, Bucket.ELIGIBLE_LATER, 0, 200, 0.5, "Delta University"),
    (6, 6, Bucket.UNKNOWN_GATED, 0, 15, 0.5, "Epsilon University"),
    (7, 7, Bucket.COVERAGE_GAP, 0, 999999, 0.0, "Zeta2 University"),
    (8, 8, Bucket.ACT_NOW, 0, 5, 0.9, "Eta University"),
]

EXPECTED_ORDER_BY_AWARD_ID = [8, 4, 2, 5, 6, 3, 1, 7]
EXPECTED_ORDER_BY_INSTITUTION = [
    "Eta University", "Gamma University", "Alpha University",
    "Delta University",
    "Epsilon University", "Beta University",
    "Zeta University",
    "Zeta2 University",
]


def _build_awards_and_evaluations():
    awards_by_id = {
        award_id: _make_award(award_id, institution)
        for _, award_id, _, _, _, _, institution in CASES
    }
    evaluations = [
        _make_evaluation(eval_id, award_id, bucket, unknown_count, days, funding)
        for eval_id, award_id, bucket, unknown_count, days, funding, _ in CASES
    ]
    return awards_by_id, evaluations


def test_sort_evaluations_orders_by_bucket_then_sort_keys():
    _, evaluations = _build_awards_and_evaluations()
    sorted_evals = sort_evaluations(evaluations)
    assert [e.award_id for e in sorted_evals] == EXPECTED_ORDER_BY_AWARD_ID


def test_render_report_lists_buckets_and_institutions_in_correct_order():
    awards_by_id, evaluations = _build_awards_and_evaluations()
    conn = get_connection(":memory:")
    init_db(conn)

    report = render_report(evaluations, awards_by_id, [], conn)

    bucket_headers = [
        "Act Now", "Eligible, Later", "Unknown-Gated", "Likely Blocked", "Coverage Gap",
    ]
    header_positions = [report.index(f"## {title}") for title in bucket_headers]
    assert header_positions == sorted(header_positions)

    institution_positions = [report.index(name) for name in EXPECTED_ORDER_BY_INSTITUTION]
    assert institution_positions == sorted(institution_positions)

    conn.close()


def test_render_report_includes_requirement_source_and_retrieved_at():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO scheme (name, funder, jurisdiction) VALUES ('S', 'F', 'AU')")
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, 'UWA', 'AU', '[\"phd\"]', 2027, "
        "'https://uwa.edu.au/award')"
    )
    conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES "
        "('https://uwa.edu.au/rules', 1, 'http', 'abc123', 'docs/1.txt', "
        "'2026-08-01T00:00:00', 'ok', 0)"
    )
    conn.execute(
        "INSERT INTO requirement (award_id, document_id, kind, operator, value, "
        "unit, raw_text, evidence, confidence, extracted_at, human_verified) VALUES "
        "(1, 1, 'research_project_fraction', '>=', '0.25', 'fraction', "
        "'at least 25 percent FTE', 'the project must be at least 25 percent FTE', "
        "0.9, '2026-08-22T00:00:00', 0)"
    )
    conn.commit()

    award = _make_award(1, "UWA")
    evaluation = _make_evaluation(
        1, 1, Bucket.LIKELY_BLOCKED, 0, 30, 0.5,
        per_requirement_outcomes={"research_project_fraction": "fail"},
    )

    report = render_report([evaluation], {1: award}, [], conn)

    assert "https://uwa.edu.au/rules" in report
    assert "2026-08-01T00:00:00" in report
    conn.close()


def test_render_report_handles_no_evaluations():
    conn = get_connection(":memory:")
    init_db(conn)
    report = render_report([], {}, [], conn)
    assert "No evaluations yet" in report
    conn.close()


def test_render_report_discovery_coverage_summary():
    conn = get_connection(":memory:")
    init_db(conn)
    run = DiscoveryRun(
        id=1,
        filter_id=1,
        filter_content_hash="hash123",
        started_at="2026-08-22T00:00:00",
        completed_at="2026-08-22T00:10:00",
        institutions_considered=42,
        institutions_with_candidates=30,
        searches_used=90,
        status=DiscoveryRunStatus.COMPLETED,
    )
    report = render_report([], {}, [run], conn)
    assert "## Discovery coverage" in report
    assert "42" in report
    assert "30" in report
    assert "12" in report  # NO_CANDIDATE_FOUND = considered - with_candidates
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reporter/test_markdown.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.reporter'`

- [ ] **Step 3: Write `src/opportunity_tracker/reporter/__init__.py` and `src/opportunity_tracker/reporter/markdown.py`**

```python
# src/opportunity_tracker/reporter/__init__.py
```

```python
# src/opportunity_tracker/reporter/markdown.py
"""Markdown report renderer. Spec §6.6, §7 (bucket-ordered ranking), §11 principle 7
(discovery coverage summary, never silently absent)."""
from __future__ import annotations

import sqlite3

from opportunity_tracker.evaluator.run import resolve_requirements_by_kind
from opportunity_tracker.models import Award, Bucket, DiscoveryRun, Evaluation

BUCKET_ORDER: list[Bucket] = [
    Bucket.ACT_NOW,
    Bucket.ELIGIBLE_LATER,
    Bucket.UNKNOWN_GATED,
    Bucket.LIKELY_BLOCKED,
    Bucket.COVERAGE_GAP,
]

BUCKET_TITLES: dict[Bucket, str] = {
    Bucket.ACT_NOW: "Act Now",
    Bucket.ELIGIBLE_LATER: "Eligible, Later",
    Bucket.UNKNOWN_GATED: "Unknown-Gated",
    Bucket.LIKELY_BLOCKED: "Likely Blocked",
    Bucket.COVERAGE_GAP: "Coverage Gap",
}

_BUCKET_RANK: dict[Bucket, int] = {bucket: i for i, bucket in enumerate(BUCKET_ORDER)}


def _sort_key(evaluation: Evaluation) -> tuple:
    sort_keys = evaluation.sort_keys
    return (
        _BUCKET_RANK[evaluation.bucket],
        sort_keys["unknown_count"],
        sort_keys["days_until_deadline"],
        -sort_keys["funding_completeness"],
    )


def sort_evaluations(evaluations: list[Evaluation]) -> list[Evaluation]:
    """Sort by bucket order (spec §7), then within-bucket by
    (unknown_count, days_until_deadline, -funding_completeness) — fewest unknowns first,
    fewest days remaining first, most funding completeness first. Shared with
    reporter/csv_report.py so both reporters agree on ordering."""
    return sorted(evaluations, key=_sort_key)


def _fetch_document_source(conn: sqlite3.Connection, document_id: int) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT url, retrieved_at FROM document WHERE id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    return row["url"], row["retrieved_at"]


def _render_evaluation_row(evaluation: Evaluation, award: Award) -> str:
    days = evaluation.sort_keys.get("days_until_deadline")
    outcomes = evaluation.per_requirement_outcomes or {}
    outcomes_summary = "; ".join(
        f"{kind}={outcome}" for kind, outcome in outcomes.items()
    ) or "no requirements assessed"
    return f"| {award.institution} | {award.country} | {days} | {outcomes_summary} |"


def _render_sources(conn: sqlite3.Connection, evaluation: Evaluation, award: Award) -> list[str]:
    # per_requirement_outcomes is a flat {kind.value: outcome.value} dict (spec §4.4's
    # resolution logic already ran once inside evaluate_award to pick these outcomes) --
    # it carries no requirement_id, so source lookup re-resolves the same effective
    # requirement per kind via the evaluator's own public helper, not a private query here.
    resolved = resolve_requirements_by_kind(conn, evaluation.award_id)
    requirement_lines: list[str] = []
    for kind, requirement in resolved.items():
        source = _fetch_document_source(conn, requirement.document_id)
        if source is None:
            continue
        url, retrieved_at = source
        outcome = evaluation.per_requirement_outcomes.get(kind.value, "unknown")
        requirement_lines.append(
            f"  - {kind.value}: {outcome} — {url} (retrieved {retrieved_at})"
        )
    if not requirement_lines:
        return []
    return [f"- **{award.institution}** sources:", *requirement_lines]


def render_report(
    evaluations: list[Evaluation],
    awards_by_id: dict[int, Award],
    discovery_runs: list[DiscoveryRun],
    conn: sqlite3.Connection,
) -> str:
    """Render the full markdown report: one section per bucket in spec §7 order, each a
    table of evaluations (institution, days remaining, per-requirement outcomes) followed
    by a per-award source list (URL + retrieved_at for each requirement used), then a
    discovery coverage summary (spec §6.6, principle 7). Never crashes on an empty
    `evaluations` list — prints a message instead (used by Task 26's `report` command)."""
    sorted_evaluations = sort_evaluations(evaluations)
    lines: list[str] = ["# Opportunity Tracker Report", ""]

    if not evaluations:
        lines.append("No evaluations yet. Run `optrack evaluate-all` first.")
        lines.append("")

    grouped: dict[Bucket, list[Evaluation]] = {bucket: [] for bucket in BUCKET_ORDER}
    for evaluation in sorted_evaluations:
        grouped.setdefault(evaluation.bucket, []).append(evaluation)

    for bucket in BUCKET_ORDER:
        bucket_evaluations = grouped.get(bucket, [])
        lines.append(f"## {BUCKET_TITLES[bucket]}")
        lines.append("")
        if not bucket_evaluations:
            lines.append("_None._")
            lines.append("")
            continue
        lines.append("| Institution | Country | Days Remaining | Requirement Outcomes |")
        lines.append("|---|---|---|---|")
        source_lines: list[str] = []
        for evaluation in bucket_evaluations:
            award = awards_by_id[evaluation.award_id]
            lines.append(_render_evaluation_row(evaluation, award))
            source_lines.extend(_render_sources(conn, evaluation, award))
        lines.append("")
        if source_lines:
            lines.append("**Sources:**")
            lines.extend(source_lines)
            lines.append("")

    lines.append("## Discovery coverage")
    lines.append("")
    if not discovery_runs:
        lines.append("_No discovery runs recorded._")
    else:
        lines.append(
            "| Filter ID | Considered | With Candidates | No Candidate Found | Searches Used |"
        )
        lines.append("|---|---|---|---|---|")
        for run in discovery_runs:
            no_candidate = run.institutions_considered - run.institutions_with_candidates
            lines.append(
                f"| {run.filter_id} | {run.institutions_considered} | "
                f"{run.institutions_with_candidates} | {no_candidate} | {run.searches_used} |"
            )
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/reporter/test_markdown.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/reporter/__init__.py src/opportunity_tracker/reporter/markdown.py tests/unit/reporter/test_markdown.py
git commit -m "feat: markdown reporter with bucket-ordered sections and discovery coverage"
```

---

### Task 25: CSV reporter (`reporter/csv_report.py`)

**Files:**
- Create: `src/opportunity_tracker/reporter/csv_report.py`
- Test: `tests/unit/reporter/test_csv_report.py`

**Interfaces:**
- Consumes: `models.Award`, `models.Evaluation`, `models.RequirementKind`,
  `models.REQUIRED_KINDS` (Task 2 — used to derive a deterministic, non-duplicated column
  list: `[kind for kind in RequirementKind if kind in REQUIRED_KINDS]`, iterating the
  enum's own declaration order rather than re-listing kind names). `db.get_connection`/
  `db.init_db` (Task 4, for the test fixture's `conn`). Task 24's
  `reporter.markdown.sort_evaluations(evaluations: list[Evaluation]) -> list[Evaluation]` —
  imported and reused as-is, not reimplemented, so both reporters agree on ordering.
- Produces: `render_csv(evaluations: list[Evaluation], awards_by_id: dict[int, Award],
  conn: sqlite3.Connection) -> str`, called by Task 26's `report --format csv` command.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/reporter/test_csv_report.py
import csv
import io

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.models import Award, Bucket, Evaluation
from opportunity_tracker.reporter.csv_report import render_csv


def _make_award(award_id: int, institution: str) -> Award:
    return Award(
        id=award_id,
        scheme_id=None,
        institution=institution,
        country="AU",
        degree_levels=["phd"],
        intake_year=2027,
        canonical_url=f"https://example.edu/{award_id}",
    )


def _make_evaluation(eval_id, award_id, bucket, unknown_count, days, funding, outcomes=None):
    return Evaluation(
        id=eval_id,
        award_id=award_id,
        profile_version=1,
        evaluated_at="2026-08-22T00:00:00",
        bucket=bucket,
        sort_keys={
            "unknown_count": unknown_count,
            "days_until_deadline": days,
            "funding_completeness": funding,
        },
        per_requirement_outcomes=outcomes or {},
    )


def test_render_csv_header_row():
    conn = get_connection(":memory:")
    init_db(conn)
    csv_text = render_csv([], {}, conn)
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == [
        "institution", "bucket", "days_remaining", "unknown_count",
        "min_grade", "research_project_fraction", "thesis_required", "english_test",
        "nationality", "deadline", "degree_level", "intake_year",
    ]
    conn.close()


def test_render_csv_row_values_match_evaluation_fields():
    conn = get_connection(":memory:")
    init_db(conn)
    award = _make_award(1, "UWA")
    evaluation = _make_evaluation(
        1, 1, Bucket.LIKELY_BLOCKED, 1, 45, 0.6,
        outcomes={"research_project_fraction": "fail", "deadline": "pass"},
    )
    csv_text = render_csv([evaluation], {1: award}, conn)
    reader = csv.DictReader(io.StringIO(csv_text))
    row = next(reader)
    assert row["institution"] == "UWA"
    assert row["bucket"] == "LIKELY_BLOCKED"
    assert row["days_remaining"] == "45"
    assert row["unknown_count"] == "1"
    assert row["research_project_fraction"] == "fail"
    assert row["deadline"] == "pass"
    assert row["min_grade"] == "unknown"
    conn.close()


def test_render_csv_sort_order_matches_markdown_reporter():
    conn = get_connection(":memory:")
    init_db(conn)
    awards_by_id = {
        1: _make_award(1, "Zeta University"),
        2: _make_award(2, "Alpha University"),
        3: _make_award(3, "Gamma University"),
    }
    evaluations = [
        _make_evaluation(1, 1, Bucket.LIKELY_BLOCKED, 0, 40, 0.5),
        _make_evaluation(2, 2, Bucket.ACT_NOW, 0, 10, 1.0),
        _make_evaluation(3, 3, Bucket.ACT_NOW, 0, 5, 0.8),
    ]
    csv_text = render_csv(evaluations, awards_by_id, conn)
    reader = csv.DictReader(io.StringIO(csv_text))
    institutions = [row["institution"] for row in reader]
    assert institutions == ["Gamma University", "Alpha University", "Zeta University"]
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reporter/test_csv_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.reporter.csv_report'`

- [ ] **Step 3: Write `src/opportunity_tracker/reporter/csv_report.py`**

```python
"""CSV reporter. Spec §6.6 — reuses the markdown reporter's sort order (spec §7) so both
artifacts rank identically."""
from __future__ import annotations

import csv
import io
import sqlite3

from opportunity_tracker.models import Award, Evaluation, REQUIRED_KINDS, RequirementKind
from opportunity_tracker.reporter.markdown import sort_evaluations

_REQUIRED_KIND_COLUMNS: list[RequirementKind] = [
    kind for kind in RequirementKind if kind in REQUIRED_KINDS
]


def render_csv(
    evaluations: list[Evaluation],
    awards_by_id: dict[int, Award],
    conn: sqlite3.Connection,
) -> str:
    """Render one CSV row per evaluation: institution, bucket, days remaining,
    unknown_count, then one column per required RequirementKind holding that kind's
    outcome ('pass'/'fail'/'unknown'; 'unknown' when the kind has no recorded outcome at
    all — absence is never evidence of pass, spec principle 5). Sorted identically to
    reporter.markdown.render_report via the shared sort_evaluations helper. `conn` is
    accepted for interface symmetry with render_report and future per-row provenance
    enrichment; the CSV format itself carries no source-URL columns."""
    buffer = io.StringIO()
    fieldnames = ["institution", "bucket", "days_remaining", "unknown_count"] + [
        kind.value for kind in _REQUIRED_KIND_COLUMNS
    ]
    writer = csv.writer(buffer)
    writer.writerow(fieldnames)

    for evaluation in sort_evaluations(evaluations):
        award = awards_by_id[evaluation.award_id]
        outcomes = evaluation.per_requirement_outcomes or {}
        row = [
            award.institution,
            evaluation.bucket.value,
            evaluation.sort_keys["days_until_deadline"],
            evaluation.sort_keys["unknown_count"],
        ]
        for kind in _REQUIRED_KIND_COLUMNS:
            row.append(outcomes.get(kind.value, "unknown"))
        writer.writerow(row)

    return buffer.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/reporter/test_csv_report.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/reporter/csv_report.py tests/unit/reporter/test_csv_report.py
git commit -m "feat: CSV reporter sharing markdown reporter's sort order"
```

---

### Task 26: CLI (`cli.py`)

**Files:**
- Create: `src/opportunity_tracker/cli.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `config.get_anthropic_api_key()`, `config.DB_PATH`, `config.PROFILE_PATH`,
  `config.FILTER_PATH`, `config.SEEDS_PATH`, `config.UNIVERSITY_DIRECTORY_PATH` (Task 3);
  `db.get_connection`, `db.init_db` (Task 4); `models.Award`, `models.Bucket`,
  `models.DiscoveryRun`, `models.Evaluation` (Task 2); `reporter.markdown.render_report`,
  `reporter.csv_report.render_csv` (Tasks 24–25). This task's calls into the sync layer,
  discovery, fetcher, extractor, digger and evaluator packages (parts B–F) were reconciled
  during self-review against each part's actual code — the signatures below are the real
  ones, not assumptions: `profile.sync_profile(yaml_path: str, conn: sqlite3.Connection) ->
  Profile` (Task 6); `filters.sync_filter(yaml_path: str, conn: sqlite3.Connection) ->
  Filter` (Task 7); `directory.load_institution_directory(json_path: str, conn:
  sqlite3.Connection, directory_version: str) -> int` (Task 8);
  `discovery.run.run_discovery(filter_obj: Filter, conn: sqlite3.Connection, api_key: str,
  force_rediscover: bool = False) -> DiscoveryRun` and `discovery.run.ingest_manual_pins(
  seeds_yaml_path: str, conn: sqlite3.Connection) -> list[int]` (Task 15);
  `fetcher.pipeline.fetch(url: str, conn: sqlite3.Connection, declared_tier: int | None =
  None) -> Document` (Task 13); `extractor.run.extract_requirements(document: Document,
  award_id: int, conn: sqlite3.Connection, api_key: str) -> tuple[list[Requirement], bool]`
  (Task 18 — the CLI fetches the `Document` row itself and unpacks the
  `extraction_failed` flag); `evaluator.run.evaluate_award(award_id: int, profile: Profile,
  conn: sqlite3.Connection, gold_set_recall: dict[str, float]) -> Evaluation` (Task 23 — the
  CLI loads the latest `Profile` row, not just its version int, and loads
  `gold_set_recall` from `data/gold_set_recall.json` if present, else `{}`);
  `digger.run.dig(award_id: int, missing_kind: RequirementKind, registrable_domain: str,
  conn: sqlite3.Connection, api_key: str) -> Requirement | None` (Task 19 — the CLI derives
  `registrable_domain` from the award's `canonical_url`).
- Produces: the `optrack` CLI entrypoint, `app` (a `typer.Typer()` instance) at
  `opportunity_tracker.cli:app`, wired by Task 1's `pyproject.toml`
  (`[project.scripts] optrack = "opportunity_tracker.cli:app"`). No later task in this plan
  imports from `cli.py` — it is the pipeline's outermost layer.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py
import pytest
from typer.testing import CliRunner

from opportunity_tracker import config, db
from opportunity_tracker.cli import app

runner = CliRunner()

ALL_COMMANDS = [
    "init-db",
    "sync-profile",
    "sync-filter",
    "load-directory",
    "discover",
    "fetch-pending",
    "extract-pending",
    "evaluate-all",
    "report",
    "dig",
    "review-unclassified",
    "run",
]


def test_init_db_creates_database_file_with_all_tables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0

    db_file = tmp_path / config.DB_PATH
    assert db_file.exists()

    conn = db.get_connection(str(db_file))
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "scheme", "award", "document", "requirement", "profile", "evaluation",
        "unclassified_rule", "institution", "filter", "discovery_run", "candidate",
    }
    assert expected <= tables
    conn.close()


def test_report_with_no_evaluations_prints_message_not_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_result = runner.invoke(app, ["init-db"])
    assert init_result.exit_code == 0

    report_result = runner.invoke(app, ["report"])
    assert report_result.exit_code == 0
    assert "No evaluations yet" in report_result.stdout


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_command_help_exits_zero(command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.cli'`

- [ ] **Step 3: Write `src/opportunity_tracker/cli.py`**

```python
"""Typer CLI wiring every pipeline stage. Spec §6 (full pipeline: filter -> discovery ->
fetcher -> extractor -> evaluator -> reporter, plus digger)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import typer

from opportunity_tracker import config, db, directory, filters, profile
from opportunity_tracker.digger import run as digger_run
from opportunity_tracker.discovery import run as discovery_run
from opportunity_tracker.evaluator import run as evaluator_run
from opportunity_tracker.extractor import run as extractor_run
from opportunity_tracker.fetcher import pipeline as fetcher_pipeline
from opportunity_tracker.models import (
    Award,
    Bucket,
    Document,
    DiscoveryRun,
    Evaluation,
    FetchMethod,
    Profile,
    RequirementKind,
    SourceTier,
)
from opportunity_tracker.reporter import csv_report, markdown

app = typer.Typer(help="Opportunity Tracker: discover, verify and rank scholarship opportunities.")

# Per-kind gold-set recall, written by `scripts/eval_gold_set.py` (Task 27). Empty until
# that script has been run at least once -- per spec principle 6 ("trust is measured, not
# chosen"), an unmeasured kind is untrusted by default, so every FAIL downgrades to
# UNKNOWN-GATED until real recall numbers exist. Deliberately a plain module constant, not
# added to config.py (Task 3), so this file doesn't require re-touching that already-locked
# contract for a value only this module reads.
_GOLD_SET_RECALL_PATH = "data/gold_set_recall.json"


def _open_db() -> sqlite3.Connection:
    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    return conn


def _latest_profile(conn: sqlite3.Connection) -> Profile | None:
    row = conn.execute(
        "SELECT id, version, created_at, attributes FROM profile ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return Profile(
        id=row["id"],
        version=row["version"],
        created_at=row["created_at"],
        attributes=json.loads(row["attributes"]),
    )


def _load_gold_set_recall() -> dict[str, float]:
    path = Path(_GOLD_SET_RECALL_PATH)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@app.command("init-db")
def init_db_command() -> None:
    """Create (or verify) the SQLite database and all tables."""
    conn = _open_db()
    conn.close()
    typer.echo(f"Database ready at {config.DB_PATH}")


@app.command("sync-profile")
def sync_profile_command() -> None:
    """Sync profile.yaml into the `profile` table."""
    conn = _open_db()
    synced = profile.sync_profile(config.PROFILE_PATH, conn)
    typer.echo(f"Profile synced: version {synced.version}")
    conn.close()


@app.command("sync-filter")
def sync_filter_command() -> None:
    """Sync filter.yaml into the `filter` table."""
    conn = _open_db()
    synced = filters.sync_filter(config.FILTER_PATH, conn)
    typer.echo(f"Filter synced: '{synced.name}' (id={synced.id}, hash={synced.content_hash[:12]})")
    conn.close()


@app.command("load-directory")
def load_directory_command(
    version: str = typer.Option(
        ..., "--version", help="Directory version label, e.g. the Hipo release date."
    ),
) -> None:
    """Load the vendored institution directory into the `institution` table."""
    conn = _open_db()
    inserted = directory.load_institution_directory(config.UNIVERSITY_DIRECTORY_PATH, conn, version)
    typer.echo(f"Institution directory loaded: {inserted} new institution(s) (version {version}).")
    conn.close()


@app.command("discover")
def discover_command(
    rediscover: bool = typer.Option(
        False, "--rediscover", help="Force a fresh discovery pass, ignoring the cache."
    ),
) -> None:
    """Run filter-driven discovery: filter.yaml -> candidate rows."""
    api_key = config.get_anthropic_api_key()
    conn = _open_db()
    filter_row = filters.sync_filter(config.FILTER_PATH, conn)
    run_row = discovery_run.run_discovery(filter_row, conn, api_key, force_rediscover=rediscover)
    typer.echo(
        f"Discovery run {run_row.id}: {run_row.institutions_considered} institution(s) "
        f"considered, {run_row.institutions_with_candidates} with candidates."
    )
    if Path(config.SEEDS_PATH).exists():
        pinned = discovery_run.ingest_manual_pins(config.SEEDS_PATH, conn)
        typer.echo(f"Manual pins ingested: {len(pinned)}")
    conn.close()


@app.command("fetch-pending")
def fetch_pending_command() -> None:
    """Fetch every candidate without a promoted award, promoting each to an award+document pair."""
    conn = _open_db()
    pending = conn.execute(
        "SELECT candidate.id AS candidate_id, candidate.url AS url, "
        "institution.name AS institution, institution.country AS country "
        "FROM candidate JOIN institution ON candidate.institution_id = institution.id "
        "WHERE candidate.promoted_to_award_id IS NULL"
    ).fetchall()
    promoted = 0
    for row in pending:
        document = fetcher_pipeline.fetch(row["url"], conn)
        cursor = conn.execute(
            "INSERT INTO award (scheme_id, institution, country, degree_levels, "
            "intake_year, canonical_url) VALUES (NULL, ?, ?, '[]', NULL, ?)",
            (row["institution"], row["country"], row["url"]),
        )
        award_id = cursor.lastrowid
        conn.execute(
            "UPDATE candidate SET promoted_to_award_id = ? WHERE id = ?",
            (award_id, row["candidate_id"]),
        )
        conn.commit()
        promoted += 1
        typer.echo(f"Fetched candidate {row['candidate_id']} -> award {award_id} (document {document.id})")
    typer.echo(f"Fetch complete: {promoted} candidate(s) promoted.")
    conn.close()


@app.command("extract-pending")
def extract_pending_command() -> None:
    """Run extraction for every award whose latest fetched document has no requirements yet."""
    api_key = config.get_anthropic_api_key()
    conn = _open_db()
    pending = conn.execute(
        "SELECT award.id AS award_id, latest.document_id AS document_id "
        "FROM award "
        "JOIN (SELECT url, MAX(id) AS document_id FROM document GROUP BY url) AS latest "
        "  ON latest.url = award.canonical_url "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM requirement WHERE requirement.document_id = latest.document_id"
        ")"
    ).fetchall()
    for row in pending:
        doc_row = conn.execute(
            "SELECT id, url, source_tier, fetch_method, content_hash, text_path, "
            "retrieved_at, fetch_status, degraded FROM document WHERE id = ?",
            (row["document_id"],),
        ).fetchone()
        document = Document(
            id=doc_row["id"],
            url=doc_row["url"],
            source_tier=SourceTier(doc_row["source_tier"]),
            fetch_method=FetchMethod(doc_row["fetch_method"]),
            content_hash=doc_row["content_hash"],
            text_path=doc_row["text_path"],
            retrieved_at=doc_row["retrieved_at"],
            fetch_status=doc_row["fetch_status"],
            degraded=bool(doc_row["degraded"]),
        )
        requirements, extraction_failed = extractor_run.extract_requirements(
            document, row["award_id"], conn, api_key
        )
        if extraction_failed:
            typer.echo(
                f"Award {row['award_id']}: extraction FAILED (document {document.id}) "
                "-- award will be UNKNOWN-GATED on empty/failed extraction."
            )
        else:
            typer.echo(f"Award {row['award_id']}: extracted {len(requirements)} requirement(s).")
    typer.echo(f"Extraction complete: {len(pending)} award(s) processed.")
    conn.close()


@app.command("evaluate-all")
def evaluate_all_command() -> None:
    """Evaluate every award against the latest synced profile."""
    conn = _open_db()
    profile_row = _latest_profile(conn)
    if profile_row is None:
        typer.echo("No profile synced yet. Run `sync-profile` first.")
        conn.close()
        raise typer.Exit(code=1)
    gold_set_recall = _load_gold_set_recall()
    award_ids = [row["id"] for row in conn.execute("SELECT id FROM award")]
    for award_id in award_ids:
        evaluation = evaluator_run.evaluate_award(award_id, profile_row, conn, gold_set_recall)
        typer.echo(f"Award {award_id}: {evaluation.bucket.value}")
    typer.echo(f"Evaluation complete: {len(award_ids)} award(s) evaluated.")
    conn.close()


@app.command("report")
def report_command(
    format: str = typer.Option("md", "--format", help="Output format: 'md' or 'csv'."),
    output: str | None = typer.Option(
        None, "--output", help="Write the report to this file instead of stdout."
    ),
) -> None:
    """Render the ranked report as markdown or CSV."""
    if format not in ("md", "csv"):
        typer.echo(f"Unknown format '{format}'. Use 'md' or 'csv'.")
        raise typer.Exit(code=1)

    conn = _open_db()
    evaluation_rows = conn.execute(
        "SELECT id, award_id, profile_version, evaluated_at, bucket, sort_keys, "
        "per_requirement_outcomes FROM evaluation"
    ).fetchall()

    if not evaluation_rows:
        typer.echo("No evaluations yet. Run `evaluate-all` first.")
        conn.close()
        return

    evaluations = [
        Evaluation(
            id=row["id"],
            award_id=row["award_id"],
            profile_version=row["profile_version"],
            evaluated_at=row["evaluated_at"],
            bucket=Bucket(row["bucket"]),
            sort_keys=json.loads(row["sort_keys"]),
            per_requirement_outcomes=json.loads(row["per_requirement_outcomes"]),
        )
        for row in evaluation_rows
    ]

    awards_by_id: dict[int, Award] = {}
    for award_row in conn.execute(
        "SELECT id, scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url FROM award"
    ):
        awards_by_id[award_row["id"]] = Award(
            id=award_row["id"],
            scheme_id=award_row["scheme_id"],
            institution=award_row["institution"],
            country=award_row["country"],
            degree_levels=json.loads(award_row["degree_levels"]),
            intake_year=award_row["intake_year"],
            canonical_url=award_row["canonical_url"],
        )

    if format == "md":
        discovery_runs = [
            DiscoveryRun(
                id=r["id"],
                filter_id=r["filter_id"],
                filter_content_hash=r["filter_content_hash"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                institutions_considered=r["institutions_considered"],
                institutions_with_candidates=r["institutions_with_candidates"],
                searches_used=r["searches_used"],
                status=r["status"],
            )
            for r in conn.execute(
                "SELECT id, filter_id, filter_content_hash, started_at, completed_at, "
                "institutions_considered, institutions_with_candidates, searches_used, "
                "status FROM discovery_run"
            )
        ]
        rendered = markdown.render_report(evaluations, awards_by_id, discovery_runs, conn)
    else:
        rendered = csv_report.render_csv(evaluations, awards_by_id, conn)

    if output:
        Path(output).write_text(rendered, encoding="utf-8")
        typer.echo(f"Report written to {output}")
    else:
        typer.echo(rendered)

    conn.close()


@app.command("dig")
def dig_command(
    award_id: int = typer.Option(..., "--award-id", help="Award id to dig for a missing field on."),
    kind: str = typer.Option(..., "--kind", help="RequirementKind value to dig for, e.g. 'deadline'."),
) -> None:
    """Run the bounded digger for one missing required field on one award."""
    api_key = config.get_anthropic_api_key()
    conn = _open_db()
    award_row = conn.execute(
        "SELECT canonical_url FROM award WHERE id = ?", (award_id,)
    ).fetchone()
    if award_row is None:
        typer.echo(f"No award with id {award_id}.")
        conn.close()
        raise typer.Exit(code=1)
    registrable_domain = urlparse(award_row["canonical_url"]).netloc
    result = digger_run.dig(
        award_id, RequirementKind(kind), registrable_domain, conn, api_key
    )
    if result is None:
        typer.echo(f"Digger found nothing for award {award_id}, kind '{kind}'.")
    else:
        typer.echo(f"Digger found requirement {result.id} for award {award_id}, kind '{kind}': {result.value}")
    conn.close()


@app.command("review-unclassified")
def review_unclassified_command() -> None:
    """List unreviewed unclassified_rule rows for manual triage."""
    conn = _open_db()
    rows = conn.execute(
        "SELECT id, document_id, raw_text, logged_at FROM unclassified_rule WHERE reviewed = 0"
    ).fetchall()
    if not rows:
        typer.echo("No unreviewed unclassified rules.")
    else:
        for row in rows:
            typer.echo(f"[{row['id']}] document {row['document_id']} ({row['logged_at']}): {row['raw_text']}")
        typer.echo(f"{len(rows)} unreviewed rule(s).")
    conn.close()


@app.command("run")
def run_command(
    rediscover: bool = typer.Option(False, "--rediscover", help="Force a fresh discovery pass."),
    format: str = typer.Option("md", "--format", help="Output format for the final report: 'md' or 'csv'."),
) -> None:
    """Run the full pipeline: discover -> fetch-pending -> extract-pending -> evaluate-all -> report."""
    typer.echo("=== Stage 1/5: discover ===")
    discover_command(rediscover=rediscover)
    typer.echo("=== Stage 2/5: fetch-pending ===")
    fetch_pending_command()
    typer.echo("=== Stage 3/5: extract-pending ===")
    extract_pending_command()
    typer.echo("=== Stage 4/5: evaluate-all ===")
    evaluate_all_command()
    typer.echo("=== Stage 5/5: report ===")
    report_command(format=format, output=None)


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS (14 tests — 2 named tests plus 12 parametrized `--help` cases)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/cli.py tests/unit/test_cli.py
git commit -m "feat: Typer CLI wiring the full pipeline"
```

---

### Task 27: Gold-set evaluation harness (`scripts/eval_gold_set.py`)

**Files:**
- Create: `scripts/eval_gold_set.py`
- Test: `tests/unit/test_eval_gold_set.py`

**Interfaces:**
- Consumes: `config.get_anthropic_api_key()`, `config.TRUST_THRESHOLD_DEFAULT` (Task 3);
  `models.RequirementKind` (Task 2); and, as an addition to Task 18's `extractor/run.py`
  Produces list, `extractor.run.extract_requirements_raw(document_text: str, api_key: str)
  -> list[dict]` — the DB-free half of Task 18's extraction logic (prompt-building + the
  single LLM call + strict-JSON parsing), factored out so this harness can score extraction
  quality against `tests/fixtures/gold_set/*.json` without a live database or any
  `document`/`award`/`requirement` rows. Each returned dict has at minimum
  `{"kind": str, "operator": str | None, "value": str | None, "unit": str | None,
  "raw_text": str, "evidence": str, "confidence": float | None}`.
- Produces: `compute_recall_precision(extracted: list[dict], annotations: list[dict]) ->
  dict[str, dict]` — pure scoring logic, keyed by requirement kind, each value
  `{"recall": float, "precision": float, "true_positives": int, "gold_count": int,
  "found_count": int}`. Not consumed by any other task in this plan; it is the harness's
  own testable core, run manually by the operator via
  `uv run python scripts/eval_gold_set.py` once real gold-set documents exist under
  `tests/fixtures/gold_set/` (spec §9.2 — that directory is empty at this point in the
  build; it is populated later by running real discovery against the operator's first
  filter and hand-annotating the results). Running the full script against real fixtures is
  therefore a manual operator step, not part of `uv run pytest`. `main()` also writes
  `data/gold_set_recall.json` (`{kind.value: recall}`, only for kinds with at least one
  gold example) — this is the file Task 26's `evaluate-all` command reads via
  `_load_gold_set_recall()` to populate `evaluator.run.evaluate_award`'s `gold_set_recall`
  argument, so a kind's trust status (spec §9.3) updates automatically the next time this
  script is run against a larger/corrected gold set.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_eval_gold_set.py
"""Unit test of the gold-set harness's SCORING logic only — compute_recall_precision, a
pure function over small synthetic in-memory extracted/annotation pairs. This does NOT run
the full scripts/eval_gold_set.py script against tests/fixtures/gold_set/: that directory
is empty until the operator populates it with real hand-annotated documents (spec §9.2),
and running the script for real is a manual step, not part of the automated test suite."""
import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_gold_set.py"
_spec = importlib.util.spec_from_file_location("eval_gold_set", SCRIPT_PATH)
eval_gold_set = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_gold_set)

compute_recall_precision = eval_gold_set.compute_recall_precision


def test_compute_recall_precision_perfect_match():
    extracted = [
        {"kind": "deadline", "value": "2027-03-31"},
        {"kind": "thesis_required", "value": "true"},
    ]
    annotations = [
        {"kind": "deadline", "value": "2027-03-31", "operator": None},
        {"kind": "thesis_required", "value": "true", "operator": None},
    ]
    results = compute_recall_precision(extracted, annotations)
    assert results["deadline"]["recall"] == 1.0
    assert results["deadline"]["precision"] == 1.0
    assert results["thesis_required"]["recall"] == 1.0


def test_compute_recall_precision_missed_requirement_hurts_recall_not_precision():
    # Gold set has two research_project_fraction annotations, extractor only found one.
    extracted = [
        {"kind": "research_project_fraction", "value": "0.25"},
    ]
    annotations = [
        {"kind": "research_project_fraction", "value": "0.25", "operator": ">="},
        {"kind": "research_project_fraction", "value": "0.10", "operator": ">="},
    ]
    results = compute_recall_precision(extracted, annotations)
    assert results["research_project_fraction"]["recall"] == 0.5
    assert results["research_project_fraction"]["precision"] == 1.0
    assert results["research_project_fraction"]["true_positives"] == 1
    assert results["research_project_fraction"]["gold_count"] == 2


def test_compute_recall_precision_hallucinated_value_hurts_precision_not_recall():
    # Extractor found a value with no matching gold annotation for that kind at all.
    extracted = [
        {"kind": "min_grade", "value": "distinction"},
    ]
    annotations = []
    results = compute_recall_precision(extracted, annotations)
    assert results["min_grade"]["recall"] == 1.0  # no gold requirement to miss
    assert results["min_grade"]["precision"] == 0.0
    assert results["min_grade"]["found_count"] == 1
    assert results["min_grade"]["gold_count"] == 0


def test_compute_recall_precision_value_matching_is_case_and_whitespace_insensitive():
    extracted = [{"kind": "english_test", "value": "  IELTS 6.5  "}]
    annotations = [{"kind": "english_test", "value": "ielts 6.5", "operator": None}]
    results = compute_recall_precision(extracted, annotations)
    assert results["english_test"]["recall"] == 1.0
    assert results["english_test"]["true_positives"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_eval_gold_set.py -v`
Expected: FAIL — `FileNotFoundError` (or an `AttributeError` on `eval_gold_set.compute_recall_precision`) because `scripts/eval_gold_set.py` does not exist yet.

- [ ] **Step 3: Write `scripts/eval_gold_set.py`**

```python
#!/usr/bin/env python
"""Gold-set evaluation harness. Spec §9.2, §9.3, §10 (Milestone 1 kill criterion).

NOT a pytest suite — spec §9.2 is explicit that the extractor gets evaluation, not tests.
This script reads real fixture files from tests/fixtures/gold_set/ and calls the real
Anthropic API via extractor.run.extract_requirements_raw. It is meant to be run by the
operator once that directory holds real hand-annotated documents:

    uv run python scripts/eval_gold_set.py

Prints per-kind recall/precision, never aggregated (spec §9.2: "aggregate accuracy hides
the single field that ruins a cycle"), and exits non-zero with a loud warning if any of the
three Milestone-1 kill-criterion kinds (deadline, thesis_required,
research_project_fraction) falls below config.TRUST_THRESHOLD_DEFAULT recall.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from opportunity_tracker import config
from opportunity_tracker.extractor.run import extract_requirements_raw
from opportunity_tracker.models import RequirementKind

GOLD_SET_DIR = Path("tests/fixtures/gold_set")

KILL_CRITERION_KINDS = {
    RequirementKind.DEADLINE.value,
    RequirementKind.THESIS_REQUIRED.value,
    RequirementKind.RESEARCH_PROJECT_FRACTION.value,
}


def _normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.strip().lower().split())


def compute_recall_precision(extracted: list[dict], annotations: list[dict]) -> dict[str, dict]:
    """Per-kind recall/precision. `extracted` and `annotations` are lists of dicts, each
    with at least a 'kind' key (str) and a 'value' key (str | None). Never aggregates
    across kinds (spec §9.2). Value comparison is simple normalized-string equality
    (case-insensitive, whitespace-collapsed) — this is the "simple equality" half of the
    spec's matching rule; fuzzy text matching is instead what the evidence validator
    (extractor/evidence.py, Task 17) applies to evidence spans against source document
    text, a different comparison than value-to-value scoring here."""
    kinds = {item["kind"] for item in extracted} | {item["kind"] for item in annotations}
    results: dict[str, dict] = {}
    for kind in kinds:
        gold = [a for a in annotations if a["kind"] == kind]
        found = [e for e in extracted if e["kind"] == kind]
        gold_values = [_normalize_value(a.get("value")) for a in gold]
        found_values = [_normalize_value(e.get("value")) for e in found]

        true_positives = 0
        remaining_found = list(found_values)
        for gold_value in gold_values:
            if gold_value in remaining_found:
                remaining_found.remove(gold_value)
                true_positives += 1

        total_gold = len(gold_values)
        total_found = len(found_values)
        recall = true_positives / total_gold if total_gold else 1.0
        precision = (
            true_positives / total_found if total_found else (1.0 if total_gold == 0 else 0.0)
        )

        results[kind] = {
            "recall": recall,
            "precision": precision,
            "true_positives": true_positives,
            "gold_count": total_gold,
            "found_count": total_found,
        }
    return results


def _load_gold_set(directory: Path) -> list[dict]:
    documents = []
    for file_path in sorted(directory.glob("*.json")):
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        documents.append({
            "name": file_path.name,
            "document_text": payload["document_text"],
            "annotations": payload["annotations"],
        })
    return documents


def _merge_kind_results(accumulated: dict[str, dict], new: dict[str, dict]) -> dict[str, dict]:
    for kind, stats in new.items():
        if kind not in accumulated:
            accumulated[kind] = {"true_positives": 0, "gold_count": 0, "found_count": 0}
        accumulated[kind]["true_positives"] += stats["true_positives"]
        accumulated[kind]["gold_count"] += stats["gold_count"]
        accumulated[kind]["found_count"] += stats["found_count"]
    return accumulated


def main() -> int:
    if not GOLD_SET_DIR.exists() or not any(GOLD_SET_DIR.glob("*.json")):
        print(
            f"No gold-set fixtures found at {GOLD_SET_DIR}. Populating it is a manual "
            "operator step (spec §9.2: run discovery for real, hand-annotate the results) "
            "and is not part of the automated test suite."
        )
        return 0

    api_key = config.get_anthropic_api_key()
    documents = _load_gold_set(GOLD_SET_DIR)

    accumulated: dict[str, dict] = {}
    for doc in documents:
        extracted = extract_requirements_raw(doc["document_text"], api_key)
        per_doc_results = compute_recall_precision(extracted, doc["annotations"])
        accumulated = _merge_kind_results(accumulated, per_doc_results)
        print(f"Scored {doc['name']}: {len(extracted)} requirement(s) extracted.")

    print()
    print(f"{'Kind':<32}{'Recall':>10}{'Precision':>12}{'TP/Gold':>12}{'Found':>8}")
    print("-" * 74)

    kill_criterion_failed: list[str] = []
    recall_by_kind: dict[str, float] = {}
    for kind in sorted(k.value for k in RequirementKind):
        stats = accumulated.get(kind, {"true_positives": 0, "gold_count": 0, "found_count": 0})
        gold_count = stats["gold_count"]
        found_count = stats["found_count"]
        true_positives = stats["true_positives"]
        recall = true_positives / gold_count if gold_count else float("nan")
        recall_display = f"{recall:.2%}" if gold_count else "n/a"
        precision_display = (
            f"{(true_positives / found_count):.2%}" if found_count else "n/a"
        )
        print(
            f"{kind:<32}{recall_display:>10}{precision_display:>12}"
            f"{f'{true_positives}/{gold_count}':>12}{found_count:>8}"
        )
        if gold_count:
            # Only kinds with at least one gold example get a recorded recall -- a kind
            # absent here (no gold examples yet) stays untrusted by default when the CLI's
            # evaluator.trust.is_trusted reads this file (missing key -> 0.0), matching
            # principle 6: trust is measured, never assumed.
            recall_by_kind[kind] = recall
        if kind in KILL_CRITERION_KINDS and gold_count and recall < config.TRUST_THRESHOLD_DEFAULT:
            kill_criterion_failed.append(kind)

    recall_path = Path("data/gold_set_recall.json")
    recall_path.write_text(json.dumps(recall_by_kind, indent=2), encoding="utf-8")
    print(f"\nPer-kind recall written to {recall_path} for `optrack evaluate-all` to use.")

    print()
    if kill_criterion_failed:
        print(
            "!!! KILL CRITERION FAILED !!!\n"
            f"Recall below trust threshold ({config.TRUST_THRESHOLD_DEFAULT:.0%}) for: "
            f"{', '.join(kill_criterion_failed)}.\n"
            "Per spec §10 (Milestone 1): stop and reconsider the extraction approach — "
            "everything downstream is worthless without these three kinds passing."
        )
        return 1

    print("All kill-criterion kinds cleared the trust threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_eval_gold_set.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_gold_set.py tests/unit/test_eval_gold_set.py
git commit -m "feat: gold-set evaluation harness (per-kind recall/precision scoring)"
```
