"""Dashboard screen: profile completeness + one card per saved search.

Profile completeness (spec §3.4): the profile has exactly 11 attribute keys
(profile.example.yaml). "Set" means the JSON value for that key is not null/missing --
a boolean `false` (e.g. has_transcripts, supervisor_confirmed) is a real, deliberate
answer and counts as SET, not "unknown". Use `is not None`, never a truthy check.

Per-search bucket breakdown (spec §3.4) scopes evaluations to the distinct set of
awards a given saved search actually produced -- found via a subquery joining
award -> candidate -> discovery_run -- and dedups to the latest evaluation per
award_id. Two joins matter here, for different reasons:

  * evaluation is an append-only log, so a re-evaluated award would otherwise be
    counted once per evaluation row instead of once per award (see routes_results.py
    for the same dedup pattern).
  * candidate.promoted_to_award_id is NOT unique: re-running a saved search after the
    discovery cache's staleness window expires can re-surface a URL it already knows
    about, producing a second candidate (under a different discovery_run) that gets
    promoted to the SAME award. A naive `JOIN candidate` (rather than a `WHERE
    award_id IN (SELECT DISTINCT ...)` subquery) would fan out to one row per
    candidate and double-count that award's single evaluation bucket.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request

from opportunity_tracker.reporter.markdown import BUCKET_ORDER, BUCKET_TITLES
from opportunity_tracker.webapp.deps import get_db, templates

router = APIRouter()

_PROFILE_FIELDS = (
    "research_project_fraction_held", "english_test_result", "target_intake_year",
    "has_transcripts", "supervisor_confirmed", "thesis_required", "degree_level",
    "nationality", "prior_scholarship_exclusion", "return_obligation", "funding_component",
)

# String-keyed view of BUCKET_TITLES so template lookups against `evaluation.bucket`
# (a plain TEXT column value) don't depend on str/Enum hash-equality subtleties.
BUCKET_LABELS: dict[str, str] = {bucket.value: BUCKET_TITLES[bucket] for bucket in BUCKET_ORDER}


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
                "SELECT e.bucket, COUNT(*) AS n "
                "FROM evaluation e "
                "WHERE e.award_id IN ("
                "  SELECT DISTINCT a.id FROM award a "
                "  JOIN candidate c ON c.promoted_to_award_id = a.id "
                "  JOIN discovery_run dr ON dr.id = c.discovery_run_id "
                "  WHERE dr.filter_id = ?"
                ") "
                "AND e.id IN (SELECT MAX(id) FROM evaluation GROUP BY award_id) "
                "GROUP BY e.bucket",
                (row["id"],),
            )
        }
        searches.append({
            "id": row["id"],
            "name": row["name"],
            "country": row["country"],
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
            "bucket_labels": BUCKET_LABELS,
        },
    )
