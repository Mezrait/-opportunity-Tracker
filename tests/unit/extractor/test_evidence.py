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
