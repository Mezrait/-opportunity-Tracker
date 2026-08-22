"""Core data structures shared across the pipeline. No I/O in this module."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RequirementKind(str, Enum):
    MIN_GRADE = "min_grade"
    RESEARCH_PROJECT_FRACTION = "research_project_fraction"
    THESIS_REQUIRED = "thesis_required"
    ENGLISH_TEST = "english_test"
    NATIONALITY = "nationality"
    DEADLINE = "deadline"
    DEGREE_LEVEL = "degree_level"
    SUPERVISOR_REQUIRED = "supervisor_required"
    PRIOR_SCHOLARSHIP_EXCLUSION = "prior_scholarship_exclusion"
    RETURN_OBLIGATION = "return_obligation"
    FUNDING_COMPONENT = "funding_component"
    INTAKE_YEAR = "intake_year"


REQUIRED_KINDS: frozenset[RequirementKind] = frozenset({
    RequirementKind.DEADLINE,
    RequirementKind.DEGREE_LEVEL,
    RequirementKind.INTAKE_YEAR,
    RequirementKind.THESIS_REQUIRED,
    RequirementKind.RESEARCH_PROJECT_FRACTION,
    RequirementKind.MIN_GRADE,
    RequirementKind.ENGLISH_TEST,
    RequirementKind.NATIONALITY,
})

INFORMATIONAL_KINDS: frozenset[RequirementKind] = frozenset({
    RequirementKind.SUPERVISOR_REQUIRED,
    RequirementKind.PRIOR_SCHOLARSHIP_EXCLUSION,
    RequirementKind.RETURN_OBLIGATION,
    RequirementKind.FUNDING_COMPONENT,
})


class FetchMethod(str, Enum):
    HTTP = "http"
    HEADLESS = "headless"
    PDF = "pdf"


class SourceTier(int, Enum):
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class InstitutionSource(str, Enum):
    HIPO_DIRECTORY = "hipo_directory"
    MANUAL = "manual"


class Bucket(str, Enum):
    ACT_NOW = "ACT_NOW"
    ELIGIBLE_LATER = "ELIGIBLE_LATER"
    UNKNOWN_GATED = "UNKNOWN_GATED"
    LIKELY_BLOCKED = "LIKELY_BLOCKED"


class Outcome(str, Enum):
    """Three-valued logic result for a single requirement."""
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class DiscoveryRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Scheme:
    id: int
    name: str
    funder: str | None
    jurisdiction: str | None


@dataclass(frozen=True)
class Award:
    id: int
    scheme_id: int | None
    institution: str
    country: str
    degree_levels: list[str]
    intake_year: int | None
    canonical_url: str


@dataclass(frozen=True)
class Document:
    id: int
    url: str
    source_tier: SourceTier
    fetch_method: FetchMethod
    content_hash: str
    text_path: str | None
    retrieved_at: str
    fetch_status: str
    degraded: bool


@dataclass(frozen=True)
class Requirement:
    id: int
    award_id: int
    document_id: int
    kind: RequirementKind
    operator: str | None
    value: str | None
    unit: str | None
    raw_text: str
    evidence: str
    confidence: float | None
    extracted_at: str
    human_verified: bool


@dataclass(frozen=True)
class Profile:
    id: int
    version: int
    created_at: str
    attributes: dict


@dataclass(frozen=True)
class Evaluation:
    id: int
    award_id: int
    profile_version: int
    evaluated_at: str
    bucket: Bucket
    sort_keys: dict
    per_requirement_outcomes: dict


@dataclass(frozen=True)
class UnclassifiedRule:
    id: int
    document_id: int
    raw_text: str
    logged_at: str
    reviewed: bool


@dataclass(frozen=True)
class Institution:
    id: int
    name: str
    country: str
    country_code: str
    domain: str
    source: InstitutionSource
    directory_version: str | None
    added_at: str


@dataclass(frozen=True)
class Filter:
    id: int
    name: str
    country: str
    degree_levels: list[str]
    fields: list[str]
    funding_type: str | None
    deadline_after: str | None
    min_grade: str | None
    institution_cap: int
    content_hash: str
    created_at: str


@dataclass(frozen=True)
class DiscoveryRun:
    id: int
    filter_id: int
    filter_content_hash: str
    started_at: str
    completed_at: str | None
    institutions_considered: int
    institutions_with_candidates: int
    searches_used: int
    status: DiscoveryRunStatus


@dataclass(frozen=True)
class Candidate:
    id: int
    discovery_run_id: int | None
    institution_id: int
    url: str
    query_used: str
    found_at: str
    promoted_to_award_id: int | None
