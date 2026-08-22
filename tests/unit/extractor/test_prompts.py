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
