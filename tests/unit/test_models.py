# tests/unit/test_models.py
from opportunity_tracker.models import RequirementKind, REQUIRED_KINDS, INFORMATIONAL_KINDS


def test_required_and_informational_kinds_partition_the_enum():
    assert REQUIRED_KINDS | INFORMATIONAL_KINDS == set(RequirementKind)
    assert REQUIRED_KINDS & INFORMATIONAL_KINDS == set()


def test_research_project_fraction_is_required():
    assert RequirementKind.RESEARCH_PROJECT_FRACTION in REQUIRED_KINDS


def test_supervisor_required_is_informational():
    assert RequirementKind.SUPERVISOR_REQUIRED in INFORMATIONAL_KINDS
    assert RequirementKind.SUPERVISOR_REQUIRED not in REQUIRED_KINDS
