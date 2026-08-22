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
