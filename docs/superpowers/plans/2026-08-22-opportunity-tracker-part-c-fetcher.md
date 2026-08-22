# Opportunity Tracker Implementation Plan — Part C: Fetcher (Tasks 9–13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

This file covers Tasks 9–13 of the Opportunity Tracker implementation plan. It builds on
Tasks 1–4 (`docs/superpowers/plans/2026-08-22-opportunity-tracker.md`), which define
`src/opportunity_tracker/models.py`, `config.py`, and `db.py` exactly as they exist in that
file — nothing here redefines any dataclass, enum, or table from those modules.

**Spec:** `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md` — primarily §6.1
(fetcher: robots.txt compliance and rate limiting, `http` → `headless` fallback, PDF text
extraction, content hashing, degraded-fetch detection) and §4.4 (append-only requirements —
"unchanged hash ⇒ no downstream work" is a decision the *caller* of `fetch()` makes, not a
skip inside the fetcher itself; see Task 13).

**Dependency note:** Task 13 (`fetcher/pipeline.py`) imports `tiering.classify_tier` from
Task 5 (`src/opportunity_tracker/tiering.py`, already specified in
`docs/superpowers/plans/2026-08-22-opportunity-tracker-part-b-sync.md`). Task 5's actual,
already-written contract is `classify_tier(domain: str, seed_override: int | None = None) ->
SourceTier`. Task 13 calls it **positionally** — `tiering.classify_tier(domain,
declared_tier)` — precisely because this file's own parameter is named `declared_tier` while
Task 5's is named `seed_override`; positional calling means the two names never need to
match. Task 13's own tests mock `tiering.classify_tier` directly (module-qualified, per the
pattern below), so they do not require Task 5's real implementation to run, only its already-
fixed signature.

**Testing note (applies to every task in this file):** none of Tasks 9–13 may hit a real
network endpoint, a real LLM, or (for Task 11) the live internet during the automated test
suite. Every external call — `urllib.request.urlopen`, `httpx.get`, the Anthropic API (not
used in this file, but see Task 14) — is mocked with `pytest-mock`'s `mocker.patch`. Task 11
is the sole exception to "external call is mocked": it drives a *real* headless Chromium
browser (Playwright is a project dependency, not a test double) against local `file://`
fixtures, never the live network — this is noted explicitly in that task.

Throughout, later-task consumption uses **module-qualified imports** (`from
opportunity_tracker.fetcher import robots` then `robots.is_allowed(...)`, never `from
opportunity_tracker.fetcher.robots import is_allowed`), matching the convention already
established in Parts B and D — this is what lets `mocker.patch("...pipeline.robots.is_allowed",
...)` intercept the call from inside `pipeline.py`.

---

### Task 9: robots.txt compliance and rate limiting (`fetcher/robots.py`)

**Files:**
- Create: `src/opportunity_tracker/fetcher/__init__.py`
- Create: `tests/unit/fetcher/__init__.py` (empty — makes `tests/unit/fetcher` a proper
  package so pytest imports its test modules under a qualified name; `fetcher/pipeline.py`'s
  test module shares no basename with anything else in this plan, but every other component
  group in this plan gives its test directory an `__init__.py` for the same reason, so this
  keeps the convention uniform across the whole test tree)
- Create: `src/opportunity_tracker/fetcher/robots.py`
- Test: `tests/unit/fetcher/test_robots.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — this module uses only Python's stdlib
  (`urllib.robotparser.RobotFileParser`, `urllib.request`, `urllib.parse.urlparse`, `time`).
- Produces: `is_allowed(url: str) -> bool` and `wait_for_host(domain: str,
  min_interval_seconds: float = 2.0) -> None` — both imported and called (module-qualified,
  as `robots.is_allowed(...)` / `robots.wait_for_host(...)`) by Task 13's `fetcher/pipeline.py`
  below.

Research finding this task encodes: university sites are usually but not universally
permissive with robots.txt, so `is_allowed` must check per host at request time — it is never
assumed, never skipped, and never hardcoded to `True`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/fetcher/test_robots.py
"""Tests for robots.txt compliance and per-host rate limiting. urllib.request.urlopen
and time.monotonic/time.sleep are mocked throughout -- this suite never fetches a real
robots.txt over the network and never actually sleeps for 2 real seconds."""
from unittest.mock import MagicMock

import pytest

from opportunity_tracker.fetcher import robots


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """robots.py caches per-host state at module scope for the process lifetime --
    reset both caches around every test so tests don't leak state into each other."""
    robots._robots_cache.clear()
    robots._last_request_time.clear()
    yield
    robots._robots_cache.clear()
    robots._last_request_time.clear()


def _mock_urlopen(mocker, body: bytes):
    mock_response = MagicMock()
    mock_response.read.return_value = body
    return mocker.patch(
        "opportunity_tracker.fetcher.robots.urllib.request.urlopen",
        return_value=mock_response,
    )


def test_is_allowed_returns_false_for_disallowed_path(mocker):
    _mock_urlopen(mocker, b"User-agent: *\nDisallow: /private/\n")

    assert robots.is_allowed("https://example.edu/private/page") is False


def test_is_allowed_returns_true_for_allowed_path(mocker):
    _mock_urlopen(mocker, b"User-agent: *\nDisallow: /private/\n")

    assert robots.is_allowed("https://example.edu/public/page") is True


def test_is_allowed_caches_parsed_robots_txt_per_host(mocker):
    mock_urlopen = _mock_urlopen(mocker, b"User-agent: *\nDisallow: /private/\n")

    robots.is_allowed("https://example.edu/a")
    robots.is_allowed("https://example.edu/b")

    assert mock_urlopen.call_count == 1  # second check for the same host is cached


def test_wait_for_host_blocks_until_min_interval_elapsed(mocker):
    monotonic_values = iter([100.0, 100.5, 102.0])
    mocker.patch(
        "opportunity_tracker.fetcher.robots.time.monotonic",
        side_effect=lambda: next(monotonic_values),
    )
    mock_sleep = mocker.patch("opportunity_tracker.fetcher.robots.time.sleep")

    robots.wait_for_host("example.edu", min_interval_seconds=2.0)
    robots.wait_for_host("example.edu", min_interval_seconds=2.0)

    mock_sleep.assert_called_once()
    (slept_for,), _ = mock_sleep.call_args
    assert slept_for == pytest.approx(1.5)


def test_wait_for_host_does_not_block_when_interval_already_elapsed(mocker):
    monotonic_values = iter([100.0, 105.0])
    mocker.patch(
        "opportunity_tracker.fetcher.robots.time.monotonic",
        side_effect=lambda: next(monotonic_values),
    )
    mock_sleep = mocker.patch("opportunity_tracker.fetcher.robots.time.sleep")

    robots.wait_for_host("example.edu", min_interval_seconds=2.0)
    robots.wait_for_host("example.edu", min_interval_seconds=2.0)

    mock_sleep.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fetcher/test_robots.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.fetcher'`

- [ ] **Step 3: Write `src/opportunity_tracker/fetcher/__init__.py`**

```python
```

(empty — marks `fetcher` as a package)

- [ ] **Step 3b: Write `tests/unit/fetcher/__init__.py`**

```python
```

(empty)

- [ ] **Step 3c: Write `src/opportunity_tracker/fetcher/robots.py`**

```python
"""robots.txt compliance and per-host rate limiting. See spec §6.1.

University sites are usually but not universally permissive with robots.txt -- this
module checks per host at request time, never assumes permissiveness and never
hardcodes an allow-all.
"""
from __future__ import annotations

import time
import urllib.request
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

# Parsed robots.txt per host, cached for the process lifetime -- repeated checks
# against the same host never re-fetch robots.txt.
_robots_cache: dict[str, RobotFileParser] = {}

# Last request timestamp (time.monotonic()) per host, for rate limiting.
_last_request_time: dict[str, float] = {}


def _get_parser(host: str) -> RobotFileParser:
    if host in _robots_cache:
        return _robots_cache[host]
    parser = RobotFileParser()
    parser.set_url(f"https://{host}/robots.txt")
    parser.read()
    _robots_cache[host] = parser
    return parser


def is_allowed(url: str) -> bool:
    """Return True if `url` may be fetched per its host's robots.txt.

    Fetches and parses https://{host}/robots.txt via the stdlib's
    urllib.robotparser on the first check for that host; every later check
    against the same host reuses the cached, already-parsed result for the
    process lifetime. If robots.txt is unreachable (network error, 404, etc.),
    RobotFileParser's own standard behaviour applies -- effectively allow-all
    for a missing file, which matches how a real crawler treats "no
    robots.txt found."
    """
    host = urlparse(url).netloc
    parser = _get_parser(host)
    return parser.can_fetch("*", url)


def wait_for_host(domain: str, min_interval_seconds: float = 2.0) -> None:
    """Block until at least `min_interval_seconds` has passed since the last
    call for `domain`. A simple per-host last-request-time dict -- no
    external scheduler or async dependency.
    """
    now = time.monotonic()
    last = _last_request_time.get(domain)
    if last is not None:
        remaining = min_interval_seconds - (now - last)
        if remaining > 0:
            time.sleep(remaining)
            now = time.monotonic()
    _last_request_time[domain] = now
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/fetcher/test_robots.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/fetcher/__init__.py \
        tests/unit/fetcher/__init__.py \
        src/opportunity_tracker/fetcher/robots.py \
        tests/unit/fetcher/test_robots.py
git commit -m "feat: robots.txt compliance and per-host rate limiting (robots.py)"
```

---

### Task 10: HTTP fetch (`fetcher/http_fetch.py`)

**Files:**
- Create: `src/opportunity_tracker/fetcher/http_fetch.py`
- Test: `tests/unit/fetcher/test_http_fetch.py`

**Interfaces:**
- Consumes: nothing from earlier tasks besides the third-party `httpx` package (already a
  pinned dependency in Task 1's `pyproject.toml`).
- Produces: dataclass `FetchResult` (fields: `text: str`, `status_code: int`, `is_degraded:
  bool`), constant `DEFAULT_LOADING_MARKERS: tuple[str, ...] = ("Loading component...",
  "Please enable JavaScript")`, and `fetch_http(url: str, min_content_length: int = 200,
  loading_markers: tuple[str, ...] = DEFAULT_LOADING_MARKERS) -> FetchResult` — all three
  imported by Task 11's `fetcher/headless_fetch.py` (`FetchResult`,
  `DEFAULT_LOADING_MARKERS` — never redefined there) and by Task 13's `fetcher/pipeline.py`
  (`http_fetch.fetch_http(...)`, module-qualified).

**Testing note:** `httpx.get` is mocked via `mocker.patch` in both tests below — this suite
never makes a real HTTP request.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/fetcher/test_http_fetch.py
"""Tests for plain HTTP GET fetch and degraded-fetch detection. httpx.get is mocked
throughout -- this suite never makes a real HTTP request."""
from opportunity_tracker.fetcher.http_fetch import FetchResult, fetch_http


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_fetch_http_normal_content_is_not_degraded(mocker):
    real_text = "Scholarship details and eligibility criteria. " * 10  # well over 200 chars
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(real_text, 200),
    )

    result = fetch_http("https://uwa.edu.au/scholarships/rtp")

    assert isinstance(result, FetchResult)
    assert result.status_code == 200
    assert result.text == real_text
    assert result.is_degraded is False


def test_fetch_http_short_loading_body_is_degraded(mocker):
    short_text = "Loading component..."
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(short_text, 200),
    )

    result = fetch_http("https://uwa.edu.au/hdr-application")

    assert result.status_code == 200
    assert result.text == short_text
    assert result.is_degraded is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fetcher/test_http_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.fetcher.http_fetch'`

- [ ] **Step 3: Write `src/opportunity_tracker/fetcher/http_fetch.py`**

```python
"""Plain HTTP GET fetch with degraded-fetch detection. See spec §6.1.

UWA's HDR page renders "Loading component..." to a plain GET -- a naive pipeline
would accept that as real content. Degraded-fetch detection here is minimum content
length plus expected-keyword (loading-placeholder) presence, exactly as the spec
requires; it is deliberately cheap and heuristic, not a full JS-awareness check --
that's what fetcher/headless_fetch.py is for.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class FetchResult:
    text: str
    status_code: int
    is_degraded: bool


DEFAULT_LOADING_MARKERS: tuple[str, ...] = (
    "Loading component...",
    "Please enable JavaScript",
)


def fetch_http(
    url: str,
    min_content_length: int = 200,
    loading_markers: tuple[str, ...] = DEFAULT_LOADING_MARKERS,
) -> FetchResult:
    """Fetch `url` via a plain HTTP GET and flag degraded fetches.

    A fetch is degraded if the response text is shorter than
    `min_content_length` OR contains any of `loading_markers`.
    """
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    text = response.text
    is_degraded = len(text) < min_content_length or any(
        marker in text for marker in loading_markers
    )
    return FetchResult(text=text, status_code=response.status_code, is_degraded=is_degraded)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/fetcher/test_http_fetch.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/fetcher/http_fetch.py tests/unit/fetcher/test_http_fetch.py
git commit -m "feat: plain HTTP fetch with degraded-fetch detection (http_fetch.py)"
```

---

### Task 11: Headless fetch (`fetcher/headless_fetch.py`)

**Files:**
- Create: `src/opportunity_tracker/fetcher/headless_fetch.py`
- Create: `tests/fixtures/loading_placeholder.html`
- Create: `tests/fixtures/real_content.html`
- Test: `tests/unit/fetcher/test_headless_fetch.py`

**Interfaces:**
- Consumes: `FetchResult` and `DEFAULT_LOADING_MARKERS` from Task 10's
  `fetcher/http_fetch.py` (imported, never redefined); the third-party `playwright.sync_api`
  package (already pinned in Task 1's `pyproject.toml`).
- Produces: `fetch_headless(url: str, min_content_length: int = 200) -> FetchResult` (the
  same `FetchResult` dataclass Task 10 defines) — imported and called (module-qualified, as
  `headless_fetch.fetch_headless(...)`) by Task 13's `fetcher/pipeline.py` as the fallback
  when `http_fetch.fetch_http` reports `is_degraded=True`.

**Testing note — read before writing this task:** a real headless Chromium browser IS
available in the test environment (Playwright is a project dependency, not mocked out here —
this is the one fetch method it's practical to test for real, deterministically, rather than
mocking Playwright's API). The test below drives `fetch_headless` against two local static
HTML fixtures via `file://` URLs, never the live network. Because a real browser is involved,
**Chromium must be installed once** before the passing-test step will work — that is its own
explicit step below (Step 4), not folded into "run the test."

- [ ] **Step 1: Create the fixtures and write the failing test**

```html
<!-- tests/fixtures/loading_placeholder.html -->
<body>Loading component...</body>
```

```html
<!-- tests/fixtures/real_content.html -->
<body>
<p>
This university offers a fully funded PhD scholarship in computer science for
international students. Applicants must hold a first-class honours degree or an
equivalent qualification, demonstrate English language proficiency, and secure a
supervisor agreement before the published application deadline for the relevant
intake year.
</p>
</body>
```

```python
# tests/unit/fetcher/test_headless_fetch.py
"""Tests for the Playwright-based headless fetch fallback. Drives a real headless
Chromium browser against local file:// fixtures -- never the live network. Requires
`uv run playwright install chromium` to have been run once (see Task 11 Step 4)."""
from pathlib import Path

from opportunity_tracker.fetcher.headless_fetch import fetch_headless

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def test_fetch_headless_flags_loading_placeholder_as_degraded():
    fixture_path = FIXTURES_DIR / "loading_placeholder.html"
    url = fixture_path.resolve().as_uri()

    result = fetch_headless(url)

    assert "Loading component..." in result.text
    assert result.is_degraded is True


def test_fetch_headless_real_content_is_not_degraded():
    fixture_path = FIXTURES_DIR / "real_content.html"
    url = fixture_path.resolve().as_uri()

    result = fetch_headless(url)

    assert len(result.text) >= 200
    assert result.is_degraded is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fetcher/test_headless_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.fetcher.headless_fetch'`

- [ ] **Step 3: Write `src/opportunity_tracker/fetcher/headless_fetch.py`**

```python
"""Playwright-based headless fetch -- fallback for JS-rendered pages that return a
near-empty shell to a plain GET. See spec §6.1."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from opportunity_tracker.fetcher.http_fetch import DEFAULT_LOADING_MARKERS, FetchResult


def fetch_headless(url: str, min_content_length: int = 200) -> FetchResult:
    """Render `url` with a headless Chromium browser and return its visible text.

    Reuses the same degraded-fetch heuristic as fetch_http: too-short body, or
    presence of a loading-placeholder marker -- a headless render can still be
    degraded (e.g. a page that never finishes loading its content component).
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            response = page.goto(url)
            text = page.inner_text("body")
            status_code = response.status if response is not None else 200
        finally:
            browser.close()

    is_degraded = len(text) < min_content_length or any(
        marker in text for marker in DEFAULT_LOADING_MARKERS
    )
    return FetchResult(text=text, status_code=status_code, is_degraded=is_degraded)
```

- [ ] **Step 4: Install Playwright's Chromium browser (one-time, before running the passing test)**

Run: `uv run playwright install chromium`
Expected: downloads and installs the Chromium browser binary Playwright drives. This is a
one-time step per machine/CI image — subsequent test runs on the same environment do not
need to repeat it. Without this step, Step 5 below fails with a Playwright
`BrowserType.launch` error telling you the executable is missing, not a test assertion
failure.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/fetcher/test_headless_fetch.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/opportunity_tracker/fetcher/headless_fetch.py \
        tests/fixtures/loading_placeholder.html \
        tests/fixtures/real_content.html \
        tests/unit/fetcher/test_headless_fetch.py
git commit -m "feat: Playwright-based headless fetch fallback (headless_fetch.py)"
```

---

### Task 12: PDF text extraction (`fetcher/pdf_fetch.py`)

**Files:**
- Create: `src/opportunity_tracker/fetcher/pdf_fetch.py`
- Test: `tests/unit/fetcher/test_pdf_fetch.py`

**Interfaces:**
- Consumes: nothing from earlier tasks besides the third-party `pdfplumber` package (already
  pinned in Task 1's `pyproject.toml`).
- Produces: `extract_pdf_text(path: str) -> str` — imported and called (module-qualified, as
  `pdf_fetch.extract_pdf_text(...)`) by Task 13's `fetcher/pipeline.py` for any URL ending in
  `.pdf`.

**Fixture note — concrete, not hand-waved:** rather than depend on a binary PDF file
existing somewhere inside the installed `pdfplumber` package (not guaranteed across
environments, and not something this plan can verify in advance), the test below
**constructs a minimal, syntactically valid single-page PDF from raw bytes at test time**,
with a helper function included directly in the test file. Every xref byte offset is
computed from the actual serialized object bytes as they're written (via `len(buf)` at each
step), never hand-typed — this is what makes the hand-built PDF reliably valid rather than
fragile. The PDF is written to a `tmp_path` file (pytest's built-in temp-directory fixture),
never committed to the repo as a binary fixture.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/fetcher/test_pdf_fetch.py
"""Tests for PDF text extraction. Builds a minimal, valid, single-page PDF from raw
bytes at test time (byte offsets computed from the actual serialized objects, not
hardcoded) rather than depending on a binary fixture file or any extra PDF-writing
dependency."""
from pathlib import Path

from opportunity_tracker.fetcher.pdf_fetch import extract_pdf_text

EXPECTED_TEXT = "SCHOLARSHIP CONDITIONS: minimum 25% FTE research project"


def _build_minimal_pdf(text: str) -> bytes:
    """Construct a minimal, syntactically valid, single-page PDF whose only content
    is `text`, drawn via a single Tj operator in Helvetica. The xref table's byte
    offsets are computed from len(buf) as each object is written, so the file is
    guaranteed structurally valid regardless of the exact text length."""
    content_stream = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n"
        + content_stream + b"\nendstream",
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj_body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode("ascii") + obj_body + b"\nendobj\n"

    xref_offset = len(buf)
    n = len(objects) + 1  # +1 for the free-list head entry (object 0)
    buf += f"xref\n0 {n}\n".encode("ascii")
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode("ascii")
    buf += (
        f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode("ascii")
    return bytes(buf)


def test_extract_pdf_text_reads_single_page_content(tmp_path: Path):
    pdf_bytes = _build_minimal_pdf(EXPECTED_TEXT)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(pdf_bytes)

    text = extract_pdf_text(str(pdf_path))

    assert EXPECTED_TEXT in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fetcher/test_pdf_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.fetcher.pdf_fetch'`

- [ ] **Step 3: Write `src/opportunity_tracker/fetcher/pdf_fetch.py`**

```python
"""PDF text extraction. Not optional -- binding scholarship conditions are commonly
PDFs linked from an HTML page (the UWA case this whole tool exists to catch: the
25%-FTE research-project rule lives in a PDF, not the scholarship page itself). See
spec §6.1."""
from __future__ import annotations

import pdfplumber


def extract_pdf_text(path: str) -> str:
    """Extract all text from the PDF at `path`.

    Each page's extracted text is joined with a single newline between pages. A
    page with no extractable text (e.g. a scanned image page with no text layer)
    contributes an empty string for that page rather than raising.
    """
    pages_text: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    return "\n".join(pages_text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/fetcher/test_pdf_fetch.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/fetcher/pdf_fetch.py tests/unit/fetcher/test_pdf_fetch.py
git commit -m "feat: PDF text extraction (pdf_fetch.py)"
```

---

### Task 13: Fetch pipeline (`fetcher/pipeline.py`)

**Files:**
- Create: `src/opportunity_tracker/fetcher/pipeline.py`
- Test: `tests/unit/fetcher/test_pipeline.py`

**Interfaces:**
- Consumes:
  - `robots.is_allowed(url: str) -> bool`, `robots.wait_for_host(domain: str,
    min_interval_seconds: float = 2.0) -> None` (Task 9, this file).
  - `http_fetch.fetch_http(url: str, min_content_length: int = 200, loading_markers:
    tuple[str, ...] = DEFAULT_LOADING_MARKERS) -> FetchResult` (Task 10, this file).
  - `headless_fetch.fetch_headless(url: str, min_content_length: int = 200) -> FetchResult`
    (Task 11, this file).
  - `pdf_fetch.extract_pdf_text(path: str) -> str` (Task 12, this file).
  - `tiering.classify_tier(domain: str, seed_override: int | None = None) -> SourceTier`
    (Task 5, `docs/superpowers/plans/2026-08-22-opportunity-tracker-part-b-sync.md`) — called
    positionally as `tiering.classify_tier(domain, declared_tier)`; see the dependency note
    at the top of this file.
  - `models.Document`, `models.FetchMethod`, `models.SourceTier` (Task 2).
  - In tests only: `db.get_connection(db_path: str) -> sqlite3.Connection`,
    `db.init_db(conn: sqlite3.Connection) -> None` (Task 4), to exercise `fetch()` against a
    real (in-memory) `document` table.
- Produces: `fetch(url: str, conn: sqlite3.Connection, declared_tier: int | None = None) ->
  Document` — **the single fetch entrypoint every other component calls**: discovery (Task
  15, once a `candidate` URL is ready to fetch), the digger (Task 19, milestone 2), and
  manual pin ingestion. Every caller gets robots compliance, rate limiting, `http` →
  `headless` fallback, PDF handling, content hashing, and a `document` row insert uniformly,
  regardless of which caller it was.

Note on "unchanged hash ⇒ no downstream work" (spec §4.4): that rule describes what a
*caller* of `fetch()` does after the fact — compare the returned `Document.content_hash`
against the immediately-previous `document` row for the same URL, and skip re-running the
extractor if they match. `fetch()` itself always performs the fetch and always inserts a
`document` row; the hash can only be known *after* fetching, so there is no earlier point at
which this function could skip anything.

**Testing note:** `robots.is_allowed`, `robots.wait_for_host`, `http_fetch.fetch_http`,
`headless_fetch.fetch_headless`, `pdf_fetch.extract_pdf_text`, `tiering.classify_tier`, and
`httpx.get` (used internally only for downloading PDF bytes) are all mocked via
`mocker.patch` in every test below — this suite never fetches over a real network, never
launches a real browser, and never parses a real PDF. `pipeline.DOCUMENTS_DIR` is also
patched to a `tmp_path` per test so the suite never writes into the real project's
`documents/` directory.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/fetcher/test_pipeline.py
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
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier",
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
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier",
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
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier",
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


def test_fetch_pdf_url_extracts_text_via_pdf_fetch(mocker, conn, tmp_path):
    mocker.patch.object(pipeline, "DOCUMENTS_DIR", tmp_path)
    mocker.patch(
        "opportunity_tracker.fetcher.pipeline.tiering.classify_tier",
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fetcher/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.fetcher.pipeline'`

- [ ] **Step 3: Write `src/opportunity_tracker/fetcher/pipeline.py`**

```python
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
        text = _fetch_pdf_text(url)
        fetch_method = FetchMethod.PDF
        is_degraded = False
    else:
        http_result = http_fetch.fetch_http(url)
        if http_result.is_degraded:
            headless_result = headless_fetch.fetch_headless(url)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/fetcher/test_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/fetcher/pipeline.py tests/unit/fetcher/test_pipeline.py
git commit -m "feat: fetch pipeline orchestration (pipeline.py)"
```
