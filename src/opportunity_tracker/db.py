"""SQLite schema and connection management. Raw SQL, no ORM — see spec §4."""
import sqlite3

from opportunity_tracker.models import (
    Bucket,
    DiscoveryRunStatus,
    FetchMethod,
    InstitutionSource,
    RequirementKind,
)


def _sql_list(values) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS scheme (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        funder TEXT,
        jurisdiction TEXT
    );

    CREATE TABLE IF NOT EXISTS award (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme_id INTEGER REFERENCES scheme(id),
        institution TEXT NOT NULL,
        country TEXT NOT NULL,
        degree_levels TEXT NOT NULL,
        intake_year INTEGER,
        canonical_url TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS document (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        source_tier INTEGER NOT NULL CHECK (source_tier IN (1, 2, 3)),
        fetch_method TEXT NOT NULL CHECK (fetch_method IN ({_sql_list(FetchMethod)})),
        content_hash TEXT NOT NULL,
        text_path TEXT,
        retrieved_at TEXT NOT NULL,
        fetch_status TEXT NOT NULL,
        degraded INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS requirement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        award_id INTEGER NOT NULL REFERENCES award(id),
        document_id INTEGER NOT NULL REFERENCES document(id),
        kind TEXT NOT NULL CHECK (kind IN ({_sql_list(RequirementKind)})),
        operator TEXT,
        value TEXT,
        unit TEXT,
        raw_text TEXT NOT NULL,
        evidence TEXT NOT NULL,
        confidence REAL,
        extracted_at TEXT NOT NULL,
        human_verified INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        attributes TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS evaluation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        award_id INTEGER NOT NULL REFERENCES award(id),
        profile_version INTEGER NOT NULL REFERENCES profile(version),
        evaluated_at TEXT NOT NULL,
        bucket TEXT NOT NULL CHECK (bucket IN ({_sql_list(Bucket)})),
        sort_keys TEXT NOT NULL,
        per_requirement_outcomes TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS unclassified_rule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER NOT NULL REFERENCES document(id),
        raw_text TEXT NOT NULL,
        logged_at TEXT NOT NULL,
        reviewed INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS institution (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        country TEXT NOT NULL,
        country_code TEXT NOT NULL,
        domain TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL CHECK (source IN ({_sql_list(InstitutionSource)})),
        directory_version TEXT,
        added_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS filter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        country TEXT NOT NULL,
        degree_levels TEXT NOT NULL,
        fields TEXT NOT NULL,
        funding_type TEXT,
        deadline_after TEXT,
        min_grade TEXT,
        institution_cap INTEGER NOT NULL DEFAULT 50,
        content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS discovery_run (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filter_id INTEGER NOT NULL REFERENCES filter(id),
        filter_content_hash TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        institutions_considered INTEGER NOT NULL DEFAULT 0,
        institutions_with_candidates INTEGER NOT NULL DEFAULT 0,
        searches_used INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK (status IN ({_sql_list(DiscoveryRunStatus)}))
    );

    CREATE TABLE IF NOT EXISTS candidate (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discovery_run_id INTEGER REFERENCES discovery_run(id),
        institution_id INTEGER NOT NULL REFERENCES institution(id),
        url TEXT NOT NULL,
        query_used TEXT NOT NULL,
        found_at TEXT NOT NULL,
        promoted_to_award_id INTEGER REFERENCES award(id)
    );
    """)
    conn.commit()
