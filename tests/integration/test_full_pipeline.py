"""End-to-end pipeline test against a real temp SQLite database.

Every cross-stage bug the whole-branch review found lived in a HANDOFF between stages --
`run` never syncing the profile so evaluate-all exited 1, manual pins re-ingested every run,
robots.txt aborting the run on one dead host, a non-2xx error page reaching the extractor as
if it were content. Unit tests could not see any of them, because each one mocked the very
boundary where the bug lived. This test mocks ONLY the true external boundaries:

  * websearch.search_institution   (the Tavily search API)
  * httpx.get                      (the network -- the real HTML extraction still runs)
  * urllib.request.urlopen         (robots.txt over the network)
  * time.sleep                     (the per-host rate limiter's wall clock)
  * groq.Groq                      (the extractor's model call)

Everything else -- the CLI commands, the schema, tiering, the fetch pipeline, evidence
validation, the Tier 1 write gate, evaluation, bucketing and both reporters -- is the real
code, run in order, against a real database file.
"""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opportunity_tracker import config, db
from opportunity_tracker.cli import app

runner = CliRunner()

# A Canadian institution on purpose: utoronto.ca matches no academic suffix, so it is Tier 3
# under pure suffix classification and can only reach Tier 1 through the institution
# directory. That makes this test cover the tiering fix and the Tier 1 write gate together --
# if either regresses, no requirement row is ever written and the report comes back empty.
_INSTITUTION_DOMAIN = "utoronto.ca"
_AWARD_URL = "https://www.utoronto.ca/scholarships/phd-award"
_DEADLINE_SENTENCE = "Applications close on 15 March 2027."

_AWARD_PAGE_HTML = f"""<!DOCTYPE html>
<html>
  <head>
    <title>Doctoral Excellence Scholarship</title>
    <style>.banner {{ color: #002a5c; }}</style>
    <script>window.__ANALYTICS__ = {{"id": "UA-0000"}};</script>
  </head>
  <body>
    <nav><a href="/study">Study</a></nav>
    <h1>Doctoral Excellence Scholarship</h1>
    <p>{_DEADLINE_SENTENCE}</p>
    <p>The award covers a full stipend and tuition for the duration of candidature, and is
       open to students commencing a doctoral programme in computer science.</p>
  </body>
</html>"""

_PROFILE_YAML = """\
research_project_fraction_held: null
english_test_result: null
target_intake_year: 2027
has_transcripts: false
supervisor_confirmed: false
thesis_required: null
degree_level: phd
nationality: Algerian
prior_scholarship_exclusion: null
return_obligation: null
funding_component: null
"""

_FILTER_YAML = """\
name: canada-cs-phd
country: Canada
degree_levels: [phd]
fields: [computer science]
funding_type: null
deadline_after: null
min_grade: null
institution_cap: 50
"""


class _FakeHttpResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class _FakeFunctionCall:
    """Shaped like the Groq SDK's tool_call.function: .name, .arguments (a JSON string)."""

    def __init__(self, name, arguments: dict):
        self.name = name
        self.arguments = json.dumps(arguments)


class _FakeToolCall:
    def __init__(self, name, arguments: dict):
        self.function = _FakeFunctionCall(name, arguments)


class _FakeMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, choices):
        self.choices = choices


class _FakeRobotsResponse:
    def read(self):
        return b"User-agent: *\nAllow: /\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A real, empty project directory: config files, a one-entry institution directory,
    and the deny-list the fetcher reads. cwd is tmp_path, so every relative path in
    config.py resolves inside it and nothing touches the developer's real database."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-not-a-real-key")

    (tmp_path / "profile.yaml").write_text(_PROFILE_YAML, encoding="utf-8")
    (tmp_path / "filter.yaml").write_text(_FILTER_YAML, encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "university_directory.json").write_text(
        json.dumps(
            [
                {
                    "name": "University of Toronto",
                    "country": "Canada",
                    "alpha_two_code": "CA",
                    "domains": [_INSTITUTION_DOMAIN],
                }
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "tier3_deny_list.yaml").write_text("[]\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def external_boundaries(mocker):
    """Stub the network, the search API, the model, and the rate limiter's clock.
    Nothing inside the pipeline itself is mocked."""
    mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        return_value=[{"url": _AWARD_URL, "title": "Doctoral Excellence Scholarship"}],
    )
    http_get = mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeHttpResponse(_AWARD_PAGE_HTML, 200),
    )
    mocker.patch(
        "opportunity_tracker.fetcher.robots.urllib.request.urlopen",
        return_value=_FakeRobotsResponse(),
    )
    mocker.patch("opportunity_tracker.fetcher.robots.time.sleep")

    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _FakeResponse(
        choices=[
            _FakeChoice(
                _FakeMessage(
                    tool_calls=[
                        _FakeToolCall(
                            "record_requirements",
                            {
                                "requirements": [
                                    {
                                        "kind": "deadline",
                                        "operator": None,
                                        "value": "2027-03-15",
                                        "unit": None,
                                        "raw_text": _DEADLINE_SENTENCE,
                                        "evidence": _DEADLINE_SENTENCE,
                                        "confidence": 0.95,
                                    }
                                ]
                            },
                        )
                    ]
                )
            )
        ]
    )
    mocker.patch("opportunity_tracker.llm_extract.Groq", return_value=fake_client)
    return {"http_get": http_get, "groq_client": fake_client}


def _open_db(project_dir):
    return db.get_connection(str(project_dir / config.DB_PATH))


def _invoke(*args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"{args} failed:\n{result.stdout}\n{result.exception}"
    return result


def test_full_pipeline_produces_a_non_empty_report(project, external_boundaries):
    _invoke("init-db")
    _invoke("load-directory", "--version", "2026.1")

    result = _invoke("run")
    report = result.stdout

    # --- the report actually rendered, with the award in it ---
    assert "# Opportunity Tracker Report" in report
    assert "University of Toronto" in report
    assert _AWARD_URL in report

    # Only the deadline was extracted, so the other required kinds are UNKNOWN and the
    # award is gated rather than asserted either way -- the expected bucket for a first
    # run with no measured gold-set recall.
    unknown_section = report.split("## Unknown-Gated", 1)[1].split("## ", 1)[0]
    assert _AWARD_URL in unknown_section

    # --- and the database backing it holds the right rows ---
    conn = _open_db(project)

    document = conn.execute(
        "SELECT source_tier, fetch_status, text_path FROM document WHERE url = ?",
        (_AWARD_URL,),
    ).fetchone()
    assert document["fetch_status"] == "ok"
    # utoronto.ca matches no academic suffix: Tier 1 here proves the institution-directory
    # lookup ran, and without it the Tier 1 write gate would have blocked every insert.
    assert document["source_tier"] == 1

    stored_text = Path(document["text_path"]).read_text(encoding="utf-8")
    assert "<p>" not in stored_text  # extracted visible text, not raw markup
    assert "window.__ANALYTICS__" not in stored_text
    assert _DEADLINE_SENTENCE in stored_text

    requirements = conn.execute("SELECT kind, value FROM requirement").fetchall()
    assert [(r["kind"], r["value"]) for r in requirements] == [("deadline", "2027-03-15")]

    evaluations = conn.execute("SELECT bucket FROM evaluation").fetchall()
    assert len(evaluations) == 1
    assert evaluations[0]["bucket"] == "UNKNOWN_GATED"

    # A profile version exists at all only because `run` syncs it -- evaluate-all exits 1
    # otherwise, which is exactly how this pipeline used to fail at stage 4.
    assert conn.execute("SELECT COUNT(*) AS n FROM profile").fetchone()["n"] == 1

    coverage = conn.execute(
        "SELECT institutions_considered, institutions_available, searches_used "
        "FROM discovery_run"
    ).fetchone()
    assert coverage["institutions_considered"] == 1
    assert coverage["institutions_available"] == 1
    assert coverage["searches_used"] >= 1
    conn.close()


def test_full_pipeline_is_idempotent_across_repeated_runs(project, external_boundaries):
    """A second `optrack run` over unchanged inputs must not re-fetch, re-extract, or
    duplicate rows -- discovery caching plus manual-pin dedup plus the promoted-candidate
    check are all handoffs no unit test can exercise together."""
    (project / "seeds.yaml").write_text(
        "- institution_domain: utoronto.ca\n"
        "  url: https://www.utoronto.ca/scholarships/pinned-award\n"
        "  declared_tier: 1\n",
        encoding="utf-8",
    )

    _invoke("init-db")
    _invoke("load-directory", "--version", "2026.1")
    _invoke("run")

    conn = _open_db(project)
    after_first = {
        "candidates": conn.execute("SELECT COUNT(*) AS n FROM candidate").fetchone()["n"],
        "documents": conn.execute("SELECT COUNT(*) AS n FROM document").fetchone()["n"],
        "requirements": conn.execute("SELECT COUNT(*) AS n FROM requirement").fetchone()["n"],
        "awards": conn.execute("SELECT COUNT(*) AS n FROM award").fetchone()["n"],
    }
    conn.close()
    assert after_first["candidates"] == 2  # one discovered, one pinned
    fetches_after_first = external_boundaries["http_get"].call_count

    _invoke("run")

    conn = _open_db(project)
    after_second = {
        "candidates": conn.execute("SELECT COUNT(*) AS n FROM candidate").fetchone()["n"],
        "documents": conn.execute("SELECT COUNT(*) AS n FROM document").fetchone()["n"],
        "requirements": conn.execute("SELECT COUNT(*) AS n FROM requirement").fetchone()["n"],
        "awards": conn.execute("SELECT COUNT(*) AS n FROM award").fetchone()["n"],
    }
    # The pinned candidate carried declared_tier=1 all the way to the document row.
    pinned = conn.execute(
        "SELECT source_tier FROM document WHERE url = ?",
        ("https://www.utoronto.ca/scholarships/pinned-award",),
    ).fetchone()
    assert pinned["source_tier"] == 1
    conn.close()

    assert after_second == after_first
    assert external_boundaries["http_get"].call_count == fetches_after_first


def test_pipeline_survives_a_dead_host_and_an_http_error_page(project, mocker):
    """One dead domain among many used to abort the whole run: robots.txt raised URLError
    straight out of is_allowed. And a 404 page, being >200 characters with no loading
    marker, was stored as fetch_status='ok' and handed to the extractor as content."""
    import urllib.error

    mocker.patch(
        "opportunity_tracker.discovery.websearch.search_institution",
        return_value=[{"url": _AWARD_URL, "title": "Doctoral Excellence Scholarship"}],
    )
    mocker.patch(
        "opportunity_tracker.fetcher.robots.urllib.request.urlopen",
        side_effect=urllib.error.URLError("getaddrinfo failed"),
    )
    mocker.patch("opportunity_tracker.fetcher.robots.time.sleep")
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeHttpResponse("Page not found. Try our site search. " * 20, 404),
    )
    fake_client = mocker.MagicMock()
    mocker.patch("opportunity_tracker.llm_extract.Groq", return_value=fake_client)

    _invoke("init-db")
    _invoke("load-directory", "--version", "2026.1")
    result = _invoke("run")  # must not raise, must not exit non-zero

    conn = _open_db(project)
    document = conn.execute(
        "SELECT fetch_status, text_path FROM document WHERE url = ?", (_AWARD_URL,)
    ).fetchone()
    assert document["fetch_status"] == "error:http_status:404"
    assert document["text_path"] is None
    # The error page never reached the extractor, so nothing was written as if it were real.
    assert conn.execute("SELECT COUNT(*) AS n FROM requirement").fetchone()["n"] == 0
    fake_client.chat.completions.create.assert_not_called()
    conn.close()

    assert "extraction skipped, fetch failed" in result.stdout


def test_report_renders_as_csv_too(project, external_boundaries):
    _invoke("init-db")
    _invoke("load-directory", "--version", "2026.1")
    _invoke("run")

    result = _invoke("report", "--format", "csv")

    lines = [line for line in result.stdout.strip().splitlines() if line]
    assert lines[0].startswith("institution,award_url,bucket")
    assert any(_AWARD_URL in line for line in lines[1:])
