"""Tests for the fetch pipeline orchestration. robots, http_fetch, headless_fetch,
pdf_fetch, tiering, and httpx are all mocked -- this suite never fetches over a real
network, launches a browser, or parses a real PDF. pipeline.DOCUMENTS_DIR is patched
to a tmp_path per test so no test writes into the real project's documents/ dir."""
from pathlib import Path

import pytest

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.fetcher import pipeline
from opportunity_tracker.fetcher.http_fetch import FetchResult
from opportunity_tracker.models import FetchMethod, SourceTier


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_fetch_plain_http_success(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mock_wait = mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        return_value=FetchResult(
            text="Real scholarship page content, well over the threshold. " * 5,
            status_code=200,
            is_degraded=False,
        ),
    )
    mock_headless = mocker.patch("opportunity_tracker.fetcher.pipeline.headless_fetch.fetch_headless")

    document = pipeline.fetch("https://uwa.edu.au/scholarships/rtp", conn)

    assert document.fetch_status == "ok"
    assert document.fetch_method == FetchMethod.HTTP
    assert document.source_tier == SourceTier.TIER_1
    assert document.degraded is False
    assert document.content_hash != ""
    assert document.text_path is not None
    assert Path(document.text_path).read_text(encoding="utf-8").startswith("Real scholarship")
    mock_headless.assert_not_called()
    mock_wait.assert_called_once_with("uwa.edu.au")

    row = conn.execute("SELECT * FROM document WHERE id = ?", (document.id,)).fetchone()
    assert row["fetch_status"] == "ok"
    assert row["content_hash"] == document.content_hash


def test_fetch_degraded_http_falls_back_to_headless(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        return_value=FetchResult(text="Loading component...", status_code=200, is_degraded=True),
    )
    mock_headless = mocker.patch(
        "opportunity_tracker.fetcher.pipeline.headless_fetch.fetch_headless",
        return_value=FetchResult(
            text="Real rendered content once JS executes, well over threshold. " * 5,
            status_code=200,
            is_degraded=False,
        ),
    )

    document = pipeline.fetch("https://uwa.edu.au/hdr", conn)

    mock_headless.assert_called_once_with("https://uwa.edu.au/hdr")
    assert document.fetch_method == FetchMethod.HEADLESS
    assert document.fetch_status == "ok"
    assert document.degraded is False


def test_fetch_robots_disallowed_still_inserts_document_row(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=False)
    mock_wait = mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mock_http = mocker.patch("opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http")

    document = pipeline.fetch("https://blocked.edu.au/page", conn)

    assert document.fetch_status == "error:robots_disallowed"
    assert document.fetch_method == FetchMethod.HTTP
    assert document.content_hash == ""
    assert document.degraded is False
    assert document.text_path is None
    mock_wait.assert_not_called()
    mock_http.assert_not_called()

    row = conn.execute("SELECT * FROM document WHERE id = ?", (document.id,)).fetchone()
    assert row is not None  # never a silent skip
    assert row["fetch_status"] == "error:robots_disallowed"


def test_fetch_http_exception_still_inserts_document_row(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        side_effect=TimeoutError("connection timed out"),
    )
    mock_headless = mocker.patch("opportunity_tracker.fetcher.pipeline.headless_fetch.fetch_headless")

    document = pipeline.fetch("https://uwa.edu.au/flaky-page", conn)

    assert document.fetch_status == "error:fetch_failed:TimeoutError"
    assert document.fetch_method == FetchMethod.HTTP
    assert document.content_hash == ""
    assert document.degraded is False
    assert document.text_path is None
    mock_headless.assert_not_called()

    row = conn.execute("SELECT * FROM document WHERE id = ?", (document.id,)).fetchone()
    assert row is not None  # never a silent skip, never an uncaught crash
    assert row["fetch_status"] == "error:fetch_failed:TimeoutError"


def test_fetch_headless_exception_still_inserts_document_row(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        return_value=FetchResult(text="Loading component...", status_code=200, is_degraded=True),
    )
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.headless_fetch.fetch_headless",
        side_effect=RuntimeError("browser crashed"),
    )

    document = pipeline.fetch("https://uwa.edu.au/hdr", conn)

    assert document.fetch_status == "error:fetch_failed:RuntimeError"
    assert document.fetch_method == FetchMethod.HEADLESS
    assert document.content_hash == ""
    assert document.degraded is False
    assert document.text_path is None

    row = conn.execute("SELECT * FROM document WHERE id = ?", (document.id,)).fetchone()
    assert row is not None
    assert row["fetch_status"] == "error:fetch_failed:RuntimeError"


def test_fetch_pdf_extraction_exception_still_inserts_document_row(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")

    fake_response = mocker.Mock()
    fake_response.content = b"%PDF-1.4 fake bytes for a mocked download"
    mocker.patch("opportunity_tracker.fetcher.pipeline.httpx.get", return_value=fake_response)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.pdf_fetch.extract_pdf_text",
        side_effect=ValueError("could not parse PDF"),
    )

    document = pipeline.fetch("https://uwa.edu.au/scholarships/conditions.PDF", conn)

    assert document.fetch_status == "error:fetch_failed:ValueError"
    assert document.fetch_method == FetchMethod.PDF
    assert document.content_hash == ""
    assert document.degraded is False
    assert document.text_path is None

    row = conn.execute("SELECT * FROM document WHERE id = ?", (document.id,)).fetchone()
    assert row is not None
    assert row["fetch_status"] == "error:fetch_failed:ValueError"


# --- Whole-branch review I7: a non-2xx response is a failed fetch, not real content -------

@pytest.mark.parametrize("status_code", [301, 404, 410, 500, 503])
def test_fetch_non_2xx_http_status_is_recorded_as_a_failure(mocker, conn, tmp_path, status_code):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    # A real 404/500 page is comfortably over the 200-char degraded threshold and carries
    # no loading marker, so the degraded heuristic alone never catches it.
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        return_value=FetchResult(
            text="Page not found. Try our search, or browse the site map. " * 10,
            status_code=status_code,
            is_degraded=False,
        ),
    )
    mock_headless = mocker.patch(
        "opportunity_tracker.fetcher.pipeline.headless_fetch.fetch_headless"
    )

    document = pipeline.fetch("https://uwa.edu.au/gone", conn)

    assert document.fetch_status == f"error:http_status:{status_code}"
    assert document.text_path is None
    assert document.content_hash == ""
    mock_headless.assert_not_called()

    row = conn.execute("SELECT * FROM document WHERE id = ?", (document.id,)).fetchone()
    assert row["fetch_status"] == f"error:http_status:{status_code}"


def test_fetch_non_2xx_headless_status_is_recorded_as_a_failure(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        return_value=FetchResult(text="Loading component...", status_code=200, is_degraded=True),
    )
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.headless_fetch.fetch_headless",
        return_value=FetchResult(text="Not found. " * 40, status_code=404, is_degraded=False),
    )

    document = pipeline.fetch("https://uwa.edu.au/hdr", conn)

    assert document.fetch_status == "error:http_status:404"
    assert document.fetch_method == FetchMethod.HEADLESS
    assert document.text_path is None


def test_fetch_2xx_status_other_than_200_is_still_a_success(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        return_value=FetchResult(
            text="Real scholarship content well over the threshold. " * 5,
            status_code=203,
            is_degraded=False,
        ),
    )

    document = pipeline.fetch("https://uwa.edu.au/ok", conn)

    assert document.fetch_status == "ok"


# --- Whole-branch review I8: a deny-listed domain is never fetched at all ------------------

def test_fetch_denied_domain_is_never_requested(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_3,
    )
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.load_deny_list",
        return_value={"scam-scholarships.example"},
    )
    mock_robots = mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed")
    mock_wait = mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mock_http = mocker.patch("opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http")

    document = pipeline.fetch("https://scam-scholarships.example/awards", conn)

    assert document.fetch_status == "error:denied_domain"
    assert document.text_path is None
    # "Excluded from fetch entirely" (spec §5) -- not even a robots.txt lookup.
    mock_robots.assert_not_called()
    mock_wait.assert_not_called()
    mock_http.assert_not_called()

    row = conn.execute("SELECT * FROM document WHERE id = ?", (document.id,)).fetchone()
    assert row is not None  # recorded, never a silent skip


def test_fetch_undenied_domain_proceeds_normally(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.load_deny_list",
        return_value={"scam-scholarships.example"},
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.http_fetch.fetch_http",
        return_value=FetchResult(
            text="Real scholarship content well over the threshold. " * 5,
            status_code=200,
            is_degraded=False,
        ),
    )

    document = pipeline.fetch("https://uwa.edu.au/scholarships", conn)

    assert document.fetch_status == "ok"


def test_shipped_deny_list_file_exists_and_parses():
    """config.DENY_LIST_PATH used to point at a file that did not exist."""
    from opportunity_tracker import config, tiering

    assert Path(config.DENY_LIST_PATH).exists()
    assert tiering.load_deny_list(config.DENY_LIST_PATH) == set()


def test_fetch_pdf_url_extracts_text_via_pdf_fetch(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier_for_url",
        return_value=SourceTier.TIER_1,
    )
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.is_allowed", return_value=True)
    mocker.patch("opportunity_tracker.fetcher.pipeline.robots.wait_for_host")

    fake_response = mocker.Mock()
    fake_response.content = b"%PDF-1.4 fake bytes for a mocked download"
    mocker.patch("opportunity_tracker.fetcher.pipeline.httpx.get", return_value=fake_response)
    mock_extract = mocker.patch(
        "opportunity_tracker.fetcher.pipeline.pdf_fetch.extract_pdf_text",
        return_value="SCHOLARSHIP CONDITIONS: minimum 25% FTE research project",
    )

    document = pipeline.fetch("https://uwa.edu.au/scholarships/conditions.PDF", conn)

    mock_extract.assert_called_once()
    assert document.fetch_method == FetchMethod.PDF
    assert document.fetch_status == "ok"
    assert document.degraded is False
    assert "SCHOLARSHIP CONDITIONS" in Path(document.text_path).read_text(encoding="utf-8")
