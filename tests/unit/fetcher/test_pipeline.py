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
