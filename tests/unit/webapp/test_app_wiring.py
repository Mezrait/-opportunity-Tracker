import pytest
from fastapi.testclient import TestClient

from opportunity_tracker import config
from opportunity_tracker.webapp.app import app


@pytest.fixture(autouse=True)
def _isolated_db_path(tmp_path, monkeypatch):
    """Every route handler resolves its DB connection via config.DB_PATH at request
    time (see webapp/deps.py:get_db), so without this override each GET below would
    open/init_db a real SQLite file at the process's cwd -- and on a machine where
    optrack has already been used for real, that's the user's actual database."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))


def test_every_screen_is_reachable():
    client = TestClient(app)
    for path in ("/", "/profile", "/searches", "/pins", "/run", "/results"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"
