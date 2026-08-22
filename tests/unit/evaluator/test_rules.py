"""Table-driven tests for per-kind three-valued requirement evaluation. Pure logic, no
network, no LLM, no file I/O -- TDD per spec §9.1."""
from opportunity_tracker.models import Outcome, Profile, Requirement, RequirementKind
from opportunity_tracker.evaluator.rules import evaluate_requirement


def _make_requirement(
    kind: RequirementKind,
    operator: str | None = None,
    value: str | None = None,
) -> Requirement:
    return Requirement(
        id=1,
        award_id=1,
        document_id=1,
        kind=kind,
        operator=operator,
        value=value,
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


# --- Spec §9.1 mandatory cases, verbatim ---

def test_research_project_fraction_fail_when_held_below_required():
    # 0.25 required (operator ">=") vs profile holding 0.10 -> fail (the UWA case)
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value="0.25"
    )
    profile = _make_profile({"research_project_fraction_held": 0.10})
    assert evaluate_requirement(requirement, profile) == Outcome.FAIL


def test_english_test_required_profile_holds_none_is_unknown_not_fail():
    requirement = _make_requirement(RequirementKind.ENGLISH_TEST)
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_min_grade_is_always_unknown_even_with_profile_data():
    # GPA -> WAM conversion is never automated (spec §6.5) -- unknown regardless of what
    # the profile holds, even data that looks relevant.
    requirement = _make_requirement(RequirementKind.MIN_GRADE, operator=">=", value="75")
    profile = _make_profile(
        {
            "min_grade_held": "80",
            "wam_equivalent": "80",
            "research_project_fraction_held": 0.9,
        }
    )
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_none_requirement_is_always_unknown():
    # Principle 5: absence of a requirement is not evidence it does not exist.
    profile = _make_profile({"research_project_fraction_held": 0.9})
    assert evaluate_requirement(None, profile) == Outcome.UNKNOWN


# --- Supplementary coverage for the remaining kinds ---

def test_research_project_fraction_pass_when_held_meets_required():
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value="0.25"
    )
    profile = _make_profile({"research_project_fraction_held": 0.30})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_research_project_fraction_unknown_when_profile_attribute_missing():
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value="0.25"
    )
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_intake_year_mismatch_is_fail():
    # Per-requirement three-valued truth only; bucket.py (Task 23) is what translates an
    # intake-year FAIL specifically into UNKNOWN-GATED rather than LIKELY BLOCKED.
    requirement = _make_requirement(RequirementKind.INTAKE_YEAR, value="2027")
    profile = _make_profile({"target_intake_year": 2028})
    assert evaluate_requirement(requirement, profile) == Outcome.FAIL


def test_intake_year_match_is_pass():
    requirement = _make_requirement(RequirementKind.INTAKE_YEAR, value="2027")
    profile = _make_profile({"target_intake_year": 2027})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_intake_year_unknown_when_profile_missing_target():
    requirement = _make_requirement(RequirementKind.INTAKE_YEAR, value="2027")
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_deadline_pass_when_value_present():
    requirement = _make_requirement(RequirementKind.DEADLINE, value="2027-06-01")
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_deadline_unknown_when_value_absent():
    requirement = _make_requirement(RequirementKind.DEADLINE, value=None)
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_boolean_kind_thesis_required_matches_profile():
    requirement = _make_requirement(RequirementKind.THESIS_REQUIRED, value="true")
    profile = _make_profile({"thesis_required": "true"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_boolean_kind_thesis_required_mismatches_profile():
    requirement = _make_requirement(RequirementKind.THESIS_REQUIRED, value="true")
    profile = _make_profile({"thesis_required": "false"})
    assert evaluate_requirement(requirement, profile) == Outcome.FAIL


def test_boolean_kind_unknown_when_profile_attribute_missing():
    requirement = _make_requirement(RequirementKind.NATIONALITY, value="australian")
    profile = _make_profile({})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_informational_boolean_kind_uses_same_rule():
    requirement = _make_requirement(RequirementKind.RETURN_OBLIGATION, value="true")
    profile = _make_profile({"return_obligation": "true"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS
