import pytest

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.models import SourceTier
from opportunity_tracker.tiering import (
    classify_tier,
    classify_tier_for_url,
    is_denied,
    load_deny_list,
)


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


# --- classify_tier_for_url: directory-aware tiering (whole-branch review C2) ---------------

@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def _insert_institution(conn, domain, name="Some University", country="Canada"):
    conn.execute(
        "INSERT INTO institution (name, country, country_code, domain, source, "
        "directory_version, added_at) VALUES (?, ?, 'CA', ?, 'hipo_directory', '2026.1', "
        "'2026-08-22T00:00:00+00:00')",
        (name, country, domain),
    )
    conn.commit()


def test_directory_domain_is_tier_1_even_without_a_recognised_suffix(conn):
    # ~97% of Canadian universities (the shipped filter.example.yaml target) use a bare
    # .ca domain that matches no academic suffix -- suffix matching alone would demote the
    # whole country to Tier 3 and, per principle 2, bar it from writing any field at all.
    assert classify_tier("utoronto.ca") == SourceTier.TIER_3  # pure function, unchanged
    _insert_institution(conn, "utoronto.ca", name="University of Toronto")
    assert classify_tier_for_url("utoronto.ca", conn) == SourceTier.TIER_1


def test_subdomain_of_a_directory_domain_is_tier_1(conn):
    _insert_institution(conn, "mcgill.ca", name="McGill University")
    assert classify_tier_for_url("www.scholarships.mcgill.ca", conn) == SourceTier.TIER_1


def test_lookalike_domain_is_not_matched_against_the_directory(conn):
    _insert_institution(conn, "ubc.ca", name="University of British Columbia")
    # "notubc.ca" contains "ubc.ca" as a substring but is not ubc.ca nor a subdomain of it.
    assert classify_tier_for_url("notubc.ca", conn) == SourceTier.TIER_3


def test_domain_absent_from_directory_falls_back_to_pure_classification(conn):
    assert classify_tier_for_url("some-random-blog.com", conn) == SourceTier.TIER_3
    assert classify_tier_for_url("mit.edu", conn) == SourceTier.TIER_1
    assert classify_tier_for_url("daad.de", conn) == SourceTier.TIER_2


def test_seed_override_still_wins_over_the_directory_lookup(conn):
    _insert_institution(conn, "mit.edu", name="MIT", country="United States")
    assert classify_tier_for_url("mit.edu", conn, seed_override=3) == SourceTier.TIER_3
    assert classify_tier_for_url("cybersure-master.eu", conn, seed_override=1) == SourceTier.TIER_1


# --- load_deny_list (whole-branch review I8) -----------------------------------------------

def test_load_deny_list_missing_file_is_empty_set(tmp_path):
    assert load_deny_list(str(tmp_path / "nope.yaml")) == set()


def test_load_deny_list_empty_yaml_list_is_empty_set(tmp_path):
    path = tmp_path / "deny.yaml"
    path.write_text("[]\n", encoding="utf-8")
    assert load_deny_list(str(path)) == set()


def test_load_deny_list_normalises_entries(tmp_path):
    path = tmp_path / "deny.yaml"
    path.write_text("- Scam-Scholarships.Example\n- ' fake-uni-list.example '\n", encoding="utf-8")
    assert load_deny_list(str(path)) == {"scam-scholarships.example", "fake-uni-list.example"}
