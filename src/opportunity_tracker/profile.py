"""profile.yaml <-> `profile` table sync. See spec §4.5, §11.

The operator's profile is in flux (English test pending, grades finalising).
Comparing the new YAML against the latest stored version means an unchanged file
never creates a spurious new profile_version, while any real change is captured
as a new, immutable version so past evaluations stay interpretable.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import yaml

from opportunity_tracker.models import Profile


def _load_yaml_attributes(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _latest_profile_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, version, created_at, attributes FROM profile "
        "ORDER BY version DESC LIMIT 1"
    ).fetchone()


def sync_profile(yaml_path: str, conn: sqlite3.Connection) -> Profile:
    attributes = _load_yaml_attributes(yaml_path)
    existing = _latest_profile_row(conn)

    if existing is not None and json.loads(existing["attributes"]) == attributes:
        return Profile(
            id=existing["id"],
            version=existing["version"],
            created_at=existing["created_at"],
            attributes=json.loads(existing["attributes"]),
        )

    next_version = (existing["version"] + 1) if existing is not None else 1
    created_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES (?, ?, ?)",
        (next_version, created_at, json.dumps(attributes, sort_keys=True)),
    )
    conn.commit()
    return Profile(
        id=cursor.lastrowid,
        version=next_version,
        created_at=created_at,
        attributes=attributes,
    )
