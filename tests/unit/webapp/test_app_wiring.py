from fastapi.testclient import TestClient

from opportunity_tracker.webapp.app import app


def test_every_screen_is_reachable():
    client = TestClient(app)
    for path in ("/", "/profile", "/searches", "/pins", "/run", "/results"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"
