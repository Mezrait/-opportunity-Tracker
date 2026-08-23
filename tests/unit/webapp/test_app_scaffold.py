from fastapi.testclient import TestClient

from opportunity_tracker.webapp.app import app


def test_static_files_are_mounted():
    client = TestClient(app)
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_base_template_renders_sidebar_links():
    from opportunity_tracker.webapp.deps import templates

    # Jinja2Templates exposes the underlying jinja2.Environment as .env
    rendered = templates.env.get_template("base.html").render(active_nav="dashboard")
    assert 'href="/profile"' in rendered
    assert 'href="/searches"' in rendered
    assert 'href="/pins"' in rendered
    assert 'href="/results"' in rendered
    assert "active" in rendered  # dashboard link carries the active class
