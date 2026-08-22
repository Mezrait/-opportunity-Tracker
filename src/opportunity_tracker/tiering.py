"""Domain -> SourceTier classification. Pure function, no I/O. See spec §5, §9.1.

The curated seed file's declared tier (`seed_override`) always wins over automatic
domain classification — suffix matching cannot recognise legitimate consortium
domains like cybersure-master.eu, an official Erasmus Mundus programme site that
matches no academic suffix. Automatic tiering still guards anything not hand-added.
"""
from __future__ import annotations

from opportunity_tracker.models import SourceTier

# Academic and government suffixes. A domain ending in any of these, with no seed
# override, is Tier 1 (the institution's own domain, or a government/agency domain).
TIER_1_SUFFIXES: tuple[str, ...] = (
    ".edu",
    ".edu.au",
    ".ac.uk",
    ".ac.nz",
    ".ac.at",
    ".ac.jp",
    ".ac.za",
    ".gov",
    ".gov.au",
    ".gov.uk",
)

# Known official aggregators: Tier 2 (discovery only, never writes fields). Small
# hardcoded list — these are catalogue/search domains, not any single institution's
# own domain, and not the primary regulatory/agency domain itself.
TIER_2_AGGREGATOR_DOMAINS: frozenset[str] = frozenset({
    "daad.de",
    "eacea.ec.europa.eu",
})


def classify_tier(domain: str, seed_override: int | None = None) -> SourceTier:
    if seed_override is not None:
        return SourceTier(seed_override)

    normalized = domain.strip().lower()

    if any(normalized.endswith(suffix) for suffix in TIER_1_SUFFIXES):
        return SourceTier.TIER_1

    if normalized in TIER_2_AGGREGATOR_DOMAINS:
        return SourceTier.TIER_2

    return SourceTier.TIER_3


def is_denied(domain: str, deny_list: set[str]) -> bool:
    normalized = domain.strip().lower()
    normalized_deny_list = {d.strip().lower() for d in deny_list}
    return normalized in normalized_deny_list
