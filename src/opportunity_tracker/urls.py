"""Registrable-domain (eTLD+1) derivation. Shared by cli.py and digger/run.py.

`urlparse(url).netloc` is a bare host, not a registrable domain: it keeps `www.` and every
other subdomain. Scoping the digger's crawl to that host meant an award hosted at
`scholarships.uwa.edu.au` could never reach `uwa.edu.au`'s course-rules pages -- the exact
UWA case that motivated the whole tool. Naive suffix trimming does not work either, because
the number of labels in a public suffix varies (`.edu.au`, `.ac.uk`, `.com`), which is what
the Public Suffix List exists to answer.

`tldextract` is the standard Python implementation of that list. The extractor here is
pinned to the packaged snapshot (`suffix_list_urls=()`), so importing this module never
makes a network request and the same URL always resolves the same way -- a fetch-time
lookup would make crawl scoping depend on network reachability.
"""
from __future__ import annotations

from urllib.parse import urlparse

import tldextract

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


def registrable_domain(url_or_domain: str) -> str:
    """Return the eTLD+1 of `url_or_domain` (a full URL or a bare host).

    Falls back to the bare lowercased host when the Public Suffix List cannot produce an
    eTLD+1 -- `localhost`, an IP literal, an intranet name. Callers compare domains for
    equality, so a stable, normalised fallback matters more than a correct-but-empty one.
    """
    if not url_or_domain:
        return ""
    extracted = _EXTRACT(url_or_domain)
    # `registered_domain` is deprecated in tldextract >= 5.3 in favour of the more
    # accurately-named `top_domain_under_public_suffix`; both mean eTLD+1. Selected by
    # presence, not truthiness -- either legitimately returns "" for a host with no public
    # suffix (localhost, an IP literal), and reading the deprecated one then would emit a
    # DeprecationWarning on every such lookup.
    if hasattr(extracted, "top_domain_under_public_suffix"):
        domain = extracted.top_domain_under_public_suffix or ""
    else:  # pragma: no cover - only on tldextract < 5.3
        domain = extracted.registered_domain or ""
    if domain:
        return domain.lower()

    host = urlparse(url_or_domain).netloc or url_or_domain
    return host.split("@")[-1].split(":")[0].strip().lower()


def is_same_registrable_domain(candidate: str, registrable: str) -> bool:
    """True if `candidate` (a URL or host) sits on the registrable domain `registrable`.

    Compares eTLD+1 to eTLD+1, so `scholarships.uwa.edu.au` matches `uwa.edu.au` while the
    suffix-spoofed lookalike `notuwa.edu.au` does not.
    """
    if not registrable:
        return False
    return registrable_domain(candidate) == registrable_domain(registrable)
