"""Searches screens: list, create, edit, and run saved searches (`filter` rows).

Each saved search is persisted as its own YAML file under `web_filters/` (spec
§4.3) -- a filesystem-safe slug of `name`, e.g. "Canada CS PhD" ->
`web_filters/canada-cs-phd.yaml` -- then synced into the `filter` table via the
real `filters.sync_filter`, which is the actual source of truth for identity:
two saves with byte-identical normalized content share a row (matched by
content_hash), while any real change creates a NEW filter row rather than
mutating the old one (already-tested behavior in filters.py, not this route's
job to reimplement).

`_WEB_FILTERS_DIR` is a relative path resolved against the process CWD, same
convention as `config.PROFILE_PATH` / `config.SEEDS_PATH`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from opportunity_tracker import filters
from opportunity_tracker.webapp import runner
from opportunity_tracker.webapp.deps import get_db, templates

router = APIRouter()

_WEB_FILTERS_DIR = Path("web_filters")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "search"


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Raw dict for a `filter` row -- used by the list screen, where optional
    fields are never rendered as bare form values so a real `None` is fine."""
    return {
        "id": row["id"],
        "name": row["name"],
        "country": row["country"],
        "degree_levels": json.loads(row["degree_levels"]),
        "fields": json.loads(row["fields"]),
        "funding_type": row["funding_type"],
        "deadline_after": row["deadline_after"],
        "min_grade": row["min_grade"],
        "institution_cap": row["institution_cap"],
    }


def _display_existing(row: sqlite3.Row) -> dict:
    """Template-facing dict for the edit form: every nullable optional field has
    `None` explicitly converted to `""` so Jinja never renders the literal string
    "None" into an input's value attribute (same bug class as profile.py)."""
    data = _row_to_dict(row)
    for key in ("funding_type", "deadline_after", "min_grade"):
        if data[key] is None:
            data[key] = ""
    return data


def _write_and_sync(
    conn: sqlite3.Connection,
    name: str,
    country: str,
    degree_levels: list[str],
    fields_raw: str,
    funding_type: str | None,
    deadline_after: str | None,
    min_grade: str | None,
    institution_cap: int,
) -> None:
    _WEB_FILTERS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(name)
    path = _WEB_FILTERS_DIR / f"{slug}.yaml"

    fields_list = [f.strip() for f in fields_raw.split(",") if f.strip()]

    data = {
        "name": name,
        "country": country,
        "degree_levels": list(degree_levels),
        "fields": fields_list,
        "funding_type": funding_type or None,
        "deadline_after": deadline_after or None,
        "min_grade": min_grade or None,
        "institution_cap": institution_cap,
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)

    filters.sync_filter(str(path), conn)


@router.get("/searches")
def list_searches(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Show one card per distinct saved search -- latest `filter` row per name,
    same dedup pattern as the dashboard (a name can have several rows over time
    as its content changes, one per edit)."""
    rows = conn.execute(
        "SELECT * FROM filter WHERE id IN (SELECT MAX(id) FROM filter GROUP BY name) "
        "ORDER BY name"
    ).fetchall()
    searches = [_row_to_dict(row) for row in rows]

    return templates.TemplateResponse(
        request, "searches_list.html",
        {
            "active_nav": "searches",
            "searches": searches,
            "has_searches": len(searches) > 0,
        },
    )


@router.get("/searches/new")
def new_search_form(request: Request):
    return templates.TemplateResponse(
        request, "search_form.html",
        {
            "active_nav": "searches",
            "existing": None,
            "form_action": "/searches/new",
        },
    )


@router.post("/searches/new")
def create_search(
    conn: sqlite3.Connection = Depends(get_db),
    name: str = Form(...),
    country: str = Form(...),
    degree_levels: list[str] = Form(...),
    fields: str = Form(...),
    funding_type: str | None = Form(None),
    deadline_after: str | None = Form(None),
    min_grade: str | None = Form(None),
    institution_cap: int = Form(50),
):
    _write_and_sync(
        conn, name, country, degree_levels, fields,
        funding_type, deadline_after, min_grade, institution_cap,
    )
    return RedirectResponse(url="/searches", status_code=303)


@router.get("/searches/{filter_id}/edit")
def edit_search_form(
    filter_id: int, request: Request, conn: sqlite3.Connection = Depends(get_db)
):
    row = conn.execute("SELECT * FROM filter WHERE id = ?", (filter_id,)).fetchone()
    existing = _display_existing(row) if row is not None else None

    return templates.TemplateResponse(
        request, "search_form.html",
        {
            "active_nav": "searches",
            "existing": existing,
            "form_action": f"/searches/{filter_id}/edit",
        },
    )


@router.post("/searches/{filter_id}/edit")
def update_search(
    filter_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    name: str = Form(...),
    country: str = Form(...),
    degree_levels: list[str] = Form(...),
    fields: str = Form(...),
    funding_type: str | None = Form(None),
    deadline_after: str | None = Form(None),
    min_grade: str | None = Form(None),
    institution_cap: int = Form(50),
):
    _write_and_sync(
        conn, name, country, degree_levels, fields,
        funding_type, deadline_after, min_grade, institution_cap,
    )
    return RedirectResponse(url="/searches", status_code=303)


@router.post("/searches/{filter_id}/run")
def run_search(filter_id: int):
    """Kick off the background pipeline for this saved search. If one is already
    active, the run screen is still the right place to be -- it shows whatever
    run IS in progress -- so this is not an error the operator needs to see."""
    try:
        runner.start_run(filter_id)
    except runner.RunAlreadyActiveError:
        pass
    return RedirectResponse(url="/run", status_code=303)
