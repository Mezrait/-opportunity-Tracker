"""Tests for robots.txt compliance and per-host rate limiting. urllib.request.urlopen
and time.monotonic/time.sleep are mocked throughout -- this suite never fetches a real
robots.txt over the network and never actually sleeps for 2 real seconds."""
import socket
import ssl
import urllib.error
from unittest.mock import MagicMock

import pytest

from opportunity_tracker.fetcher import robots


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """robots.py caches per-host state at module scope for the process lifetime --
    reset both caches around every test so tests don't leak state into each other."""
    robots._robots_cache.clear()
    robots._last_request_time.clear()
    yield
    robots._robots_cache.clear()
    robots._last_request_time.clear()


def _mock_urlopen(mocker, body: bytes):
    mock_response = MagicMock()
    mock_response.read.return_value = body
    return mocker.patch(
        "opportunity_tracker.fetcher.robots.urllib.request.urlopen",
        return_value=mock_response,
    )


def test_is_allowed_returns_false_for_disallowed_path(mocker):
    _mock_urlopen(mocker, b"User-agent: *\nDisallow: /private/\n")

    assert robots.is_allowed("https://example.edu/private/page") is False


def test_is_allowed_returns_true_for_allowed_path(mocker):
    _mock_urlopen(mocker, b"User-agent: *\nDisallow: /private/\n")

    assert robots.is_allowed("https://example.edu/public/page") is True


def test_is_allowed_caches_parsed_robots_txt_per_host(mocker):
    mock_urlopen = _mock_urlopen(mocker, b"User-agent: *\nDisallow: /private/\n")

    robots.is_allowed("https://example.edu/a")
    robots.is_allowed("https://example.edu/b")

    assert mock_urlopen.call_count == 1  # second check for the same host is cached


# --- Whole-branch review C3: is_allowed must never raise, and must never hang ---------------

def test_is_allowed_does_not_propagate_url_error(mocker):
    """RobotFileParser.read() only catches HTTPError internally -- a URLError (DNS
    failure, connection refused, TLS error) used to propagate straight out of is_allowed
    and abort the whole run on one dead domain among 50 discovered institutions."""
    mocker.patch(
        "opportunity_tracker.fetcher.robots.urllib.request.urlopen",
        side_effect=urllib.error.URLError("getaddrinfo failed"),
    )

    assert robots.is_allowed("https://dead-domain.example/page") is True  # fail-open


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError("connection refused"),
        socket.timeout("timed out"),
        ssl.SSLError("certificate verify failed"),
        OSError("network unreachable"),
    ],
)
def test_is_allowed_survives_every_urlopen_failure_mode(mocker, exc):
    mocker.patch(
        "opportunity_tracker.fetcher.robots.urllib.request.urlopen", side_effect=exc
    )

    assert robots.is_allowed("https://broken.example/page") is True


def test_is_allowed_passes_an_explicit_timeout_to_urlopen(mocker):
    """No timeout at all means a black-holed host hangs `optrack run` indefinitely."""
    mock_urlopen = _mock_urlopen(mocker, b"User-agent: *\nDisallow: /private/\n")

    robots.is_allowed("https://example.edu/public/page")

    _, kwargs = mock_urlopen.call_args
    assert kwargs["timeout"] == robots.ROBOTS_TIMEOUT_SECONDS


def test_failed_robots_fetch_is_cached_so_a_dead_host_costs_one_timeout(mocker):
    mock_urlopen = mocker.patch(
        "opportunity_tracker.fetcher.robots.urllib.request.urlopen",
        side_effect=urllib.error.URLError("getaddrinfo failed"),
    )

    robots.is_allowed("https://dead-domain.example/a")
    robots.is_allowed("https://dead-domain.example/b")

    assert mock_urlopen.call_count == 1


def test_wait_for_host_blocks_until_min_interval_elapsed(mocker):
    monotonic_values = iter([100.0, 100.5, 102.0])
    mocker.patch(
        "opportunity_tracker.fetcher.robots.time.monotonic",
        side_effect=lambda: next(monotonic_values),
    )
    mock_sleep = mocker.patch("opportunity_tracker.fetcher.robots.time.sleep")

    robots.wait_for_host("example.edu", min_interval_seconds=2.0)
    robots.wait_for_host("example.edu", min_interval_seconds=2.0)

    mock_sleep.assert_called_once()
    (slept_for,), _ = mock_sleep.call_args
    assert slept_for == pytest.approx(1.5)


def test_wait_for_host_does_not_block_when_interval_already_elapsed(mocker):
    monotonic_values = iter([100.0, 105.0])
    mocker.patch(
        "opportunity_tracker.fetcher.robots.time.monotonic",
        side_effect=lambda: next(monotonic_values),
    )
    mock_sleep = mocker.patch("opportunity_tracker.fetcher.robots.time.sleep")

    robots.wait_for_host("example.edu", min_interval_seconds=2.0)
    robots.wait_for_host("example.edu", min_interval_seconds=2.0)

    mock_sleep.assert_not_called()
