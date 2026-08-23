"""Tests for the Searches screens (Task 5): list, new, edit, run.

Each saved search is persisted to its own YAML file under `web_filters/` (spec
§4.3), then synced into the `filter` table via the real `filters.sync_filter` --
editing an existing search overwrites that same slug's file and re-syncs, and if
the content actually changed this naturally creates a NEW `filter` row (different
`content_hash`) per `sync_filter`'s own identity-based semantics, not something
this route needs to special-case.

`routes_searches.py` defines its own `_WEB_FILTERS_DIR = Path("web_filters")`
module-level constant (a relative path, resolved against the process CWD, same
convention as `config.PROFILE_PATH` etc.) -- tests `monkeypatch.chdir(tmp_path)`
so it lands in the temp dir instead of the real repo.
"""
from __future__ import annotations

import json
import re
import sqlite3

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opportunity_tracker import db
from opportunity_tracker.webapp import routes_searches, runner
from opportunity_tracker.webapp.deps import get_db

FULL_POST_DATA = {
    "name": "Canada CS PhD",
    "country": "Canada",
    "degree_levels": ["phd", "masters"],
    "fields": "computer science, machine learning",
    "funding_type": "fully funded",
    "deadline_after": "2027-01-01",
    "min_grade": "First Class",
    "institution_cap": "30",
}


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(routes_searches.router)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded_db():
    """Return an in-memory SQLite connection with initialized schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """`_WEB_FILTERS_DIR` is a relative path resolved against the process CWD --
    chdir into a temp dir so `web_filters/` lands there instead of the real repo."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def wired(app, seeded_db):
    """Wire the test app's get_db dependency to the seeded in-memory connection."""
    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db
    return seeded_db


def _tag_for_name(html: str, name: str) -> str:
    """Extract the single <input ...> tag whose `name="<name>"` attribute matches."""
    match = re.search(rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*>', html)
    assert match is not None, f"no <input> found for name={name!r}"
    return match.group(0)


def _checkbox_tags_for_name(html: str, name: str) -> list[str]:
    return re.findall(
        rf'<input\b[^>]*\btype="checkbox"[^>]*\bname="{re.escape(name)}"[^>]*>|'
        rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*\btype="checkbox"[^>]*>',
        html,
    )


def test_get_searches_empty_db_shows_empty_state(client, wired):
    """Case 1: GET /searches on an empty DB -> 200, empty-state message, link to
    /searches/new."""
    response = client.get("/searches")
    assert response.status_code == 200
    assert "no search" in response.text.lower()
    assert "/searches/new" in response.text


def test_post_new_full_payload_creates_filter_and_yaml(client, wired, tmp_path):
    """Case 2: POST /searches/new with a full valid payload -> 303 redirect to
    /searches; a filter row exists with the right values; web_filters/<slug>.yaml
    exists on disk and parses back to matching values."""
    response = client.post("/searches/new", data=FULL_POST_DATA, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/searches"

    row = wired.execute("SELECT * FROM filter").fetchone()
    assert row is not None
    assert row["name"] == "Canada CS PhD"
    assert row["country"] == "Canada"
    assert json.loads(row["degree_levels"]) == ["phd", "masters"]
    assert json.loads(row["fields"]) == ["computer science", "machine learning"]
    assert row["funding_type"] == "fully funded"
    assert row["deadline_after"] == "2027-01-01"
    assert row["min_grade"] == "First Class"
    assert row["institution_cap"] == 30

    yaml_path = tmp_path / "web_filters" / "canada-cs-phd.yaml"
    assert yaml_path.exists(), f"expected {yaml_path} to exist"
    on_disk = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert on_disk["name"] == "Canada CS PhD"
    assert on_disk["country"] == "Canada"
    assert on_disk["degree_levels"] == ["phd", "masters"]
    assert on_disk["fields"] == ["computer science", "machine learning"]
    assert on_disk["funding_type"] == "fully funded"
    assert on_disk["deadline_after"] == "2027-01-01"
    assert on_disk["min_grade"] == "First Class"
    assert on_disk["institution_cap"] == 30


def test_post_new_colliding_slugs_do_not_overwrite_each_other(client, wired, tmp_path):
    """Regression test for the slug-collision bug: `_slugify` strips punctuation,
    so two different search names -- "Canada CS!!!" and "Canada CS???" -- both
    reduce to the slug "canada-cs". Both searches must still get their own
    correct, distinct filter row (already true before the fix) AND their own
    distinct on-disk YAML file (the actual bug: both used to be written to the
    same `web_filters/canada-cs.yaml`, so the second save silently overwrote
    the first's file). Assert both files exist, are different paths, and each
    file's content matches only its own search -- neither was clobbered."""
    data_a = dict(FULL_POST_DATA)
    data_a["name"] = "Canada CS!!!"
    data_a["country"] = "Canada"

    data_b = dict(FULL_POST_DATA)
    data_b["name"] = "Canada CS???"
    data_b["country"] = "United States"

    resp_a = client.post("/searches/new", data=data_a, follow_redirects=False)
    assert resp_a.status_code == 303
    resp_b = client.post("/searches/new", data=data_b, follow_redirects=False)
    assert resp_b.status_code == 303

    rows = wired.execute("SELECT id, name, country FROM filter ORDER BY id").fetchall()
    assert len(rows) == 2, "each search must still get its own distinct filter row"
    assert {row["name"] for row in rows} == {"Canada CS!!!", "Canada CS???"}
    assert {row["country"] for row in rows} == {"Canada", "United States"}

    web_filters_dir = tmp_path / "web_filters"
    yaml_files = sorted(web_filters_dir.glob("*.yaml"))
    assert len(yaml_files) == 2, (
        "two colliding-slug searches must produce two distinct on-disk YAML "
        f"files, not one overwriting the other; found: {[p.name for p in yaml_files]}"
    )
    assert yaml_files[0] != yaml_files[1]

    contents_by_name = {}
    for path in yaml_files:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        contents_by_name[parsed["name"]] = parsed

    assert set(contents_by_name) == {"Canada CS!!!", "Canada CS???"}
    assert contents_by_name["Canada CS!!!"]["country"] == "Canada"
    assert contents_by_name["Canada CS???"]["country"] == "United States"


def test_get_searches_after_post_shows_name_and_country(client, wired):
    """Case 3: GET /searches after Step 2's POST -> 200, response body contains
    the search's name and country."""
    client.post("/searches/new", data=FULL_POST_DATA, follow_redirects=False)

    response = client.get("/searches")
    assert response.status_code == 200
    assert "Canada CS PhD" in response.text
    assert "Canada" in response.text


def test_get_edit_form_prefilled_with_current_values(client, wired):
    """Case 4: GET /searches/{id}/edit for an existing search -> 200, form
    pre-filled with its current values."""
    client.post("/searches/new", data=FULL_POST_DATA, follow_redirects=False)
    filter_id = wired.execute("SELECT id FROM filter").fetchone()["id"]

    response = client.get(f"/searches/{filter_id}/edit")
    assert response.status_code == 200
    html = response.text

    name_tag = _tag_for_name(html, "name")
    assert 'value="Canada CS PhD"' in name_tag

    country_tag = _tag_for_name(html, "country")
    assert 'value="Canada"' in country_tag

    checkboxes = _checkbox_tags_for_name(html, "degree_levels")
    assert len(checkboxes) == 2
    for box in checkboxes:
        assert "checked" in box, f"expected both degree_levels checked, got: {box}"

    fields_tag = _tag_for_name(html, "fields")
    assert "computer science" in fields_tag and "machine learning" in fields_tag

    funding_tag = _tag_for_name(html, "funding_type")
    assert 'value="fully funded"' in funding_tag

    deadline_tag = _tag_for_name(html, "deadline_after")
    assert 'value="2027-01-01"' in deadline_tag

    min_grade_tag = _tag_for_name(html, "min_grade")
    assert 'value="First Class"' in min_grade_tag

    cap_tag = _tag_for_name(html, "institution_cap")
    assert 'value="30"' in cap_tag


def test_post_edit_changed_country_creates_new_filter_row(client, wired, tmp_path):
    """Case 5: POST /searches/{id}/edit with changed country -> a new filter row
    is created (different content_hash than the original); GET /searches shows
    the updated country."""
    client.post("/searches/new", data=FULL_POST_DATA, follow_redirects=False)
    original_row = wired.execute("SELECT id, content_hash FROM filter").fetchone()
    filter_id = original_row["id"]
    original_hash = original_row["content_hash"]

    edit_data = dict(FULL_POST_DATA)
    edit_data["country"] = "United States"

    response = client.post(
        f"/searches/{filter_id}/edit", data=edit_data, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/searches"

    rows = wired.execute("SELECT id, country, content_hash FROM filter ORDER BY id").fetchall()
    assert len(rows) == 2, "editing should create a new filter row, not mutate the old one"
    newest = rows[-1]
    assert newest["country"] == "United States"
    assert newest["content_hash"] != original_hash

    list_response = client.get("/searches")
    assert "United States" in list_response.text


def test_post_run_calls_start_run_with_filter_id_and_redirects(client, wired, monkeypatch):
    """Case 6: POST /searches/{id}/run -> 303 redirect to /run; start_run is
    called with the right filter_id (monkeypatched on the runner module so the
    route's own module-attribute lookup picks it up)."""
    client.post("/searches/new", data=FULL_POST_DATA, follow_redirects=False)
    filter_id = wired.execute("SELECT id FROM filter").fetchone()["id"]

    calls = []

    def fake_start_run(fid):
        calls.append(fid)

    monkeypatch.setattr(runner, "start_run", fake_start_run)

    response = client.post(f"/searches/{filter_id}/run", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/run"
    assert calls == [filter_id]


def test_post_run_already_active_still_redirects_not_500(client, wired, monkeypatch):
    """Case 7: POST /searches/{id}/run when runner.start_run raises
    RunAlreadyActiveError -> still redirects to /run (not a 500)."""
    client.post("/searches/new", data=FULL_POST_DATA, follow_redirects=False)
    filter_id = wired.execute("SELECT id FROM filter").fetchone()["id"]

    def fake_start_run(fid):
        raise runner.RunAlreadyActiveError("A run is already in progress.")

    monkeypatch.setattr(runner, "start_run", fake_start_run)

    response = client.post(f"/searches/{filter_id}/run", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/run"
