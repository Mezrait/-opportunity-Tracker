"""Tests for the fuzzy evidence-span validator. Pure stdlib difflib logic -- no
model, no network, no mocking needed. Mechanical, no model involved (spec section
8): non-matching evidence must be rejected."""
import random
import time

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


# --- Whole-branch review C4: rejection is the common path and must be fast -----------------

TRUE_SPAN = (
    "The research project component of the PhD must constitute at least 25 percent "
    "of a full time equivalent annual enrolment."
)


def _large_document(char_target: int = 50_000) -> str:
    """A realistic ~50KB scholarship-page-shaped document with TRUE_SPAN buried in it.

    Deliberately built from the same vocabulary as the spans below, so the fabricated and
    near-miss spans are genuinely hard cases (high character overlap, plausible wording)
    rather than trivially-distinguishable noise.
    """
    rng = random.Random(20260822)
    vocabulary = (
        "eligible applicants must have completed an honours degree with a minimum "
        "weighted average mark and submit certified transcripts scholarship research "
        "project component enrolment candidature faculty stipend allowance tuition fee "
        "application closing date international domestic supervisor agreement thesis "
        "percent equivalent annual full time constitute at least of the"
    ).split()
    filler = " ".join(rng.choice(vocabulary) for _ in range(char_target // 5))
    midpoint = len(filler) // 2
    return filler[:midpoint] + " " + TRUE_SPAN + " " + filler[midpoint:]


def test_large_document_rejections_are_fast_and_still_correct():
    document = _large_document()
    assert len(document) >= 50_000

    near_miss = (
        "The research project component of the MPhil must constitute at least 90 percent "
        "of a completely different kind of annual enrolment quota altogether."
    )
    fabricated = (
        "Scholarships are available to students from any country with absolutely no "
        "restrictions whatsoever on prior awards or previously held scholarships."
    )

    start = time.perf_counter()
    assert validate_evidence(near_miss, document) is False
    assert validate_evidence(fabricated, document) is False
    elapsed = time.perf_counter() - start

    # Before this fix, each of these two rejections took ~3 minutes on a document this
    # size (a fresh SequenceMatcher per character offset, three window sizes). The fixed
    # implementation measures ~0.1-0.2s for both in isolation, but this threshold is
    # generous (15s, ~100x that) rather than tight, because wall-clock assertions are
    # sensitive to system load when run as part of the full suite (241 other tests,
    # some spinning up Playwright/SQLite) rather than in isolation. The regression this
    # guards against is orders of magnitude (minutes, not seconds), so a loose threshold
    # still catches it cleanly without being flaky under normal CI/full-suite variance.
    assert elapsed < 15.0, f"two rejections took {elapsed:.2f}s on a ~50KB document"


def test_large_document_still_accepts_an_exact_span():
    document = _large_document()
    assert validate_evidence(TRUE_SPAN, document) is True


def test_large_document_still_accepts_a_span_with_transcription_noise():
    # Same span, with a handful of characters mangled the way extraction noise mangles
    # them -- still well above the 0.85 threshold, and must still be accepted.
    document = _large_document()
    noisy = TRUE_SPAN.replace("PhD", "PhO").replace("25 percent", "25 percerit")
    assert noisy not in document  # not the trivial exact-substring fast path
    assert validate_evidence(noisy, document) is True
