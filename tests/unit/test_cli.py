import pytest
from typer.testing import CliRunner

from opportunity_tracker import config, db
from opportunity_tracker.cli import app

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
