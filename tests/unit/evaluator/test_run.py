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
