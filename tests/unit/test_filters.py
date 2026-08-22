from pathlib import Path

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.filters import sync_filter
from opportunity_tracker.models import Filter

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "filter_canada_cs_phd.yaml"


def test_sync_filter_creates_row_from_fixture():
    conn = get_connection(":memory:")
    init_db(conn)

    filt = sync_filter(str(FIXTURE_PATH), conn)

    assert isinstance(filt, Filter)
    assert filt.name == "canada-cs-phd"
    assert filt.country == "Canada"
    assert filt.degree_levels == ["phd"]
    assert filt.fields == ["computer science"]
    assert filt.funding_type is None
    assert filt.institution_cap == 50
    rows = conn.execute("SELECT COUNT(*) AS n FROM filter").fetchone()
    assert rows["n"] == 1


def test_sync_filter_same_file_twice_reuses_row():
    conn = get_connection(":memory:")
    init_db(conn)

    first = sync_filter(str(FIXTURE_PATH), conn)
    second = sync_filter(str(FIXTURE_PATH), conn)

    assert first.id == second.id
    assert first.content_hash == second.content_hash
    rows = conn.execute("SELECT COUNT(*) AS n FROM filter").fetchone()
    assert rows["n"] == 1


def test_sync_filter_changed_fields_produces_new_row(tmp_path):
    conn = get_connection(":memory:")
    init_db(conn)
    first = sync_filter(str(FIXTURE_PATH), conn)

    changed_path = tmp_path / "filter_changed.yaml"
    changed_path.write_text(
        "name: canada-cs-phd\n"
        "country: Canada\n"
        "degree_levels: [phd]\n"
        "fields: [robotics]\n"
        "funding_type: null\n"
        "deadline_after: null\n"
        "min_grade: null\n"
        "institution_cap: 50\n",
        encoding="utf-8",
    )
    second = sync_filter(str(changed_path), conn)

    assert second.id != first.id
    assert second.fields == ["robotics"]
    assert second.content_hash != first.content_hash
    rows = conn.execute("SELECT COUNT(*) AS n FROM filter").fetchone()
    assert rows["n"] == 2


def test_sync_filter_missing_institution_cap_defaults_to_50(tmp_path):
    conn = get_connection(":memory:")
    init_db(conn)

    path = tmp_path / "filter_no_cap.yaml"
    path.write_text(
        "name: no-cap-filter\n"
        "country: Canada\n"
        "degree_levels: [phd]\n"
        "fields: [computer science]\n",
        encoding="utf-8",
    )
    filt = sync_filter(str(path), conn)

    assert filt.institution_cap == 50
