"""Hipo world_universities_and_domains.json -> `institution` table loader.
See spec §4.3, §6.0, §11.

Append-only, keyed by domain: reloading the directory inserts new institutions and
never deletes or updates existing rows — including rows a domain shares with a
manually-added institution, which always wins and is never overwritten.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from opportunity_tracker.models import Institution, InstitutionSource


def _row_to_institution(row: sqlite3.Row) -> Institution:
    return Institution(
        id=row["id"],
        name=row["name"],
        country=row["country"],
        country_code=row["country_code"],
        domain=row["domain"],
        source=InstitutionSource(row["source"]),
        directory_version=row["directory_version"],
        added_at=row["added_at"],
    )


def load_institution_directory(
    json_path: str, conn: sqlite3.Connection, directory_version: str
) -> int:
    with open(json_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    inserted = 0
    added_at = datetime.now(timezone.utc).isoformat()
    for entry in entries:
        name = entry.get("name")
        country = entry.get("country")
        country_code = entry.get("alpha_two_code")
        for domain in entry.get("domains") or []:
            existing = conn.execute(
                "SELECT id FROM institution WHERE domain = ?", (domain,)
            ).fetchone()
            if existing is not None:
                continue
            conn.execute(
                "INSERT INTO institution (name, country, country_code, domain, "
                "source, directory_version, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    country,
                    country_code,
                    domain,
                    InstitutionSource.HIPO_DIRECTORY.value,
                    directory_version,
                    added_at,
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def list_institutions(conn: sqlite3.Connection, country: str) -> list[Institution]:
    rows = conn.execute(
        "SELECT * FROM institution WHERE LOWER(country) = LOWER(?) ORDER BY name",
        (country,),
    ).fetchall()
    return [_row_to_institution(row) for row in rows]
