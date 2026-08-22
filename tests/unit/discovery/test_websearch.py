"""Tests for the Claude web_search wrapper. anthropic.Anthropic is mocked entirely --
this suite never calls the real Anthropic API."""
from opportunity_tracker.discovery.websearch import build_query, search_domain, search_institution
from opportunity_tracker.models import Filter, Institution, InstitutionSource


def _make_institution() -> Institution:
    return Institution(
        id=1,
        name="University of Western Australia",
        country="Australia",
        country_code="AU",
        domain="uwa.edu.au",
        source=InstitutionSource.HIPO_DIRECTORY,
        directory_version="2026.1",
        added_at="2026-08-22T00:00:00+00:00",
    )


def _make_filter() -> Filter:
    return Filter(
        id=1,
        name="AU PhD CS",
        country="Australia",
        degree_levels=["PhD"],
        fields=["Computer Science"],
        funding_type=None,
        deadline_after=None,
        min_grade=None,
        institution_cap=50,
        content_hash="hash-1",
        created_at="2026-08-22T00:00:00+00:00",
    )


class _FakeResultItem:
    """Shaped like the SDK's web_search_result content items: .url, .title."""

    def __init__(self, url, title):
        self.url = url
        self.title = title


class _FakeContentBlock:
    """Shaped like a Message.content entry: .type, .content."""

    def __init__(self, block_type, content):
        self.type = block_type
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def test_build_query_uses_first_degree_level_and_field():
    query = build_query(_make_filter(), _make_institution())
    assert query == (
        "PhD Computer Science scholarship international students site info "
        "for University of Western Australia"
    )


def test_search_institution_extracts_and_dedupes_results(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(content=[
        _FakeContentBlock("text", "some preamble"),
        _FakeContentBlock("web_search_tool_result", [
            _FakeResultItem("https://uwa.edu.au/scholarships/rtp", "RTP Scholarship"),
            _FakeResultItem("https://uwa.edu.au/scholarships/rtp", "RTP Scholarship (dup)"),
            _FakeResultItem("https://uwa.edu.au/scholarships/other", "Other Scholarship"),
        ]),
    ])
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    results = search_institution(_make_institution(), _make_filter(), api_key="sk-test")

    assert results == [
        {"url": "https://uwa.edu.au/scholarships/rtp", "title": "RTP Scholarship"},
        {"url": "https://uwa.edu.au/scholarships/other", "title": "Other Scholarship"},
    ]


def test_search_institution_scopes_tools_argument_to_institution_domain(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(content=[])
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    search_institution(_make_institution(), _make_filter(), api_key="sk-test", max_uses=5)

    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "allowed_domains": ["uwa.edu.au"],
        }
    ]
    assert kwargs["messages"][0]["content"] == (
        "PhD Computer Science scholarship international students site info "
        "for University of Western Australia"
    )


def test_search_institution_handles_server_tool_error_block(mocker):
    # Server-tool errors return HTTP 200 with content as a single error object
    # instead of a list -- must degrade to [] rather than raise or index-crash.
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(content=[
        _FakeContentBlock("web_search_tool_result", {"error_code": "max_uses_exceeded"}),
    ])
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    results = search_institution(_make_institution(), _make_filter(), api_key="sk-test")

    assert results == []


def test_search_domain_scopes_tools_to_bare_domain_and_returns_results(mocker):
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _FakeResponse(
        content=[
            _FakeContentBlock(
                "web_search_tool_result",
                [_FakeResultItem("https://uwa.edu.au/rules/deadline", "Deadline")],
            )
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    results = search_domain("uwa.edu.au", "application deadline", api_key="sk-test", max_uses=1)

    assert results == [{"url": "https://uwa.edu.au/rules/deadline", "title": "Deadline"}]
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 1,
            "allowed_domains": ["uwa.edu.au"],
        }
    ]
    assert kwargs["messages"][0]["content"] == "application deadline"
