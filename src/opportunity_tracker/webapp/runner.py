"""Background pipeline orchestration for the web UI's "Run" button. Reimplements
cli.py's `run` command as a non-blocking, progress-reporting background thread --
see spec §3.2 for why this can't just call cli.py's Typer command functions."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from opportunity_tracker import config, db, directory, profile as profile_module
from opportunity_tracker.discovery import run as discovery_run
from opportunity_tracker.evaluator import run as evaluator_run
from opportunity_tracker.extractor import run as extractor_run
from opportunity_tracker.fetcher import pipeline as fetcher_pipeline
from opportunity_tracker.models import Document, FetchMethod, Filter, Profile, SourceTier

_GOLD_SET_RECALL_PATH = "data/gold_set_recall.json"
_MAX_LOG_ENTRIES = 100


class RunAlreadyActiveError(Exception):
    """Raised by start_run() when a run is already in progress."""


@dataclass
class RunState:
    active: bool = False
    filter_id: int | None = None
    filter_name: str | None = None
    phase: str = "idle"  # idle|discovering|fetching|extracting|evaluating|done|failed
    phase_current: int = 0
    phase_total: int = 0
    discovery_run_id: int | None = None
    candidates_found: int = 0
    log: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def add_log(self, message: str) -> None:
        self.log.append(message)
        if len(self.log) > _MAX_LOG_ENTRIES:
            del self.log[: len(self.log) - _MAX_LOG_ENTRIES]


RUN_STATE = RunState()
_LOCK = threading.Lock()


def start_run(filter_id: int) -> None:
    with _LOCK:
        if RUN_STATE.active:
            raise RunAlreadyActiveError("A run is already in progress.")
        RUN_STATE.__dict__.update(RunState().__dict__)
        RUN_STATE.active = True
        RUN_STATE.filter_id = filter_id
        RUN_STATE.started_at = datetime.now(timezone.utc).isoformat()
    thread = threading.Thread(target=_run_pipeline, args=(filter_id,), daemon=True)
    thread.start()


def _load_gold_set_recall() -> dict[str, float]:
    path = Path(_GOLD_SET_RECALL_PATH)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_profile(conn: sqlite3.Connection) -> Profile | None:
    row = conn.execute(
        "SELECT id, version, created_at, attributes FROM profile ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return Profile(
        id=row["id"], version=row["version"], created_at=row["created_at"],
        attributes=json.loads(row["attributes"]),
    )


def _row_to_filter(row: sqlite3.Row) -> Filter:
    return Filter(
        id=row["id"], name=row["name"], country=row["country"],
        degree_levels=json.loads(row["degree_levels"]), fields=json.loads(row["fields"]),
        funding_type=row["funding_type"], deadline_after=row["deadline_after"],
        min_grade=row["min_grade"], institution_cap=row["institution_cap"],
        content_hash=row["content_hash"], created_at=row["created_at"],
    )


def _ensure_institution_directory_loaded(conn: sqlite3.Connection) -> None:
    # A fresh DB (e.g. a first-ever `optrack serve` run) has no `institution` rows --
    # the CLI required a separate, manual `optrack load-directory --version ...`
    # step before `discover` could find anything. The web UI has no equivalent
    # command anywhere in its six screens, so without this a first-time user's
    # search silently completes with 0 institutions considered and 0 candidates
    # found, with nothing telling them why. Loading is idempotent (keyed by
    # domain, existing rows are never touched -- see directory.py's own
    # docstring), so this only does real work once per fresh database.
    count = conn.execute("SELECT COUNT(*) AS n FROM institution").fetchone()["n"]
    if count > 0:
        return
    inserted = directory.load_institution_directory(
        config.UNIVERSITY_DIRECTORY_PATH, conn, directory_version="web-ui-auto"
    )
    RUN_STATE.add_log(f"Loaded institution directory: {inserted} institution(s).")


def _run_pipeline(filter_id: int) -> None:
    conn = None
    try:
        conn = db.get_connection(config.DB_PATH)
        db.init_db(conn)
        search_api_key = config.get_tavily_api_key()
        llm_api_key = config.get_groq_api_key()

        _ensure_institution_directory_loaded(conn)

        profile_module.sync_profile(config.PROFILE_PATH, conn)

        filter_row = conn.execute(
            "SELECT * FROM filter WHERE id = ?", (filter_id,)
        ).fetchone()
        if filter_row is None:
            raise ValueError(f"No saved search with id {filter_id}.")
        filter_obj = _row_to_filter(filter_row)
        RUN_STATE.filter_name = filter_obj.name

        RUN_STATE.phase = "discovering"
        RUN_STATE.add_log(f"Starting discovery for '{filter_obj.name}'...")
        _run_discovery_with_polling(filter_obj, conn, search_api_key)

        if Path(config.SEEDS_PATH).exists():
            pinned = discovery_run.ingest_manual_pins(config.SEEDS_PATH, conn)
            RUN_STATE.add_log(f"Ingested {len(pinned)} manual pin(s).")

        _run_fetch_phase(conn)
        _run_extract_phase(conn, llm_api_key)
        _run_evaluate_phase(conn)

        RUN_STATE.phase = "done"
        RUN_STATE.finished_at = datetime.now(timezone.utc).isoformat()
    except Exception as exc:  # the run screen surfaces this verbatim -- spec §3.2
        RUN_STATE.phase = "failed"
        RUN_STATE.error = str(exc)
        RUN_STATE.finished_at = datetime.now(timezone.utc).isoformat()
    finally:
        RUN_STATE.active = False
        if conn is not None:
            conn.close()


def _run_discovery_with_polling(
    filter_obj: Filter, conn: sqlite3.Connection, search_api_key: str
) -> None:
    # `conn` was created in THIS thread (by _run_pipeline) and sqlite3 connections are
    # thread-affine by default (db.get_connection does not pass check_same_thread=False,
    # confirmed in db.py) -- so run_discovery(..., conn, ...) must stay on this thread.
    # The poller instead gets its OWN thread with its OWN fresh connection, so neither
    # connection ever crosses a thread boundary.
    stop_event = threading.Event()

    def _poll_loop() -> None:
        poll_conn = db.get_connection(config.DB_PATH)
        try:
            while not stop_event.is_set():
                _poll_discovery_progress(poll_conn, filter_obj.id)
                stop_event.wait(1.0)
        finally:
            poll_conn.close()

    poller = threading.Thread(target=_poll_loop, daemon=True)
    poller.start()
    try:
        run_row = discovery_run.run_discovery(
            filter_obj, conn, search_api_key, force_rediscover=False
        )
    finally:
        stop_event.set()
        poller.join()

    RUN_STATE.discovery_run_id = run_row.id
    RUN_STATE.candidates_found = run_row.institutions_with_candidates
    RUN_STATE.add_log(
        f"Discovery complete: {run_row.institutions_considered} institution(s) "
        f"considered, {run_row.institutions_with_candidates} with candidates."
    )


def _poll_discovery_progress(poll_conn: sqlite3.Connection, filter_id: int) -> None:
    row = poll_conn.execute(
        "SELECT id, institutions_considered, institutions_available, "
        "institutions_with_candidates FROM discovery_run WHERE filter_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (filter_id,),
    ).fetchone()
    if row is None:
        return
    RUN_STATE.discovery_run_id = row["id"]
    RUN_STATE.phase_current = row["institutions_considered"]
    RUN_STATE.phase_total = row["institutions_available"]
    RUN_STATE.candidates_found = row["institutions_with_candidates"]


def _run_fetch_phase(conn: sqlite3.Connection) -> None:
    RUN_STATE.phase = "fetching"
    pending = conn.execute(
        "SELECT candidate.id AS candidate_id, candidate.url AS url, "
        "candidate.declared_tier AS declared_tier, "
        "institution.name AS institution, institution.country AS country "
        "FROM candidate JOIN institution ON candidate.institution_id = institution.id "
        "WHERE candidate.promoted_to_award_id IS NULL"
    ).fetchall()
    RUN_STATE.phase_current = 0
    RUN_STATE.phase_total = len(pending)
    for row in pending:
        document = fetcher_pipeline.fetch(row["url"], conn, declared_tier=row["declared_tier"])
        conn.execute(
            "INSERT INTO award (scheme_id, institution, country, degree_levels, "
            "intake_year, canonical_url) VALUES (NULL, ?, ?, '[]', NULL, ?) "
            "ON CONFLICT(canonical_url) DO NOTHING",
            (row["institution"], row["country"], row["url"]),
        )
        award_row = conn.execute(
            "SELECT id FROM award WHERE canonical_url = ?", (row["url"],)
        ).fetchone()
        conn.execute(
            "UPDATE candidate SET promoted_to_award_id = ? WHERE id = ?",
            (award_row["id"], row["candidate_id"]),
        )
        conn.commit()
        RUN_STATE.phase_current += 1
        RUN_STATE.add_log(
            f"Fetched {row['institution']} (document {document.id})"
        )
    RUN_STATE.add_log(f"Fetch complete: {len(pending)} candidate(s) promoted.")


def _run_extract_phase(conn: sqlite3.Connection, llm_api_key: str) -> None:
    RUN_STATE.phase = "extracting"
    pending = conn.execute(
        "SELECT award.id AS award_id, latest.document_id AS document_id "
        "FROM award "
        "JOIN (SELECT url, MAX(id) AS document_id FROM document "
        "      WHERE text_path IS NOT NULL GROUP BY url) AS latest "
        "  ON latest.url = award.canonical_url "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM requirement WHERE requirement.document_id = latest.document_id"
        ")"
    ).fetchall()
    RUN_STATE.phase_current = 0
    RUN_STATE.phase_total = len(pending)
    for row in pending:
        doc_row = conn.execute(
            "SELECT id, url, source_tier, fetch_method, content_hash, text_path, "
            "retrieved_at, fetch_status, degraded FROM document WHERE id = ?",
            (row["document_id"],),
        ).fetchone()
        document = Document(
            id=doc_row["id"], url=doc_row["url"], source_tier=SourceTier(doc_row["source_tier"]),
            fetch_method=FetchMethod(doc_row["fetch_method"]), content_hash=doc_row["content_hash"],
            text_path=doc_row["text_path"], retrieved_at=doc_row["retrieved_at"],
            fetch_status=doc_row["fetch_status"], degraded=bool(doc_row["degraded"]),
        )
        requirements, extraction_failed = extractor_run.extract_requirements(
            document, row["award_id"], conn, llm_api_key
        )
        RUN_STATE.phase_current += 1
        if extraction_failed:
            RUN_STATE.add_log(f"Award {row['award_id']}: extraction FAILED.")
        else:
            RUN_STATE.add_log(
                f"Award {row['award_id']}: extracted {len(requirements)} requirement(s)."
            )
    RUN_STATE.add_log(f"Extraction complete: {len(pending)} award(s) processed.")


def _run_evaluate_phase(conn: sqlite3.Connection) -> None:
    RUN_STATE.phase = "evaluating"
    profile_row = _latest_profile(conn)
    if profile_row is None:
        raise RuntimeError("No profile synced yet.")
    gold_set_recall = _load_gold_set_recall()
    award_ids = [row["id"] for row in conn.execute("SELECT id FROM award")]
    RUN_STATE.phase_current = 0
    RUN_STATE.phase_total = len(award_ids)
    for award_id in award_ids:
        evaluation = evaluator_run.evaluate_award(award_id, profile_row, conn, gold_set_recall)
        RUN_STATE.phase_current += 1
        RUN_STATE.add_log(f"Award {award_id}: {evaluation.bucket.value}")
    RUN_STATE.add_log(f"Evaluation complete: {len(award_ids)} award(s) evaluated.")
