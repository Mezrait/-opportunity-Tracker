import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opportunity_tracker import db
from opportunity_tracker.models import Bucket, DiscoveryRunStatus
from opportunity_tracker.webapp import routes_dashboard
from opportunity_tracker.webapp.deps import get_db


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(routes_dashboard.router)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded_db():
    """Return an in-memory SQLite connection with initialized schema and no seed rows
    (unlike the Results screen's fixture, the Dashboard's empty-DB case is meaningful and
    must be tested with a genuinely empty profile/filter table)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.init_db(conn)
    yield conn
    conn.close()


def _override(app, seeded_db):
    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db


def _insert_filter(conn, filter_id=1, name="PhD Physics UK", country="United Kingdom"):
    conn.execute(
        "INSERT INTO filter (id, name, country, degree_levels, fields, funding_type, "
        "deadline_after, min_grade, institution_cap, content_hash, created_at) "
        "VALUES (?, ?, ?, '[\"phd\"]', '[\"physics\"]', NULL, NULL, NULL, 50, 'hash1', "
        "'2026-08-20T00:00:00')",
        (filter_id, name, country),
    )


def _insert_discovery_run(conn, run_id=1, filter_id=1, status=DiscoveryRunStatus.COMPLETED.value):
    conn.execute(
        "INSERT INTO discovery_run (id, filter_id, filter_content_hash, started_at, "
        "completed_at, institutions_considered, institutions_available, "
        "institutions_with_candidates, searches_used, status) "
        "VALUES (?, ?, 'hash1', '2026-08-21T00:00:00', '2026-08-21T01:00:00', 10, 10, 3, "
        "5, ?)",
        (run_id, filter_id, status),
    )


def test_empty_db_shows_empty_state_and_zero_profile(client, seeded_db, app):
    """Case 1: empty DB -> 200, empty-state message + link to /searches, "0/11 fields set"."""
    _override(app, seeded_db)

    response = client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "No searches yet" in text
    assert "/searches" in text
    assert "0/11 fields set" in text


def test_profile_completeness_counts_false_booleans_as_set(client, seeded_db, app):
    """Case 2: a profile row with some non-null attrs, including a `false` boolean, must
    count the `false` value as SET (not treated as unknown/unset)."""
    attrs = {
        "research_project_fraction_held": None,
        "english_test_result": None,
        "target_intake_year": 2027,
        "has_transcripts": False,
        "supervisor_confirmed": False,
        "thesis_required": None,
        "degree_level": "phd",
        "nationality": None,
        "prior_scholarship_exclusion": None,
        "return_obligation": None,
        "funding_component": None,
    }
    seeded_db.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES "
        "(1, '2026-08-23T00:00:00', ?)",
        (json.dumps(attrs),),
    )
    seeded_db.commit()
    _override(app, seeded_db)

    response = client.get("/")

    assert response.status_code == 200
    # target_intake_year, has_transcripts(False), supervisor_confirmed(False), degree_level = 4
    assert "4/11 fields set" in response.text


def test_saved_search_shows_last_run_status(client, seeded_db, app):
    """Case 3: a filter + discovery_run row -> the search's name and last-run status show
    up on the dashboard."""
    _insert_filter(seeded_db)
    _insert_discovery_run(seeded_db, status=DiscoveryRunStatus.COMPLETED.value)
    seeded_db.commit()
    _override(app, seeded_db)

    response = client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "PhD Physics UK" in text
    assert "completed" in text.lower()


def test_search_with_no_runs_shows_never_run(client, seeded_db, app):
    """A saved search with no discovery_run row at all shows 'Never run', not a crash."""
    _insert_filter(seeded_db)
    seeded_db.commit()
    _override(app, seeded_db)

    response = client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "PhD Physics UK" in text
    assert "Never run" in text


def test_search_with_evaluation_shows_act_now_count(client, seeded_db, app):
    """Case 4: a full filter -> discovery_run -> candidate -> award -> evaluation chain
    with bucket='ACT_NOW' shows a non-zero ACT_NOW count on that search's card. This is
    the dedup-by-award_id bucket-breakdown query -- the most important query in this task."""
    _insert_filter(seeded_db)
    _insert_discovery_run(seeded_db, status=DiscoveryRunStatus.COMPLETED.value)
    seeded_db.execute(
        "INSERT INTO institution (id, name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (1, 'Test Uni', 'United Kingdom', 'GB', "
        "'test.ac.uk', 'manual', NULL, '2026-08-01T00:00:00')"
    )
    seeded_db.execute(
        "INSERT INTO award (id, scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, NULL, 'Test Uni', 'United Kingdom', "
        "'[\"phd\"]', 2027, 'https://test.ac.uk/award')"
    )
    seeded_db.execute(
        "INSERT INTO candidate (id, discovery_run_id, institution_id, url, query_used, "
        "found_at, promoted_to_award_id, declared_tier) VALUES (1, 1, 1, "
        "'https://test.ac.uk/award', 'phd physics', '2026-08-21T00:30:00', 1, 1)"
    )
    seeded_db.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES "
        "(1, '2026-08-20T00:00:00', ?)",
        (json.dumps({"degree_level": "phd"}),),
    )
    # Two evaluations for the SAME award_id (append-only log, e.g. re-evaluated) -- the
    # dedup-by-MAX(id) must count this award only once, under its LATEST bucket.
    seeded_db.execute(
        "INSERT INTO evaluation (id, award_id, profile_version, evaluated_at, bucket, "
        "sort_keys, per_requirement_outcomes) VALUES (1, 1, 1, '2026-08-21T01:00:00', ?, "
        "?, ?)",
        (
            Bucket.COVERAGE_GAP.value,
            json.dumps({"unknown_count": 5, "days_until_deadline": None, "funding_completeness": 0.0}),
            json.dumps({"deadline": "unknown"}),
        ),
    )
    seeded_db.execute(
        "INSERT INTO evaluation (id, award_id, profile_version, evaluated_at, bucket, "
        "sort_keys, per_requirement_outcomes) VALUES (2, 1, 1, '2026-08-21T02:00:00', ?, "
        "?, ?)",
        (
            Bucket.ACT_NOW.value,
            json.dumps({"unknown_count": 0, "days_until_deadline": 30, "funding_completeness": 1.0}),
            json.dumps({"deadline": "pass"}),
        ),
    )
    seeded_db.commit()
    _override(app, seeded_db)

    response = client.get("/")

    assert response.status_code == 200
    text = response.text
    assert "PhD Physics UK" in text
    assert "Act Now: 1" in text
    # The stale COVERAGE_GAP evaluation must not also be counted -- only 1 award total.
    assert "Coverage Gap: 1" not in text
