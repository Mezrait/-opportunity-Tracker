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
