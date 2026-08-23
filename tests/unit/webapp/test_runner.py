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
