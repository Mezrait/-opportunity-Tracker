"""Fetch pipeline: URL -> `document` row. See spec §6.1, §4.4.

This is the single fetch entrypoint the whole rest of the system calls -- discovery,
the digger, and manual seed ingestion all route through fetch() so every fetch is
robots-checked, rate-limited, hashed, and logged identically regardless of caller.
It never raises on a disallowed or failed fetch and always inserts a `document` row
-- failure is recorded as data, not as an exception, per "every error degrades
toward UNKNOWN-GATED, never toward silent deletion" (spec principle 4).

"Unchanged hash => no downstream work" (spec §4.4) is a decision the CALLER makes by
comparing the returned Document.content_hash against the immediately-previous
document row for the same URL -- this function always fetches and always inserts a
row; the hash can only be known after fetching, so there is nothing earlier to skip.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from opportunity_tracker import tiering
from opportunity_tracker.fetcher import headless_fetch, http_fetch, pdf_fetch, robots
from opportunity_tracker.models import Document, FetchMethod, SourceTier

DOCUMENTS_DIR = Path("documents")


def fetch(url: str, conn: sqlite3.Connection, declared_tier: int | None = None) -> Document:
    """Fetch `url`, hash and persist its text, and insert+return a `document` row."""
    domain = urlparse(url).netloc
    source_tier = tiering.classify_tier(domain, declared_tier)

    if not robots.is_allowed(url):
        return _insert_document(
            conn,
            url=url,
            source_tier=source_tier,
            fetch_method=FetchMethod.HTTP,
            content_hash="",
            text_path=None,
            fetch_status="error:robots_disallowed",
            degraded=False,
        )

    robots.wait_for_host(domain)

    if url.lower().endswith(".pdf"):
        try:
            text = _fetch_pdf_text(url)
        except Exception as exc:  # noqa: BLE001 - any fetch failure degrades to a recorded row, never a crash
            return _fetch_failed_document(conn, url, source_tier, FetchMethod.PDF, exc)
        fetch_method = FetchMethod.PDF
        is_degraded = False
    else:
        try:
            http_result = http_fetch.fetch_http(url)
        except Exception as exc:  # noqa: BLE001
            return _fetch_failed_document(conn, url, source_tier, FetchMethod.HTTP, exc)
        if http_result.is_degraded:
            try:
                headless_result = headless_fetch.fetch_headless(url)
            except Exception as exc:  # noqa: BLE001
                return _fetch_failed_document(conn, url, source_tier, FetchMethod.HEADLESS, exc)
            text = headless_result.text
            fetch_method = FetchMethod.HEADLESS
            is_degraded = headless_result.is_degraded
        else:
            text = http_result.text
            fetch_method = FetchMethod.HTTP
            is_degraded = http_result.is_degraded

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    text_path = _save_text(content_hash, text)

    return _insert_document(
        conn,
        url=url,
        source_tier=source_tier,
        fetch_method=fetch_method,
        content_hash=content_hash,
        text_path=text_path,
        fetch_status="ok",
        degraded=is_degraded,
    )


def _fetch_failed_document(
    conn: sqlite3.Connection,
    url: str,
    source_tier: SourceTier,
    fetch_method: FetchMethod,
    exc: Exception,
) -> Document:
    """Record a fetch that raised (network error, timeout, PDF parse failure, ...) as a
    `document` row instead of letting the exception propagate and crash the pipeline.
    Mirrors the robots-disallowed case: never raise, always insert a row (spec §8)."""
    return _insert_document(
        conn,
        url=url,
        source_tier=source_tier,
        fetch_method=fetch_method,
        content_hash="",
        text_path=None,
        fetch_status=f"error:fetch_failed:{type(exc).__name__}",
        degraded=False,
    )


def _fetch_pdf_text(url: str) -> str:
    """Download the PDF at `url` to a temp file and extract its text."""
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(tmp_path, "wb") as f:
            f.write(response.content)
        return pdf_fetch.extract_pdf_text(tmp_path)
    finally:
        os.unlink(tmp_path)


def _save_text(content_hash: str, text: str) -> str:
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCUMENTS_DIR / f"{content_hash}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _insert_document(
    conn: sqlite3.Connection,
    *,
    url: str,
    source_tier: SourceTier,
    fetch_method: FetchMethod,
    content_hash: str,
    text_path: str | None,
    fetch_status: str,
    degraded: bool,
) -> Document:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            url,
            source_tier.value,
            fetch_method.value,
            content_hash,
            text_path,
            retrieved_at,
            fetch_status,
            int(degraded),
        ),
    )
    conn.commit()
    return Document(
        id=cursor.lastrowid,
        url=url,
        source_tier=source_tier,
        fetch_method=fetch_method,
        content_hash=content_hash,
        text_path=text_path,
        retrieved_at=retrieved_at,
        fetch_status=fetch_status,
        degraded=degraded,
    )
