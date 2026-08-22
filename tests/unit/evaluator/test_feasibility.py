"""Pure lead-time estimation -- spec §6.4. No network, no LLM, no file I/O."""
from opportunity_tracker.models import Profile, Requirement, RequirementKind
from opportunity_tracker.evaluator.feasibility import estimate_lead_time_days


def _make_requirement(kind: RequirementKind) -> Requirement:
    return Requirement(
        id=1,
        award_id=1,
        document_id=1,
        kind=kind,
        operator=None,
        value=None,
        unit=None,
        raw_text="raw text",
        evidence="evidence span",
        confidence=0.9,
        extracted_at="2026-08-22T00:00:00+00:00",
        human_verified=False,
    )


def _make_profile(attributes: dict) -> Profile:
    return Profile(
        id=1, version=1, created_at="2026-08-22T00:00:00+00:00", attributes=attributes
    )


def test_missing_everything_sums_all_three_lead_times():
    profile = _make_profile({})
    requirements = [
        _make_requirement(RequirementKind.ENGLISH_TEST),
        _make_requirement(RequirementKind.SUPERVISOR_REQUIRED),
    ]
    # 21 (english test) + 35 (supervisor agreement midpoint, (28+42)/2) + 7 (transcripts)
    assert estimate_lead_time_days(profile, requirements) == 21 + 35 + 7


def test_all_prerequisites_satisfied_is_zero():
    profile = _make_profile(
        {
            "english_test_result": {"test": "IELTS", "score": 7.0},
            "supervisor_confirmed": True,
            "has_transcripts": True,
        }
    )
    requirements = [
        _make_requirement(RequirementKind.ENGLISH_TEST),
        _make_requirement(RequirementKind.SUPERVISOR_REQUIRED),
    ]
    assert estimate_lead_time_days(profile, requirements) == 0


def test_missing_only_transcripts_is_seven():
    profile = _make_profile(
        {
            "english_test_result": {"test": "IELTS", "score": 7.0},
            "supervisor_confirmed": True,
            "has_transcripts": False,
        }
    )
    requirements = [
        _make_requirement(RequirementKind.ENGLISH_TEST),
        _make_requirement(RequirementKind.SUPERVISOR_REQUIRED),
    ]
    assert estimate_lead_time_days(profile, requirements) == 7


def test_no_relevant_requirement_kinds_ignores_english_and_supervisor_gaps():
    # transcripts is checked unconditionally; english/supervisor lead time is only added
    # when a requirement of that kind is actually present for the award.
    profile = _make_profile({"has_transcripts": True})
    requirements = [_make_requirement(RequirementKind.DEADLINE)]
    assert estimate_lead_time_days(profile, requirements) == 0
