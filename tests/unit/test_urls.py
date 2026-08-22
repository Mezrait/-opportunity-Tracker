"""Tests for registrable-domain (eTLD+1) derivation. Pure -- tldextract is pinned to its
packaged Public Suffix List snapshot, so this suite makes no network request."""
import pytest

from opportunity_tracker.urls import is_same_registrable_domain, registrable_domain


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # The motivating case: an award hosted on a scholarships subdomain must resolve to
        # the institution's registrable domain so the digger's crawl can reach the
        # course-rules pages that live on the apex.
        ("https://scholarships.uwa.edu.au/rtp", "uwa.edu.au"),
        ("https://www.uwa.edu.au/study/scholarships", "uwa.edu.au"),
        ("https://uwa.edu.au/", "uwa.edu.au"),
        ("uwa.edu.au", "uwa.edu.au"),
        # Multi-part public suffixes: a naive "last two labels" trim gives edu.au / ac.uk.
        ("https://www.ox.ac.uk/admissions", "ox.ac.uk"),
        ("https://apply.utoronto.ca/x", "utoronto.ca"),
        ("https://www.cybersure-master.eu/admission", "cybersure-master.eu"),
        ("https://sub.deep.example.com/a/b", "example.com"),
        ("HTTPS://WWW.UWA.EDU.AU/", "uwa.edu.au"),
    ],
)
def test_registrable_domain_resolves_etld_plus_one(value, expected):
    assert registrable_domain(value) == expected


def test_registrable_domain_falls_back_to_the_bare_host():
    # No eTLD+1 exists for these; a stable normalised host beats an empty string, since
    # callers compare domains for equality.
    assert registrable_domain("http://localhost:8000/page") == "localhost"
    assert registrable_domain("") == ""


def test_is_same_registrable_domain_accepts_sibling_subdomains():
    assert is_same_registrable_domain("https://scholarships.uwa.edu.au/rtp", "uwa.edu.au")
    assert is_same_registrable_domain("https://www.uwa.edu.au/", "scholarships.uwa.edu.au")


def test_is_same_registrable_domain_rejects_suffix_spoofed_lookalikes():
    assert not is_same_registrable_domain("https://notuwa.edu.au/apply", "uwa.edu.au")
    assert not is_same_registrable_domain("https://xuwa.edu.au/apply", "uwa.edu.au")
    assert not is_same_registrable_domain("https://uwa.edu.au.evil.example/", "uwa.edu.au")
