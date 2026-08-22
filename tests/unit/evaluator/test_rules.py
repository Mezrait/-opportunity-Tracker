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


def test_boolean_kind_degree_level_matches_profile():
    # Proves DEGREE_LEVEL actually wires to a real "degree_level" profile attribute lookup
    # -- a typo here would silently strand this kind at permanent UNKNOWN with no test
    # catching it.
    requirement = _make_requirement(RequirementKind.DEGREE_LEVEL, value="phd")
    profile = _make_profile({"degree_level": "phd"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_boolean_kind_supervisor_required_matches_profile():
    requirement = _make_requirement(RequirementKind.SUPERVISOR_REQUIRED, value="true")
    profile = _make_profile({"supervisor_required": "true"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_boolean_kind_prior_scholarship_exclusion_matches_profile():
    requirement = _make_requirement(
        RequirementKind.PRIOR_SCHOLARSHIP_EXCLUSION, value="true"
    )
    profile = _make_profile({"prior_scholarship_exclusion": "true"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_boolean_kind_funding_component_matches_profile():
    requirement = _make_requirement(RequirementKind.FUNDING_COMPONENT, value="stipend")
    profile = _make_profile({"funding_component": "stipend"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


# --- Fix: RESEARCH_PROJECT_FRACTION float() conversion must degrade to UNKNOWN, not raise ---

def test_research_project_fraction_unknown_when_requirement_value_non_numeric():
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value="not-a-number"
    )
    profile = _make_profile({"research_project_fraction_held": 0.30})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_research_project_fraction_unknown_when_requirement_value_is_none():
    requirement = _make_requirement(
        RequirementKind.RESEARCH_PROJECT_FRACTION, operator=">=", value=None
    )
    profile = _make_profile({"research_project_fraction_held": 0.30})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


# --- Design decision: ENGLISH_TEST never manufactures a PASS -------------------------------
# Holding SOME english_test_result used to return PASS regardless of the requirement's
# actual threshold -- the only rule that could manufacture a false PASS on a required kind,
# presenting an ineligible award as ACT_NOW. Same ruling as MIN_GRADE (spec §6.5): a
# comparison that cannot be made with confidence yields UNKNOWN, not a guess.

def test_english_test_is_unknown_even_when_the_profile_holds_a_result():
    requirement = _make_requirement(
        RequirementKind.ENGLISH_TEST, operator=">=", value="IELTS 7.0, no band below 6.5"
    )
    profile = _make_profile({"english_test_result": {"test": "IELTS", "score": 6.5}})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_english_test_is_unknown_even_when_the_profile_clearly_exceeds_it():
    requirement = _make_requirement(
        RequirementKind.ENGLISH_TEST, operator=">=", value="IELTS 6.0"
    )
    profile = _make_profile({"english_test_result": {"test": "IELTS", "score": 8.5}})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


# --- Whole-branch review I11: required free-text kinds never manufacture a FAIL ------------

def test_nationality_exact_match_is_pass():
    requirement = _make_requirement(RequirementKind.NATIONALITY, value="Algerian")
    profile = _make_profile({"nationality": "algerian"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_nationality_plausible_but_different_phrasing_is_unknown_not_fail():
    # The false-block case: "open to international students" is not evidence that an
    # Algerian applicant is ineligible, but naive string equality made it a FAIL, which
    # buckets the award LIKELY BLOCKED and hides a real opportunity for good.
    requirement = _make_requirement(
        RequirementKind.NATIONALITY, value="open to international students"
    )
    profile = _make_profile({"nationality": "Algerian"})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_nationality_normalises_case_and_whitespace_before_comparing():
    requirement = _make_requirement(RequirementKind.NATIONALITY, value="  ALGERIAN  ")
    profile = _make_profile({"nationality": "algerian"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_nationality_unknown_when_profile_attribute_missing():
    requirement = _make_requirement(RequirementKind.NATIONALITY, value="australian")
    assert evaluate_requirement(requirement, _make_profile({})) == Outcome.UNKNOWN


def test_degree_level_exact_match_is_pass():
    requirement = _make_requirement(RequirementKind.DEGREE_LEVEL, value="PhD")
    profile = _make_profile({"degree_level": "phd"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_degree_level_known_synonym_is_pass_not_fail():
    requirement = _make_requirement(RequirementKind.DEGREE_LEVEL, value="Doctor of Philosophy")
    profile = _make_profile({"degree_level": "phd"})
    assert evaluate_requirement(requirement, profile) == Outcome.PASS


def test_degree_level_genuine_conflict_within_the_known_vocabulary_is_fail():
    # Both sides resolve through the synonym table, so this comparison IS confident.
    requirement = _make_requirement(RequirementKind.DEGREE_LEVEL, value="masters")
    profile = _make_profile({"degree_level": "PhD"})
    assert evaluate_requirement(requirement, profile) == Outcome.FAIL


def test_degree_level_unrecognised_phrasing_is_unknown_not_fail():
    requirement = _make_requirement(
        RequirementKind.DEGREE_LEVEL, value="Doctoral Training Programme in Cyber Security"
    )
    profile = _make_profile({"degree_level": "phd"})
    assert evaluate_requirement(requirement, profile) == Outcome.UNKNOWN


def test_degree_level_unknown_when_profile_attribute_missing():
    requirement = _make_requirement(RequirementKind.DEGREE_LEVEL, value="phd")
    assert evaluate_requirement(requirement, _make_profile({})) == Outcome.UNKNOWN
