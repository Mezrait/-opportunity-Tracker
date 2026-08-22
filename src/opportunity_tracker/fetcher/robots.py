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


def _get_parser(host: str) -> RobotFileParser:
    if host in _robots_cache:
        return _robots_cache[host]
    parser = RobotFileParser()
    parser.set_url(f"https://{host}/robots.txt")
    parser.read()
    _robots_cache[host] = parser
    return parser


def is_allowed(url: str) -> bool:
    """Return True if `url` may be fetched per its host's robots.txt.

    Fetches and parses https://{host}/robots.txt via the stdlib's
    urllib.robotparser on the first check for that host; every later check
    against the same host reuses the cached, already-parsed result for the
    process lifetime. If robots.txt is unreachable (network error, 404, etc.),
    RobotFileParser's own standard behaviour applies -- effectively allow-all
    for a missing file, which matches how a real crawler treats "no
    robots.txt found."
    """
    host = urlparse(url).netloc
    parser = _get_parser(host)
    return parser.can_fetch("*", url)


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
