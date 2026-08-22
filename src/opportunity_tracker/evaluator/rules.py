"""Per-kind three-valued requirement evaluation. Pure function -- spec §6.5, §9.1. No
network, no LLM, no file I/O. `requirement is None` always yields UNKNOWN (principle 5:
absence of a requirement is not evidence it does not exist).

Three kinds deliberately decline to produce a FAIL from a comparison this module cannot
make with confidence -- MIN_GRADE, ENGLISH_TEST, and (for anything outside a small known
vocabulary) NATIONALITY and DEGREE_LEVEL. The precedent is spec §6.5's ruling on MIN_GRADE:
GPA -> WAM conversion is never automated, so a stated threshold with no verified conversion
yields UNKNOWN rather than a computed pass or fail. Extending that stance is the
conservative direction for a REQUIRED kind, because a FAIL on one is what buckets an award
as LIKELY BLOCKED -- a manufactured FAIL hides a real opportunity for good, while an UNKNOWN
surfaces it in Unknown-Gated where the operator can check it by hand. The trust gate in
trust.py does not help here: it gates on extraction recall, not on comparison correctness.
"""
from __future__ import annotations

import operator as _operator
import re

from opportunity_tracker.models import Outcome, Profile, Requirement, RequirementKind

_COMPARATORS = {
    ">=": _operator.ge,
    "<=": _operator.le,
    "==": _operator.eq,
    ">": _operator.gt,
    "<": _operator.lt,
}

_WHITESPACE = re.compile(r"\s+")

# Degree-level vocabulary: surface spellings -> canonical level. Two values that BOTH
# normalise into this table can be compared with confidence, so they yield a real PASS or
# FAIL. If either side is not in it ("Doctoral Training Programme in Cyber Security",
# "research higher degree by thesis"), the comparison is not confident and yields UNKNOWN.
# Deliberately small and literal: guessing at degree nomenclature is what produces the
# false blocks this table exists to prevent.
_DEGREE_LEVEL_SYNONYMS: dict[str, str] = {
    "phd": "phd",
    "ph.d": "phd",
    "ph.d.": "phd",
    "d.phil": "phd",
    "dphil": "phd",
    "doctorate": "phd",
    "doctoral": "phd",
    "doctor of philosophy": "phd",
    "masters": "masters",
    "master": "masters",
    "master's": "masters",
    "masters degree": "masters",
    "master's degree": "masters",
    "msc": "masters",
    "m.sc": "masters",
    "m.sc.": "masters",
    "ma": "masters",
    "mphil": "masters",
    "master of philosophy": "masters",
    "master of science": "masters",
    "master of arts": "masters",
    "master of engineering": "masters",
    "bachelors": "bachelors",
    "bachelor": "bachelors",
    "bachelor's": "bachelors",
    "bachelors degree": "bachelors",
    "bachelor's degree": "bachelors",
    "bsc": "bachelors",
    "b.sc": "bachelors",
    "b.sc.": "bachelors",
    "undergraduate": "bachelors",
    "honours": "honours",
    "honors": "honours",
    "bachelor honours": "honours",
}


def _normalize(value) -> str | None:
    """Lowercase and collapse whitespace. None/empty -> None."""
    if value is None:
        return None
    collapsed = _WHITESPACE.sub(" ", str(value)).strip().lower()
    return collapsed or None


def _compare_conservatively(
    requirement_value, profile_value, synonyms: dict[str, str] | None = None
) -> Outcome:
    """PASS/FAIL only when both sides can be compared with confidence; UNKNOWN otherwise.

    Exact match after normalisation is always confident. With a `synonyms` table, two values
    that both resolve through it are also confident (so "Doctor of Philosophy" vs "phd" is a
    real PASS, and "phd" vs "masters" a real FAIL). Anything else -- a requirement phrased
    as "open to international students" against a profile nationality of "Algerian", or a
    degree title the table does not know -- is a superficial string mismatch, not evidence
    of ineligibility, and must not manufacture a FAIL on a required kind.
    """
    required = _normalize(requirement_value)
    held = _normalize(profile_value)
    if required is None or held is None:
        return Outcome.UNKNOWN

    if required == held:
        return Outcome.PASS

    if synonyms is not None:
        canonical_required = synonyms.get(required)
        canonical_held = synonyms.get(held)
        if canonical_required is not None and canonical_held is not None:
            return Outcome.PASS if canonical_required == canonical_held else Outcome.FAIL

    return Outcome.UNKNOWN

# For the boolean/informational kinds, the matching profile.attributes key shares the
# kind's own enum value. NATIONALITY and DEGREE_LEVEL used to live here too, but naive
# string equality on those free-text REQUIRED kinds manufactured false FAILs; they now have
# their own conservative branches in evaluate_requirement. The kinds left here are
# genuinely boolean-ish or informational, where a mismatch is real and, for the
# informational ones, does not gate the award into LIKELY BLOCKED on its own.
_BOOLEAN_KIND_ATTRIBUTES: dict[RequirementKind, str] = {
    RequirementKind.THESIS_REQUIRED: "thesis_required",
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
        try:
            held_value = float(held)
            required_value = float(requirement.value)
        except (TypeError, ValueError):
            return Outcome.UNKNOWN
        return Outcome.PASS if compare(held_value, required_value) else Outcome.FAIL

    if kind == RequirementKind.ENGLISH_TEST:
        # Mandatory case (spec §9.1): required, profile holds none -> unknown, never fail.
        #
        # Design decision (whole-branch review): holding SOME english_test_result used to
        # return PASS regardless of whether it met the requirement's actual threshold --
        # the only rule in the system that could manufacture a false PASS on a required
        # kind, and the worst possible direction to be wrong in, since it presents an
        # ineligible award as ACT_NOW and sends the operator to spend real effort on it.
        # Reliably comparing "IELTS 6.5" against "IELTS 7.0 with no band below 6.5" means
        # parsing test name, overall score, per-band minima and accepted-test equivalences
        # out of free text -- exactly the class of comparison spec §6.5 rules out
        # automating for MIN_GRADE (GPA -> WAM conversion is never automated). Same ruling
        # applies here: UNKNOWN until a real comparison scheme exists, so the award lands
        # in Unknown-Gated for a human to check rather than being asserted either way.
        # Do not "improve" this into a numeric comparison without that scheme.
        return Outcome.UNKNOWN

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

    if kind == RequirementKind.NATIONALITY:
        # Required kind, and free-text on both sides: a requirement reads "open to
        # international students" or "Australian citizens and permanent residents" while a
        # profile holds "Algerian". Naive case-insensitive equality turned every such pair
        # into a FAIL, i.e. LIKELY BLOCKED, i.e. a real opportunity hidden by a string
        # mismatch. No synonym table can bridge citizenship phrasing safely, so only an
        # exact normalised match is confident; everything else is UNKNOWN.
        return _compare_conservatively(
            requirement.value, profile.attributes.get("nationality")
        )

    if kind == RequirementKind.DEGREE_LEVEL:
        # Required kind. "Doctor of Philosophy" vs a profile's "phd" means the same thing
        # and must not FAIL; "phd" vs "masters" genuinely conflicts and should. The small
        # synonym table above is the line between the two -- anything it does not
        # recognise on either side is UNKNOWN rather than a guess.
        return _compare_conservatively(
            requirement.value,
            profile.attributes.get("degree_level"),
            _DEGREE_LEVEL_SYNONYMS,
        )

    attribute_key = _BOOLEAN_KIND_ATTRIBUTES.get(kind)
    if attribute_key is not None:
        profile_value = profile.attributes.get(attribute_key)
        if profile_value is None:
            return Outcome.UNKNOWN
        if str(requirement.value).strip().lower() == str(profile_value).strip().lower():
            return Outcome.PASS
        return Outcome.FAIL

    return Outcome.UNKNOWN
