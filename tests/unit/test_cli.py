import json

import pytest
from typer.testing import CliRunner

from opportunity_tracker import config, db
from opportunity_tracker.cli import app
from opportunity_tracker.digger import run as digger_run
from opportunity_tracker.evaluator import run as evaluator_run
from opportunity_tracker.extractor import run as extractor_run
from opportunity_tracker.fetcher import pipeline as fetcher_pipeline
from opportunity_tracker.models import (
    Bucket,
    Document,
    Evaluation,
    FetchMethod,
    Profile,
    RequirementKind,
    SourceTier,
)

runner = CliRunner()

ALL_COMMANDS = [
    "init-db",
    "sync-profile",
    "sync-filter",
    "load-directory",
    "discover",
    "fetch-pending",
    "extract-pending",
    "evaluate-all",
    "report",
    "dig",
    "review-unclassified",
    "run",
]


def test_init_db_creates_database_file_with_all_tables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0

    db_file = tmp_path / config.DB_PATH
    assert db_file.exists()

    conn = db.get_connection(str(db_file))
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "scheme", "award", "document", "requirement", "profile", "evaluation",
        "unclassified_rule", "institution", "filter", "discovery_run", "candidate",
    }
    assert expected <= tables
    conn.close()


def test_report_with_no_evaluations_prints_message_not_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_result = runner.invoke(app, ["init-db"])
    assert init_result.exit_code == 0

    report_result = runner.invoke(app, ["report"])
    assert report_result.exit_code == 0
    assert "No evaluations yet" in report_result.stdout


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_command_help_exits_zero(command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout


def _seed_db(tmp_path):
    """Open a real sqlite file at the (cwd-relative) config.DB_PATH, init the schema, and
    return the connection for the caller to seed rows into. Caller must commit and close
    before invoking a CLI command against the same path."""
    db_path = tmp_path / config.DB_PATH
    conn = db.get_connection(str(db_path))
    db.init_db(conn)
    return conn


# --- Fix 1 (Critical): extract-pending must not select, or crash on, a document whose
# fetch failed (text_path=NULL, fetch_status='error:...'). ---------------------------------

def test_extract_pending_excludes_failed_fetch_document_and_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url) VALUES (NULL, 'UWA', 'AU', '[]', NULL, 'https://uwa.edu.au/award')"
    )
    conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, text_path, "
        "retrieved_at, fetch_status, degraded) VALUES ('https://uwa.edu.au/award', 1, "
        "'http', '', NULL, '2026-08-22T00:00:00+00:00', "
        "'error:fetch_failed:ConnectError', 0)"
    )
    conn.commit()
    conn.close()

    called = {"hit": False}

    def fake_extract(document, award_id, conn_arg, api_key):
        called["hit"] = True
        return [], False

    monkeypatch.setattr(extractor_run, "extract_requirements", fake_extract)

    result = runner.invoke(app, ["extract-pending"])
    assert result.exit_code == 0, result.stdout
    assert called["hit"] is False
    assert "skipped" in result.stdout
    assert "fetch failed" in result.stdout


# --- Fix 2 (Important): report must dedup to the latest evaluation per award. --------------

def test_report_dedups_to_latest_evaluation_per_award(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url) VALUES (NULL, 'UWA', 'AU', '[]', NULL, 'https://uwa.edu.au/award')"
    )
    conn.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES "
        "(1, '2026-08-22T00:00:00+00:00', '{}')"
    )
    sort_keys = json.dumps(
        {"unknown_count": 0, "days_until_deadline": 10, "funding_completeness": 1.0}
    )
    conn.execute(
        "INSERT INTO evaluation (award_id, profile_version, evaluated_at, bucket, "
        "sort_keys, per_requirement_outcomes) VALUES "
        "(1, 1, '2026-08-22T00:00:00+00:00', 'LIKELY_BLOCKED', ?, '{}')",
        (sort_keys,),
    )
    conn.execute(
        "INSERT INTO evaluation (award_id, profile_version, evaluated_at, bucket, "
        "sort_keys, per_requirement_outcomes) VALUES "
        "(1, 1, '2026-08-22T01:00:00+00:00', 'ACT_NOW', ?, '{}')",
        (sort_keys,),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["report", "--format", "csv"])
    assert result.exit_code == 0, result.stdout

    data_lines = [line for line in result.stdout.strip().splitlines() if line]
    # header + exactly one data row, from the higher-id (ACT_NOW) evaluation.
    assert len(data_lines) == 2
    assert "ACT_NOW" in data_lines[1]
    assert "LIKELY_BLOCKED" not in result.stdout


# --- Fix 3 (Important): fetch-pending must not crash on a duplicate canonical_url. ---------

def test_fetch_pending_duplicate_canonical_url_relinks_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES ('UWA', 'Australia', 'AU', 'uwa.edu.au', "
        "'manual', NULL, '2026-08-22T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO candidate (discovery_run_id, institution_id, url, query_used, "
        "found_at, promoted_to_award_id) VALUES "
        "(NULL, 1, 'https://uwa.edu.au/award', 'q', '2026-08-22T00:00:00+00:00', NULL)"
    )
    conn.execute(
        "INSERT INTO candidate (discovery_run_id, institution_id, url, query_used, "
        "found_at, promoted_to_award_id) VALUES "
        "(NULL, 1, 'https://uwa.edu.au/award', 'q', '2026-08-22T00:00:00+00:00', NULL)"
    )
    conn.commit()
    conn.close()

    def fake_fetch(url, conn_arg, declared_tier=None):
        cursor = conn_arg.execute(
            "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
            "text_path, retrieved_at, fetch_status, degraded) VALUES "
            "(?, 1, 'http', 'hash', 'docs/x.txt', '2026-08-22T00:00:00+00:00', 'ok', 0)",
            (url,),
        )
        conn_arg.commit()
        return Document(
            id=cursor.lastrowid,
            url=url,
            source_tier=SourceTier.TIER_1,
            fetch_method=FetchMethod.HTTP,
            content_hash="hash",
            text_path="docs/x.txt",
            retrieved_at="2026-08-22T00:00:00+00:00",
            fetch_status="ok",
            degraded=False,
        )

    monkeypatch.setattr(fetcher_pipeline, "fetch", fake_fetch)

    result = runner.invoke(app, ["fetch-pending"])
    assert result.exit_code == 0, result.stdout

    conn2 = db.get_connection(str(tmp_path / config.DB_PATH))
    awards = conn2.execute("SELECT id FROM award").fetchall()
    assert len(awards) == 1

    candidates = conn2.execute(
        "SELECT promoted_to_award_id FROM candidate ORDER BY id"
    ).fetchall()
    assert len(candidates) == 2
    assert candidates[0]["promoted_to_award_id"] == awards[0]["id"]
    assert candidates[1]["promoted_to_award_id"] == awards[0]["id"]
    conn2.close()


# --- Fix 4 (Important): targeted argument-passing tests for the three thinnest commands. ---

def test_evaluate_all_passes_profile_instance_and_gold_set_dict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO profile (version, created_at, attributes) VALUES "
        "(1, '2026-08-22T00:00:00+00:00', '{}')"
    )
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url) VALUES (NULL, 'UWA', 'AU', '[]', NULL, 'https://uwa.edu.au/award')"
    )
    conn.commit()
    conn.close()

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "gold_set_recall.json").write_text(
        json.dumps({"deadline": 0.9}), encoding="utf-8"
    )

    captured = {}

    def fake_evaluate(award_id, profile_arg, conn_arg, gold_set_recall_arg):
        captured["award_id"] = award_id
        captured["profile"] = profile_arg
        captured["gold_set_recall"] = gold_set_recall_arg
        return Evaluation(
            id=1,
            award_id=award_id,
            profile_version=profile_arg.version,
            evaluated_at="2026-08-22T00:00:00+00:00",
            bucket=Bucket.ACT_NOW,
            sort_keys={},
            per_requirement_outcomes={},
        )

    monkeypatch.setattr(evaluator_run, "evaluate_award", fake_evaluate)

    result = runner.invoke(app, ["evaluate-all"])
    assert result.exit_code == 0, result.stdout
    assert isinstance(captured["profile"], Profile)
    assert not isinstance(captured["profile"], int)
    assert isinstance(captured["gold_set_recall"], dict)
    assert captured["gold_set_recall"] == {"deadline": 0.9}


def test_extract_pending_passes_document_instance_and_unpacks_tuple(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url) VALUES (NULL, 'UWA', 'AU', '[]', NULL, 'https://uwa.edu.au/award')"
    )
    conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, text_path, "
        "retrieved_at, fetch_status, degraded) VALUES ('https://uwa.edu.au/award', 1, "
        "'http', 'hash', 'docs/x.txt', '2026-08-22T00:00:00+00:00', 'ok', 0)"
    )
    conn.commit()
    conn.close()

    captured = {}

    def fake_extract(document, award_id, conn_arg, api_key):
        captured["document"] = document
        captured["award_id"] = award_id
        return [], True  # simulate an extraction failure to exercise tuple unpacking

    monkeypatch.setattr(extractor_run, "extract_requirements", fake_extract)

    result = runner.invoke(app, ["extract-pending"])
    assert result.exit_code == 0, result.stdout
    assert isinstance(captured["document"], Document)
    assert not isinstance(captured["document"], int)
    assert "FAILED" in result.stdout


# --- Whole-branch review I9: the seed tier-override must reach the fetcher ----------------

def test_fetch_pending_passes_candidate_declared_tier_to_the_fetcher(tmp_path, monkeypatch):
    """Spec §5's mandatory regression case: cybersure-master.eu matches no academic suffix
    and is in no institution directory, so it resolves Tier 1 only via the seed override --
    which was unreachable at runtime because no caller ever passed declared_tier."""
    monkeypatch.chdir(tmp_path)
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES ('CyberSure', 'Unknown', 'XX', "
        "'cybersure-master.eu', 'manual', NULL, '2026-08-22T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO candidate (discovery_run_id, institution_id, url, query_used, "
        "found_at, promoted_to_award_id, declared_tier) VALUES "
        "(NULL, 1, 'https://www.cybersure-master.eu/admission', 'manual_pin', "
        "'2026-08-22T00:00:00+00:00', NULL, 1)"
    )
    conn.execute(
        "INSERT INTO candidate (discovery_run_id, institution_id, url, query_used, "
        "found_at, promoted_to_award_id, declared_tier) VALUES "
        "(NULL, 1, 'https://www.cybersure-master.eu/other', 'manual_pin', "
        "'2026-08-22T00:00:00+00:00', NULL, NULL)"
    )
    conn.commit()
    conn.close()

    captured = {}

    def fake_fetch(url, conn_arg, declared_tier=None):
        captured[url] = declared_tier
        cursor = conn_arg.execute(
            "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
            "text_path, retrieved_at, fetch_status, degraded) VALUES "
            "(?, ?, 'http', 'hash', 'docs/x.txt', '2026-08-22T00:00:00+00:00', 'ok', 0)",
            (url, declared_tier or 3),
        )
        conn_arg.commit()
        return Document(
            id=cursor.lastrowid,
            url=url,
            source_tier=SourceTier(declared_tier or 3),
            fetch_method=FetchMethod.HTTP,
            content_hash="hash",
            text_path="docs/x.txt",
            retrieved_at="2026-08-22T00:00:00+00:00",
            fetch_status="ok",
            degraded=False,
        )

    monkeypatch.setattr(fetcher_pipeline, "fetch", fake_fetch)

    result = runner.invoke(app, ["fetch-pending"])
    assert result.exit_code == 0, result.stdout
    assert captured["https://www.cybersure-master.eu/admission"] == 1
    assert captured["https://www.cybersure-master.eu/other"] is None


def test_dig_passes_requirement_kind_enum_and_correct_registrable_domain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url) VALUES (NULL, 'UWA', 'AU', '[]', NULL, 'https://uwa.edu.au/award')"
    )
    conn.commit()
    conn.close()

    captured = {}

    def fake_dig(award_id, missing_kind, registrable_domain, conn_arg, api_key):
        captured["award_id"] = award_id
        captured["missing_kind"] = missing_kind
        captured["registrable_domain"] = registrable_domain
        return None

    monkeypatch.setattr(digger_run, "dig", fake_dig)

    result = runner.invoke(app, ["dig", "--award-id", "1", "--kind", "deadline"])
    assert result.exit_code == 0, result.stdout
    assert isinstance(captured["missing_kind"], RequirementKind)
    assert captured["missing_kind"] is RequirementKind.DEADLINE
    assert captured["registrable_domain"] == "uwa.edu.au"


def test_dig_derives_an_etld_plus_one_not_a_bare_netloc(tmp_path, monkeypatch):
    """urlparse().netloc keeps `www.` and every subdomain, so an award hosted at
    scholarships.uwa.edu.au scoped the crawl to that host and could never reach
    uwa.edu.au's course-rules pages -- the exact UWA case that motivated the tool."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    conn = _seed_db(tmp_path)
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, intake_year, "
        "canonical_url) VALUES (NULL, 'UWA', 'AU', '[]', NULL, "
        "'https://scholarships.uwa.edu.au/international-rtp')"
    )
    conn.commit()
    conn.close()

    captured = {}

    def fake_dig(award_id, missing_kind, registrable_domain, conn_arg, api_key):
        captured["registrable_domain"] = registrable_domain
        return None

    monkeypatch.setattr(digger_run, "dig", fake_dig)

    result = runner.invoke(app, ["dig", "--award-id", "1", "--kind", "deadline"])
    assert result.exit_code == 0, result.stdout
    assert captured["registrable_domain"] == "uwa.edu.au"
