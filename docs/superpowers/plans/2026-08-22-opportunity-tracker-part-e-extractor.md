# Opportunity Tracker Implementation Plan — Part E: Extractor & Digger (Tasks 16–19)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

This file covers Tasks 16–19 of the Opportunity Tracker implementation plan. It builds on
Tasks 1–4 (`docs/superpowers/plans/2026-08-22-opportunity-tracker.md`), which define
`src/opportunity_tracker/models.py`, `config.py`, and `db.py` exactly as they exist in that
file — nothing here redefines any dataclass, enum, or table from those modules.

**Spec:** `docs/superpowers/specs/2026-08-22-opportunity-tracker-design.md` — primarily §6.2
(extractor: single LLM call, strict JSON schema, closed `kind` enum, `NULL` preserved,
evidence span mandatory, extractor never sees the operator's profile), §6.3 (digger: bounded
budget of 5 fetches / depth 2 / same registrable domain / one target field, web-search-first
then bounded fetch-and-follow fallback), §8 (failure modes: hallucinated value with plausible
evidence, unparseable LLM output), and §9.1/§9.2 (evidence-span validator is a mandatory unit
test; the extractor itself is evaluated, not unit-tested, against the gold set in a later
task).

**Dependency notes:**

- Task 18 (`extractor/run.py`) and Task 19 (`digger/run.py`) both import
  `fetcher.pipeline.fetch(url: str, conn: sqlite3.Connection, declared_tier: int | None =
  None) -> Document` from Task 13 (`docs/superpowers/plans/2026-08-22-opportunity-tracker-part-c-fetcher.md`,
  already written). Called module-qualified as `pipeline.fetch(...)`.
- Task 19 (`digger/run.py`) imports from Task 14's `discovery/websearch.py`
  (`docs/superpowers/plans/2026-08-22-opportunity-tracker-part-d-discovery.md`, already
  written), which currently exposes `search_institution(institution, filter_obj, api_key,
  max_uses=3) -> list[dict]` and `build_query(filter_obj, institution) -> str`. Neither fits
  a bare-domain-plus-target-kind query (the digger has no `Institution`/`Filter` pair — only
  a registrable domain and a missing `RequirementKind`), so Task 19 **adds** a small sibling
  function, `search_domain(domain: str, query: str, api_key: str, max_uses: int = 1) ->
  list[dict]`, to the end of that already-existing file. This is an addition, not a rewrite —
  `search_institution` and `build_query` are untouched.
- Both Task 18 and Task 19 depend on Task 17 (`extractor/evidence.py`, this file, above) for
  `validate_evidence`.

**Testing note (applies to Tasks 18 and 19):** neither may hit a real network endpoint or a
real LLM in the automated test suite. Every external call — `anthropic.Anthropic(...)`,
`fetcher.pipeline.fetch`, `discovery.websearch.search_domain` — is mocked with
`pytest-mock`'s `mocker.patch`. Task 17 (`evidence.py`) is pure stdlib logic and is unit-
tested with strict TDD instead, per spec §9.1's mandatory "fabricated span must be rejected"
case.

Throughout, later-task consumption uses **module-qualified imports** (`from
opportunity_tracker.extractor import evidence` then `evidence.validate_evidence(...)`, never
`from opportunity_tracker.extractor.evidence import validate_evidence`), matching the
convention already established in Parts C and D — this is what lets
`mocker.patch("opportunity_tracker.extractor.run.evidence.validate_evidence", ...)` (or the
equivalent for `digger.run`) intercept the call from inside the calling module.

---

### Task 16: Requirement schema and prompt (`extractor/schema.py`, `extractor/prompts.py`)

**Files:**
- Create: `src/opportunity_tracker/extractor/__init__.py`
- Create: `tests/unit/extractor/__init__.py` (empty — makes `tests/unit/extractor` a proper
  package so pytest imports its test modules under a qualified name, matching the convention
  established in Parts C and D for every component group with a `run.py` test module)
- Create: `src/opportunity_tracker/extractor/schema.py`
- Create: `src/opportunity_tracker/extractor/prompts.py`
- Test: `tests/unit/extractor/test_schema.py`
- Test: `tests/unit/extractor/test_prompts.py`

**Interfaces:**
- Consumes: `opportunity_tracker.models.RequirementKind` (Task 2) — the closed `kind` enum's
  single source of truth; `schema.py` builds its enum list from this, never a second
  hardcoded list.
- Produces: `REQUIREMENT_JSON_SCHEMA: dict` and `build_extraction_prompt(document_text: str)
  -> str` — both imported and called (module-qualified, as `schema.REQUIREMENT_JSON_SCHEMA`
  / `prompts.build_extraction_prompt(...)`) by Task 18's `extractor/run.py` below.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/extractor/test_schema.py
"""Regression test against schema/model drift: REQUIREMENT_JSON_SCHEMA's closed `kind`
enum must always match models.RequirementKind exactly, since schema.py builds it from
that enum rather than hardcoding a second list."""
from opportunity_tracker.extractor.schema import REQUIREMENT_JSON_SCHEMA
from opportunity_tracker.models import RequirementKind


def test_schema_kind_enum_matches_requirement_kind_exactly():
    kind_schema = (
        REQUIREMENT_JSON_SCHEMA["properties"]["requirements"]["items"]["properties"]["kind"]
    )
    assert set(kind_schema["enum"]) == {k.value for k in RequirementKind}


def test_schema_requires_kind_raw_text_evidence():
    item_schema = REQUIREMENT_JSON_SCHEMA["properties"]["requirements"]["items"]
    assert set(item_schema["required"]) == {"kind", "raw_text", "evidence"}


def test_schema_top_level_requires_requirements_array():
    assert REQUIREMENT_JSON_SCHEMA["required"] == ["requirements"]
    assert REQUIREMENT_JSON_SCHEMA["properties"]["requirements"]["type"] == "array"
```

```python
# tests/unit/extractor/test_prompts.py
"""The extractor prompt must never mention profile/applicant/fit-judgment concepts --
that blindness is what keeps the extractor from reasoning about eligibility instead of
faithfully transcribing what the document states (spec section 6.2)."""
from opportunity_tracker.extractor.prompts import build_extraction_prompt

FORBIDDEN_WORDS = ("profile", "applicant", "operator", "eligible", "suitable")

SAMPLE_DOCUMENT_TEXT = (
    "Minimum weighted average mark of 80 out of 100 is required. "
    "A minimum overall IELTS band score of 6.5 is required, with no band below 6.0. "
    "The application deadline for the 2027 intake is 15 March 2027."
)


def test_prompt_contains_document_text():
    prompt = build_extraction_prompt(SAMPLE_DOCUMENT_TEXT)
    assert SAMPLE_DOCUMENT_TEXT in prompt


def test_prompt_never_mentions_profile_or_fit_concepts():
    prompt = build_extraction_prompt(SAMPLE_DOCUMENT_TEXT)
    lowered = prompt.lower()
    for word in FORBIDDEN_WORDS:
        assert word not in lowered, f"prompt must never mention {word!r}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/extractor/test_schema.py tests/unit/extractor/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.extractor'`

- [ ] **Step 3: Write `src/opportunity_tracker/extractor/__init__.py`**

```python
```

(empty — marks `extractor` as a package)

- [ ] **Step 3b: Write `tests/unit/extractor/__init__.py`**

```python
```

(empty)

- [ ] **Step 3c: Write `src/opportunity_tracker/extractor/schema.py`**

```python
"""Requirement-extraction JSON schema. Closed `kind` enum sourced from
models.RequirementKind -- never a second hardcoded list, so schema and model can never
drift apart. Shaped as an Anthropic tool's `input_schema` (spec section 6.2)."""
from __future__ import annotations

from opportunity_tracker.models import RequirementKind

REQUIREMENT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "description": (
                "Every discrete admission/scholarship requirement found in the "
                "document, in the order encountered."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [k.value for k in RequirementKind],
                        "description": "The closed requirement category this entry belongs to.",
                    },
                    "operator": {
                        "type": ["string", "null"],
                        "description": (
                            "Comparison symbol attached to a numeric/graded threshold "
                            "(e.g. '>=', '=', '<='), or null if the document states "
                            "no such comparison."
                        ),
                    },
                    "value": {
                        "type": ["string", "null"],
                        "description": "The threshold or stated value, or null if not stated.",
                    },
                    "unit": {
                        "type": ["string", "null"],
                        "description": "The unit for `value` (e.g. 'percent', 'WAM'), or null.",
                    },
                    "raw_text": {
                        "type": "string",
                        "description": "The verbatim clause this requirement was extracted from.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": (
                            "A short quotation copied character-for-character from "
                            "the source document -- never paraphrased."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Extraction confidence, between 0 and 1.",
                    },
                },
                "required": ["kind", "raw_text", "evidence"],
            },
        },
    },
    "required": ["requirements"],
}
```

- [ ] **Step 3d: Write `src/opportunity_tracker/extractor/prompts.py`**

```python
"""Extractor prompt template. The extractor never sees the operator's profile --
given both the rules and the applicant, a model will reason about fit and
rationalise (spec section 6.2). This module's prompt text must never mention any
profile/applicant/fit-judgment concept; test_prompts.py enforces that mechanically."""
from __future__ import annotations


def build_extraction_prompt(document_text: str) -> str:
    """Build the single-call extraction prompt for `document_text`.

    Instructs the model to extract every admission/scholarship requirement it
    finds, preserve null for any operator/value/unit the document does not
    state, and quote evidence verbatim from the source text. Says nothing
    about applicant fit, eligibility judgment, or any operator/profile
    concept -- that separation is structural, not just a suggestion.
    """
    return f"""You are extracting structured admission and scholarship requirements from a single source document.

Read the document text below and identify every discrete requirement it states: grading thresholds, English-language test requirements, nationality restrictions, application deadlines, degree-level requirements, thesis or research-project requirements, supervisor requirements, prior-scholarship exclusions, return obligations, funding components, and intake-year statements.

For each requirement you find, record:
- which closed category it belongs to
- any comparison symbol attached to a numeric or graded threshold (e.g. ">=", "=", "<="), left unset if the requirement carries no such comparison
- the value and unit the requirement states, left unset if the document does not state one
- the exact verbatim clause you extracted the requirement from
- a short evidence quotation, copied character-for-character from the document text below -- never paraphrased, never summarized, never invented
- a confidence score between 0 and 1

Rules:
- If the document does not state a comparison symbol, value, or unit for a given requirement, leave that field null. Do not guess or infer a value that is not written in the document.
- The evidence you quote must be an exact, verbatim substring of the document text below. Do not alter capitalization, punctuation, or wording.
- Extract every requirement you find, even if it seems minor or purely informational.
- Your only job is faithful extraction of what the document states. Do not judge, rank, assess, or comment on any requirement in any way.
- If the document states no requirements at all, return an empty list.

Document text:
---
{document_text}
---
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/extractor/test_schema.py tests/unit/extractor/test_prompts.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/extractor/__init__.py \
        src/opportunity_tracker/extractor/schema.py \
        src/opportunity_tracker/extractor/prompts.py \
        tests/unit/extractor/__init__.py \
        tests/unit/extractor/test_schema.py \
        tests/unit/extractor/test_prompts.py
git commit -m "feat: requirement JSON schema and blind extraction prompt"
```

---

### Task 17: Evidence-span validator (`extractor/evidence.py`)

**Files:**
- Create: `src/opportunity_tracker/extractor/evidence.py`
- Test: `tests/unit/extractor/test_evidence.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — pure Python stdlib (`difflib.SequenceMatcher`)
  only, no model, no network. This is the mechanical defence named in spec §8's first
  failure mode ("Hallucinated value with plausible evidence") and §9.1's mandatory test
  case ("a fabricated span must be rejected").
- Produces: `validate_evidence(evidence: str, document_text: str, threshold: float = 0.85) ->
  bool` — imported and called (module-qualified, as `evidence.validate_evidence(...)`) by
  Task 18's `extractor/run.py` and Task 19's `digger/run.py`, both below.

This is a deterministic, pure-logic component — strict TDD applies, with the spec's own
mandatory "fabricated span must be rejected" case included verbatim below.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/extractor/test_evidence.py
"""Tests for the fuzzy evidence-span validator. Pure stdlib difflib logic -- no
model, no network, no mocking needed. Mechanical, no model involved (spec section
8): non-matching evidence must be rejected."""
from opportunity_tracker.extractor.evidence import validate_evidence

DOCUMENT_TEXT = (
    "Eligible applicants must have completed an honours degree with a minimum "
    "weighted average mark of 80 out of 100, and must submit an overall IELTS "
    "band score of at least 6.5 with no individual band below 6.0. The research "
    "project component of the PhD must constitute at least 25 percent of a full "
    "time equivalent annual enrolment."
)


def test_exact_substring_match_passes():
    evidence = "minimum weighted average mark of 80 out of 100"
    assert validate_evidence(evidence, DOCUMENT_TEXT) is True


def test_near_match_with_minor_extraction_noise_passes():
    # 3 characters altered from the real substring, simulating minor
    # transcription/extraction noise -- still >= 0.85 similarity.
    evidence = "minimum weighted averaqe mark of 8O out of 1o0"
    assert validate_evidence(evidence, DOCUMENT_TEXT) is True


def test_fabricated_span_is_rejected():
    # Spec section 9.1's mandatory case: a fabricated span must be rejected.
    evidence = (
        "Scholarships are available to students from any country with no "
        "restrictions whatsoever on prior awards."
    )
    assert validate_evidence(evidence, DOCUMENT_TEXT) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/extractor/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.extractor.evidence'`

- [ ] **Step 3: Write `src/opportunity_tracker/extractor/evidence.py`**

```python
"""Fuzzy evidence-span validator. Mechanical, no model involved (spec section 8):
"Evidence span must fuzzy-match text in the stored document. Non-matching =>
requirement rejected." This is the mechanical defence against a hallucinated value
with plausible-looking evidence -- and spec section 9.1's mandatory test case, "a
fabricated span must be rejected", is exactly what this function exists to do.
"""
from __future__ import annotations

from difflib import SequenceMatcher


def validate_evidence(evidence: str, document_text: str, threshold: float = 0.85) -> bool:
    """Return True if `evidence` fuzzy-matches some window of `document_text`.

    Slides windows sized close to len(evidence) (+/- 20% tolerance, to absorb a
    few inserted/dropped characters from extraction noise) across
    document_text, and returns True the moment any window's
    difflib.SequenceMatcher ratio against `evidence` clears `threshold`. Pure
    stdlib, no LLM call, no network -- this must be mechanically reliable
    since it is the sole gate between a candidate requirement and being
    written to the `requirement` table.
    """
    evidence = evidence.strip()
    if not evidence or not document_text:
        return False

    if evidence in document_text:
        return True

    evidence_len = len(evidence)
    doc_len = len(document_text)

    tolerance = max(1, int(evidence_len * 0.2))
    window_sizes = sorted(
        {
            max(1, evidence_len - tolerance),
            evidence_len,
            evidence_len + tolerance,
        }
    )

    for window_size in window_sizes:
        if window_size > doc_len:
            continue
        for start in range(0, doc_len - window_size + 1):
            window = document_text[start : start + window_size]
            ratio = SequenceMatcher(None, evidence, window).ratio()
            if ratio >= threshold:
                return True

    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/extractor/test_evidence.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/extractor/evidence.py tests/unit/extractor/test_evidence.py
git commit -m "feat: fuzzy evidence-span validator (evidence.py)"
```

---

### Task 18: Extractor run (`extractor/run.py`)

**Files:**
- Create: `src/opportunity_tracker/extractor/run.py`
- Test: `tests/unit/extractor/test_run.py`

**Interfaces:**
- Consumes:
  - `opportunity_tracker.models.Document`, `Requirement`, `RequirementKind` (Task 2).
  - `schema.REQUIREMENT_JSON_SCHEMA` (Task 16, this file), `prompts.build_extraction_prompt`
    (Task 16, this file) — both module-qualified.
  - `evidence.validate_evidence(evidence: str, document_text: str, threshold: float = 0.85)
    -> bool` (Task 17, this file) — module-qualified, so tests can mock it at
    `opportunity_tracker.extractor.evidence.validate_evidence`.
  - The third-party `anthropic.Anthropic` client class.
  - `opportunity_tracker.db` tables `requirement` and `unclassified_rule` (Task 4) —
    accessed via raw SQL against the `sqlite3.Connection` passed in, no ORM.
- Produces: `extract_requirements(document: Document, award_id: int, conn:
  sqlite3.Connection, api_key: str) -> tuple[list[Requirement], bool]` — the second value is
  `extraction_failed: bool`. This is the entry point a later CLI/pipeline-orchestration task
  calls once per fetched document; when `extraction_failed` is `True` the caller is
  responsible for flagging the award UNKNOWN-GATED (spec §8) — this function never silently
  swallows an unparseable-after-retry failure, it reports it via the return value instead.
  Also produces `extract_requirements_raw(document_text: str, api_key: str) -> list[dict]` —
  the DB-free half of the same logic (prompt, retried API call, evidence validation, no
  `kind`-enum check, no database writes), consumed directly by Task 27's
  `scripts/eval_gold_set.py`, which has raw document text and hand-annotated ground truth
  but no database rows to write against.

**Testing note:** `anthropic.Anthropic` is mocked entirely in every test below — this suite
never calls the real Anthropic API. `evidence.validate_evidence` is mocked directly (not
exercised for real) in three of the four tests, since its own correctness is Task 17's
concern; the fourth test (clean success) also mocks it, to `True`, keeping this suite
focused purely on `extract_requirements`'s own orchestration logic.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/extractor/test_run.py
"""Tests for the extractor run: a single (or retried-once) Anthropic tool-use call
per document, with evidence validation gating every insert. anthropic.Anthropic and
evidence.validate_evidence are both mocked -- this suite never calls the real
Anthropic API and never depends on evidence.py's real fuzzy-matching logic (that is
covered separately in test_evidence.py)."""
import pytest

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.extractor.run import extract_requirements
from opportunity_tracker.models import Document, FetchMethod, SourceTier


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    connection.execute(
        "INSERT INTO scheme (name, funder, jurisdiction) VALUES ('S', 'F', 'AU')"
    )
    connection.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, 'UWA', 'AU', '[\"phd\"]', 2027, "
        "'https://uwa.edu.au/award')"
    )
    connection.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES "
        "('https://uwa.edu.au/rules', 1, 'http', 'abc123', 'placeholder', "
        "'2026-08-22T00:00:00', 'ok', 0)"
    )
    connection.commit()
    yield connection
    connection.close()


def _make_document(text_path: str) -> Document:
    return Document(
        id=1,
        url="https://uwa.edu.au/rules",
        source_tier=SourceTier.TIER_1,
        fetch_method=FetchMethod.HTTP,
        content_hash="abc123",
        text_path=text_path,
        retrieved_at="2026-08-22T00:00:00",
        fetch_status="ok",
        degraded=False,
    )


class _FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _good_response(requirements):
    return _FakeResponse(
        content=[_FakeToolUseBlock("record_requirements", {"requirements": requirements})]
    )


def _unparseable_response():
    return _FakeResponse(content=[_FakeTextBlock("sorry, I can't do that")])


def test_clean_single_requirement_response_inserts_one_row(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text(
        "The research project must be at least 25 percent of a full time "
        "equivalent annual enrolment.",
        encoding="utf-8",
    )
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _good_response(
        [
            {
                "kind": "research_project_fraction",
                "operator": ">=",
                "value": "0.25",
                "unit": "fraction",
                "raw_text": "at least 25 percent of a full time equivalent annual enrolment",
                "evidence": "at least 25 percent of a full time equivalent annual enrolment",
                "confidence": 0.95,
            }
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "opportunity_tracker.extractor.evidence.validate_evidence", return_value=True
    )

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert extraction_failed is False
    assert len(requirements) == 1
    assert requirements[0].kind.value == "research_project_fraction"
    fake_client.messages.create.assert_called_once()

    row = conn.execute("SELECT * FROM requirement").fetchone()
    assert row["kind"] == "research_project_fraction"
    assert row["value"] == "0.25"


def test_evidence_validation_failure_produces_zero_rows_no_crash(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Some document text about scholarships.", encoding="utf-8")
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _good_response(
        [
            {
                "kind": "deadline",
                "operator": None,
                "value": "2027-03-15",
                "unit": None,
                "raw_text": "applications close 15 March 2027",
                "evidence": "a completely fabricated evidence string not in the document",
                "confidence": 0.4,
            }
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "opportunity_tracker.extractor.evidence.validate_evidence", return_value=False
    )

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert extraction_failed is False
    assert requirements == []
    row = conn.execute("SELECT COUNT(*) AS n FROM requirement").fetchone()
    assert row["n"] == 0


def test_unparseable_first_response_then_retry_succeeds(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Minimum IELTS overall band score of 6.5.", encoding="utf-8")
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        _unparseable_response(),
        _good_response(
            [
                {
                    "kind": "english_test",
                    "operator": ">=",
                    "value": "6.5",
                    "unit": "IELTS band",
                    "raw_text": "Minimum IELTS overall band score of 6.5.",
                    "evidence": "Minimum IELTS overall band score of 6.5.",
                    "confidence": 0.9,
                }
            ]
        ),
    ]
    mocker.patch("anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "opportunity_tracker.extractor.evidence.validate_evidence", return_value=True
    )

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert extraction_failed is False
    assert len(requirements) == 1
    assert fake_client.messages.create.call_count == 2


def test_both_calls_unparseable_returns_extraction_failed(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Some document text.", encoding="utf-8")
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        _unparseable_response(),
        _unparseable_response(),
    ]
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert requirements == []
    assert extraction_failed is True
    assert fake_client.messages.create.call_count == 2


def test_extract_requirements_raw_returns_validated_candidate_dicts_no_db(mocker):
    document_text = "Minimum IELTS overall band score of 6.5."
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _good_response(
        [
            {
                "kind": "english_test",
                "operator": ">=",
                "value": "6.5",
                "unit": "IELTS band",
                "raw_text": "Minimum IELTS overall band score of 6.5.",
                "evidence": "Minimum IELTS overall band score of 6.5.",
                "confidence": 0.9,
            }
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    from opportunity_tracker.extractor.run import extract_requirements_raw

    results = extract_requirements_raw(document_text, api_key="sk-test")

    assert results == [
        {
            "kind": "english_test",
            "operator": ">=",
            "value": "6.5",
            "unit": "IELTS band",
            "raw_text": "Minimum IELTS overall band score of 6.5.",
            "evidence": "Minimum IELTS overall band score of 6.5.",
            "confidence": 0.9,
        }
    ]
    fake_client.messages.create.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/extractor/test_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'opportunity_tracker.extractor.run'`

- [ ] **Step 3: Write `src/opportunity_tracker/extractor/run.py`**

```python
"""Extractor run: one document -> requirement rows via a single (or, on unparseable
output, retried-once) Anthropic tool-use call. See spec section 6.2, section 8.

The extractor never sees the operator's profile (that separation lives in
prompts.py) and every candidate requirement's evidence is mechanically validated
against the stored document text (evidence.py) before it is ever written to the
`requirement` table -- a requirement whose evidence does not fuzzy-match the
document is silently rejected, never inserted, never surfaced as a false positive.
An enum violation on `kind` (defensive -- the JSON schema should already prevent
this) is logged to `unclassified_rule` instead of being inserted as a requirement.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import anthropic

from opportunity_tracker.extractor import evidence
from opportunity_tracker.extractor.prompts import build_extraction_prompt
from opportunity_tracker.extractor.schema import REQUIREMENT_JSON_SCHEMA
from opportunity_tracker.models import Document, Requirement, RequirementKind

_MODEL = "claude-opus-5"
_MAX_TOKENS = 4096
_TOOL_NAME = "record_requirements"
_RETRY_INSTRUCTION = (
    "\n\nYour previous response could not be parsed as a valid tool call. You MUST "
    "call the record_requirements tool exactly once with a single JSON object "
    "matching its schema. Do not respond with plain text."
)


def _call_model(client: "anthropic.Anthropic", prompt: str) -> list | None:
    """Call the model once, forcing the record_requirements tool.

    Returns the parsed `requirements` list, or None if the response could not
    be parsed as a well-formed tool call (no matching tool_use block, or its
    `input` is not a dict with a `requirements` list).
    """
    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        tools=[
            {
                "name": _TOOL_NAME,
                "description": "Record every requirement extracted from the document.",
                "input_schema": REQUIREMENT_JSON_SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )

    for block in getattr(response, "content", []):
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) != _TOOL_NAME:
            continue
        tool_input = getattr(block, "input", None)
        if not isinstance(tool_input, dict):
            continue
        requirements = tool_input.get("requirements")
        if not isinstance(requirements, list):
            continue
        return requirements

    return None


def _call_with_retry(client: "anthropic.Anthropic", prompt: str) -> list | None:
    """Call the model once; on an unparseable response, retry once with a stricter
    instruction (spec §8). Returns None only if both calls fail to parse. Shared by
    `extract_requirements` and `extract_requirements_raw` so the retry policy lives in
    exactly one place."""
    try:
        raw_requirements = _call_model(client, prompt)
    except Exception:
        raw_requirements = None

    if raw_requirements is None:
        try:
            raw_requirements = _call_model(client, prompt + _RETRY_INSTRUCTION)
        except Exception:
            raw_requirements = None

    return raw_requirements


def extract_requirements_raw(document_text: str, api_key: str) -> list[dict]:
    """DB-free half of extraction: prompt-building, the (possibly retried) API call, and
    evidence validation -- returning validated candidate dicts, never `Requirement` rows.

    Used directly by scripts/eval_gold_set.py (Task 27), which has no database and no
    award/document rows to write against -- only raw document text and hand-annotated
    ground truth. Does not check `kind` against the closed RequirementKind enum -- that
    check only matters once a candidate needs a real `requirement` row, which is
    `extract_requirements`'s job, not this function's. Returns an empty list both when the
    model call fails to parse after retry, and when every candidate fails evidence
    validation -- the gold-set harness only measures recall against what was extracted, so
    unlike `extract_requirements` it has no need for an `extraction_failed` flag.
    """
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_extraction_prompt(document_text)
    raw_requirements = _call_with_retry(client, prompt)
    if raw_requirements is None:
        return []

    validated: list[dict] = []
    for candidate in raw_requirements:
        if not isinstance(candidate, dict):
            continue
        if not evidence.validate_evidence(candidate.get("evidence", ""), document_text):
            continue
        validated.append(candidate)
    return validated


def extract_requirements(
    document: Document,
    award_id: int,
    conn: sqlite3.Connection,
    api_key: str,
) -> tuple[list[Requirement], bool]:
    """Extract requirements from `document` and insert them (or log them to
    `unclassified_rule`) against `award_id`.

    Returns (requirements, extraction_failed). `extraction_failed` is True only
    when the model's tool-call output could not be parsed even after one retry
    with a stricter instruction (spec section 8) -- the caller is responsible
    for flagging the award UNKNOWN-GATED in that case; this function never
    silently swallows the failure, it reports it via the return value.
    """
    with open(document.text_path, "r", encoding="utf-8") as f:
        document_text = f.read()

    prompt = build_extraction_prompt(document_text)
    client = anthropic.Anthropic(api_key=api_key)
    raw_requirements = _call_with_retry(client, prompt)

    if raw_requirements is None:
        return [], True

    inserted: list[Requirement] = []
    extracted_at = datetime.now(timezone.utc).isoformat()
    valid_kinds = {k.value for k in RequirementKind}

    for candidate in raw_requirements:
        if not isinstance(candidate, dict):
            continue

        raw_text = candidate.get("raw_text", "")
        evidence_text = candidate.get("evidence", "")
        kind_value = candidate.get("kind")

        if not evidence.validate_evidence(evidence_text, document_text):
            continue

        if kind_value not in valid_kinds:
            conn.execute(
                "INSERT INTO unclassified_rule (document_id, raw_text, logged_at, "
                "reviewed) VALUES (?, ?, ?, 0)",
                (document.id, raw_text, extracted_at),
            )
            conn.commit()
            continue

        cursor = conn.execute(
            "INSERT INTO requirement (award_id, document_id, kind, operator, "
            "value, unit, raw_text, evidence, confidence, extracted_at, "
            "human_verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                award_id,
                document.id,
                kind_value,
                candidate.get("operator"),
                candidate.get("value"),
                candidate.get("unit"),
                raw_text,
                evidence_text,
                candidate.get("confidence"),
                extracted_at,
            ),
        )
        conn.commit()

        inserted.append(
            Requirement(
                id=cursor.lastrowid,
                award_id=award_id,
                document_id=document.id,
                kind=RequirementKind(kind_value),
                operator=candidate.get("operator"),
                value=candidate.get("value"),
                unit=candidate.get("unit"),
                raw_text=raw_text,
                evidence=evidence_text,
                confidence=candidate.get("confidence"),
                extracted_at=extracted_at,
                human_verified=False,
            )
        )

    return inserted, False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/extractor/test_run.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/extractor/run.py tests/unit/extractor/test_run.py
git commit -m "feat: extractor run -- single LLM call, retry-once, evidence-gated inserts"
```

---

### Task 19: Digger (`digger/run.py`)

**Files:**
- Create: `src/opportunity_tracker/digger/__init__.py`
- Create: `tests/unit/digger/__init__.py` (empty — makes `tests/unit/digger` a proper
  package; `digger/run.py`'s test module shares its basename `test_run.py` with both
  `fetcher/pipeline.py`'s and `discovery/run.py`'s test modules, so this is required, not
  optional, matching the convention already established in Parts C and D)
- Edit: `src/opportunity_tracker/discovery/websearch.py` (append `search_domain` — an
  addition to Task 14's existing file, `search_institution` and `build_query` untouched)
- Edit: `tests/unit/discovery/test_websearch.py` (append a test for `search_domain`, and add
  it to the existing top-of-file import line)
- Create: `src/opportunity_tracker/digger/run.py`
- Test: `tests/unit/digger/test_run.py`

**Interfaces:**
- Consumes:
  - `opportunity_tracker.models.RequirementKind`, `Requirement`, `Document` (Task 2).
  - `fetcher.pipeline.fetch(url: str, conn: sqlite3.Connection, declared_tier: int | None =
    None) -> Document` (Task 13) — module-qualified, as `pipeline.fetch(...)`.
  - `discovery.websearch.search_domain(domain: str, query: str, api_key: str, max_uses: int
    = 1) -> list[dict]` (Task 14's file, addition made in this task) — module-qualified, as
    `websearch.search_domain(...)`.
  - `extractor.evidence.validate_evidence(evidence: str, document_text: str, threshold:
    float = 0.85) -> bool` (Task 17, this file) — module-qualified, as
    `evidence.validate_evidence(...)`.
  - The third-party `anthropic.Anthropic` client class.
  - `opportunity_tracker.db` table `requirement` (Task 4) — accessed via raw SQL.
- Produces: `dig(award_id: int, missing_kind: RequirementKind, registrable_domain: str,
  conn: sqlite3.Connection, api_key: str) -> Requirement | None` — the entry point a later
  Milestone-2 orchestration task calls once per award-per-missing-required-field, per the
  budget in spec §6.3 (never exceeding 5 total fetches). Returns `None` on a confirmed
  not-found within budget; the caller records that as data (not a crash).

**Testing note:** `anthropic.Anthropic`, `fetcher.pipeline.fetch`, and
`discovery.websearch.search_domain` are all mocked via `mocker.patch` in every digger test
below — this suite never calls a real search API, fetches over a real network, or calls a
real LLM.

- [ ] **Step 1: Write the failing tests**

First, append a test for the new `search_domain` function to the existing
`tests/unit/discovery/test_websearch.py`. Change its import line from:

```python
from opportunity_tracker.discovery.websearch import build_query, search_institution
```

to:

```python
from opportunity_tracker.discovery.websearch import build_query, search_domain, search_institution
```

Then append this test function at the end of the file (it reuses `_FakeResultItem`,
`_FakeContentBlock`, `_FakeResponse` already defined earlier in that file by Task 14):

```python
def test_search_domain_scopes_tools_to_bare_domain_and_returns_results(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(
        content=[
            _FakeContentBlock(
                "web_search_tool_result",
                [_FakeResultItem("https://uwa.edu.au/rules/deadline", "Deadline")],
            )
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    results = search_domain("uwa.edu.au", "application deadline", api_key="sk-test", max_uses=1)

    assert results == [{"url": "https://uwa.edu.au/rules/deadline", "title": "Deadline"}]
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 1,
            "allowed_domains": ["uwa.edu.au"],
        }
    ]
    assert kwargs["messages"][0]["content"] == "application deadline"
```

Now the new digger test file:

```python
# tests/unit/digger/test_run.py
"""Tests for the bounded digger. websearch.search_domain, fetcher.pipeline.fetch, and
anthropic.Anthropic are all mocked -- this suite never calls a real search API,
fetches over a real network, or calls a real LLM."""
from opportunity_tracker.digger.run import dig
from opportunity_tracker.models import Document, FetchMethod, RequirementKind, SourceTier


class _FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _found_response(**fields):
    payload = {
        "found": True,
        "operator": None,
        "value": None,
        "unit": None,
        "raw_text": None,
        "evidence": None,
        "confidence": None,
    }
    payload.update(fields)
    return _FakeResponse(content=[_FakeToolUseBlock("record_requirement", payload)])


def _not_found_response():
    return _FakeResponse(
        content=[
            _FakeToolUseBlock(
                "record_requirement",
                {
                    "found": False,
                    "operator": None,
                    "value": None,
                    "unit": None,
                    "raw_text": None,
                    "evidence": None,
                    "confidence": None,
                },
            )
        ]
    )


def _make_document(doc_id, text_path, url):
    return Document(
        id=doc_id,
        url=url,
        source_tier=SourceTier.TIER_1,
        fetch_method=FetchMethod.HTTP,
        content_hash=f"hash-{doc_id}",
        text_path=str(text_path),
        retrieved_at="2026-08-22T00:00:00",
        fetch_status="ok",
        degraded=False,
    )


def test_dig_finds_field_via_web_search_uses_one_fetch(mocker, tmp_path):
    doc_text = "The application deadline for the 2027 intake is 15 March 2027."
    doc_path = tmp_path / "found.txt"
    doc_path.write_text(doc_text, encoding="utf-8")

    mocker.patch(
        "opportunity_tracker.digger.run.websearch.search_domain",
        return_value=[{"url": "https://uwa.edu.au/found", "title": "Deadlines"}],
    )
    fetch_mock = mocker.patch(
        "opportunity_tracker.digger.run.pipeline.fetch",
        return_value=_make_document(1, doc_path, "https://uwa.edu.au/found"),
    )
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _found_response(
        operator="=",
        value="2027-03-15",
        unit=None,
        raw_text=doc_text,
        evidence=doc_text,
        confidence=0.9,
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    conn = mocker.MagicMock()
    conn.execute.return_value.lastrowid = 42

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.DEADLINE,
        registrable_domain="uwa.edu.au",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is not None
    assert requirement.kind == RequirementKind.DEADLINE
    assert requirement.value == "2027-03-15"
    fetch_mock.assert_called_once_with("https://uwa.edu.au/found", conn)
    fake_client.messages.create.assert_called_once()


def test_dig_falls_back_to_crawl_when_search_finds_nothing(mocker, tmp_path):
    homepage_text = (
        '<html><body><a href="https://uwa.edu.au/requirements">Requirements</a></body></html>'
    )
    homepage_path = tmp_path / "homepage.txt"
    homepage_path.write_text(homepage_text, encoding="utf-8")

    target_text = "Minimum overall IELTS band score of 6.5 required, no band below 6.0."
    target_path = tmp_path / "requirements.txt"
    target_path.write_text(target_text, encoding="utf-8")

    mocker.patch("opportunity_tracker.digger.run.websearch.search_domain", return_value=[])

    homepage_doc = _make_document(1, homepage_path, "https://uwa.edu.au/")
    target_doc = _make_document(2, target_path, "https://uwa.edu.au/requirements")

    fetch_mock = mocker.patch(
        "opportunity_tracker.digger.run.pipeline.fetch",
        side_effect=[homepage_doc, target_doc],
    )

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        _not_found_response(),
        _found_response(
            operator=">=",
            value="6.5",
            unit="IELTS band",
            raw_text=target_text,
            evidence=target_text,
            confidence=0.92,
        ),
    ]
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    conn = mocker.MagicMock()
    conn.execute.return_value.lastrowid = 99

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.ENGLISH_TEST,
        registrable_domain="uwa.edu.au",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is not None
    assert requirement.value == "6.5"
    assert fetch_mock.call_count == 2
    fetch_mock.assert_any_call("https://uwa.edu.au/", conn)
    fetch_mock.assert_any_call("https://uwa.edu.au/requirements", conn)


def test_dig_returns_none_when_budget_exhausted(mocker, tmp_path):
    links_html = "".join(
        f'<a href="https://uwa.edu.au/page{i}">Page {i}</a>' for i in range(10)
    )
    homepage_text = f"<html><body>{links_html}</body></html>"
    homepage_path = tmp_path / "homepage.txt"
    homepage_path.write_text(homepage_text, encoding="utf-8")

    subpage_text = "Nothing relevant on this page."
    subpage_path = tmp_path / "subpage.txt"
    subpage_path.write_text(subpage_text, encoding="utf-8")

    mocker.patch("opportunity_tracker.digger.run.websearch.search_domain", return_value=[])

    homepage_doc = _make_document(1, homepage_path, "https://uwa.edu.au/")
    subpage_docs = [
        _make_document(i + 2, subpage_path, f"https://uwa.edu.au/page{i}") for i in range(10)
    ]
    fetch_mock = mocker.patch(
        "opportunity_tracker.digger.run.pipeline.fetch",
        side_effect=[homepage_doc] + subpage_docs,
    )

    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _not_found_response()
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    conn = mocker.MagicMock()

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.MIN_GRADE,
        registrable_domain="uwa.edu.au",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is None
    assert fetch_mock.call_count == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/discovery/test_websearch.py tests/unit/digger/test_run.py -v`
Expected: FAIL — the new `search_domain` test fails with `ImportError: cannot import name
'search_domain'`; the digger tests fail with `ModuleNotFoundError: No module named
'opportunity_tracker.digger'`

- [ ] **Step 3: Append `search_domain` to `src/opportunity_tracker/discovery/websearch.py`**

Append this function to the end of the existing file (do not touch `search_institution` or
`build_query` above it — this reuses the module's existing `_WEB_SEARCH_TOOL_TYPE`, `_MODEL`,
`_MAX_TOKENS` constants):

```python
def search_domain(domain: str, query: str, api_key: str, max_uses: int = 1) -> list[dict]:
    """Run one domain-scoped Claude web_search against a bare registrable domain.

    Sibling to search_institution, for a caller (the digger) that has a
    registrable domain and a free-text query but no Institution/Filter pair to
    build one from via build_query(). Same URL/title-only, deduplicated,
    error-degrades-to-[] contract as search_institution.
    """
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": query}],
        tools=[
            {
                "type": _WEB_SEARCH_TOOL_TYPE,
                "name": "web_search",
                "max_uses": max_uses,
                "allowed_domains": [domain],
            }
        ],
    )

    results: list[dict] = []
    seen_urls: set[str] = set()

    for block in response.content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        content = block.content
        if not isinstance(content, list):
            continue
        for item in content:
            url = getattr(item, "url", None)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = getattr(item, "title", None) or ""
            results.append({"url": url, "title": title})

    return results
```

- [ ] **Step 3b: Write `src/opportunity_tracker/digger/__init__.py`**

```python
```

(empty — marks `digger` as a package)

- [ ] **Step 3c: Write `tests/unit/digger/__init__.py`**

```python
```

(empty)

- [ ] **Step 3d: Write `src/opportunity_tracker/digger/run.py`**

```python
"""Bounded gap-filler sub-agent. Per award with a NULL on a required field: a
bounded budget of 5 fetches, depth 2, same registrable domain, one target field
per invocation (spec section 6.3). Strategy, in order: (1) one domain-scoped
web_search targeting the missing field; (2) if that fails, a bounded
fetch-and-follow crawl starting from the registrable domain's homepage. Routes
every fetch through fetcher.pipeline.fetch, so every dig is cached, logged and
replayable, exactly like every other fetch in the system. Returns None on a
confirmed not-found within budget -- never raises, never silently loops forever.

Milestone-2 sequencing note (spec section 6.3, section 10): this module ships
code-complete now; its keep/delete decision is deferred until Milestone 1's
gold-set recall baseline exists. Nothing in this module's own contract depends
on that sequencing -- dig() is a pure bounded function regardless of when its
caller starts invoking it for real.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import anthropic

from opportunity_tracker.discovery import websearch
from opportunity_tracker.extractor import evidence
from opportunity_tracker.fetcher import pipeline
from opportunity_tracker.models import Document, Requirement, RequirementKind

_MODEL = "claude-opus-5"
_MAX_TOKENS = 1024
_MAX_FETCHES = 5
_MAX_DEPTH = 2

_HREF_PATTERN = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

_SINGLE_FIELD_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "found": {
            "type": "boolean",
            "description": "Whether the document states the target requirement.",
        },
        "operator": {"type": ["string", "null"]},
        "value": {"type": ["string", "null"]},
        "unit": {"type": ["string", "null"]},
        "raw_text": {"type": ["string", "null"]},
        "evidence": {"type": ["string", "null"]},
        "confidence": {"type": ["number", "null"]},
    },
    "required": ["found"],
}


def _build_single_field_prompt(missing_kind: RequirementKind, document_text: str) -> str:
    return (
        f"You are looking for exactly one specific requirement in the document "
        f"text below: the value for '{missing_kind.value}'. Read the document and "
        f"determine whether it states this requirement.\n\n"
        f"If the document states this requirement, call the record_requirement "
        f"tool with found=true and the operator/value/unit you found (null for "
        f"any of those not stated), the exact verbatim clause as raw_text, a "
        f"verbatim quotation from the document as evidence, and a confidence "
        f"score between 0 and 1.\n\n"
        f"If the document does NOT state this requirement, call the "
        f"record_requirement tool with found=false and every other field null.\n\n"
        f"Never invent a value that is not written in the document. The evidence "
        f"you quote must be an exact, verbatim substring of the document text "
        f"below.\n\n"
        f"Document text:\n---\n{document_text}\n---\n"
    )


def _extract_single_field(
    document_text: str,
    missing_kind: RequirementKind,
    api_key: str,
) -> dict | None:
    """Run a targeted, single-field version of the extractor prompt against
    `document_text`, looking only for `missing_kind`. Returns a candidate
    requirement dict (operator/value/unit/raw_text/evidence/confidence) if the
    model reports finding it, or None if it reports not finding it, or if its
    tool-call output could not be parsed.
    """
    prompt = _build_single_field_prompt(missing_kind, document_text)
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        tools=[
            {
                "name": "record_requirement",
                "description": "Record whether the target requirement was found.",
                "input_schema": _SINGLE_FIELD_SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "record_requirement"},
    )

    for block in getattr(response, "content", []):
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) != "record_requirement":
            continue
        tool_input = getattr(block, "input", None)
        if not isinstance(tool_input, dict):
            continue
        if not tool_input.get("found"):
            return None
        return {
            "operator": tool_input.get("operator"),
            "value": tool_input.get("value"),
            "unit": tool_input.get("unit"),
            "raw_text": tool_input.get("raw_text", ""),
            "evidence": tool_input.get("evidence", ""),
            "confidence": tool_input.get("confidence"),
        }

    return None


def _extract_same_domain_links(
    document_text: str, base_url: str, registrable_domain: str
) -> list[str]:
    """Extract same-domain absolute links from `document_text` relative to
    `base_url`. Links outside `registrable_domain`, and non-http(s) links
    (mailto:, tel:, javascript:, fragment-only anchors), are excluded -- the
    digger's crawl is bounded to a single registrable domain (spec section 6.3).
    """
    links: list[str] = []
    for match in _HREF_PATTERN.finditer(document_text):
        href = match.group(1)
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if not parsed.netloc.endswith(registrable_domain):
            continue
        links.append(absolute)
    return links


def _try_extract_and_insert(
    document: Document,
    award_id: int,
    missing_kind: RequirementKind,
    conn: sqlite3.Connection,
    api_key: str,
) -> Requirement | None:
    if document.text_path is None:
        return None

    with open(document.text_path, "r", encoding="utf-8") as f:
        document_text = f.read()

    candidate = _extract_single_field(document_text, missing_kind, api_key)
    if candidate is None:
        return None

    if not evidence.validate_evidence(candidate["evidence"], document_text):
        return None

    extracted_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO requirement (award_id, document_id, kind, operator, value, "
        "unit, raw_text, evidence, confidence, extracted_at, human_verified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (
            award_id,
            document.id,
            missing_kind.value,
            candidate["operator"],
            candidate["value"],
            candidate["unit"],
            candidate["raw_text"],
            candidate["evidence"],
            candidate["confidence"],
            extracted_at,
        ),
    )
    conn.commit()

    return Requirement(
        id=cursor.lastrowid,
        award_id=award_id,
        document_id=document.id,
        kind=missing_kind,
        operator=candidate["operator"],
        value=candidate["value"],
        unit=candidate["unit"],
        raw_text=candidate["raw_text"],
        evidence=candidate["evidence"],
        confidence=candidate["confidence"],
        extracted_at=extracted_at,
        human_verified=False,
    )


def dig(
    award_id: int,
    missing_kind: RequirementKind,
    registrable_domain: str,
    conn: sqlite3.Connection,
    api_key: str,
) -> Requirement | None:
    """Bounded gap-filler for one award's one missing required field.

    Strategy, in order (spec section 6.3):
    1. One domain-scoped web_search (websearch.search_domain) targeting
       `missing_kind`, scoped to `registrable_domain`. If it returns a
       candidate URL, fetch it and run a targeted single-field extraction.
    2. If web-search finds nothing (or the extraction on its top result comes
       up empty), fall back to fetching `registrable_domain`'s homepage and
       following links up to `_MAX_DEPTH` deep, same domain only, stopping the
       moment the field is found or the total fetch budget (`_MAX_FETCHES`,
       shared across both strategies) is exhausted.

    Never issues more than `_MAX_FETCHES` calls to fetcher.pipeline.fetch in
    total. Returns None -- a confirmed not-found, never an exception -- if the
    budget is exhausted with nothing found.
    """
    fetches_used = 0
    query = f"{missing_kind.value.replace('_', ' ')} requirement"

    try:
        search_results = websearch.search_domain(registrable_domain, query, api_key, max_uses=1)
    except Exception:
        search_results = []

    if search_results:
        url = search_results[0]["url"]
        document = pipeline.fetch(url, conn)
        fetches_used += 1
        requirement = _try_extract_and_insert(document, award_id, missing_kind, conn, api_key)
        if requirement is not None:
            return requirement

    # Fallback: bounded fetch-and-follow crawl of registrable_domain, same
    # domain only, up to _MAX_DEPTH links deep, sharing the same total
    # _MAX_FETCHES budget as the web-search step above.
    homepage_url = f"https://{registrable_domain}/"
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(homepage_url, 0)]

    while queue and fetches_used < _MAX_FETCHES:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        document = pipeline.fetch(url, conn)
        fetches_used += 1

        requirement = _try_extract_and_insert(document, award_id, missing_kind, conn, api_key)
        if requirement is not None:
            return requirement

        if depth < _MAX_DEPTH and document.text_path is not None:
            with open(document.text_path, "r", encoding="utf-8") as f:
                document_text = f.read()
            for link_url in _extract_same_domain_links(document_text, url, registrable_domain):
                if link_url not in visited:
                    queue.append((link_url, depth + 1))

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/discovery/test_websearch.py tests/unit/digger/test_run.py -v`
Expected: PASS (5 tests for `test_websearch.py`, 3 tests for `test_run.py`)

- [ ] **Step 5: Commit**

```bash
git add src/opportunity_tracker/discovery/websearch.py \
        tests/unit/discovery/test_websearch.py \
        src/opportunity_tracker/digger/__init__.py \
        tests/unit/digger/__init__.py \
        src/opportunity_tracker/digger/run.py \
        tests/unit/digger/test_run.py
git commit -m "feat: bounded digger -- web-search-first with fetch-and-follow fallback"
```
