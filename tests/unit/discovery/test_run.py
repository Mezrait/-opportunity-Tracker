"""Tests for discovery run orchestration: caching, institution_cap enforcement,
principle-7 counting, and manual pin ingestion. websearch.search_institution and
directory.list_institutions are always mocked -- this suite never calls the real
Anthropic API or a real database file (uses in-memory sqlite)."""
import json

import pytest
import yaml

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.discovery import websearch
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


# --- Whole-branch review I4: a capped run must be visibly partial, not silently complete ---

def test_run_records_total_available_institutions_before_the_cap(mocker, conn):
    filter_obj = _insert_filter(conn, institution_cap=2)
    institutions = [
        _insert_institution(conn, f"uni{i}.edu.au", name=f"Uni {i}") for i in range(5)
    ]
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=institutions)
    mocker.patch("opportunity_tracker.discovery.websearch.search_institution", return_value=[])

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.institutions_considered == 2
    assert run.institutions_available == 5  # the 3 past the cap are neither searched nor lost


def test_uncapped_run_reports_available_equal_to_considered(mocker, conn):
    filter_obj = _insert_filter(conn, institution_cap=50)
    institutions = [
        _insert_institution(conn, f"uni{i}.edu.au", name=f"Uni {i}") for i in range(3)
    ]
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=institutions)
    mocker.patch("opportunity_tracker.discovery.websearch.search_institution", return_value=[])

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.institutions_considered == run.institutions_available == 3


# --- Whole-branch review I5: searches_used is the billed count, not one per institution ----

def test_searches_used_reads_the_actual_billed_search_count(mocker, conn):
    filter_obj = _insert_filter(conn)
    institutions = [
        _insert_institution(conn, f"uni{i}.edu.au", name=f"Uni {i}") for i in range(2)
    ]
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=institutions)

    def _side_effect(institution, filter_obj_arg, api_key, max_uses=3):
        results = websearch.SearchResults(
            [{"url": f"https://{institution.domain}/rtp", "title": "RTP"}]
        )
        results.searches_used = 3  # search_institution is called with max_uses=3
        return results

    mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution", side_effect=_side_effect
    )

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.institutions_considered == 2
    assert run.searches_used == 6  # not 2 -- a flat +1 per institution undercounted by 3x


def test_searches_used_falls_back_to_one_for_a_plain_list_result(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "uwa.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        return_value=[{"url": "https://uwa.edu.au/rtp", "title": "RTP"}],
    )

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.searches_used == 1


def test_searches_used_counts_a_failed_search_as_one(mocker, conn):
    filter_obj = _insert_filter(conn)
    inst = _insert_institution(conn, "bad.edu.au")
    mocker.patch("opportunity_tracker.directory.list_institutions", return_value=[inst])
    mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        side_effect=RuntimeError("network exploded"),
    )

    run = run_discovery(filter_obj, conn, api_key="sk-test")

    assert run.searches_used == 1
    assert run.status == DiscoveryRunStatus.COMPLETED


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


# --- Whole-branch review I6: pins must not be re-ingested on every run --------------------

def _write_seeds(tmp_path, seeds):
    seeds_path = tmp_path / "seeds.yaml"
    seeds_path.write_text(yaml.safe_dump(seeds), encoding="utf-8")
    return str(seeds_path)


def test_ingesting_the_same_pins_twice_does_not_duplicate_candidates(tmp_path, conn):
    """ingest_manual_pins runs unconditionally on every `optrack run`. Without dedup, each
    run inserted a fresh candidate per pin, and each of those triggered a full re-fetch,
    re-extraction, and a duplicate set of requirement rows for an unchanged page."""
    seeds_path = _write_seeds(
        tmp_path,
        [{"institution_domain": "pinned.edu.au", "url": "https://pinned.edu.au/manual"}],
    )

    first = ingest_manual_pins(seeds_path, conn)
    second = ingest_manual_pins(seeds_path, conn)

    assert len(first) == 1
    assert second == []
    total = conn.execute("SELECT COUNT(*) AS n FROM candidate").fetchone()["n"]
    assert total == 1


def test_pin_is_skipped_when_discovery_already_found_the_same_url(tmp_path, conn):
    inst = _insert_institution(conn, "pinned.edu.au")
    conn.execute(
        "INSERT INTO candidate (discovery_run_id, institution_id, url, query_used, "
        "found_at, promoted_to_award_id) VALUES (NULL, ?, ?, 'q', ?, NULL)",
        (inst.id, "https://pinned.edu.au/manual", "2026-08-22T00:00:00+00:00"),
    )
    conn.commit()
    seeds_path = _write_seeds(
        tmp_path,
        [{"institution_domain": "pinned.edu.au", "url": "https://pinned.edu.au/manual"}],
    )

    assert ingest_manual_pins(seeds_path, conn) == []
    assert conn.execute("SELECT COUNT(*) AS n FROM candidate").fetchone()["n"] == 1


def test_a_new_pin_is_still_ingested_alongside_an_already_known_one(tmp_path, conn):
    seeds_path = _write_seeds(
        tmp_path,
        [{"institution_domain": "pinned.edu.au", "url": "https://pinned.edu.au/manual"}],
    )
    ingest_manual_pins(seeds_path, conn)

    seeds_path = _write_seeds(
        tmp_path,
        [
            {"institution_domain": "pinned.edu.au", "url": "https://pinned.edu.au/manual"},
            {"institution_domain": "pinned.edu.au", "url": "https://pinned.edu.au/second"},
        ],
    )
    new_ids = ingest_manual_pins(seeds_path, conn)

    assert len(new_ids) == 1
    urls = {r["url"] for r in conn.execute("SELECT url FROM candidate")}
    assert urls == {"https://pinned.edu.au/manual", "https://pinned.edu.au/second"}


# --- Whole-branch review I9: seeds.yaml can declare a source tier -------------------------

def test_pin_declared_tier_is_stored_on_the_candidate_row(tmp_path, conn):
    # Spec §5/§9.1's mandatory regression case: cybersure-master.eu matches no academic
    # suffix and is in no institution directory, so only a seed override makes it Tier 1.
    seeds_path = _write_seeds(
        tmp_path,
        [
            {
                "institution_domain": "cybersure-master.eu",
                "url": "https://www.cybersure-master.eu/admission",
                "declared_tier": 1,
            }
        ],
    )

    new_ids = ingest_manual_pins(seeds_path, conn)

    row = conn.execute(
        "SELECT declared_tier FROM candidate WHERE id = ?", (new_ids[0],)
    ).fetchone()
    assert row["declared_tier"] == 1


def test_pin_without_declared_tier_stores_null(tmp_path, conn):
    seeds_path = _write_seeds(
        tmp_path,
        [{"institution_domain": "pinned.edu.au", "url": "https://pinned.edu.au/manual"}],
    )

    new_ids = ingest_manual_pins(seeds_path, conn)

    row = conn.execute(
        "SELECT declared_tier FROM candidate WHERE id = ?", (new_ids[0],)
    ).fetchone()
    assert row["declared_tier"] is None
