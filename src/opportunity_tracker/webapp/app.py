"""FastAPI app for the Opportunity Tracker web UI. Wires every screen's router
together with the shared static assets. Each route module's own tests build their
own minimal app instead of importing this one (Global Constraints) — this file is
exercised end-to-end only by test_app_wiring.py."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from opportunity_tracker.webapp import (
    routes_dashboard,
    routes_pins,
    routes_profile,
    routes_results,
    routes_run,
    routes_searches,
)

_BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Opportunity Tracker")
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

app.include_router(routes_dashboard.router)
app.include_router(routes_profile.router)
app.include_router(routes_searches.router)
app.include_router(routes_pins.router)
app.include_router(routes_run.router)
app.include_router(routes_results.router)
