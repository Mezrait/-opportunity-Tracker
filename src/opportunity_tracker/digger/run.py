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
from opportunity_tracker.models import Document, Requirement, RequirementKind, SourceTier

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
    model reports finding it, or None if it reports not finding it, if its
    tool-call output could not be parsed, or if the API call itself failed
    (rate limit, timeout, network blip, etc.) -- dig() must never raise, so a
    transient LLM failure here is treated the same as "field not found on
    this page" rather than propagated.
    """
    prompt = _build_single_field_prompt(missing_kind, document_text)
    client = anthropic.Anthropic(api_key=api_key)

    try:
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
    except Exception:
        return None

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
        if not (
            parsed.netloc == registrable_domain
            or parsed.netloc.endswith("." + registrable_domain)
        ):
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

    if document.source_tier != SourceTier.TIER_1:
        # Principle 2 (spec §61-62): only Tier 1 sources write to fields. The digger's
        # crawl can wander onto a Tier 2/3 page (an aggregator mirror, a student blog
        # linked from a faculty page); whatever it says there is logged for review, never
        # written into `requirement` as if it were verified primary-source data. Logged,
        # not dropped -- the operator sees it via `optrack review-unclassified`.
        conn.execute(
            "INSERT INTO unclassified_rule (document_id, raw_text, logged_at, reviewed) "
            "VALUES (?, ?, ?, 0)",
            (
                document.id,
                f"[tier-{document.source_tier.value} source, not written to requirement] "
                f"{missing_kind.value}: {candidate['raw_text']}",
                extracted_at,
            ),
        )
        conn.commit()
        return None

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
