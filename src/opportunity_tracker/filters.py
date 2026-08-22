"""filter.yaml <-> `filter` table sync. See spec §4.3.

Same sync pattern as profile.py, but keyed by content hash instead of a monotonic
version — a filter has no "supersedes" semantics, just identity. Reusing a row for
byte-identical content is what makes discovery_run caching (§6.0) possible: an
unchanged filter, matched by content_hash, reuses a prior discovery_run within the
staleness window instead of spending searches again.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import yaml

from opportunity_tracker import config
from opportunity_tracker.models import Filter


def _load_yaml(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _normalize(data: dict) -> dict:
    return {
        "name": data.get("name"),
        "country": data.get("country"),
        "degree_levels": data.get("degree_levels") or [],
        "fields": data.get("fields") or [],
        "funding_type": data.get("funding_type"),
        "deadline_after": data.get("deadline_after"),
        "min_grade": data.get("min_grade"),
        "institution_cap": data.get("institution_cap", config.INSTITUTION_CAP_DEFAULT),
    }


def _content_hash(normalized: dict) -> str:
    serialized = json.dumps(normalized, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _row_to_filter(row: sqlite3.Row) -> Filter:
    return Filter(
        id=row["id"],
        name=row["name"],
        country=row["country"],
        degree_levels=json.loads(row["degree_levels"]),
        fields=json.loads(row["fields"]),
        funding_type=row["funding_type"],
        deadline_after=row["deadline_after"],
        min_grade=row["min_grade"],
        institution_cap=row["institution_cap"],
        content_hash=row["content_hash"],
        created_at=row["created_at"],
    )


def sync_filter(yaml_path: str, conn: sqlite3.Connection) -> Filter:
    normalized = _normalize(_load_yaml(yaml_path))
    content_hash = _content_hash(normalized)

    existing = conn.execute(
        "SELECT * FROM filter WHERE content_hash = ? ORDER BY id LIMIT 1",
        (content_hash,),
    ).fetchone()
    if existing is not None:
        return _row_to_filter(existing)

    created_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO filter (name, country, degree_levels, fields, funding_type, "
        "deadline_after, min_grade, institution_cap, content_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            normalized["name"],
            normalized["country"],
            json.dumps(normalized["degree_levels"]),
            json.dumps(normalized["fields"]),
            normalized["funding_type"],
            normalized["deadline_after"],
            normalized["min_grade"],
            normalized["institution_cap"],
            content_hash,
            created_at,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM filter WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_filter(row)
