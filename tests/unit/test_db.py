import sqlite3

import pytest

from opportunity_tracker.db import get_connection, init_db


def test_init_db_creates_all_tables():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "scheme", "award", "document", "requirement", "profile", "evaluation",
        "unclassified_rule", "institution", "filter", "discovery_run", "candidate",
    }
    assert expected <= tables


def test_init_db_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    init_db(conn)  # must not raise


def test_requirement_roundtrip_and_kind_constraint():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO scheme (name, funder, jurisdiction) VALUES ('S', 'F', 'AU')"
    )
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, 'UWA', 'AU', '[\"phd\"]', 2027, "
        "'https://uwa.edu.au/award')"
    )
    conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES "
        "('https://uwa.edu.au/rules', 1, 'http', 'abc123', 'docs/1.txt', "
        "'2026-08-22T00:00:00', 'ok', 0)"
    )
    conn.execute(
        "INSERT INTO requirement (award_id, document_id, kind, operator, value, "
        "unit, raw_text, evidence, confidence, extracted_at, human_verified) VALUES "
        "(1, 1, 'research_project_fraction', '>=', '0.25', 'fraction', "
        "'at least 25 percent FTE', 'the project must be at least 25 percent FTE', "
        "0.9, '2026-08-22T00:00:00', 0)"
    )
    conn.commit()
    row = conn.execute("SELECT kind, value FROM requirement").fetchone()
    assert row["kind"] == "research_project_fraction"
    assert row["value"] == "0.25"

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO requirement (award_id, document_id, kind, operator, "
            "value, unit, raw_text, evidence, extracted_at, human_verified) VALUES "
            "(1, 1, 'not_a_real_kind', null, null, null, 'x', 'x', "
            "'2026-08-22T00:00:00', 0)"
        )
