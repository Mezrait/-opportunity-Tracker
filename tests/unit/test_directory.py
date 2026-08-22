from pathlib import Path

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.directory import load_institution_directory, list_institutions
from opportunity_tracker.models import Institution, InstitutionSource

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "institution_directory_sample.json"
)


def test_load_institution_directory_inserts_new_rows():
    conn = get_connection(":memory:")
    init_db(conn)

    inserted = load_institution_directory(
        str(FIXTURE_PATH), conn, directory_version="2026-08-01"
    )

    assert inserted == 4
    canada = list_institutions(conn, "canada")  # lower-case: case-insensitive match
    assert [i.name for i in canada] == [
        "McGill University",
        "University of British Columbia",
        "University of Toronto",
    ]
    assert all(isinstance(i, Institution) for i in canada)
    assert all(i.source == InstitutionSource.HIPO_DIRECTORY for i in canada)
    assert all(i.directory_version == "2026-08-01" for i in canada)


def test_load_institution_directory_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    load_institution_directory(str(FIXTURE_PATH), conn, directory_version="2026-08-01")

    second_pass = load_institution_directory(
        str(FIXTURE_PATH), conn, directory_version="2026-09-01"
    )

    assert second_pass == 0
    total = conn.execute("SELECT COUNT(*) AS n FROM institution").fetchone()["n"]
    assert total == 4


def test_load_institution_directory_does_not_overwrite_manual_row():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "U of T (manually added)",
            "Canada",
            "CA",
            "utoronto.ca",
            InstitutionSource.MANUAL.value,
            None,
            "2026-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()

    inserted = load_institution_directory(
        str(FIXTURE_PATH), conn, directory_version="2026-08-01"
    )

    assert inserted == 3  # utoronto.ca already present as a manual row, skipped
    row = conn.execute(
        "SELECT name, source FROM institution WHERE domain = ?", ("utoronto.ca",)
    ).fetchone()
    assert row["name"] == "U of T (manually added)"
    assert row["source"] == InstitutionSource.MANUAL.value
