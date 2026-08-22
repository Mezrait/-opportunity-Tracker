"""Per-kind three-valued requirement evaluation. Pure function -- spec §6.5, §9.1. No
network, no LLM, no file I/O. `requirement is None` always yields UNKNOWN (principle 5:
absence of a requirement is not evidence it does not exist)."""
from __future__ import annotations

import operator as _operator

from opportunity_tracker.models import Outcome, Profile, Requirement, RequirementKind

_COMPARATORS = {
    ">=": _operator.ge,
    "<=": _operator.le,
    "==": _operator.eq,
    ">": _operator.gt,
    "<": _operator.lt,
}

# For the boolean/informational kinds, the matching profile.attributes key shares the
# kind's own enum value.
_BOOLEAN_KIND_ATTRIBUTES: dict[RequirementKind, str] = {
    RequirementKind.THESIS_REQUIRED: "thesis_required",
    RequirementKind.DEGREE_LEVEL: "degree_level",
    RequirementKind.NATIONALITY: "nationality",
    RequirementKind.SUPERVISOR_REQUIRED: "supervisor_required",
    RequirementKind.PRIOR_SCHOLARSHIP_EXCLUSION: "prior_scholarship_exclusion",
    RequirementKind.RETURN_OBLIGATION: "return_obligation",
    RequirementKind.FUNDING_COMPONENT: "funding_component",
}


def evaluate_requirement(requirement: Requirement | None, profile: Profile) -> Outcome:
    if requirement is None:
        return Outcome.UNKNOWN

    kind = requirement.kind

    if kind == RequirementKind.RESEARCH_PROJECT_FRACTION:
        held = profile.attributes.get("research_project_fraction_held")
        if held is None:
            return Outcome.UNKNOWN
        compare = _COMPARATORS.get(requirement.operator)
        if compare is None:
            return Outcome.UNKNOWN
        held_value = float(held)
        required_value = float(requirement.value)
        return Outcome.PASS if compare(held_value, required_value) else Outcome.FAIL

    if kind == RequirementKind.ENGLISH_TEST:
        # Mandatory case (spec §9.1): required, profile holds none -> unknown, never fail.
        result = profile.attributes.get("english_test_result")
        if result is None:
            return Outcome.UNKNOWN
        return Outcome.PASS

    if kind == RequirementKind.INTAKE_YEAR:
        target = profile.attributes.get("target_intake_year")
        if target is None:
            return Outcome.UNKNOWN
        try:
            required_year = int(requirement.value)
            target_year = int(target)
        except (TypeError, ValueError):
            return Outcome.UNKNOWN
        # A mismatch here is a per-requirement FAIL. bucket.py (Task 23) is responsible for
        # translating specifically an intake-year FAIL into UNKNOWN-GATED rather than
        # LIKELY BLOCKED at the bucket level (spec §8) -- this function's contract is just
        # per-requirement three-valued truth.
        return Outcome.PASS if required_year == target_year else Outcome.FAIL

    if kind == RequirementKind.MIN_GRADE:
        # Spec §6.5: GPA -> WAM conversion is never automated. A stated grade threshold with
        # no verified conversion yields unknown, not a computed pass or fail -- always,
        # regardless of what profile data is present. Do not add a numeric comparison here.
        return Outcome.UNKNOWN

    if kind == RequirementKind.DEADLINE:
        # Existence is what's being checked at this layer; date math against the deadline
        # happens in feasibility.py/bucket.py (Tasks 21, 23).
        return Outcome.PASS if requirement.value is not None else Outcome.UNKNOWN

    attribute_key = _BOOLEAN_KIND_ATTRIBUTES.get(kind)
    if attribute_key is not None:
        profile_value = profile.attributes.get(attribute_key)
        if profile_value is None:
            return Outcome.UNKNOWN
        if str(requirement.value).strip().lower() == str(profile_value).strip().lower():
            return Outcome.PASS
        return Outcome.FAIL

    return Outcome.UNKNOWN
