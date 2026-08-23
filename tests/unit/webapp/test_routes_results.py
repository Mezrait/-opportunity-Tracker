import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opportunity_tracker import db
from opportunity_tracker.models import Bucket
from opportunity_tracker.webapp import routes_results
from opportunity_tracker.webapp.deps import get_db


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(routes_results.router)

    @test_app.get("/")
    def home():
        return {"message": "test"}

    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded_db():
    """Return an in-memory SQLite connection with initialized schema."""
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.init_db(conn)
    # Seed a profile row so evaluations can reference it
    conn.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES (1, '2026-08-23T00:00:00', ?)",
        (json.dumps({"degree_level": "phd"}),),
    )
    conn.commit()
    yield conn
    conn.close()


def test_empty_db_returns_empty_state(client, seeded_db, app):
    """Empty DB → GET `/results` → 200, empty-state message, link to `/searches`."""
    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/results")
    assert response.status_code == 200
    assert "No results yet" in response.text or "no results" in response.text.lower()
    assert "/searches" in response.text


def test_single_award_with_evaluation(client, seeded_db, app):
    """Seed one award + evaluation → shows institution, bucket title, badges."""
    # Seed the data
    seeded_db.execute(
        "INSERT INTO award (id, scheme_id, institution, country, degree_levels, intake_year, canonical_url) "
        "VALUES (1, NULL, 'Test University', 'Testland', '[]', NULL, 'https://test.edu/award')"
    )
    seeded_db.execute(
        "INSERT INTO evaluation "
        "(id, award_id, profile_version, evaluated_at, bucket, sort_keys, per_requirement_outcomes) "
        "VALUES (1, 1, 1, '2026-08-23T00:00:00', ?, ?, ?)",
        (
            Bucket.ACT_NOW.value,
            json.dumps({"unknown_count": 0, "days_until_deadline": 30, "funding_completeness": 1.0}),
            json.dumps({"deadline": "pass"}),
        ),
    )
    seeded_db.commit()

    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/results")
    assert response.status_code == 200
    assert "Test University" in response.text
    assert "Act Now" in response.text
    assert "pass" in response.text.lower()


def test_multiple_buckets_in_order(client, seeded_db, app):
    """Seed two awards/evaluations with different buckets → ACT_NOW before COVERAGE_GAP."""
    # Seed awards
    seeded_db.execute(
        "INSERT INTO award (id, scheme_id, institution, country, degree_levels, intake_year, canonical_url) "
        "VALUES (1, NULL, 'ACT NOW Uni', 'Testland', '[]', NULL, 'https://test1.edu/award')"
    )
    seeded_db.execute(
        "INSERT INTO award (id, scheme_id, institution, country, degree_levels, intake_year, canonical_url) "
        "VALUES (2, NULL, 'Coverage Gap Uni', 'Testland', '[]', NULL, 'https://test2.edu/award')"
    )
    # Seed evaluations
    seeded_db.execute(
        "INSERT INTO evaluation "
        "(id, award_id, profile_version, evaluated_at, bucket, sort_keys, per_requirement_outcomes) "
        "VALUES (1, 1, 1, '2026-08-23T00:00:00', ?, ?, ?)",
        (
            Bucket.ACT_NOW.value,
            json.dumps({"unknown_count": 0, "days_until_deadline": 30, "funding_completeness": 1.0}),
            json.dumps({"deadline": "pass"}),
        ),
    )
    seeded_db.execute(
        "INSERT INTO evaluation "
        "(id, award_id, profile_version, evaluated_at, bucket, sort_keys, per_requirement_outcomes) "
        "VALUES (2, 2, 1, '2026-08-23T00:00:00', ?, ?, ?)",
        (
            Bucket.COVERAGE_GAP.value,
            json.dumps({"unknown_count": 5, "days_until_deadline": None, "funding_completeness": 0.0}),
            json.dumps({"deadline": "unknown"}),
        ),
    )
    seeded_db.commit()

    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/results")
    assert response.status_code == 200
    # ACT_NOW section should appear before COVERAGE_GAP in the HTML
    act_now_pos = response.text.find("Act Now")
    coverage_gap_pos = response.text.find("Coverage Gap")
    assert act_now_pos > -1, "Act Now section not found"
    assert coverage_gap_pos > -1, "Coverage Gap section not found"
    assert act_now_pos < coverage_gap_pos, "Act Now should appear before Coverage Gap"


def test_latest_evaluation_per_award(client, seeded_db, app):
    """Seed two evaluations for same award_id → shows award once with newer evaluation's bucket."""
    # Seed one award
    seeded_db.execute(
        "INSERT INTO award (id, scheme_id, institution, country, degree_levels, intake_year, canonical_url) "
        "VALUES (1, NULL, 'Test Uni', 'Testland', '[]', NULL, 'https://test.edu/award')"
    )
    # Seed two evaluations for the same award (older one)
    seeded_db.execute(
        "INSERT INTO evaluation "
        "(id, award_id, profile_version, evaluated_at, bucket, sort_keys, per_requirement_outcomes) "
        "VALUES (1, 1, 1, '2026-08-23T00:00:00', ?, ?, ?)",
        (
            Bucket.COVERAGE_GAP.value,
            json.dumps({"unknown_count": 5, "days_until_deadline": None, "funding_completeness": 0.0}),
            json.dumps({"deadline": "unknown"}),
        ),
    )
    # Seed newer evaluation for same award with different bucket
    seeded_db.execute(
        "INSERT INTO evaluation "
        "(id, award_id, profile_version, evaluated_at, bucket, sort_keys, per_requirement_outcomes) "
        "VALUES (2, 1, 1, '2026-08-23T01:00:00', ?, ?, ?)",
        (
            Bucket.ACT_NOW.value,
            json.dumps({"unknown_count": 0, "days_until_deadline": 30, "funding_completeness": 1.0}),
            json.dumps({"deadline": "pass"}),
        ),
    )
    seeded_db.commit()

    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/results")
    assert response.status_code == 200
    # Count how many times "Test Uni" appears (should be only once)
    count = response.text.count("Test Uni")
    assert count == 1, f"Expected Test Uni to appear once, but it appeared {count} times"
    # Verify it's using the newer evaluation's bucket (ACT_NOW, not COVERAGE_GAP)
    assert "Act Now" in response.text
