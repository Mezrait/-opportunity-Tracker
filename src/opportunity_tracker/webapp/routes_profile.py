"""Profile screen: the operator's own eligibility attributes, edited as a form and
persisted to `config.PROFILE_PATH` (YAML) then synced into the append-only `profile`
table via `profile.sync_profile` -- see spec §4.5, §11.

GET always reads the *latest synced* attributes from the DB (never re-parses the YAML
file directly): the DB is the source of truth `sync_profile` writes to, and the YAML
file on disk could be stale or out of sync with it in ways the DB never is.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from opportunity_tracker import config, profile
from opportunity_tracker.webapp.deps import get_db, templates

router = APIRouter()

# The plain text/number/select fields whose blank pre-fill must render as an empty
# `value=""` attribute -- NEVER the literal string "None". `None` is normalized to
# `""` here with an explicit `is None` check (not a truthy `or ""` shortcut), because
# a genuine falsy-but-valid value like `research_project_fraction_held == 0.0` must be
# preserved, not coerced to blank the same way a stray None would be.
_TEXT_NUMBER_FIELDS = (
    "research_project_fraction_held",
    "english_test_result",
    "target_intake_year",
    "degree_level",
    "nationality",
    "return_obligation",
    "funding_component",
)


def _latest_attributes(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT attributes FROM profile ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {}
    return json.loads(row["attributes"])


def _display_context(attributes: dict) -> dict:
    """Build the template-facing profile dict: every nullable text/number/select
    field has `None` explicitly converted to `""`; the two plain booleans default to
    `False` (never `None`); the two tri-state radios pass through their real
    True/False/None so the template can pick the correct radio via `is true`/`is
    false`/`is none` rather than ever printing the value as text."""
    display: dict = {}
    for key in _TEXT_NUMBER_FIELDS:
        value = attributes.get(key)
        display[key] = "" if value is None else value

    display["has_transcripts"] = bool(attributes.get("has_transcripts") or False)
    display["supervisor_confirmed"] = bool(attributes.get("supervisor_confirmed") or False)
    display["thesis_required"] = attributes.get("thesis_required")
    display["prior_scholarship_exclusion"] = attributes.get("prior_scholarship_exclusion")
    return display


@router.get("/profile")
def show_profile(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Load the latest synced attributes dict (empty dict if no profile row exists
    yet) from the DB and pre-fill the form."""
    attributes = _latest_attributes(conn)

    return templates.TemplateResponse(
        request, "profile.html",
        {
            "active_nav": "profile",
            "profile": _display_context(attributes),
        },
    )


@router.post("/profile")
def save_profile(
    conn: sqlite3.Connection = Depends(get_db),
    research_project_fraction_held: float | None = Form(None),
    english_test_result: str | None = Form(None),
    target_intake_year: int | None = Form(None),
    has_transcripts: bool = Form(False),
    supervisor_confirmed: bool = Form(False),
    thesis_required: bool | None = Form(None),
    degree_level: str | None = Form(None),
    nationality: str | None = Form(None),
    prior_scholarship_exclusion: bool | None = Form(None),
    return_obligation: str | None = Form(None),
    funding_component: str | None = Form(None),
):
    """Write the posted 11 fields to `config.PROFILE_PATH` as YAML, sync that file
    into the `profile` table, then redirect back to the form."""
    attributes = {
        "research_project_fraction_held": research_project_fraction_held,
        "english_test_result": english_test_result,
        "target_intake_year": target_intake_year,
        "has_transcripts": has_transcripts,
        "supervisor_confirmed": supervisor_confirmed,
        "thesis_required": thesis_required,
        "degree_level": degree_level,
        "nationality": nationality,
        "prior_scholarship_exclusion": prior_scholarship_exclusion,
        "return_obligation": return_obligation,
        "funding_component": funding_component,
    }

    profile_path = Path(config.PROFILE_PATH)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(attributes, f)

    profile.sync_profile(config.PROFILE_PATH, conn)

    return RedirectResponse(url="/profile", status_code=303)
