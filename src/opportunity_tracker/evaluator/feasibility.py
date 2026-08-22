"""Feasibility: minimum lead time implied by the profile's missing prerequisites, given a
set of requirements. Pure function -- spec §6.4. No network, no LLM, no file I/O."""
from __future__ import annotations

from opportunity_tracker import config
from opportunity_tracker.models import Profile, Requirement, RequirementKind


def estimate_lead_time_days(profile: Profile, requirements: list[Requirement]) -> int:
    kinds_present = {requirement.kind for requirement in requirements}
    total_days = 0

    if RequirementKind.ENGLISH_TEST in kinds_present:
        if profile.attributes.get("english_test_result") is None:
            total_days += int(config.FEASIBILITY_LEAD_DAYS["english_test_result"])

    if RequirementKind.SUPERVISOR_REQUIRED in kinds_present:
        if profile.attributes.get("supervisor_confirmed") is not True:
            low, high = config.FEASIBILITY_LEAD_DAYS["supervisor_agreement"]
            total_days += (low + high) // 2

    if profile.attributes.get("has_transcripts") is not True:
        total_days += int(config.FEASIBILITY_LEAD_DAYS["transcripts"])

    return total_days
