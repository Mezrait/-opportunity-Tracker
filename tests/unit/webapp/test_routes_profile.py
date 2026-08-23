"""Tests for the Profile screen (Task 4). The profile form's 11 fields are synced to
`config.PROFILE_PATH` (YAML) and then into the `profile` table via `profile.sync_profile`
-- GET must read the latest *synced* attributes from the DB (never re-parse the YAML
file directly, which could be stale or unsynced), and every nullable field's blank
pre-fill must render as an empty value, never the literal text "None" (a confirmed bug
in a prior attempt at this task: `dict.get(key, '')` only substitutes the default when
the key is ABSENT, but a saved-blank field is present with value `None`, so `.get()`
returns `None` and Jinja renders the 4-character string "None" into the input)."""
from __future__ import annotations

import json
import re
import sqlite3

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opportunity_tracker import config, db
from opportunity_tracker.webapp import routes_profile
from opportunity_tracker.webapp.deps import get_db

FULL_POST_DATA = {
    "research_project_fraction_held": "0.5",
    "english_test_result": "IELTS 7.5",
    "target_intake_year": "2027",
    "has_transcripts": "true",
    "supervisor_confirmed": "true",
    "thesis_required": "true",
    "degree_level": "phd",
    "nationality": "Testland",
    "prior_scholarship_exclusion": "false",
    "return_obligation": "5 years of service",
    "funding_component": "full tuition + stipend",
}

FULL_ATTRIBUTES = {
    "research_project_fraction_held": 0.5,
    "english_test_result": "IELTS 7.5",
    "target_intake_year": 2027,
    "has_transcripts": True,
    "supervisor_confirmed": True,
    "thesis_required": True,
    "degree_level": "phd",
    "nationality": "Testland",
    "prior_scholarship_exclusion": False,
    "return_obligation": "5 years of service",
    "funding_component": "full tuition + stipend",
}


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(routes_profile.router)
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
def _isolated_profile_path(tmp_path, monkeypatch):
    """`config.PROFILE_PATH` is read fresh on every request, so patching the module
    attribute is enough -- no need to touch anything inside routes_profile itself."""
    monkeypatch.setattr(config, "PROFILE_PATH", str(tmp_path / "profile.yaml"))


@pytest.fixture
def wired(app, seeded_db):
    """Wire the test app's get_db dependency to the seeded in-memory connection."""
    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db
    return seeded_db


def _tag_for_name(html: str, name: str) -> str:
    """Extract the single <input ...> (or <select ...>...</select>) tag/block whose
    `name="<name>"` attribute matches -- attribute-order-agnostic."""
    # Try a self-closing/void <input ...> tag first.
    input_match = re.search(
        rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*>', html
    )
    if input_match:
        return input_match.group(0)
    # Fall back to a <select ...>...</select> block.
    select_match = re.search(
        rf'<select\b[^>]*\bname="{re.escape(name)}"[^>]*>.*?</select>', html, re.DOTALL
    )
    assert select_match is not None, f"no <input>/<select> found for name={name!r}"
    return select_match.group(0)


def _radio_tags_for_name(html: str, name: str) -> list[str]:
    return re.findall(
        rf'<input\b[^>]*\btype="radio"[^>]*\bname="{re.escape(name)}"[^>]*>|'
        rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*\btype="radio"[^>]*>',
        html,
    )


def test_get_profile_empty_db_renders_blank_form(client, wired):
    """Case 1: GET /profile with no profile row yet -> 200, every field blank/unchecked."""
    response = client.get("/profile")
    assert response.status_code == 200
    html = response.text

    for name in (
        "research_project_fraction_held",
        "english_test_result",
        "target_intake_year",
        "nationality",
        "return_obligation",
        "funding_component",
    ):
        tag = _tag_for_name(html, name)
        assert 'value=""' in tag, f"{name} should be blank, got: {tag}"
        assert "None" not in tag, f"{name} rendered the literal string None: {tag}"

    for name in ("has_transcripts", "supervisor_confirmed"):
        tag = _tag_for_name(html, name)
        assert "checked" not in tag, f"{name} should be unchecked, got: {tag}"

    select_tag = _tag_for_name(html, "degree_level")
    assert 'value="phd" selected' not in select_tag
    assert 'value="masters" selected' not in select_tag

    for name in ("thesis_required", "prior_scholarship_exclusion"):
        radios = _radio_tags_for_name(html, name)
        assert len(radios) == 3, f"expected 3 radios for {name}, got {radios}"
        blank_radio = next(r for r in radios if 'value=""' in r)
        assert "checked" in blank_radio
        for r in radios:
            if 'value=""' not in r:
                assert "checked" not in r


def test_post_profile_full_values_persists_and_redirects(client, wired):
    """Case 2: POST /profile with a full set of values -> 303 redirect to /profile;
    a profile row exists with version=1 and the posted values under the right keys;
    the YAML file at config.PROFILE_PATH round-trips to the same dict."""
    response = client.post("/profile", data=FULL_POST_DATA, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile"

    row = wired.execute("SELECT version, attributes FROM profile").fetchone()
    assert row is not None
    assert row["version"] == 1
    assert json.loads(row["attributes"]) == FULL_ATTRIBUTES

    profile_path = config.PROFILE_PATH
    import pathlib
    assert pathlib.Path(profile_path).exists()
    on_disk = yaml.safe_load(pathlib.Path(profile_path).read_text(encoding="utf-8"))
    assert on_disk == FULL_ATTRIBUTES


def test_post_profile_blank_optional_text_fields_store_null(client, wired):
    """Case 3: POST /profile leaving english_test_result and nationality blank -> the
    stored attributes JSON has null for them, not empty strings."""
    data = dict(FULL_POST_DATA)
    data["english_test_result"] = ""
    data["nationality"] = ""

    response = client.post("/profile", data=data, follow_redirects=False)
    assert response.status_code == 303

    row = wired.execute("SELECT attributes FROM profile").fetchone()
    stored = json.loads(row["attributes"])
    assert stored["english_test_result"] is None
    assert stored["nationality"] is None
    assert stored["english_test_result"] != ""
    assert stored["nationality"] != ""


def test_post_profile_twice_identical_values_stays_one_row(client, wired):
    """Case 4: POST /profile twice with identical values -> still only one profile
    row (version stays 1) -- sync_profile's own no-op-on-unchanged behavior."""
    first = client.post("/profile", data=FULL_POST_DATA, follow_redirects=False)
    second = client.post("/profile", data=FULL_POST_DATA, follow_redirects=False)

    assert first.status_code == 303
    assert second.status_code == 303

    rows = wired.execute("SELECT version FROM profile").fetchall()
    assert len(rows) == 1
    assert rows[0]["version"] == 1


def test_get_profile_after_post_prefills_correctly_no_none_literal(client, wired):
    """Case 5: GET /profile after a POST -> fields pre-filled from the latest synced
    values (checkbox checked, select has right option selected), AND a field left
    blank on the POST renders as an EMPTY value attribute, never the string "None"."""
    data = dict(FULL_POST_DATA)
    data["english_test_result"] = ""  # left blank on purpose
    data["nationality"] = ""  # left blank on purpose
    data["degree_level"] = "masters"
    data["thesis_required"] = ""  # unknown
    data["prior_scholarship_exclusion"] = "false"

    post_response = client.post("/profile", data=data, follow_redirects=False)
    assert post_response.status_code == 303

    response = client.get("/profile")
    assert response.status_code == 200
    html = response.text

    # The blank fields must render as an empty value -- NEVER the literal "None".
    for name in ("english_test_result", "nationality"):
        tag = _tag_for_name(html, name)
        assert 'value=""' in tag, f"{name} should render blank, got: {tag}"
        assert "None" not in tag, f'BUG: {name} rendered the literal string "None": {tag}'

    # Filled text fields keep their value.
    return_tag = _tag_for_name(html, "return_obligation")
    assert 'value="5 years of service"' in return_tag

    # Checkboxes reflect the checked state.
    for name in ("has_transcripts", "supervisor_confirmed"):
        tag = _tag_for_name(html, name)
        assert "checked" in tag, f"{name} should be checked, got: {tag}"

    # The select has the right option selected.
    select_tag = _tag_for_name(html, "degree_level")
    assert 'value="masters" selected' in select_tag or re.search(
        r'<option[^>]*value="masters"[^>]*selected', select_tag
    )
    assert 'value="phd" selected' not in select_tag

    # thesis_required left "unknown" -> the blank radio is checked, not true/false.
    thesis_radios = _radio_tags_for_name(html, "thesis_required")
    blank_radio = next(r for r in thesis_radios if 'value=""' in r)
    assert "checked" in blank_radio
    for r in thesis_radios:
        if 'value=""' not in r:
            assert "checked" not in r

    # prior_scholarship_exclusion=false -> the "false" radio is checked.
    prior_radios = _radio_tags_for_name(html, "prior_scholarship_exclusion")
    false_radio = next(r for r in prior_radios if 'value="false"' in r)
    assert "checked" in false_radio

    # Belt-and-braces: the literal string "None" must not appear anywhere near a
    # form value in the whole page.
    assert 'value="None"' not in html


def test_post_profile_zero_fraction_is_not_treated_as_blank(client, wired):
    """A genuine 0.0 for research_project_fraction_held is a real, falsy-but-valid
    value -- it must round-trip and render as "0.0", not be coerced to blank the way
    a naive `value or ''` template pattern would (0.0 is falsy in both Python and
    Jinja2)."""
    data = dict(FULL_POST_DATA)
    data["research_project_fraction_held"] = "0"

    post_response = client.post("/profile", data=data, follow_redirects=False)
    assert post_response.status_code == 303

    row = wired.execute("SELECT attributes FROM profile").fetchone()
    stored = json.loads(row["attributes"])
    assert stored["research_project_fraction_held"] == 0.0

    response = client.get("/profile")
    tag = _tag_for_name(response.text, "research_project_fraction_held")
    assert 'value=""' not in tag, f"a genuine 0 must not render blank: {tag}"
    assert re.search(r'value="0(\.0)?"', tag), f"expected value=\"0\"/\"0.0\", got: {tag}"
