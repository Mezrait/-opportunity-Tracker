# Opportunity Tracker Implementation Plan — Part F: Evaluator (Tasks 20–23)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

This file covers Tasks 20–23 of the Opportunity Tracker implementation plan. It builds on
Tasks 1–4 (`docs/superpowers/plans/2026-08-22-opportunity-tracker.md`), which define
`src/opportunity_tracker/models.py`, `config.py`, and `db.py` exactly as they exist in that
file — nothing here redefines any dataclass, enum, or table from those modules, except the
one explicit, called-out addition to `models.Bucket` in Task 23 below.

**Spec:** `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md` — primarily §6.5
(evaluator: pure function, no network, no LLM), §6.4 (feasibility), §7 (ranking/bucket
order/sort keys), §8 (failure modes, intake-year mismatch, coverage gap), §9.1 (evaluator's
mandatory test cases), §9.3 and §12 (trust gate, 0.85 default threshold), principle 5
(absence of a requirement is not evidence it does not exist), principle 6 (trust is
measured, not chosen).

**Central invariant, true of every function in this file:** no network calls, no LLM calls,
no file I/O beyond reading from the `sqlite3.Connection` passed into `run.py`'s
`evaluate_award`. `rules.py`, `feasibility.py`, `trust.py`, and `bucket.py` are all pure
functions of their arguments — this is what spec §6.5 means by "unit-testable" and "why is
this blocked answerable in one line."

**Dependency note:** Task 23's `run.py` calls `rules.evaluate_requirement` (Task 20),
`feasibility.estimate_lead_time_days` (Task 21), `trust.downgrade_if_untrusted` (Task 22),
and `bucket.assign_bucket` (Task 23's own `bucket.py`, written earlier in this same task) —
so within this file, execute Tasks 20, 21, 22 before Task 23 in that order. This file does
not depend on Parts B/C/D/E; the evaluator only reads `requirement` and `profile` rows
already sitting in the database (via a `sqlite3.Connection` the caller constructs with
`db.get_connection`/`db.init_db` from Task 4) — it never calls the fetcher, discovery, or
extractor itself.

---

### Task 20: Per-kind rules (`evaluator/rules.py`)

**Files:**
- Create: `src/opportunity_tracker/evaluator/__init__.py` (empty — the evaluator package
  does not exist before this task)
- Create: `src/opportunity_tracker/evaluator/rules.py`
- Create: `tests/unit/evaluator/__init__.py` (empty — makes `tests/unit/evaluator` a proper
  package so pytest imports its test modules under a qualified name; several other
  components in this plan are also named `run.py` (`discovery/run.py`, `extractor/run.py`,
  `digger/run.py`, `evaluator/run.py`), and an unqualified `test_run.py` in multiple test
  directories would otherwise collide under pytest's rootless import mode)
- Test: `tests/unit/evaluator/test_rules.py`

**Interfaces:**
- Consumes: `opportunity_tracker.models.Outcome`, `.Profile` (field: `attributes: dict`),
  `.Requirement` (fields: `kind: RequirementKind`, `operator: str | None`, `value: str |
  None`), `.RequirementKind` — all from Task 2's `models.py`, unmodified.
- Produces: `evaluate_requirement(requirement: Requirement | None, profile: Profile) ->
  Outcome` — called once per `RequirementKind` by Task 23's `run.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/evaluator/test_rules.py
"""Table-driven tests for per-kind three-valued requirement evaluation. Pure logic, no
network, no LLM, no file I/O -- TDD per spec §9.1."""
from opportunity_tracker.models import Outcome, Profile, Requirement, RequirementKind
from opportunity_tracker.evaluator.rules import evaluate_requirement


def _make_requirement(
    kind: RequirementKind,
    operator: str | None = None,
    value: str | None = None,
) -> Requirement:
    return Requirement(
        id=1,
        award_id=1,
        document_id=1,
        kind=kind,
        operator=operator,
        value=value,
        unit=None,
        raw_text="raw text",
        evidence="evidence span",
        confidence=0.9,
        extracted_at="2026-08-22T00:00:00+00:00",
        human_verified=False,
    )


def _make_profile(attributes: dict) -> Profile:
    return Profile(
        id=1, version=1, created_at="2026-08-22T00:00:00+00:00", attributes=attributes
    )


# --- Spec §9.1 mandatory cases, verbatim ---

def test_research_project_fraction_fail_when_held_below_required():
    # 0.25 required (operator ">=") vs profile holding 0.10 -> fail (the UWA case)
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value="0.25"
    )
    profile = _make_profile({"research_project_fraction_held": 0.10})
    assert evaluate_requirement(requirement, profile) == Outcome.FAIL


def test_english_test_required_profile_holds_none_is_unknown_not_fail():
    requirement = _make_requirement(RequirementKind.ENGLISH_TEST)
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_min_grade_is_always_unknown_even_with_profile_data():
    # GPA -> WAM conversion is never automated (spec §6.5) -- unknown regardless of what
    # the profile holds, even data that looks relevant.
    requirement = _make_requirement(RequirementKind.MIN_GRADE, operator=">=", value="75")
    profile = _make_profile(
        {
            "min_grade_held": "80",
            "wam_equivalent": "80",
            "research_project_fraction_held": 0.9,
        }
    )
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_none_requirement_is_always_unknown():
    # Principle 5: absence of a requirement is not evidence it does not exist.
    profile = _make_profile({"research_project_fraction_held": 0.9})
    assert evaluate_requirement(None, profile) == Outcome.UNKNOWN


# --- Supplementary coverage for the remaining kinds ---

def test_research_project_fraction_pass_when_held_meets_required():
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value="0.25"
    )
    profile = _make_profile({"research_project_fraction_held": 0.30})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_research_project_fraction_unknown_when_profile_attribute_missing():
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value="0.25"
    )
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_intake_year_mismatch_is_fail():
    # Per-requirement three-valued truth only; bucket.py (Task 23) is what translates an
    # intake-year FAIL specifically into UNKNOWN-GATED rather than LIKELY BLOCKED.
    requirement = _make_requirement(RequirementKind.INTAKE_YEAR, value="2027")
    profile = _make_profile({"target_intake_year": 2028})
    assert evaluate_requirement(requirement, profile) == Outcome.FAIL


def test_intake_year_match_is_pass():
    requirement = _make_requirement(RequirementKind.INTAKE_YEAR, value="2027")
    profile = _make_profile({"target_intake_year": 2027})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_intake_year_unknown_when_profile_missing_target():
    requirement = _make_requirement(RequirementKind.INTAKE_YEAR, value="2027")
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_deadline_pass_when_value_present():
    requirement = _make_requirement(RequirementKind.DEADLINE, value="2027-06-01")
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_deadline_unknown_when_value_absent():
    requirement = _make_requirement(RequirementKind.DEADLINE, value=None)
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_boolean_kind_thesis_required_matches_profile():
    requirement = _make_requirement(RequirementKind.THESIS_REQUIRED, value="true")
    profile = _make_profile({"thesis_required": "true"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_boolean_kind_thesis_required_mismatches_profile():
    requirement = _make_requirement(RequirementKind.THESIS_REQUIRED, value="true")
    profile = _make_profile({"thesis_required": "false"})
    assert evaluate_requirement(requirement, profile) == Outcome.FAIL


def test_boolean_kind_unknown_when_profile_attribute_missing():
    requirement = _make_requirement(RequirementKind.NATIONALITY, value="australian")
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_informational_boolean_kind_uses_same_rule():
    requirement = _make_requirement(RequirementKind.RETURN_OBLIGATION, value="true")
    profile = _make_profile({"return_obligation": "true"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/evaluator/test_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.evaluator'`

- [ ] **Step 3: Write `src/opportunity_tracker/evaluator/__init__.py`**

```python
```

(empty file — marks `evaluator` as a package)

- [ ] **Step 3b: Write `tests/unit/evaluator/__init__.py`**

```python
```

(empty file — see rationale in Files above)

- [ ] **Step 3c: Write `src/opportunity_tracker/evaluator/rules.py`**

```python
"""Per-kind three-valued requirement evaluation. Pure function -- spec §6.5, §9.1. No
network, no LLM, no file I/O. `requirement is None` always yields UNKNOWN (principle 5:
absence of a requirement is not evidence it does not exist)."""
from __future__ import annotations

import operator as _operator

from opportunity_tracker.models import Outcome, Profile, Requirement, RequirementKind

_COMPARATORS = {
    ">=": _operator.ge,
    "<=": _operator.le,
    "==": _operator.eq,
    ">": _operator.gt,
    "<": _operator.lt,
}

# For the boolean/informational kinds, the matching profile.attributes key shares the
# kind's own enum value.
_BOOLEAN_KIND_ATTRIBUTES: dict[RequirementKind, str] = {
    RequirementKind.THESIS_REQUIRED: "thesis_required",
    RequirementKind.DEGREE_LEVEL: "degree_level",
    RequirementKind.NATIONALITY: "nationality",
    RequirementKind.SUPERVISOR_REQUIRED: "supervisor_required",
    RequirementKind.PRIOR_SCHOLARSHIP_EXCLUSION: "prior_scholarship_exclusion",
    RequirementKind.RETURN_OBLIGATION: "return_obligation",
    RequirementKind.FUNDING_COMPONENT: "funding_component",
}


def evaluate_requirement(requirement: Requirement | None, profile: Profile) -> Outcome:
    if requirement is None:
        return Outcome.UNKNOWN

    kind = requirement.kind

    if kind == RequirementKind.RESEARCH_PROJECT_FRACTION:
        held = profile.attributes.get("research_project_fraction_held")
        if held is None:
            return Outcome.UNKNOWN
        compare = _COMPARATORS.get(requirement.operator)
        if compare is None:
            return Outcome.UNKNOWN
        held_value = float(held)
        required_value = float(requirement.value)
        return Outcome.PASS if compare(held_value, required_value) else Outcome.FAIL

    if kind == RequirementKind.ENGLISH_TEST:
        # Mandatory case (spec §9.1): required, profile holds none -> unknown, never fail.
        result = profile.attributes.get("english_test_result")
        if result is None:
            return Outcome.UNKNOWN
        return Outcome.PASS

    if kind == RequirementKind.INTAKE_YEAR:
        target = profile.attributes.get("target_intake_year")
        if target is None:
            return Outcome.UNKNOWN
        try:
            required_year = int(requirement.value)
            target_year = int(target)
        except (TypeError, ValueError):
            return Outcome.UNKNOWN
        # A mismatch here is a per-requirement FAIL. bucket.py (Task 23) is responsible for
        # translating specifically an intake-year FAIL into UNKNOWN-GATED rather than
        # LIKELY BLOCKED at the bucket level (spec §8) -- this function's contract is just
        # per-requirement three-valued truth.
        return Outcome.PASS if required_year == target_year else Outcome.FAIL

    if kind == RequirementKind.MIN_GRADE:
        # Spec §6.5: GPA -> WAM conversion is never automated. A stated grade threshold with
        # no verified conversion yields unknown, not a computed pass or fail -- always,
        # regardless of what profile data is present. Do not add a numeric comparison here.
        return Outcome.UNKNOWN

    if kind == RequirementKind.DEADLINE:
        # Existence is what's being checked at this layer; date math against the deadline
        # happens in feasibility.py/bucket.py (Tasks 21, 23).
        return Outcome.PASS if requirement.value is not None else Outcome.UNKNOWN

    attribute_key = _BOOLEAN_KIND_ATTRIBUTES.get(kind)
    if attribute_key is not None:
        profile_value = profile.attributes.get(attribute_key)
        if profile_value is None:
            return Outcome.UNKNOWN
        if str(requirement.value).strip().lower() == str(profile_value).strip().lower():
            return Outcome.PASS
        return Outcome.FAIL

    return Outcome.UNKNOWN
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/evaluator/test_rules.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/evaluator/__init__.py \
        src/opportunity_tracker/evaluator/rules.py \
        tests/unit/evaluator/__init__.py \
        tests/unit/evaluator/test_rules.py
git commit -m "feat: per-kind three-valued requirement evaluation rules"
```

---

### Task 21: Feasibility (`evaluator/feasibility.py`)

**Files:**
- Create: `src/opportunity_tracker/evaluator/feasibility.py`
- Test: `tests/unit/evaluator/test_feasibility.py`

**Interfaces:**
- Consumes: `opportunity_tracker.config.FEASIBILITY_LEAD_DAYS` (Task 3);
  `opportunity_tracker.models.Profile` (field: `attributes: dict`), `.Requirement` (field:
  `kind: RequirementKind`), `.RequirementKind` (Task 2) — unmodified.
- Produces: `estimate_lead_time_days(profile: Profile, requirements: list[Requirement]) ->
  int` — called by Task 23's `run.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/evaluator/test_feasibility.py
"""Pure lead-time estimation -- spec §6.4. No network, no LLM, no file I/O."""
from opportunity_tracker.models import Profile, Requirement, RequirementKind
from opportunity_tracker.evaluator.feasibility import estimate_lead_time_days


def _make_requirement(kind: RequirementKind) -> Requirement:
    return Requirement(
        id=1,
        award_id=1,
        document_id=1,
        kind=kind,
        operator=None,
        value=None,
        unit=None,
        raw_text="raw text",
        evidence="evidence span",
        confidence=0.9,
        extracted_at="2026-08-22T00:00:00+00:00",
        human_verified=False,
    )


def _make_profile(attributes: dict) -> Profile:
    return Profile(
        id=1, version=1, created_at="2026-08-22T00:00:00+00:00", attributes=attributes
    )


def test_missing_everything_sums_all_three_lead_times():
    profile = _make_profile({})
    requirements = [
        _make_requirement(RequirementKind.ENGLISH_TEST),
        _make_requirement(RequirementKind.SUPERVISOR_REQUIRED),
    ]
    # 21 (english test) + 35 (supervisor agreement midpoint, (28+42)/2) + 7 (transcripts)
    assert estimate_lead_time_days(profile, requirements) == 21 + 35 + 7


def test_all_prerequisites_satisfied_is_zero():
    profile = _make_profile(
        {
            "english_test_result": {"test": "IELTS", "score": 7.0},
            "supervisor_confirmed": True,
            "has_transcripts": True,
        }
    )
    requirements = [
        _make_requirement(RequirementKind.ENGLISH_TEST),
        _make_requirement(RequirementKind.SUPERVISOR_REQUIRED),
    ]
    assert estimate_lead_time_days(profile, requirements) == 0


def test_missing_only_transcripts_is_seven():
    profile = _make_profile(
        {
            "english_test_result": {"test": "IELTS", "score": 7.0},
            "supervisor_confirmed": True,
            "has_transcripts": False,
        }
    )
    requirements = [
        _make_requirement(RequirementKind.ENGLISH_TEST),
        _make_requirement(RequirementKind.SUPERVISOR_REQUIRED),
    ]
    assert estimate_lead_time_days(profile, requirements) == 7


def test_no_relevant_requirement_kinds_ignores_english_and_supervisor_gaps():
    # transcripts is checked unconditionally; english/supervisor lead time is only added
    # when a requirement of that kind is actually present for the award.
    profile = _make_profile({"has_transcripts": True})
    requirements = [_make_requirement(RequirementKind.DEADLINE)]
    assert estimate_lead_time_days(profile, requirements) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/evaluator/test_feasibility.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.evaluator.feasibility'`

- [ ] **Step 3: Write `src/opportunity_tracker/evaluator/feasibility.py`**

```python
"""Feasibility: minimum lead time implied by the profile's missing prerequisites, given a
set of requirements. Pure function -- spec §6.4. No network, no LLM, no file I/O."""
from __future__ import annotations

from opportunity_tracker import config
from opportunity_tracker.models import Profile, Requirement, RequirementKind


def estimate_lead_time_days(profile: Profile, requirements: list[Requirement]) -> int:
    kinds_present = {requirement.kind for requirement in requirements}
    total_days = 0

    if RequirementKind.ENGLISH_TEST in kinds_present:
        if profile.attributes.get("english_test_result") is None:
            total_days += int(config.FEASIBILITY_LEAD_DAYS["english_test_result"])

    if RequirementKind.SUPERVISOR_REQUIRED in kinds_present:
        if profile.attributes.get("supervisor_confirmed") is not True:
            low, high = config.FEASIBILITY_LEAD_DAYS["supervisor_agreement"]
            total_days += (low + high) // 2

    if profile.attributes.get("has_transcripts") is not True:
        total_days += int(config.FEASIBILITY_LEAD_DAYS["transcripts"])

    return total_days
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/evaluator/test_feasibility.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/evaluator/feasibility.py tests/unit/evaluator/test_feasibility.py
git commit -m "feat: feasibility lead-time estimator"
```

---

### Task 22: Trust gate (`evaluator/trust.py`)

**Files:**
- Create: `src/opportunity_tracker/evaluator/trust.py`
- Test: `tests/unit/evaluator/test_trust.py`

**Interfaces:**
- Consumes: `opportunity_tracker.config.TRUST_THRESHOLD_DEFAULT` (Task 3);
  `opportunity_tracker.models.Outcome`, `.RequirementKind` (Task 2) — unmodified.
- Produces: `is_trusted(kind: RequirementKind, gold_set_recall: dict[str, float], threshold:
  float = config.TRUST_THRESHOLD_DEFAULT) -> bool` and `downgrade_if_untrusted(outcome:
  Outcome, kind: RequirementKind, gold_set_recall: dict[str, float]) -> Outcome` — both
  called by Task 23's `run.py`; `is_trusted` is also independently useful to a later
  reporter/CLI task that surfaces trust status per kind.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/evaluator/test_trust.py
"""Trust gate -- spec §6, §9.3, §12, principle 6. Pure function, no network, no LLM."""
from opportunity_tracker.models import Outcome, RequirementKind
from opportunity_tracker.evaluator.trust import downgrade_if_untrusted, is_trusted


def test_kind_at_exactly_threshold_is_trusted():
    gold_set_recall = {RequirementKind.DEADLINE.value: 0.85}
    assert is_trusted(RequirementKind.DEADLINE, gold_set_recall) is True


def test_kind_just_below_threshold_is_untrusted():
    gold_set_recall = {RequirementKind.DEADLINE.value: 0.84}
    assert is_trusted(RequirementKind.DEADLINE, gold_set_recall) is False


def test_kind_absent_from_recall_dict_is_untrusted_by_default():
    # A kind never measured on the gold set must never be assumed trustworthy.
    assert is_trusted(RequirementKind.DEADLINE, {}) is False


def test_fail_for_untrusted_kind_downgrades_to_unknown():
    gold_set_recall = {RequirementKind.THESIS_REQUIRED.value: 0.50}
    result = downgrade_if_untrusted(
        Outcome.FAIL, RequirementKind.THESIS_REQUIRED, gold_set_recall
    )
    assert result == Outcome.UNKNOWN


def test_fail_for_trusted_kind_stays_fail():
    gold_set_recall = {RequirementKind.THESIS_REQUIRED.value: 0.90}
    result = downgrade_if_untrusted(
        Outcome.FAIL, RequirementKind.THESIS_REQUIRED, gold_set_recall
    )
    assert result == Outcome.FAIL


def test_pass_outcome_is_never_downgraded_regardless_of_trust():
    result = downgrade_if_untrusted(Outcome.PASS, RequirementKind.THESIS_REQUIRED, {})
    assert result == Outcome.PASS


def test_unknown_outcome_is_never_touched():
    gold_set_recall = {RequirementKind.THESIS_REQUIRED.value: 0.90}
    result = downgrade_if_untrusted(
        Outcome.UNKNOWN, RequirementKind.THESIS_REQUIRED, gold_set_recall
    )
    assert result == Outcome.UNKNOWN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/evaluator/test_trust.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.evaluator.trust'`

- [ ] **Step 3: Write `src/opportunity_tracker/evaluator/trust.py`**

```python
"""Trust gate: a requirement kind may produce a blocking FAIL only once its gold-set recall
clears the threshold. Pure function -- spec §6, §9.3, §12, principle 6. No network, no LLM,
no file I/O."""
from __future__ import annotations

from opportunity_tracker import config
from opportunity_tracker.models import Outcome, RequirementKind


def is_trusted(
    kind: RequirementKind,
    gold_set_recall: dict[str, float],
    threshold: float = config.TRUST_THRESHOLD_DEFAULT,
) -> bool:
    # A kind absent from the recall dict is untrusted by default -- never assumed
    # trustworthy in the absence of measurement.
    return gold_set_recall.get(kind.value, 0.0) >= threshold


def downgrade_if_untrusted(
    outcome: Outcome,
    kind: RequirementKind,
    gold_set_recall: dict[str, float],
) -> Outcome:
    if outcome == Outcome.FAIL and not is_trusted(kind, gold_set_recall):
        return Outcome.UNKNOWN
    return outcome
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/evaluator/test_trust.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/evaluator/trust.py tests/unit/evaluator/test_trust.py
git commit -m "feat: trust gate for gold-set recall thresholds"
```

---

### Task 23: Evaluator orchestration (`evaluator/bucket.py`, `evaluator/run.py`)

**Files:**
- Modify: `src/opportunity_tracker/models.py` — add a 5th member, `COVERAGE_GAP =
  "COVERAGE_GAP"`, to the `Bucket` enum defined in Task 2. This is the **only** change this
  plan makes to Task 2's `models.py`; every other dataclass/enum in that file is untouched.
  `"COVERAGE_GAP"` is not a valid value of the existing 4-member `Bucket` enum, so it must be
  added as a real enum member, not returned as a bare string literal.
- Create: `src/opportunity_tracker/evaluator/bucket.py`
- Create: `src/opportunity_tracker/evaluator/run.py`
- Test: `tests/unit/evaluator/test_bucket.py`
- Test: `tests/unit/evaluator/test_run.py`

**Interfaces:**
- Consumes: `opportunity_tracker.models.Bucket` (**extended by this task** with
  `COVERAGE_GAP`), `.Outcome`, `.RequirementKind`, `.REQUIRED_KINDS`, `.INFORMATIONAL_KINDS`,
  `.Requirement`, `.Profile`, `.Evaluation` (Task 2); `opportunity_tracker.config
  .STALENESS_DAYS` (Task 3); `opportunity_tracker.db.get_connection`, `.init_db` (Task 4 —
  used by this task's tests to build an in-memory fixture database;
  `evaluator/run.py` itself only consumes an already-open `sqlite3.Connection` passed in by
  its caller, it never opens one itself); `evaluator.rules.evaluate_requirement` (Task 20);
  `evaluator.feasibility.estimate_lead_time_days` (Task 21);
  `evaluator.trust.downgrade_if_untrusted` (Task 22).
- Produces:
  - `models.Bucket.COVERAGE_GAP` — the enum addition itself, consumed by the same later
    reporter task that reads any other `Bucket` member.
  - `evaluator.bucket.assign_bucket(outcomes: dict[RequirementKind, Outcome],
    has_any_requirements: bool, days_until_deadline: int | None, lead_time_days: int,
    most_stale_days: int) -> tuple[Bucket, dict]` — called by `run.py` in this same task.
  - `evaluator.run.evaluate_award(award_id: int, profile: Profile, conn: sqlite3.Connection,
    gold_set_recall: dict[str, float]) -> Evaluation` — the evaluator's one public entry
    point, called once per award by the later reporter/CLI task (Tasks 24–27). Its
    `per_requirement_outcomes` field is a flat `dict[str, str]` keyed by `RequirementKind
    .value`, mapping to `Outcome.value` — e.g. `{"deadline": "pass", "research_project
    _fraction": "fail"}`. It carries no `requirement_id` or source information; a consumer
    needing the source URL/`retrieved_at` behind a given kind's outcome (the reporter, Tasks
    24–25) must call `resolve_requirements_by_kind` below for that award, not read it out of
    this dict.
  - `evaluator.run.resolve_requirements_by_kind(conn: sqlite3.Connection, award_id: int) ->
    dict[RequirementKind, Requirement]` — the effective (resolved, per spec §4.4) requirement
    row per kind for an award, including each row's `document_id` for source lookups. Used
    internally by `evaluate_award` above, and reused directly by the reporter (Task 24) to
    render each requirement's source URL and `retrieved_at` — the reporter must import and
    call this rather than assuming `per_requirement_outcomes` carries a `requirement_id`.

**Note on `db.py`:** `db.init_db`'s `evaluation.bucket` `CHECK` constraint is built from
`_sql_list(Bucket)` — it iterates the `Bucket` enum at the time `init_db` runs. Because
Task 4's `db.py` already treats `models.py` as the single source of truth for this
constraint (see Task 4's own Interfaces note), adding `COVERAGE_GAP` to `Bucket` in this
task requires **no change to `db.py` at all** — the constraint picks it up automatically the
next time `init_db` runs against a fresh database. Do not hand-edit the `CHECK` clause in
`db.py`.

#### bucket.py

- [ ] **Step 1: Write the failing test for `bucket.py`**

```python
# tests/unit/evaluator/test_bucket.py
"""Bucket assignment and sort-key computation -- spec §7, §8, §9.1. Pure function: no
network, no LLM, no file I/O. `assign_bucket` takes outcomes as a raw dict, so these tests
exercise the bucket-assignment rule directly without going through rules.py -- this is
deliberate: RequirementKind.MIN_GRADE always evaluates to Outcome.UNKNOWN via rules.py
(spec §6.5), which would make an "all required kinds pass" scenario impossible to construct
through the real per-kind rules. Testing assign_bucket's own contract directly is the
correct layer for the staleness/deadline mandatory cases below."""
from opportunity_tracker.models import (
    INFORMATIONAL_KINDS,
    REQUIRED_KINDS,
    Bucket,
    Outcome,
    RequirementKind,
)
from opportunity_tracker.evaluator.bucket import assign_bucket


def _all_pass_outcomes() -> dict[RequirementKind, Outcome]:
    return {kind: Outcome.PASS for kind in RequirementKind}


def test_empty_requirement_set_is_coverage_gap():
    # Spec §9.1 mandatory case: empty requirement set -> COVERAGE GAP, never ELIGIBLE.
    bucket, _sort_keys = assign_bucket(
        outcomes={},
        has_any_requirements=False,
        days_until_deadline=100,
        lead_time_days=10,
        most_stale_days=0,
    )
    assert bucket == Bucket.COVERAGE_GAP
    assert bucket != Bucket.ACT_NOW


def test_intake_year_fail_forces_unknown_gated_even_when_no_other_required_kind_fails():
    # Spec §8: intake-year mismatch -> UNKNOWN-GATED, never LIKELY BLOCKED. Without the
    # special-case check running before the general FAIL check, this would incorrectly
    # produce LIKELY_BLOCKED (intake_year is itself a REQUIRED_KIND that failed).
    outcomes = _all_pass_outcomes()
    outcomes[RequirementKind.INTAKE_YEAR] = Outcome.FAIL
    bucket, _sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=100,
        lead_time_days=10,
        most_stale_days=0,
    )
    assert bucket == Bucket.UNKNOWN_GATED
    assert bucket != Bucket.LIKELY_BLOCKED


def test_other_required_fail_is_likely_blocked():
    outcomes = _all_pass_outcomes()
    outcomes[RequirementKind.RESEARCH_PROJECT_FRACTION] = Outcome.FAIL
    bucket, _sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=100,
        lead_time_days=10,
        most_stale_days=0,
    )
    assert bucket == Bucket.LIKELY_BLOCKED


def test_required_unknown_is_unknown_gated():
    outcomes = _all_pass_outcomes()
    outcomes[RequirementKind.ENGLISH_TEST] = Outcome.UNKNOWN
    bucket, _sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=100,
        lead_time_days=10,
        most_stale_days=0,
    )
    assert bucket == Bucket.UNKNOWN_GATED


def test_stale_requirement_bars_act_now():
    # Spec §7: a record whose retrieved_at is older than the staleness threshold cannot
    # enter ACT NOW, even though every required kind otherwise passes.
    outcomes = _all_pass_outcomes()
    bucket, _sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=100,
        lead_time_days=10,
        most_stale_days=31,  # > config.STALENESS_DAYS (30)
    )
    assert bucket == Bucket.ELIGIBLE_LATER
    assert bucket != Bucket.ACT_NOW


def test_deadline_sooner_than_lead_time_is_eligible_later():
    outcomes = _all_pass_outcomes()
    bucket, _sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=5,
        lead_time_days=63,
        most_stale_days=0,
    )
    assert bucket == Bucket.ELIGIBLE_LATER


def test_unknown_or_passed_deadline_is_eligible_later():
    outcomes = _all_pass_outcomes()
    bucket, _sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=None,
        lead_time_days=10,
        most_stale_days=0,
    )
    assert bucket == Bucket.ELIGIBLE_LATER


def test_all_pass_within_lead_time_is_act_now():
    outcomes = _all_pass_outcomes()
    bucket, _sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=100,
        lead_time_days=10,
        most_stale_days=0,
    )
    assert bucket == Bucket.ACT_NOW


def test_sort_keys_unknown_count_orders_records_with_0_1_2_unknowns():
    # Property test: sort_keys["unknown_count"] must correctly order records with
    # increasingly many unknowns among REQUIRED_KINDS (spec §7's safety valve).
    required_list = sorted(REQUIRED_KINDS, key=lambda k: k.value)
    scenarios = []
    for n_unknown in (0, 1, 2):
        outcomes = _all_pass_outcomes()
        for kind in required_list[:n_unknown]:
            outcomes[kind] = Outcome.UNKNOWN
        _bucket, sort_keys = assign_bucket(
            outcomes=outcomes,
            has_any_requirements=True,
            days_until_deadline=100,
            lead_time_days=10,
            most_stale_days=0,
        )
        scenarios.append(sort_keys)

    assert [s["unknown_count"] for s in scenarios] == [0, 1, 2]
    ordered = sorted(scenarios, key=lambda s: s["unknown_count"])
    assert [s["unknown_count"] for s in ordered] == [0, 1, 2]


def test_funding_completeness_counts_non_unknown_informational_kinds():
    outcomes = _all_pass_outcomes()
    for kind in INFORMATIONAL_KINDS:
        outcomes[kind] = Outcome.UNKNOWN
    _bucket, sort_keys = assign_bucket(
        outcomes=outcomes,
        has_any_requirements=True,
        days_until_deadline=100,
        lead_time_days=10,
        most_stale_days=0,
    )
    assert sort_keys["funding_completeness"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/evaluator/test_bucket.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.evaluator.bucket'`

- [ ] **Step 3: Edit `src/opportunity_tracker/models.py`, then write `src/opportunity_tracker/evaluator/bucket.py`**

Edit the existing `Bucket` enum in `src/opportunity_tracker/models.py` (defined in Task 2) —
add one line, change nothing else in the file:

```python
class Bucket(str, Enum):
    ACT_NOW = "ACT_NOW"
    ELIGIBLE_LATER = "ELIGIBLE_LATER"
    UNKNOWN_GATED = "UNKNOWN_GATED"
    LIKELY_BLOCKED = "LIKELY_BLOCKED"
    COVERAGE_GAP = "COVERAGE_GAP"
```

Then create `src/opportunity_tracker/evaluator/bucket.py`:

```python
"""Bucket assignment and sort-key computation. Pure function -- spec §7, §8. No network, no
LLM, no file I/O (spec §6.5's central invariant)."""
from __future__ import annotations

from opportunity_tracker import config
from opportunity_tracker.models import (
    INFORMATIONAL_KINDS,
    REQUIRED_KINDS,
    Bucket,
    Outcome,
    RequirementKind,
)


def assign_bucket(
    outcomes: dict[RequirementKind, Outcome],
    has_any_requirements: bool,
    days_until_deadline: int | None,
    lead_time_days: int,
    most_stale_days: int,
) -> tuple[Bucket, dict]:
    if not has_any_requirements:
        # Spec §9.1 mandatory case: empty requirement set -> COVERAGE GAP, never ELIGIBLE.
        bucket = Bucket.COVERAGE_GAP
    elif outcomes.get(RequirementKind.INTAKE_YEAR) == Outcome.FAIL:
        # Spec §8: an intake-year mismatch is UNKNOWN-GATED, never LIKELY BLOCKED -- this
        # check must run before the general required-kind-FAIL check below.
        bucket = Bucket.UNKNOWN_GATED
    elif any(outcomes.get(kind) == Outcome.FAIL for kind in REQUIRED_KINDS):
        bucket = Bucket.LIKELY_BLOCKED
    elif any(outcomes.get(kind) == Outcome.UNKNOWN for kind in REQUIRED_KINDS):
        bucket = Bucket.UNKNOWN_GATED
    elif most_stale_days > config.STALENESS_DAYS:
        # Stale data bars ACT NOW (spec §7), but the award is otherwise fully eligible so
        # it is not downgraded further than ELIGIBLE_LATER.
        bucket = Bucket.ELIGIBLE_LATER
    elif days_until_deadline is not None and days_until_deadline < lead_time_days:
        # Not feasible in the time remaining, but not blocked either (spec §6.4).
        bucket = Bucket.ELIGIBLE_LATER
    elif days_until_deadline is None or days_until_deadline < 0:
        # Deadline unknown, or already passed -- not right now, but not blocked.
        bucket = Bucket.ELIGIBLE_LATER
    else:
        bucket = Bucket.ACT_NOW

    unknown_count = sum(
        1 for kind in REQUIRED_KINDS if outcomes.get(kind) == Outcome.UNKNOWN
    )
    funding_completeness = sum(
        1
        for kind in INFORMATIONAL_KINDS
        if outcomes.get(kind) is not None and outcomes.get(kind) != Outcome.UNKNOWN
    )
    sort_keys = {
        "unknown_count": unknown_count,
        "days_until_deadline": (
            days_until_deadline if days_until_deadline is not None else 999999
        ),
        "funding_completeness": funding_completeness,
    }
    return bucket, sort_keys
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/evaluator/test_bucket.py -v`
Expected: PASS (9 tests)

#### run.py

- [ ] **Step 5: Write the failing test for `run.py`**

```python
# tests/unit/evaluator/test_run.py
"""Integration tests for evaluate_award: real in-memory sqlite3 DB via db.get_connection /
db.init_db, exercising requirement resolution order (spec §4.4) and evaluation persistence.
No network, no LLM anywhere in this module."""
import json

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.models import Bucket, Profile
from opportunity_tracker.evaluator.run import evaluate_award


def _make_conn():
    conn = get_connection(":memory:")
    init_db(conn)
    return conn


def _insert_profile(conn, version=1, attributes=None):
    attributes = attributes or {}
    conn.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES (?, ?, ?)",
        (version, "2026-08-22T00:00:00+00:00", json.dumps(attributes)),
    )
    conn.commit()
    return Profile(
        id=1, version=version, created_at="2026-08-22T00:00:00+00:00", attributes=attributes
    )


def _insert_award(conn, canonical_url="https://uwa.edu.au/award", intake_year=2027):
    conn.execute("INSERT INTO scheme (name, funder, jurisdiction) VALUES ('S', 'F', 'AU')")
    cursor = conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, 'UWA', 'AU', '[\"phd\"]', ?, ?)",
        (intake_year, canonical_url),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_document(conn, url, source_tier=1, retrieved_at="2026-08-22T00:00:00+00:00"):
    cursor = conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES "
        "(?, ?, 'http', 'hash123', 'docs/1.txt', ?, 'ok', 0)",
        (url, source_tier, retrieved_at),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_requirement(
    conn,
    award_id,
    document_id,
    kind,
    operator=None,
    value=None,
    unit=None,
    raw_text="raw",
    evidence="evidence",
    human_verified=0,
    extracted_at="2026-08-22T00:00:00+00:00",
):
    cursor = conn.execute(
        "INSERT INTO requirement (award_id, document_id, kind, operator, value, unit, "
        "raw_text, evidence, confidence, extracted_at, human_verified) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, 0.9, ?, ?)",
        (
            award_id,
            document_id,
            kind,
            operator,
            value,
            unit,
            raw_text,
            evidence,
            extracted_at,
            human_verified,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def test_evaluate_award_with_no_requirements_is_coverage_gap():
    # Spec §9.1 mandatory case, end to end through the database.
    conn = _make_conn()
    profile = _insert_profile(conn)
    award_id = _insert_award(conn)

    evaluation = evaluate_award(award_id, profile, conn, gold_set_recall={})

    assert evaluation.bucket == Bucket.COVERAGE_GAP
    assert evaluation.bucket != Bucket.ACT_NOW

    stored = conn.execute(
        "SELECT bucket FROM evaluation WHERE award_id = ?", (award_id,)
    ).fetchone()
    assert stored["bucket"] == "COVERAGE_GAP"


def test_evaluate_award_resolution_prefers_human_verified_over_other_rows():
    # Spec §4.4 resolution order: latest human_verified wins over a later-inserted but
    # unverified row, and over an earlier extraction.
    conn = _make_conn()
    profile = _insert_profile(conn, attributes={"research_project_fraction_held": 0.30})
    award_id = _insert_award(conn)
    document_id = _insert_document(conn, "https://uwa.edu.au/rules")

    _insert_requirement(
        conn,
        award_id,
        document_id,
        "research_project_fraction",
        ">=",
        "0.50",  # a wrong/uncorrected extraction
        "fraction",
        human_verified=0,
        extracted_at="2026-01-01T00:00:00+00:00",
    )
    _insert_requirement(
        conn,
        award_id,
        document_id,
        "research_project_fraction",
        ">=",
        "0.25",  # the human-corrected true value
        "fraction",
        human_verified=1,
        extracted_at="2026-06-01T00:00:00+00:00",
    )

    evaluation = evaluate_award(award_id, profile, conn, gold_set_recall={})

    # held (0.30) >= 0.25 -> pass. If resolution had picked the unverified 0.50 row instead,
    # this would be "fail" (0.30 >= 0.50 is false).
    assert evaluation.per_requirement_outcomes["research_project_fraction"] == "pass"


def test_evaluate_award_persists_evaluation_row_with_json_fields():
    conn = _make_conn()
    profile = _insert_profile(conn)
    award_id = _insert_award(conn)

    evaluation = evaluate_award(award_id, profile, conn, gold_set_recall={})

    row = conn.execute(
        "SELECT award_id, profile_version, bucket, sort_keys, per_requirement_outcomes "
        "FROM evaluation WHERE id = ?",
        (evaluation.id,),
    ).fetchone()
    assert row["award_id"] == award_id
    assert row["profile_version"] == profile.version
    assert row["bucket"] == evaluation.bucket.value
    assert json.loads(row["sort_keys"]) == evaluation.sort_keys
    assert json.loads(row["per_requirement_outcomes"]) == evaluation.per_requirement_outcomes
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/unit/evaluator/test_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.evaluator.run'`

- [ ] **Step 7: Write `src/opportunity_tracker/evaluator/run.py`**

```python
"""Evaluator orchestration: one award -> one Evaluation, using the append-only resolution
order from spec §4.4. No network, no LLM anywhere in this module -- the only I/O is reading
from and writing to the already-open sqlite3.Connection passed in by the caller (spec
§6.5's central invariant)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from opportunity_tracker.evaluator import bucket as bucket_module
from opportunity_tracker.evaluator import feasibility, rules, trust
from opportunity_tracker.models import (
    Evaluation,
    Outcome,
    Profile,
    Requirement,
    RequirementKind,
)


def resolve_requirements_by_kind(
    conn: sqlite3.Connection, award_id: int
) -> dict[RequirementKind, Requirement]:
    """Effective value per kind, per spec §4.4: latest human_verified row if any exist for
    that kind, else the latest row from the highest (best) source_tier, else latest by
    extracted_at."""
    rows = conn.execute(
        """
        SELECT r.id, r.award_id, r.document_id, r.kind, r.operator, r.value, r.unit,
               r.raw_text, r.evidence, r.confidence, r.extracted_at, r.human_verified,
               d.source_tier AS document_source_tier
        FROM requirement r
        JOIN document d ON d.id = r.document_id
        WHERE r.award_id = ?
        """,
        (award_id,),
    ).fetchall()

    by_kind: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)

    resolved: dict[RequirementKind, Requirement] = {}
    for kind_value, kind_rows in by_kind.items():
        verified_rows = [r for r in kind_rows if r["human_verified"]]
        if verified_rows:
            chosen = max(verified_rows, key=lambda r: r["extracted_at"])
        else:
            # Lower numeric value == higher-priority tier (Tier 1 is the most
            # authoritative source; see spec §5).
            best_tier = min(r["document_source_tier"] for r in kind_rows)
            tier_rows = [r for r in kind_rows if r["document_source_tier"] == best_tier]
            chosen = max(tier_rows, key=lambda r: r["extracted_at"])
        resolved[RequirementKind(kind_value)] = Requirement(
            id=chosen["id"],
            award_id=chosen["award_id"],
            document_id=chosen["document_id"],
            kind=RequirementKind(chosen["kind"]),
            operator=chosen["operator"],
            value=chosen["value"],
            unit=chosen["unit"],
            raw_text=chosen["raw_text"],
            evidence=chosen["evidence"],
            confidence=chosen["confidence"],
            extracted_at=chosen["extracted_at"],
            human_verified=bool(chosen["human_verified"]),
        )
    return resolved


def evaluate_award(
    award_id: int,
    profile: Profile,
    conn: sqlite3.Connection,
    gold_set_recall: dict[str, float],
) -> Evaluation:
    resolved = resolve_requirements_by_kind(conn, award_id)
    has_any_requirements = len(resolved) > 0

    outcomes: dict[RequirementKind, Outcome] = {}
    for kind in RequirementKind:
        requirement = resolved.get(kind)
        raw_outcome = rules.evaluate_requirement(requirement, profile)
        outcomes[kind] = trust.downgrade_if_untrusted(raw_outcome, kind, gold_set_recall)

    deadline_requirement = resolved.get(RequirementKind.DEADLINE)
    days_until_deadline: int | None = None
    if deadline_requirement is not None and deadline_requirement.value:
        try:
            deadline_date = datetime.fromisoformat(deadline_requirement.value).date()
            days_until_deadline = (
                deadline_date - datetime.now(timezone.utc).date()
            ).days
        except ValueError:
            days_until_deadline = None

    most_stale_days = 0
    if resolved:
        document_ids = sorted({req.document_id for req in resolved.values()})
        placeholders = ",".join("?" for _ in document_ids)
        doc_rows = conn.execute(
            f"SELECT retrieved_at FROM document WHERE id IN ({placeholders})",
            document_ids,
        ).fetchall()
        now = datetime.now(timezone.utc)
        ages = []
        for doc_row in doc_rows:
            retrieved_at = datetime.fromisoformat(doc_row["retrieved_at"])
            if retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
            ages.append((now - retrieved_at).days)
        most_stale_days = max(ages) if ages else 0

    lead_time_days = feasibility.estimate_lead_time_days(profile, list(resolved.values()))

    bucket_value, sort_keys = bucket_module.assign_bucket(
        outcomes=outcomes,
        has_any_requirements=has_any_requirements,
        days_until_deadline=days_until_deadline,
        lead_time_days=lead_time_days,
        most_stale_days=most_stale_days,
    )

    evaluated_at = datetime.now(timezone.utc).isoformat()
    per_requirement_outcomes = {k.value: v.value for k, v in outcomes.items()}

    cursor = conn.execute(
        "INSERT INTO evaluation (award_id, profile_version, evaluated_at, bucket, "
        "sort_keys, per_requirement_outcomes) VALUES (?, ?, ?, ?, ?, ?)",
        (
            award_id,
            profile.version,
            evaluated_at,
            bucket_value.value,
            json.dumps(sort_keys),
            json.dumps(per_requirement_outcomes),
        ),
    )
    conn.commit()

    return Evaluation(
        id=cursor.lastrowid,
        award_id=award_id,
        profile_version=profile.version,
        evaluated_at=evaluated_at,
        bucket=bucket_value,
        sort_keys=sort_keys,
        per_requirement_outcomes=per_requirement_outcomes,
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/unit/evaluator/test_run.py -v`
Expected: PASS (3 tests)

Then run the whole evaluator suite together to confirm nothing regressed:

Run: `uv run pytest tests/unit/evaluator/ tests/unit/test_models.py -v`
Expected: PASS (all tests across `test_rules.py`, `test_feasibility.py`, `test_trust.py`,
`test_bucket.py`, `test_run.py`, and the existing `test_models.py` — the `Bucket` enum
edit must not break any of Task 2's original model tests)

- [ ] **Step 9: Commit**

```bash
git add src/opportunity_tracker/models.py \
        src/opportunity_tracker/evaluator/bucket.py \
        src/opportunity_tracker/evaluator/run.py \
        tests/unit/evaluator/test_bucket.py \
        tests/unit/evaluator/test_run.py
git commit -m "feat: evaluator bucket assignment and per-award orchestration"
```
