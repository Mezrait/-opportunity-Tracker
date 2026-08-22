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
            "| Filter ID | Considered / Available | With Candidates | No Candidate Found "
            "| Searches Used | Coverage |"
        )
        lines.append("|---|---|---|---|---|---|")
        for run in discovery_runs:
            no_candidate = run.institutions_considered - run.institutions_with_candidates
            # filter.institution_cap truncates the directory listing before discovery runs,
            # so institutions past the cap are never searched and never recorded as
            # NO_CANDIDATE_FOUND -- they are simply absent. Showing considered/available
            # (and flagging the shortfall) is what keeps a capped run from reading as a
            # complete one; spec principle 7, a miss is logged, never silent.
            available = run.institutions_available
            if available > run.institutions_considered:
                coverage = (
                    f"**partial — capped, {available - run.institutions_considered} "
                    "institution(s) not searched**"
                )
            elif available == 0:
                coverage = "unknown (not recorded)"
            else:
                coverage = "complete"
            lines.append(
                f"| {run.filter_id} | {run.institutions_considered} / {available} | "
                f"{run.institutions_with_candidates} | {no_candidate} | "
                f"{run.searches_used} | {coverage} |"
            )
    lines.append("")

    return "\n".join(lines)
