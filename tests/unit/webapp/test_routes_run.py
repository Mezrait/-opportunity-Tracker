import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opportunity_tracker.webapp import routes_run
from opportunity_tracker.webapp.runner import RUN_STATE, RunState


@pytest.fixture(autouse=True)
def _reset_run_state():
    """RUN_STATE is a process-global singleton (Task 2) -- reset it before and after
    each test so state mutated by one test can't bleed into another."""
    RUN_STATE.__dict__.update(RunState().__dict__)
    yield
    RUN_STATE.__dict__.update(RunState().__dict__)


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(routes_run.router)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_idle_state_shows_no_search_running(client):
    """RUN_STATE.phase == 'idle' -> GET /run -> 200, 'No search is running' message
    and a link to /searches."""
    RUN_STATE.phase = "idle"

    response = client.get("/run")

    assert response.status_code == 200
    assert "No search is running" in response.text
    assert "/searches" in response.text


def test_active_run_shows_state_and_poll_script(client):
    """RUN_STATE mid-run -> GET /run -> 200, body includes filter name and the
    poll.js bootstrap script tag so the browser starts polling."""
    RUN_STATE.phase = "discovering"
    RUN_STATE.phase_current = 3
    RUN_STATE.phase_total = 10
    RUN_STATE.filter_name = "test-search"

    response = client.get("/run")

    assert response.status_code == 200
    assert "test-search" in response.text
    assert '<script src="/static/poll.js">' in response.text


def test_status_endpoint_returns_matching_json(client):
    """GET /api/run/status -> 200, JSON fields match RUN_STATE exactly."""
    RUN_STATE.phase = "discovering"
    RUN_STATE.phase_current = 3
    RUN_STATE.phase_total = 10
    RUN_STATE.filter_name = "test-search"

    response = client.get("/api/run/status")

    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "discovering"
    assert body["phase_current"] == 3
    assert body["phase_total"] == 10
    assert body["filter_name"] == "test-search"


def test_done_state_links_to_results(client):
    """RUN_STATE.phase == 'done' -> GET /run -> body contains a link to /results."""
    RUN_STATE.phase = "done"
    RUN_STATE.discovery_run_id = 5

    response = client.get("/run")

    assert response.status_code == 200
    assert "/results" in response.text


def test_failed_state_shows_error_and_link_back(client):
    """RUN_STATE.phase == 'failed' -> GET /run -> body contains the literal error
    message and a link back to /searches."""
    RUN_STATE.phase = "failed"
    RUN_STATE.error = "boom"

    response = client.get("/run")

    assert response.status_code == 200
    assert "boom" in response.text
    assert "/searches" in response.text
