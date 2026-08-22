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
    """Render one CSV row per evaluation: institution, award_url, bucket, days remaining,
    unknown_count, then one column per required RequirementKind holding that kind's
    outcome ('pass'/'fail'/'unknown'; 'unknown' when the kind has no recorded outcome at
    all — absence is never evidence of pass, spec principle 5). Sorted identically to
    reporter.markdown.render_report via the shared sort_evaluations helper. `conn` is
    accepted for interface symmetry with render_report and future per-row provenance
    enrichment; beyond award_url the CSV carries no source-URL columns.

    award_url is the award's canonical_url: one institution routinely offers several awards,
    and institution alone does not identify a row (matching the markdown reporter's table)."""
    buffer = io.StringIO()
    fieldnames = ["institution", "award_url", "bucket", "days_remaining", "unknown_count"] + [
        kind.value for kind in _REQUIRED_KIND_COLUMNS
    ]
    writer = csv.writer(buffer)
    writer.writerow(fieldnames)

    for evaluation in sort_evaluations(evaluations):
        award = awards_by_id[evaluation.award_id]
        outcomes = evaluation.per_requirement_outcomes or {}
        row = [
            award.institution,
            award.canonical_url,
            evaluation.bucket.value,
            evaluation.sort_keys["days_until_deadline"],
            evaluation.sort_keys["unknown_count"],
        ]
        for kind in _REQUIRED_KIND_COLUMNS:
            row.append(outcomes.get(kind.value, "unknown"))
        writer.writerow(row)

    return buffer.getvalue()
