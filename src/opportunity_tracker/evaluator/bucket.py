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
