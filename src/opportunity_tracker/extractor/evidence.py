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
