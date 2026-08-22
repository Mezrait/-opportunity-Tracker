"""Tests for discovery run orchestration: caching, institution_cap enforcement,
principle-7 counting, and manual pin ingestion. websearch.search_institution and
directory.list_institutions are always mocked -- this suite never calls the real
Anthropic API or a real database file (uses in-memory sqlite)."""
import json

import pytest
import yaml

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.discovery.run import ingest_manual_pins, run_discovery
from opportunity_tracker.models import DiscoveryRunStatus, Filter, Institution, InstitutionSource


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    return c


def _insert_filter(conn, content_hash="hash-1", institution_cap=50, country="Australia"):
    cursor = conn.execute(
        "INSERT INTO filter (name, country, degree_levels, fields, funding_type, "
        "deadline_after, min_grade, institution_cap, content_hash, created_at) "
        "VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
        (
            "AU PhD CS",
            country,
            json.dumps(["PhD"]),
            json.dumps(["Computer Science"]),
            institution_cap,
            content_hash,
            "2026-08-22T00:00:00+00:00",
        ),
    )
    conn.commit()
    return Filter(
        id=cursor.lastrowid,
        name="AU PhD CS",
        country=country,
        degree_levels=["PhD"],
        fields=["Computer Science"],
        funding_type=None,
        deadline_after=None,
        min_grade=None,
        institution_cap=institution_cap,
        content_hash=content_hash,
        created_at="2026-08-22T00:00:00+00:00",
    )


def _insert_institution(conn, domain, name=None, country="Australia", country_code="AU"):
    name = name or domain
    cursor = conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, country, country_code, domain, InstitutionSource.HIPO_DIRECTORY.value,
         "2026.1", "2026-08-22T00:00:00+00:00"),
    )
    conn.commit()
    return Institution(
        id=cursor.lastrowid,
        name=name,
        country=country,
        country_code=country_code,
        domain=domain,
        source=InstitutionSource.HIPO_DIRECTORY,
        directory_version="2026.1",
        added_at="2026-08-22T00:00:00+00:00",
    )


def test_run_discovery_caches_within_staleness_window(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "uwa.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    search_mock = mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        return_value=[{"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP"}],
    )

    first = run_discovery(filter_obj, conn, api_key="sk-test")
    assert first.status == DiscoveryRunStatus.COMPLETED
    assert search_mock.call_count == 1

    second = run_discovery(filter_obj, conn, api_key="sk-test")
    assert second.id == first.id
    assert search_mock.call_count == 1  # not called again -- cache hit


def test_force_rediscover_bypasses_cache(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "uwa.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    search_mock = mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        return_value=[{"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP"}],
    )

    first = run_discovery(filter_obj, conn, api_key="sk-test")
    second = run_discovery(filter_obj, conn, api_key="sk-test", force_rediscover=True)

    assert second.id != first.id
    assert search_mock.call_count == 2


def test_institution_with_no_results_still_counted_considered(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "empty.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    mocker.patch("opportunity_tracker.discovery.websearch.search_institution", return_value=[])

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.institutions_considered == 1
    assert run.institutions_with_candidates == 0
    assert run.status == DiscoveryRunStatus.COMPLETED


def test_institution_cap_is_respected(mocker, conn):
    filter_obj = _insert_filter(conn, institution_cap=2)
    institutions = [
        _insert_institution(conn, f"uni{i}.edu.au", name=f"Uni {i}") for i in range(5)
    ]
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=institutions)
    search_mock = mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution", return_value=[]
    )

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert search_mock.call_count == 2
    assert run.institutions_considered == 2


def test_search_failure_for_one_institution_does_not_abort_run(mocker, conn):
    filter_obj = _insert_filter(conn)
    bad = _insert_institution(conn, "bad.edu.au", name="Bad Uni")
    good = _insert_institution(conn, "good.edu.au", name="Good Uni")
    mocker.patch(
        "opportunity_tracker.directory.list_institutions", return_value=[bad, good]
    )

    def _side_effect(institution, filter_obj_arg, api_key, max_uses=3):
        if institution.domain == "bad.edu.au":
            raise RuntimeError("network exploded")
        return [{"url": "https://good.edu.au/scholarships/rtp", "title": "RTP"}]

    mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution", side_effect=_side_effect
    )

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.status == DiscoveryRunStatus.COMPLETED
    assert run.institutions_considered == 2
    assert run.institutions_with_candidates == 1


def test_ingest_manual_pins_creates_candidate_with_null_discovery_run(tmp_path, conn):
    seeds_path = tmp_path / "seeds.yaml"
    seeds_path.write_text(
        yaml.safe_dump([
            {
                "institution_domain": "pinned.edu.au",
                "url": "https://pinned.edu.au/scholarships/manual",
                "name": "Pinned University",
                "country": "Australia",
                "country_code": "AU",
            }
        ]),
        encoding="utf-8",
    )

    new_ids = ingest_manual_pins(str(seeds_path), conn)

    assert len(new_ids) == 1
    row = conn.execute(
        "SELECT discovery_run_id, query_used, url FROM candidate WHERE id = ?",
        (new_ids[0],),
    ).fetchone()
    assert row["discovery_run_id"] is None
    assert row["query_used"] == "manual_pin"
    assert row["url"] == "https://pinned.edu.au/scholarships/manual"

    institution_row = conn.execute(
        "SELECT source FROM institution WHERE domain = ?", ("pinned.edu.au",)
    ).fetchone()
    assert institution_row["source"] == InstitutionSource.MANUAL.value
