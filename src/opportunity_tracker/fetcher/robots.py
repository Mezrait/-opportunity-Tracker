"""robots.txt compliance and per-host rate limiting. See spec §6.1.

University sites are usually but not universally permissive with robots.txt -- this
module checks per host at request time, never assumes permissiveness and never
hardcodes an allow-all.
"""
from __future__ import annotations

import time
import urllib.request
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

# Parsed robots.txt per host, cached for the process lifetime -- repeated checks
# against the same host never re-fetch robots.txt.
_robots_cache: dict[str, RobotFileParser] = {}

# Last request timestamp (time.monotonic()) per host, for rate limiting.
_last_request_time: dict[str, float] = {}


ROBOTS_TIMEOUT_SECONDS = 10.0


def _get_parser(host: str) -> RobotFileParser:
    """Fetch and parse https://{host}/robots.txt, caching the result per host.

    Deliberately does NOT use RobotFileParser.read(): that method has no timeout (a
    black-holed host hangs the whole `optrack run` forever) and only catches HTTPError
    internally, so a URLError -- DNS failure, connection refused, TLS handshake error --
    propagates straight out and aborts the run. One dead domain among 50 discovered
    institutions must not take the pipeline down.

    FAIL-OPEN on an unreachable robots.txt: the parser is left allow-all, matching the
    standard crawler convention for "no robots.txt found" (and RobotFileParser's own
    behaviour on a 404). If the host is genuinely unreachable, the subsequent page fetch
    fails too and is recorded as `error:fetch_failed:...` by fetcher/pipeline.py -- so
    nothing is silently treated as successfully fetched. The failed parser is cached like
    any other, so a dead host costs one timeout per process, not one per URL.
    """
    if host in _robots_cache:
        return _robots_cache[host]

    parser = RobotFileParser()
    parser.set_url(f"https://{host}/robots.txt")
    try:
        response = urllib.request.urlopen(
            f"https://{host}/robots.txt", timeout=ROBOTS_TIMEOUT_SECONDS
        )
        raw = response.read()
    except Exception:  # noqa: BLE001 - URLError, socket.timeout, TLS/SSL, HTTPError, ...
        parser.allow_all = True
    else:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        parser.parse(raw.splitlines())

    _robots_cache[host] = parser
    return parser


def is_allowed(url: str) -> bool:
    """Return True if `url` may be fetched per its host's robots.txt.

    Fetches and parses https://{host}/robots.txt on the first check for that host; every
    later check against the same host reuses the cached, already-parsed result for the
    process lifetime. Never raises: an unreachable or unparseable robots.txt is treated as
    allow-all (see `_get_parser` for why fail-open, and for the timeout).
    """
    host = urlparse(url).netloc
    try:
        parser = _get_parser(host)
        return parser.can_fetch("*", url)
    except Exception:  # noqa: BLE001 - fetcher/pipeline.fetch documents "never raises"
        return True


def wait_for_host(domain: str, min_interval_seconds: float = 2.0) -> None:
    """Block until at least `min_interval_seconds` has passed since the last
    call for `domain`. A simple per-host last-request-time dict -- no
    external scheduler or async dependency.
    """
    now = time.monotonic()
    last = _last_request_time.get(domain)
    if last is not None:
        remaining = min_interval_seconds - (now - last)
        if remaining > 0:
            time.sleep(remaining)
            now = time.monotonic()
    _last_request_time[domain] = now
