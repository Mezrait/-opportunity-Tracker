"""Trust gate: a requirement kind may produce a blocking FAIL only once its gold-set recall
clears the threshold. Pure function -- spec §6, §9.3, §12, principle 6. No network, no LLM,
no file I/O."""
from __future__ import annotations

from opportunity_tracker import config
from opportunity_tracker.models import Outcome, RequirementKind


def is_trusted(
    kind: RequirementKind,
    gold_set_recall: dict[str, float],
    threshold: float = config.TRUST_THRESHOLD_DEFAULT,
) -> bool:
    # A kind absent from the recall dict is untrusted by default -- never assumed
    # trustworthy in the absence of measurement.
    return gold_set_recall.get(kind.value, 0.0) >= threshold


def downgrade_if_untrusted(
    outcome: Outcome,
    kind: RequirementKind,
    gold_set_recall: dict[str, float],
) -> Outcome:
    if outcome == Outcome.FAIL and not is_trusted(kind, gold_set_recall):
        return Outcome.UNKNOWN
    return outcome
