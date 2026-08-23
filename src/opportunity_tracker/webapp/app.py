"""FastAPI app for the Opportunity Tracker web UI. Route modules are wired in by
Task 9 (`app.include_router(...)`) once every screen's router exists; until then this
file serves only the static assets and is not itself the app under test — each route
module's tests build their own minimal app (Global Constraints)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

_BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Opportunity Tracker")
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

# Task 9 adds one `app.include_router(...)` line per screen here, once every route
# module (Tasks 3-8) exists:
#   from opportunity_tracker.webapp import (
#       routes_dashboard, routes_pins, routes_profile, routes_results, routes_run,
#       routes_searches,
#   )
#   app.include_router(routes_dashboard.router)
#   app.include_router(routes_profile.router)
#   app.include_router(routes_searches.router)
#   app.include_router(routes_pins.router)
#   app.include_router(routes_run.router)
#   app.include_router(routes_results.router)
