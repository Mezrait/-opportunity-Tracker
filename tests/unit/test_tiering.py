from opportunity_tracker.models import SourceTier
from opportunity_tracker.tiering import classify_tier, is_denied


def test_seed_override_wins_even_when_domain_matches_no_known_pattern():
    # Regression test (spec §5, §9.1): cybersure-master.eu is a real Erasmus
    # Mundus consortium domain that matches no academic/government suffix, but
    # the curated seed file marks it Tier 1. Suffix matching alone would wrongly
    # classify it Tier 3 — an observed bug in an earlier throwaway prototype.
    assert classify_tier("cybersure-master.eu", seed_override=1) == SourceTier.TIER_1


def test_seed_override_can_downgrade_an_academic_domain():
    assert classify_tier("mit.edu", seed_override=3) == SourceTier.TIER_3


def test_academic_edu_domain_is_tier_1_without_override():
    assert classify_tier("mit.edu") == SourceTier.TIER_1


def test_edu_au_domain_is_tier_1():
    assert classify_tier("unimelb.edu.au") == SourceTier.TIER_1


def test_ac_uk_domain_is_tier_1():
    assert classify_tier("ox.ac.uk") == SourceTier.TIER_1


def test_gov_domain_is_tier_1():
    assert classify_tier("education.gov.au") == SourceTier.TIER_1


def test_known_aggregator_domains_are_tier_2():
    assert classify_tier("daad.de") == SourceTier.TIER_2
    assert classify_tier("eacea.ec.europa.eu") == SourceTier.TIER_2


def test_unknown_domain_is_tier_3():
    assert classify_tier("some-random-blog.com") == SourceTier.TIER_3


def test_is_denied_true_for_listed_domain():
    deny_list = {"scam-scholarships.example", "fake-uni-list.example"}
    assert is_denied("scam-scholarships.example", deny_list) is True


def test_is_denied_false_for_unlisted_domain():
    deny_list = {"scam-scholarships.example"}
    assert is_denied("legit-university.edu", deny_list) is False
