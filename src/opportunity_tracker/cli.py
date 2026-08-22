"""Typer CLI wiring every pipeline stage. Spec §6 (full pipeline: filter -> discovery ->
fetcher -> extractor -> evaluator -> reporter, plus digger)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import typer

from opportunity_tracker import config, db, directory, filters, profile, urls
from opportunity_tracker.digger import run as digger_run
from opportunity_tracker.discovery import run as discovery_run
from opportunity_tracker.evaluator import run as evaluator_run
from opportunity_tracker.extractor import run as extractor_run
from opportunity_tracker.fetcher import pipeline as fetcher_pipeline
from opportunity_tracker.models import (
    Award,
    Bucket,
    Document,
    DiscoveryRun,
    DiscoveryRunStatus,
    Evaluation,
    FetchMethod,
    Profile,
    RequirementKind,
    SourceTier,
)
from opportunity_tracker.reporter import csv_report, markdown

app = typer.Typer(help="Opportunity Tracker: discover, verify and rank scholarship opportunities.")

# Per-kind gold-set recall, written by `scripts/eval_gold_set.py` (Task 27). Empty until
# that script has been run at least once -- per spec principle 6 ("trust is measured, not
# chosen"), an unmeasured kind is untrusted by default, so every FAIL downgrades to
# UNKNOWN-GATED until real recall numbers exist. Deliberately a plain module constant, not
# added to config.py (Task 3), so this file doesn't require re-touching that already-locked
# contract for a value only this module reads.
_GOLD_SET_RECALL_PATH = "data/gold_set_recall.json"


def _open_db() -> sqlite3.Connection:
    conn = db.get_connection(config.DB_PATH)
    db.init_db(conn)
    return conn


def _latest_profile(conn: sqlite3.Connection) -> Profile | None:
    row = conn.execute(
        "SELECT id, version, created_at, attributes FROM profile ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return Profile(
        id=row["id"],
        version=row["version"],
        created_at=row["created_at"],
        attributes=json.loads(row["attributes"]),
    )


def _load_gold_set_recall() -> dict[str, float]:
    path = Path(_GOLD_SET_RECALL_PATH)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@app.command("init-db")
def init_db_command() -> None:
    """Create (or verify) the SQLite database and all tables."""
    conn = _open_db()
    conn.close()
    typer.echo(f"Database ready at {config.DB_PATH}")


@app.command("sync-profile")
def sync_profile_command() -> None:
    """Sync profile.yaml into the `profile` table."""
    conn = _open_db()
    synced = profile.sync_profile(config.PROFILE_PATH, conn)
    typer.echo(f"Profile synced: version {synced.version}")
    conn.close()


@app.command("sync-filter")
def sync_filter_command() -> None:
    """Sync filter.yaml into the `filter` table."""
    conn = _open_db()
    synced = filters.sync_filter(config.FILTER_PATH, conn)
    typer.echo(f"Filter synced: '{synced.name}' (id={synced.id}, hash={synced.content_hash[:12]})")
    conn.close()


@app.command("load-directory")
def load_directory_command(
    version: str = typer.Option(
        ..., "--version", help="Directory version label, e.g. the Hipo release date."
    ),
) -> None:
    """Load the vendored institution directory into the `institution` table."""
    conn = _open_db()
    inserted = directory.load_institution_directory(config.UNIVERSITY_DIRECTORY_PATH, conn, version)
    typer.echo(f"Institution directory loaded: {inserted} new institution(s) (version {version}).")
    conn.close()


@app.command("discover")
def discover_command(
    rediscover: bool = typer.Option(
        False, "--rediscover", help="Force a fresh discovery pass, ignoring the cache."
    ),
) -> None:
    """Run filter-driven discovery: filter.yaml -> candidate rows."""
    api_key = config.get_anthropic_api_key()
    conn = _open_db()
    filter_row = filters.sync_filter(config.FILTER_PATH, conn)
    run_row = discovery_run.run_discovery(filter_row, conn, api_key, force_rediscover=rediscover)
    typer.echo(
        f"Discovery run {run_row.id}: {run_row.institutions_considered} institution(s) "
        f"considered, {run_row.institutions_with_candidates} with candidates."
    )
    if Path(config.SEEDS_PATH).exists():
        pinned = discovery_run.ingest_manual_pins(config.SEEDS_PATH, conn)
        typer.echo(f"Manual pins ingested: {len(pinned)}")
    conn.close()


@app.command("fetch-pending")
def fetch_pending_command() -> None:
    """Fetch every candidate without a promoted award, promoting each to an award+document pair.

    `award.canonical_url` is UNIQUE, and candidates are NOT deduplicated against existing
    awards before this runs (manual pins are never deduplicated against discovery results,
    per discovery/run.py, and a fresh discovery pass can re-surface an un-promoted candidate
    for a URL that was already promoted in a prior run). So the insert below uses
    `ON CONFLICT ... DO NOTHING` and then looks the award up by canonical_url, whether it was
    just inserted or already existed -- a duplicate candidate re-links to the existing award
    instead of raising `sqlite3.IntegrityError` and aborting the loop mid-batch.

    `candidate.declared_tier` (set from seeds.yaml for manual pins) is passed through to
    the fetcher, which is what makes the spec §5 seed tier-override path actually reachable
    at runtime -- `cybersure-master.eu` matches no academic suffix and is in no institution
    directory, so without the override it would be Tier 3 and, per principle 2, unable to
    write a single field.
    """
    conn = _open_db()
    pending = conn.execute(
        "SELECT candidate.id AS candidate_id, candidate.url AS url, "
        "candidate.declared_tier AS declared_tier, "
        "institution.name AS institution, institution.country AS country "
        "FROM candidate JOIN institution ON candidate.institution_id = institution.id "
        "WHERE candidate.promoted_to_award_id IS NULL"
    ).fetchall()
    promoted = 0
    for row in pending:
        document = fetcher_pipeline.fetch(
            row["url"], conn, declared_tier=row["declared_tier"]
        )
        conn.execute(
            "INSERT INTO award (scheme_id, institution, country, degree_levels, "
            "intake_year, canonical_url) VALUES (NULL, ?, ?, '[]', NULL, ?) "
            "ON CONFLICT(canonical_url) DO NOTHING",
            (row["institution"], row["country"], row["url"]),
        )
        award_row = conn.execute(
            "SELECT id FROM award WHERE canonical_url = ?", (row["url"],)
        ).fetchone()
        award_id = award_row["id"]
        conn.execute(
            "UPDATE candidate SET promoted_to_award_id = ? WHERE id = ?",
            (award_id, row["candidate_id"]),
        )
        conn.commit()
        promoted += 1
        typer.echo(f"Fetched candidate {row['candidate_id']} -> award {award_id} (document {document.id})")
    typer.echo(f"Fetch complete: {promoted} candidate(s) promoted.")
    conn.close()


@app.command("extract-pending")
def extract_pending_command() -> None:
    """Run extraction for every award whose latest successfully-fetched document has no
    requirements yet.

    fetcher.pipeline.fetch never raises on a failed fetch -- it records the failure as a
    `document` row with `text_path=NULL` and `fetch_status='error:...'` (spec §8: never
    silently skipped, never raises). The pending-documents query below only considers
    documents with `text_path IS NOT NULL` as candidates for "latest", so a degraded/failed
    fetch is never handed to extract_requirements (which does `open(document.text_path)` and
    would crash with a TypeError on None). Awards whose *only* document(s) failed to fetch
    are reported separately below as skipped, so they stay visible instead of silently
    disappearing from the run.
    """
    api_key = config.get_anthropic_api_key()
    conn = _open_db()
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
    skipped = conn.execute(
        "SELECT award.id AS award_id FROM award "
        "WHERE EXISTS (SELECT 1 FROM document WHERE document.url = award.canonical_url) "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM document WHERE document.url = award.canonical_url "
        "  AND document.text_path IS NOT NULL"
        ") "
        "AND NOT EXISTS (SELECT 1 FROM requirement WHERE requirement.award_id = award.id)"
    ).fetchall()
    for row in skipped:
        typer.echo(
            f"Award {row['award_id']}: extraction skipped, fetch failed "
            "(no successfully fetched document)."
        )
    for row in pending:
        doc_row = conn.execute(
            "SELECT id, url, source_tier, fetch_method, content_hash, text_path, "
            "retrieved_at, fetch_status, degraded FROM document WHERE id = ?",
            (row["document_id"],),
        ).fetchone()
        document = Document(
            id=doc_row["id"],
            url=doc_row["url"],
            source_tier=SourceTier(doc_row["source_tier"]),
            fetch_method=FetchMethod(doc_row["fetch_method"]),
            content_hash=doc_row["content_hash"],
            text_path=doc_row["text_path"],
            retrieved_at=doc_row["retrieved_at"],
            fetch_status=doc_row["fetch_status"],
            degraded=bool(doc_row["degraded"]),
        )
        requirements, extraction_failed = extractor_run.extract_requirements(
            document, row["award_id"], conn, api_key
        )
        if extraction_failed:
            typer.echo(
                f"Award {row['award_id']}: extraction FAILED (document {document.id}) "
                "-- award will be UNKNOWN-GATED on empty/failed extraction."
            )
        else:
            typer.echo(f"Award {row['award_id']}: extracted {len(requirements)} requirement(s).")
    typer.echo(
        f"Extraction complete: {len(pending)} award(s) processed, "
        f"{len(skipped)} skipped (fetch failed)."
    )
    conn.close()


@app.command("evaluate-all")
def evaluate_all_command() -> None:
    """Evaluate every award against the latest synced profile."""
    conn = _open_db()
    profile_row = _latest_profile(conn)
    if profile_row is None:
        typer.echo("No profile synced yet. Run `sync-profile` first.")
        conn.close()
        raise typer.Exit(code=1)
    gold_set_recall = _load_gold_set_recall()
    award_ids = [row["id"] for row in conn.execute("SELECT id FROM award")]
    for award_id in award_ids:
        evaluation = evaluator_run.evaluate_award(award_id, profile_row, conn, gold_set_recall)
        typer.echo(f"Award {award_id}: {evaluation.bucket.value}")
    typer.echo(f"Evaluation complete: {len(award_ids)} award(s) evaluated.")
    conn.close()


@app.command("report")
def report_command(
    format: str = typer.Option("md", "--format", help="Output format: 'md' or 'csv'."),
    output: str | None = typer.Option(
        None, "--output", help="Write the report to this file instead of stdout."
    ),
) -> None:
    """Render the ranked report as markdown or CSV."""
    if format not in ("md", "csv"):
        typer.echo(f"Unknown format '{format}'. Use 'md' or 'csv'.")
        raise typer.Exit(code=1)

    conn = _open_db()
    # `evaluation` is an append-only log (spec §4.5) -- evaluate_award never updates or
    # deletes a prior row, it always inserts a new one. Re-running `evaluate-all` therefore
    # leaves every earlier evaluation in place, so this query keeps only the highest-id
    # (i.e. most recent) row per award_id; without this a re-run would make every award
    # appear once per evaluation ever recorded, possibly in different buckets.
    evaluation_rows = conn.execute(
        "SELECT id, award_id, profile_version, evaluated_at, bucket, sort_keys, "
        "per_requirement_outcomes FROM evaluation "
        "WHERE id IN (SELECT MAX(id) FROM evaluation GROUP BY award_id)"
    ).fetchall()

    if not evaluation_rows:
        typer.echo("No evaluations yet. Run `evaluate-all` first.")
        conn.close()
        return

    evaluations = [
        Evaluation(
            id=row["id"],
            award_id=row["award_id"],
            profile_version=row["profile_version"],
            evaluated_at=row["evaluated_at"],
            bucket=Bucket(row["bucket"]),
            sort_keys=json.loads(row["sort_keys"]),
            per_requirement_outcomes=json.loads(row["per_requirement_outcomes"]),
        )
        for row in evaluation_rows
    ]

    awards_by_id: dict[int, Award] = {}
    for award_row in conn.execute(
        "SELECT id, scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url FROM award"
    ):
        awards_by_id[award_row["id"]] = Award(
            id=award_row["id"],
            scheme_id=award_row["scheme_id"],
            institution=award_row["institution"],
            country=award_row["country"],
            degree_levels=json.loads(award_row["degree_levels"]),
            intake_year=award_row["intake_year"],
            canonical_url=award_row["canonical_url"],
        )

    if format == "md":
        discovery_runs = [
            DiscoveryRun(
                id=r["id"],
                filter_id=r["filter_id"],
                filter_content_hash=r["filter_content_hash"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                institutions_considered=r["institutions_considered"],
                institutions_with_candidates=r["institutions_with_candidates"],
                searches_used=r["searches_used"],
                status=DiscoveryRunStatus(r["status"]),
                institutions_available=r["institutions_available"],
            )
            for r in conn.execute(
                "SELECT id, filter_id, filter_content_hash, started_at, completed_at, "
                "institutions_considered, institutions_available, "
                "institutions_with_candidates, searches_used, status FROM discovery_run"
            )
        ]
        rendered = markdown.render_report(evaluations, awards_by_id, discovery_runs, conn)
    else:
        rendered = csv_report.render_csv(evaluations, awards_by_id, conn)

    if output:
        Path(output).write_text(rendered, encoding="utf-8")
        typer.echo(f"Report written to {output}")
    else:
        typer.echo(rendered)

    conn.close()


@app.command("dig")
def dig_command(
    award_id: int = typer.Option(..., "--award-id", help="Award id to dig for a missing field on."),
    kind: str = typer.Option(..., "--kind", help="RequirementKind value to dig for, e.g. 'deadline'."),
) -> None:
    """Run the bounded digger for one missing required field on one award."""
    api_key = config.get_anthropic_api_key()
    conn = _open_db()
    award_row = conn.execute(
        "SELECT canonical_url FROM award WHERE id = ?", (award_id,)
    ).fetchone()
    if award_row is None:
        typer.echo(f"No award with id {award_id}.")
        conn.close()
        raise typer.Exit(code=1)
    # An actual registrable domain (eTLD+1), not urlparse().netloc: the bare host keeps
    # `www.` and every subdomain, so an award at scholarships.uwa.edu.au could never let the
    # digger's crawl reach uwa.edu.au's course-rules pages -- the exact UWA case that
    # motivated the tool.
    registrable = urls.registrable_domain(award_row["canonical_url"])
    result = digger_run.dig(award_id, RequirementKind(kind), registrable, conn, api_key)
    if result is None:
        typer.echo(f"Digger found nothing for award {award_id}, kind '{kind}'.")
    else:
        typer.echo(f"Digger found requirement {result.id} for award {award_id}, kind '{kind}': {result.value}")
    conn.close()


@app.command("review-unclassified")
def review_unclassified_command() -> None:
    """List unreviewed unclassified_rule rows for manual triage."""
    conn = _open_db()
    rows = conn.execute(
        "SELECT id, document_id, raw_text, logged_at FROM unclassified_rule WHERE reviewed = 0"
    ).fetchall()
    if not rows:
        typer.echo("No unreviewed unclassified rules.")
    else:
        for row in rows:
            typer.echo(f"[{row['id']}] document {row['document_id']} ({row['logged_at']}): {row['raw_text']}")
        typer.echo(f"{len(rows)} unreviewed rule(s).")
    conn.close()


@app.command("run")
def run_command(
    rediscover: bool = typer.Option(False, "--rediscover", help="Force a fresh discovery pass."),
    format: str = typer.Option("md", "--format", help="Output format for the final report: 'md' or 'csv'."),
) -> None:
    """Run the full pipeline: discover -> fetch-pending -> extract-pending -> evaluate-all -> report."""
    # `discover` syncs filter.yaml itself, but nothing else syncs profile.yaml -- and
    # `evaluate-all` exits 1 when no profile row exists, so a fresh `optrack run` aborted at
    # stage 4 every time. Sync it up front, mirroring how discover_command syncs the filter.
    typer.echo("=== Stage 0/5: sync-profile ===")
    sync_profile_command()
    typer.echo("=== Stage 1/5: discover ===")
    discover_command(rediscover=rediscover)
    typer.echo("=== Stage 2/5: fetch-pending ===")
    fetch_pending_command()
    typer.echo("=== Stage 3/5: extract-pending ===")
    extract_pending_command()
    typer.echo("=== Stage 4/5: evaluate-all ===")
    evaluate_all_command()
    typer.echo("=== Stage 5/5: report ===")
    report_command(format=format, output=None)


if __name__ == "__main__":
    app()
