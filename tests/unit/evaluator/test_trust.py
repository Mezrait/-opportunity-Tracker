"""Trust gate -- spec §6, §9.3, §12, principle 6. Pure function, no network, no LLM."""
from opportunity_tracker.models import Outcome, RequirementKind
from opportunity_tracker.evaluator.trust import downgrade_if_untrusted, is_trusted


def test_kind_at_exactly_threshold_is_trusted():
    gold_set_recall = {RequirementKind.DEADLINE.value: 0.85}
    assert is_trusted(RequirementKind.DEADLINE, gold_set_recall) is True


def test_kind_just_below_threshold_is_untrusted():
    gold_set_recall = {RequirementKind.DEADLINE.value: 0.84}
    assert is_trusted(RequirementKind.DEADLINE, gold_set_recall) is False


def test_kind_absent_from_recall_dict_is_untrusted_by_default():
    # A kind never measured on the gold set must never be assumed trustworthy.
    assert is_trusted(RequirementKind.DEADLINE, {}) is False


def test_fail_for_untrusted_kind_downgrades_to_unknown():
    gold_set_recall = {RequirementKind.THESIS_REQUIRED.value: 0.50}
    result = downgrade_if_untrusted(
        Outcome.FAIL, RequirementKind.THESIS_REQUIRED, gold_set_recall
    )
    assert result == Outcome.UNKNOWN


def test_fail_for_trusted_kind_stays_fail():
    gold_set_recall = {RequirementKind.THESIS_REQUIRED.value: 0.90}
    result = downgrade_if_untrusted(
        Outcome.FAIL, RequirementKind.THESIS_REQUIRED, gold_set_recall
    )
    assert result == Outcome.FAIL


def test_pass_outcome_is_never_downgraded_regardless_of_trust():
    result = downgrade_if_untrusted(Outcome.PASS, RequirementKind.THESIS_REQUIRED, {})
    assert result == Outcome.PASS


def test_unknown_outcome_is_never_touched():
    gold_set_recall = {RequirementKind.THESIS_REQUIRED.value: 0.90}
    result = downgrade_if_untrusted(
        Outcome.UNKNOWN, RequirementKind.THESIS_REQUIRED, gold_set_recall
    )
    assert result == Outcome.UNKNOWN
