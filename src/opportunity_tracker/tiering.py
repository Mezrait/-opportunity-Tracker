"""Domain -> SourceTier classification. See spec §5, §9.1.

`classify_tier` is the pure, I/O-free core: seed override first, then academic/government
suffix matching, then the aggregator list, then Tier 3. The curated seed file's declared
tier (`seed_override`) always wins over automatic domain classification — suffix matching
cannot recognise legitimate consortium domains like cybersure-master.eu, an official
Erasmus Mundus programme site that matches no academic suffix.

`classify_tier_for_url` wraps that pure core with a lookup against the loaded `institution`
directory. Suffix matching alone cannot see that `utoronto.ca`, `mcgill.ca` or `ubc.ca` are
universities' own domains — most countries outside the US/UK/AU academic-suffix conventions
have no `.edu`-style marker at all, so ~97% of Canada (the shipped filter.example.yaml
target) would fall through to Tier 3 and, per principle 2, never write a single field.
Spec §5's claim that domain-scoped discovery yields "automatically Tier 1" documents only
holds if tiering can recognise an institution's own domain regardless of suffix, which is
exactly what the directory lookup provides.
"""
from __future__ import annotations

import sqlite3

import yaml

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


def classify_tier_for_url(
    domain: str, conn: sqlite3.Connection, seed_override: int | None = None
) -> SourceTier:
    """Directory-aware tiering: `classify_tier`, plus a lookup against `institution`.

    Resolution order:
      1. `seed_override` (the curated seed file's declared tier) always wins, exactly as
         in `classify_tier` — an operator's explicit declaration is never second-guessed.
      2. Otherwise, if `domain` is a loaded institution's own domain, or a subdomain of
         one (`scholarships.utoronto.ca` under `utoronto.ca`), it is Tier 1 — that IS the
         spec §5 definition of Tier 1 ("the institution's own domain"), and the directory
         is the only place the system knows which domains those are.
      3. Otherwise fall back to the pure suffix/aggregator classification.

    Kept separate from `classify_tier` so the pure function stays pure and independently
    testable; production callers (fetcher/pipeline.py) use this one.
    """
    if seed_override is not None:
        return SourceTier(seed_override)

    normalized = domain.strip().lower()
    if normalized:
        # `domain` itself, plus every parent domain of it -- an institution row for any of
        # them means this URL lives on that institution's own domain. Matching by explicit
        # parent list rather than a LIKE pattern keeps `_`/`%` in a stored domain from
        # acting as a wildcard.
        labels = normalized.split(".")
        candidates = [normalized] + [
            ".".join(labels[i:]) for i in range(1, max(1, len(labels) - 1))
        ]
        placeholders = ",".join("?" for _ in candidates)
        row = conn.execute(
            f"SELECT 1 FROM institution WHERE LOWER(domain) IN ({placeholders}) LIMIT 1",
            candidates,
        ).fetchone()
        if row is not None:
            return SourceTier.TIER_1

    return classify_tier(domain, seed_override)


def is_denied(domain: str, deny_list: set[str]) -> bool:
    normalized = domain.strip().lower()
    normalized_deny_list = {d.strip().lower() for d in deny_list}
    return normalized in normalized_deny_list


def load_deny_list(path: str) -> set[str]:
    """Load the Tier 3 deny-list (spec §5: domains observed publishing fabricated figures,
    "excluded from fetch entirely"). A missing or empty file is an empty deny-list, not an
    error -- the deny-list is an operator-maintained exception list, and its absence must
    never stop the pipeline."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            entries = yaml.safe_load(f)
    except FileNotFoundError:
        return set()
    if not entries:
        return set()
    return {str(entry).strip().lower() for entry in entries if str(entry).strip()}
