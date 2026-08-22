"""Discovery run orchestration: filter -> candidate rows, with caching and manual
pin ingestion. Spec sections 6.0, 4.3, and principle 7 (NO_CANDIDATE_FOUND, never
silent)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import yaml

from opportunity_tracker import config, directory
from opportunity_tracker.discovery import websearch
from opportunity_tracker.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    Filter,
    InstitutionSource,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_discovery_run(row: sqlite3.Row) -> DiscoveryRun:
    return DiscoveryRun(
        id=row["id"],
        filter_id=row["filter_id"],
        filter_content_hash=row["filter_content_hash"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        institutions_considered=row["institutions_considered"],
        institutions_with_candidates=row["institutions_with_candidates"],
        searches_used=row["searches_used"],
        status=DiscoveryRunStatus(row["status"]),
    )


def _find_reusable_run(conn: sqlite3.Connection, filter_obj: Filter) -> DiscoveryRun | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.STALENESS_DAYS)).isoformat()
    row = conn.execute(
        "SELECT * FROM discovery_run WHERE filter_content_hash = ? AND status = ? "
        "AND started_at >= ? ORDER BY started_at DESC LIMIT 1",
        (filter_obj.content_hash, DiscoveryRunStatus.COMPLETED.value, cutoff),
    ).fetchone()
    return None if row is None else _row_to_discovery_run(row)


def run_discovery(
    filter_obj: Filter,
    conn: sqlite3.Connection,
    api_key: str,
    force_rediscover: bool = False,
) -> DiscoveryRun:
    """Run (or reuse) a discovery pass for `filter_obj`.

    Unless `force_rediscover`, a completed discovery_run with the same
    filter_content_hash started within config.STALENESS_DAYS is returned
    unchanged -- no new searches are spent (spec section 6.0 caching, section
    12 decision log: mirrors the fetcher's "unchanged hash => no downstream
    work" rule).

    Otherwise a new discovery_run row is inserted with status='running', and
    every institution the directory lists for `filter_obj.country` (capped at
    `filter_obj.institution_cap`) is searched via websearch.search_institution.
    An institution that yields zero results, or whose search call raises, is
    still counted in `institutions_considered` -- principle 7: discovery
    misses are logged, not silent. It is simply excluded from
    `institutions_with_candidates`. The row is updated to status='completed'
    once every institution has been processed.
    """
    if not force_rediscover:
        reusable = _find_reusable_run(conn, filter_obj)
        if reusable is not None:
            return reusable

    started_at = _now_iso()
    cursor = conn.execute(
        "INSERT INTO discovery_run (filter_id, filter_content_hash, started_at, "
        "completed_at, institutions_considered, institutions_with_candidates, "
        "searches_used, status) VALUES (?, ?, ?, NULL, 0, 0, 0, ?)",
        (filter_obj.id, filter_obj.content_hash, started_at, DiscoveryRunStatus.RUNNING.value),
    )
    conn.commit()
    run_id = cursor.lastrowid

    institutions = directory.list_institutions(conn, filter_obj.country)
    institutions = institutions[: filter_obj.institution_cap]

    institutions_considered = 0
    institutions_with_candidates = 0
    searches_used = 0

    for institution in institutions:
        institutions_considered += 1
        query_used = websearch.build_query(filter_obj, institution)

        try:
            results = websearch.search_institution(institution, filter_obj, api_key)
        except Exception:
            # A search failure degrades to "no candidate found" for this one
            # institution rather than aborting the whole run -- principle 4:
            # every error degrades toward UNKNOWN-GATED, never toward
            # deletion. The institution is still counted above; it's simply
            # excluded from institutions_with_candidates below.
            results = []
        searches_used += 1

        if results:
            institutions_with_candidates += 1
            for result in results:
                conn.execute(
                    "INSERT INTO candidate (discovery_run_id, institution_id, url, "
                    "query_used, found_at, promoted_to_award_id) VALUES "
                    "(?, ?, ?, ?, ?, NULL)",
                    (run_id, institution.id, result["url"], query_used, _now_iso()),
                )

        conn.execute(
            "UPDATE discovery_run SET institutions_considered = ?, "
            "institutions_with_candidates = ?, searches_used = ? WHERE id = ?",
            (institutions_considered, institutions_with_candidates, searches_used, run_id),
        )
        conn.commit()

    conn.execute(
        "UPDATE discovery_run SET completed_at = ?, status = ? WHERE id = ?",
        (_now_iso(), DiscoveryRunStatus.COMPLETED.value, run_id),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM discovery_run WHERE id = ?", (run_id,)).fetchone()
    return _row_to_discovery_run(row)


def ingest_manual_pins(seeds_yaml_path: str, conn: sqlite3.Connection) -> list[int]:
    """Ingest operator-curated seeds.yaml pins as `candidate` rows.

    Each seed is a mapping with at least `institution_domain` and `url`; it may
    optionally carry `name`, `country`, `country_code` to fill in a new
    institution row. The institution is looked up by domain; if missing, it's
    created with source=InstitutionSource.MANUAL, defaulting `name` to the
    domain and `country`/`country_code` to "Unknown"/"XX" when not given in
    the seed. Every inserted candidate has discovery_run_id=NULL and
    query_used='manual_pin', and is never deduplicated against discovery
    results -- a pin always represents explicit operator intent (spec section
    4.3). Returns the list of newly-inserted candidate ids, in seed order.
    """
    with open(seeds_yaml_path, "r", encoding="utf-8") as f:
        seeds = yaml.safe_load(f) or []

    new_candidate_ids: list[int] = []

    for seed in seeds:
        domain = seed["institution_domain"]
        url = seed["url"]

        institution_row = conn.execute(
            "SELECT id FROM institution WHERE domain = ?", (domain,)
        ).fetchone()

        if institution_row is None:
            cursor = conn.execute(
                "INSERT INTO institution (name, country, country_code, domain, "
                "source, directory_version, added_at) VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (
                    seed.get("name", domain),
                    seed.get("country", "Unknown"),
                    seed.get("country_code", "XX"),
                    domain,
                    InstitutionSource.MANUAL.value,
                    _now_iso(),
                ),
            )
            institution_id = cursor.lastrowid
        else:
            institution_id = institution_row["id"]

        cursor = conn.execute(
            "INSERT INTO candidate (discovery_run_id, institution_id, url, "
            "query_used, found_at, promoted_to_award_id) VALUES "
            "(NULL, ?, ?, 'manual_pin', ?, NULL)",
            (institution_id, url, _now_iso()),
        )
        new_candidate_ids.append(cursor.lastrowid)
        conn.commit()

    return new_candidate_ids
