"""Results screen: global ranked view of all evaluations, grouped by bucket."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request

from opportunity_tracker.models import Award, Bucket, Evaluation
from opportunity_tracker.reporter.markdown import BUCKET_ORDER, BUCKET_TITLES, sort_evaluations
from opportunity_tracker.webapp.deps import get_db, templates

router = APIRouter()


@router.get("/results")
def results(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Display all evaluations ranked by bucket, then by sort criteria within each bucket."""
    # Query the latest evaluation per award_id (spec §4.5 -- evaluation is append-only,
    # re-running evaluate-all would otherwise duplicate every award)
    evaluation_rows = conn.execute(
        "SELECT id, award_id, profile_version, evaluated_at, bucket, sort_keys, "
        "per_requirement_outcomes FROM evaluation "
        "WHERE id IN (SELECT MAX(id) FROM evaluation GROUP BY award_id)"
    ).fetchall()

    if not evaluation_rows:
        return templates.TemplateResponse(
            request, "results.html",
            {
                "active_nav": "results",
                "by_bucket": {},
                "BUCKET_TITLES": BUCKET_TITLES,
                "awards_by_id": {},
                "has_results": False,
            },
        )

    # Build Evaluation objects from rows
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

    # Fetch all awards into a dict for easy lookup by id
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

    # Sort evaluations using the real, tested ranking logic
    ordered = sort_evaluations(evaluations)

    # Group by bucket in BUCKET_ORDER
    by_bucket = {bucket: [] for bucket in BUCKET_ORDER}
    for evaluation in ordered:
        by_bucket[evaluation.bucket].append(evaluation)

    return templates.TemplateResponse(
        request, "results.html",
        {
            "active_nav": "results",
            "by_bucket": by_bucket,
            "BUCKET_TITLES": BUCKET_TITLES,
            "awards_by_id": awards_by_id,
            "has_results": len(evaluations) > 0,
        },
    )
