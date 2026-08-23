"""Live run-progress screen: a page shell plus the JSON status endpoint it polls."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from opportunity_tracker.webapp import runner
from opportunity_tracker.webapp.deps import templates

router = APIRouter()


@router.get("/run", name="run_page")
def run_page(request: Request):
    return templates.TemplateResponse(
        request, "run.html", {"active_nav": "run", "state": runner.RUN_STATE}
    )


@router.get("/api/run/status", name="run_status")
def run_status():
    return asdict(runner.RUN_STATE)
