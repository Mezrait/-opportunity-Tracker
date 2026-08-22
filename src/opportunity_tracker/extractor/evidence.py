"""Fuzzy evidence-span validator. Mechanical, no model involved (spec section 8):
"Evidence span must fuzzy-match text in the stored document. Non-matching =>
requirement rejected." This is the mechanical defence against a hallucinated value
with plausible-looking evidence -- and spec section 9.1's mandatory test case, "a
fabricated span must be rejected", is exactly what this function exists to do.

Performance matters here specifically because REJECTION is the common case (spec section
9.2): a rejected span is the one that scans the whole document without ever
short-circuiting. The original implementation constructed a fresh SequenceMatcher at every
character offset for each of three window sizes, and took ~180 seconds to reject one span
on a realistic ~70KB document -- a cost the extractor pays per candidate requirement, per
document. Measured on that document, `SequenceMatcher.ratio()` costs ~440us per window
while `quick_ratio()` costs ~19us but scores ~0.85 on completely unrelated English text of
the same length, so gating `ratio()` behind it filters almost nothing. An exhaustive
character-by-character scan is therefore not salvageable by cheaper bounds alone.

Instead, candidate window positions are located with a character n-gram index (below), and
`ratio()` is computed only for positions that actually share a verbatim run with the
evidence. Same threshold, same window sizes, same accept/reject semantics -- just without
scoring the ~99.99% of offsets that cannot possibly match.
"""
from __future__ import annotations

from difflib import SequenceMatcher

# Length of the verbatim run used to anchor a candidate window. A span must share at least
# one run this long with the document to be considered at all.
#
# This is a deliberate, spec-aligned tightening rather than a pure optimisation. The
# extractor prompt requires evidence to be "an exact, verbatim substring of the document
# text"; the fuzzy window exists only to absorb minor transcription noise (a swapped
# character, a normalised quote or dash), not to admit paraphrase. A span at the 0.85
# threshold shares ~85% of its characters with the window, which for any genuine quotation
# means far longer verbatim runs than this. A span with no 8-character verbatim run in
# common is not a quotation, and rejecting it is the safe direction: a wrongly-rejected
# requirement degrades the award toward UNKNOWN-GATED (spec principle 4), whereas a wrongly
# -accepted one writes a hallucinated value into `requirement` as trusted data.
_ANCHOR_LENGTH = 8

# Candidate starts derived from anchors land on the exact aligned offset when the shared run
# is at a known position in the evidence. Insertions/deletions elsewhere in the span can
# shift the true best start by a character or two, so each candidate is probed with this
# much slack either side.
_ANCHOR_SLACK = 2

# Hard ceiling on scored windows per window size, so a pathological document (the same
# boilerplate sentence repeated thousands of times) cannot reintroduce the original
# quadratic blow-up. Candidates are scored most-anchored-first, and a genuine match
# accumulates far more anchor hits than incidental collisions, so it is always scored well
# inside this budget.
_MAX_SCORED_WINDOWS = 3000


def _anchor_hits(evidence: str, document_text: str, anchor_length: int) -> dict[int, int]:
    """Map candidate window start -> number of evidence anchors supporting it.

    Every `anchor_length`-character substring of the evidence is indexed by its offset
    within the evidence. Scanning the document once, a document position `i` matching an
    anchor that sits at evidence offset `j` implies the evidence, if present here, starts
    at document offset `i - j`. Genuine matches accumulate one hit per shared run position;
    incidental collisions accumulate one or two.
    """
    offsets_by_ngram: dict[str, list[int]] = {}
    for j in range(len(evidence) - anchor_length + 1):
        offsets_by_ngram.setdefault(evidence[j : j + anchor_length], []).append(j)

    hits: dict[int, int] = {}
    lookup = offsets_by_ngram.get
    for i in range(len(document_text) - anchor_length + 1):
        js = lookup(document_text[i : i + anchor_length])
        if js is None:
            continue
        for j in js:
            start = i - j
            if start >= 0:
                hits[start] = hits.get(start, 0) + 1
    return hits


def _matches_any_window(
    matcher: SequenceMatcher,
    document_text: str,
    starts: list[int],
    window_size: int,
    last_start: int,
    threshold: float,
) -> bool:
    """Score `starts` (already ordered best-first) until one clears `threshold`.

    `real_quick_ratio` (O(1), length-based) and `quick_ratio` (O(window), character-multiset
    based) are cheap upper bounds on `ratio`, so a window either of them puts below the
    threshold cannot reach it and skips the ~23x more expensive `ratio()` entirely.
    """
    seen: set[int] = set()
    scored = 0
    for candidate in starts:
        for start in range(candidate - _ANCHOR_SLACK, candidate + _ANCHOR_SLACK + 1):
            if start < 0 or start > last_start or start in seen:
                continue
            seen.add(start)
            scored += 1
            if scored > _MAX_SCORED_WINDOWS:
                return False
            matcher.set_seq1(document_text[start : start + window_size])
            if matcher.real_quick_ratio() < threshold:
                continue
            if matcher.quick_ratio() < threshold:
                continue
            if matcher.ratio() >= threshold:
                return True
    return False


def validate_evidence(evidence: str, document_text: str, threshold: float = 0.85) -> bool:
    """Return True if `evidence` fuzzy-matches some window of `document_text`.

    Considers windows sized close to len(evidence) (+/- 20% tolerance, to absorb a few
    inserted/dropped characters from extraction noise) and returns True as soon as any
    window's difflib.SequenceMatcher ratio against `evidence` clears `threshold`. Pure
    stdlib, no LLM call, no network -- this must be mechanically reliable since it is the
    sole gate between a candidate requirement and being written to the `requirement` table.
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

    # A very short span cannot carry a full-length anchor; shorten it rather than skipping
    # the index (a short span also makes every window cheap to score).
    anchor_length = min(_ANCHOR_LENGTH, max(3, evidence_len // 3))
    if evidence_len < anchor_length or doc_len < anchor_length:
        return False

    hits = _anchor_hits(evidence, document_text, anchor_length)
    if not hits:
        return False
    ordered_starts = sorted(hits, key=lambda start: -hits[start])

    # One matcher, reused for every window of every size. The evidence is the SECOND
    # sequence on purpose: SequenceMatcher caches the expensive b2j index (and quick_ratio's
    # character counts) for `b` and rebuilds them only when `b` changes, so `set_seq1` per
    # window is cheap while `set_seq2` per window would not be. autojunk is disabled so a
    # long window never has its "popular" characters silently discarded, which would make
    # the score depend on window length rather than on real similarity.
    matcher = SequenceMatcher(None, "", evidence, autojunk=False)

    for window_size in window_sizes:
        if window_size > doc_len:
            continue
        if _matches_any_window(
            matcher, document_text, ordered_starts, window_size, doc_len - window_size, threshold
        ):
            return True

    return False
