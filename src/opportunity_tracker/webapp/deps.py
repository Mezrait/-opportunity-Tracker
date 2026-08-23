"""Shared FastAPI dependencies for the web UI: DB connections and the Jinja2
environment. Every route module imports from here, never from app.py (circular)."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi.templating import Jinja2Templates

from opportunity_tracker import config, db

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()
