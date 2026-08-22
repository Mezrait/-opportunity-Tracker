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
