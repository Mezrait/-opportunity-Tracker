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
