import json
import threading
import time
from pathlib import Path

import pytest

from opportunity_tracker import config, db, filters
from opportunity_tracker.webapp import runner


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "PROFILE_PATH", str(tmp_path / "profile.yaml"))
    monkeypatch.setattr(config, "SEEDS_PATH", str(tmp_path / "seeds.yaml"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    Path(config.PROFILE_PATH).write_text(
        "degree_level: phd\nnationality: Testland\n", encoding="utf-8"
    )
    # Reset the module-level singleton between tests -- it is process-global.
    runner.RUN_STATE.__dict__.update(runner.RunState().__dict__)
    yield


@pytest.fixture
def seeded_filter_id(tmp_path):
    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    filter_yaml = tmp_path / "one_filter.yaml"
    filter_yaml.write_text(
        "name: test-search\ncountry: Testland\ndegree_levels: [phd]\n"
        "fields: [computer science]\ninstitution_cap: 1\n",
        encoding="utf-8",
    )
    row = filters.sync_filter(str(filter_yaml), conn)
    conn.close()
    return row.id


def test_start_run_rejects_a_second_concurrent_run(seeded_filter_id):
    # Simulate an in-progress run directly -- start_run's lock check happens before
    # it ever touches the pipeline, so no mocking of the pipeline itself is needed.
    runner.RUN_STATE.active = True
    with pytest.raises(runner.RunAlreadyActiveError):
        runner.start_run(seeded_filter_id)


def test_run_pipeline_reaches_done_with_mocked_network(seeded_filter_id, monkeypatch):
    from opportunity_tracker.discovery import websearch as websearch_module

    def fake_search_institution(institution, filter_obj, api_key, max_uses=3):
        return []  # no candidates found -- still a complete, valid run

    monkeypatch.setattr(
        websearch_module, "search_institution", fake_search_institution
    )

    runner.start_run(seeded_filter_id)

    deadline = time.time() + 10
    while runner.RUN_STATE.phase not in ("done", "failed") and time.time() < deadline:
        time.sleep(0.1)

    assert runner.RUN_STATE.phase == "done", runner.RUN_STATE.error
    assert runner.RUN_STATE.active is False
    assert runner.RUN_STATE.finished_at is not None


def test_ensure_institution_directory_loaded_populates_an_empty_table(tmp_path, monkeypatch):
    fixture_path = tmp_path / "tiny_directory.json"
    fixture_path.write_text(
        json.dumps([
            {
                "name": "Testland Institute of Technology",
                "country": "Testland",
                "alpha_two_code": "TL",
                "domains": ["testland-tech.example"],
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "UNIVERSITY_DIRECTORY_PATH", str(fixture_path))

    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM institution").fetchone()["n"] == 0

    runner._ensure_institution_directory_loaded(conn)

    rows = conn.execute("SELECT domain, country FROM institution").fetchall()
    assert [dict(r) for r in rows] == [
        {"domain": "testland-tech.example", "country": "Testland"}
    ]
    conn.close()


def test_ensure_institution_directory_loaded_skips_an_already_populated_table(
    tmp_path, monkeypatch
):
    # Point at a fixture that would insert a DIFFERENT institution than the one
    # already seeded -- if the guard's COUNT(*) check were missing or broken, this
    # institution would show up too.
    fixture_path = tmp_path / "should_not_load.json"
    fixture_path.write_text(
        json.dumps([
            {
                "name": "Should Not Be Loaded University",
                "country": "Nowhere",
                "alpha_two_code": "XX",
                "domains": ["should-not-load.example"],
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "UNIVERSITY_DIRECTORY_PATH", str(fixture_path))

    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Pre-seeded University", "Testland", "TL", "pre-seeded.example",
         "hipo_directory", "test", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()

    runner._ensure_institution_directory_loaded(conn)

    domains = {r["domain"] for r in conn.execute("SELECT domain FROM institution")}
    assert domains == {"pre-seeded.example"}
    conn.close()


def test_run_pipeline_on_a_fresh_db_finds_a_candidate_at_a_real_institution(
    seeded_filter_id, monkeypatch
):
    # Reproduces the exact bug a real user hit: a brand-new database (no institution
    # rows) running a search that should match a real institution. Before the fix,
    # this silently completed with 0 institutions considered and 0 candidates found,
    # with nothing telling the user why.
    from opportunity_tracker.discovery import websearch as websearch_module

    fixture_path = Path(config.DB_PATH).parent / "one_real_institution.json"
    fixture_path.write_text(
        json.dumps([
            {
                "name": "Testland Institute of Technology",
                "country": "Testland",
                "alpha_two_code": "TL",
                "domains": ["testland-tech.example"],
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "UNIVERSITY_DIRECTORY_PATH", str(fixture_path))

    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM institution").fetchone()["n"] == 0
    conn.close()

    def fake_search_institution(institution, filter_obj, api_key, max_uses=3):
        return [{"url": "https://testland-tech.example/scholarships/phd", "title": "PhD Scholarship"}]

    monkeypatch.setattr(websearch_module, "search_institution", fake_search_institution)

    runner.start_run(seeded_filter_id)

    deadline = time.time() + 10
    while runner.RUN_STATE.phase not in ("done", "failed") and time.time() < deadline:
        time.sleep(0.1)

    assert runner.RUN_STATE.phase == "done", runner.RUN_STATE.error
    assert runner.RUN_STATE.candidates_found >= 1

    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM institution").fetchone()["n"] == 1
    candidate_count = conn.execute("SELECT COUNT(*) AS n FROM candidate").fetchone()["n"]
    assert candidate_count >= 1
    conn.close()


def test_run_pipeline_handles_db_connection_failure(seeded_filter_id, monkeypatch):
    """Test that RUN_STATE is correctly reset even if db.get_connection raises."""
    def failing_get_connection(db_path):
        raise OSError("Simulated disk full / permission error")

    monkeypatch.setattr(db, "get_connection", failing_get_connection)

    runner.start_run(seeded_filter_id)

    deadline = time.time() + 10
    while runner.RUN_STATE.active and time.time() < deadline:
        time.sleep(0.1)

    assert runner.RUN_STATE.active is False
    assert runner.RUN_STATE.phase == "failed"
    assert runner.RUN_STATE.error is not None
    assert "Simulated disk full" in runner.RUN_STATE.error
    assert runner.RUN_STATE.finished_at is not None
