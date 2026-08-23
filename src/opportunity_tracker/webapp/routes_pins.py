"""Pinned Links screen: lets the operator hand-add a URL that discovery might miss
(directory gaps, search misses). A pin is written to `seeds.yaml` (`config.SEEDS_PATH`)
in the same shape as `seeds.example.yaml`, then immediately ingested via
`discovery_run.ingest_manual_pins` so it shows up as a real `candidate` row
(`discovery_run_id IS NULL`) and flows through the same fetch/extract/evaluate pipeline
as a discovered candidate -- see spec §4.3, §6.0."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from opportunity_tracker import config
from opportunity_tracker.discovery import run as discovery_run
from opportunity_tracker.webapp.deps import get_db, templates

router = APIRouter()


@router.get("/pins")
def list_pins(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Show every manually pinned link -- distinguished from a discovery-found
    candidate by `discovery_run_id IS NULL` -- alongside the add-a-link form."""
    pins = conn.execute(
        "SELECT candidate.*, institution.name AS institution_name, "
        "institution.country FROM candidate "
        "JOIN institution ON candidate.institution_id = institution.id "
        "WHERE candidate.discovery_run_id IS NULL "
        "ORDER BY candidate.found_at DESC"
    ).fetchall()

    return templates.TemplateResponse(
        request, "pins.html",
        {
            "active_nav": "pins",
            "pins": pins,
            "has_pins": len(pins) > 0,
        },
    )


@router.post("/pins/add")
def add_pin(
    institution_domain: str = Form(...),
    url: str = Form(...),
    name: str = Form(""),
    country: str = Form(""),
    declared_tier: str = Form(""),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Append a new entry to `seeds.yaml`, then ingest it. Only non-blank optional
    keys are written -- matching `seeds.example.yaml`'s own shape, where an absent
    optional key is simply not present rather than set to null."""
    seeds_path = Path(config.SEEDS_PATH)
    if seeds_path.exists():
        with open(seeds_path, "r", encoding="utf-8") as f:
            seeds = yaml.safe_load(f) or []
    else:
        seeds = []

    entry: dict[str, str | int] = {
        "institution_domain": institution_domain.strip(),
        "url": url.strip(),
    }
    if name.strip():
        entry["name"] = name.strip()
    if country.strip():
        entry["country"] = country.strip()
    if declared_tier.strip():
        entry["declared_tier"] = int(declared_tier.strip())

    seeds.append(entry)

    with open(seeds_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(seeds, f)

    discovery_run.ingest_manual_pins(config.SEEDS_PATH, conn)

    return RedirectResponse(url="/pins", status_code=303)
