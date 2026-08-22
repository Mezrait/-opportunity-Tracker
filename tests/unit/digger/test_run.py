# tests/unit/digger/test_run.py
"""Tests for the bounded digger. websearch.search_domain, fetcher.pipeline.fetch, and
anthropic.Anthropic are all mocked -- this suite never calls a real search API,
fetches over a real network, or calls a real LLM."""
from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.digger.run import _extract_same_domain_links, dig
from opportunity_tracker.models import Document, FetchMethod, RequirementKind, SourceTier


class _FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _found_response(**fields):
    payload = {
        "found": True,
        "operator": None,
        "value": None,
        "unit": None,
        "raw_text": None,
        "evidence": None,
        "confidence": None,
    }
    payload.update(fields)
    return _FakeResponse(content=[_FakeToolUseBlock("record_requirement", payload)])


def _not_found_response():
    return _FakeResponse(
        content=[
            _FakeToolUseBlock(
                "record_requirement",
                {
                    "found": False,
                    "operator": None,
                    "value": None,
                    "unit": None,
                    "raw_text": None,
                    "evidence": None,
                    "confidence": None,
                },
            )
        ]
    )


def _make_document(doc_id, text_path, url, source_tier=SourceTier.TIER_1):
    return Document(
        id=doc_id,
        url=url,
        source_tier=source_tier,
        fetch_method=FetchMethod.HTTP,
        content_hash=f"hash-{doc_id}",
        text_path=str(text_path),
        retrieved_at="2026-08-22T00:00:00",
        fetch_status="ok",
        degraded=False,
    )


def test_dig_finds_field_via_web_search_uses_one_fetch(mocker, tmp_path):
    doc_text = "The application deadline for the 2027 intake is 15 March 2027."
    doc_path = tmp_path / "found.txt"
    doc_path.write_text(doc_text, encoding="utf-8")

    mocker.patch(
        "opportunity_tracker.digger.run.websearch.search_domain",
        return_value=[{"url": "https://uwa.edu.au/found", "title": "Deadlines"}],
    )
    fetch_mock = mocker.patch(
        "opportunity_tracker.digger.run.pipeline.fetch",
        return_value=_make_document(1, doc_path, "https://uwa.edu.au/found"),
    )
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _found_response(
        operator="=",
        value="2027-03-15",
        unit=None,
        raw_text=doc_text,
        evidence=doc_text,
        confidence=0.9,
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    conn = mocker.MagicMock()
    conn.execute.return_value.lastrowid = 42

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.DEADLINE,
        registrable_domain="uwa.edu.au",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is not None
    assert requirement.kind == RequirementKind.DEADLINE
    assert requirement.value == "2027-03-15"
    fetch_mock.assert_called_once_with("https://uwa.edu.au/found", conn)
    fake_client.messages.create.assert_called_once()


def test_dig_falls_back_to_crawl_when_search_finds_nothing(mocker, tmp_path):
    homepage_text = (
        '<html><body><a href="https://uwa.edu.au/requirements">Requirements</a></body></html>'
    )
    homepage_path = tmp_path / "homepage.txt"
    homepage_path.write_text(homepage_text, encoding="utf-8")

    target_text = "Minimum overall IELTS band score of 6.5 required, no band below 6.0."
    target_path = tmp_path / "requirements.txt"
    target_path.write_text(target_text, encoding="utf-8")

    mocker.patch("opportunity_tracker.digger.run.websearch.search_domain", return_value=[])

    homepage_doc = _make_document(1, homepage_path, "https://uwa.edu.au/")
    target_doc = _make_document(2, target_path, "https://uwa.edu.au/requirements")

    fetch_mock = mocker.patch(
        "opportunity_tracker.digger.run.pipeline.fetch",
        side_effect=[homepage_doc, target_doc],
    )

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        _not_found_response(),
        _found_response(
            operator=">=",
            value="6.5",
            unit="IELTS band",
            raw_text=target_text,
            evidence=target_text,
            confidence=0.92,
        ),
    ]
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    conn = mocker.MagicMock()
    conn.execute.return_value.lastrowid = 99

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.ENGLISH_TEST,
        registrable_domain="uwa.edu.au",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is not None
    assert requirement.value == "6.5"
    assert fetch_mock.call_count == 2
    fetch_mock.assert_any_call("https://uwa.edu.au/", conn)
    fetch_mock.assert_any_call("https://uwa.edu.au/requirements", conn)


def test_dig_returns_none_when_budget_exhausted(mocker, tmp_path):
    links_html = "".join(
        f'<a href="https://uwa.edu.au/page{i}">Page {i}</a>' for i in range(10)
    )
    homepage_text = f"<html><body>{links_html}</body></html>"
    homepage_path = tmp_path / "homepage.txt"
    homepage_path.write_text(homepage_text, encoding="utf-8")

    subpage_text = "Nothing relevant on this page."
    subpage_path = tmp_path / "subpage.txt"
    subpage_path.write_text(subpage_text, encoding="utf-8")

    mocker.patch("opportunity_tracker.digger.run.websearch.search_domain", return_value=[])

    homepage_doc = _make_document(1, homepage_path, "https://uwa.edu.au/")
    subpage_docs = [
        _make_document(i + 2, subpage_path, f"https://uwa.edu.au/page{i}") for i in range(10)
    ]
    fetch_mock = mocker.patch(
        "opportunity_tracker.digger.run.pipeline.fetch",
        side_effect=[homepage_doc] + subpage_docs,
    )

    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _not_found_response()
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    conn = mocker.MagicMock()

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.MIN_GRADE,
        registrable_domain="uwa.edu.au",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is None
    assert fetch_mock.call_count == 5


def test_extract_same_domain_links_rejects_suffix_spoofed_lookalike():
    document_text = (
        '<html><body>'
        '<a href="https://notuwa.edu.au/apply">Not actually UWA</a>'
        '<a href="https://xuwa.edu.au/apply">Also not UWA</a>'
        '<a href="https://apply.uwa.edu.au/apply">Real UWA subdomain</a>'
        '<a href="https://uwa.edu.au/apply">Real UWA root domain</a>'
        '</body></html>'
    )

    links = _extract_same_domain_links(
        document_text, base_url="https://uwa.edu.au/", registrable_domain="uwa.edu.au"
    )

    assert "https://notuwa.edu.au/apply" not in links
    assert "https://xuwa.edu.au/apply" not in links
    assert "https://apply.uwa.edu.au/apply" in links
    assert "https://uwa.edu.au/apply" in links


def test_dig_does_not_raise_when_llm_call_fails(mocker, tmp_path):
    """client.messages.create raising (rate limit, timeout, network blip) must
    never propagate out of dig() -- the contract is 'never raise', with a
    confirmed-not-found treated as ordinary data, not a crash."""
    doc_text = "Some page text that never gets read by a working LLM call."
    doc_path = tmp_path / "page.txt"
    doc_path.write_text(doc_text, encoding="utf-8")

    mocker.patch(
        "opportunity_tracker.digger.run.websearch.search_domain",
        return_value=[{"url": "https://uwa.edu.au/found", "title": "Deadlines"}],
    )

    homepage_doc = _make_document(1, doc_path, "https://uwa.edu.au/found")
    fallback_homepage_doc = _make_document(2, doc_path, "https://uwa.edu.au/")
    fetch_mock = mocker.patch(
        "opportunity_tracker.digger.run.pipeline.fetch",
        side_effect=[homepage_doc, fallback_homepage_doc],
    )

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("transient API failure")
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    conn = mocker.MagicMock()

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.DEADLINE,
        registrable_domain="uwa.edu.au",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is None
    assert fetch_mock.call_count == 2


# --- Principle 2: only Tier 1 sources write to fields (whole-branch review C1) -------------

def test_dig_never_writes_a_requirement_from_a_non_tier_1_document(mocker, tmp_path):
    """The digger's crawl can wander onto an aggregator mirror or a student blog linked
    from a faculty page. Whatever it says is logged for review, never written to
    `requirement` as if it were verified primary-source data (spec principle 2)."""
    doc_text = "The application deadline for the 2027 intake is 15 March 2027."
    doc_path = tmp_path / "tier3.txt"
    doc_path.write_text(doc_text, encoding="utf-8")

    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, text_path, "
        "retrieved_at, fetch_status, degraded) VALUES "
        "('https://aggregator.example/found', 3, 'http', 'h', ?, "
        "'2026-08-22T00:00:00+00:00', 'ok', 0)",
        (str(doc_path),),
    )
    conn.commit()

    tier3_doc = _make_document(
        1, doc_path, "https://aggregator.example/found", source_tier=SourceTier.TIER_3
    )
    mocker.patch(
        "opportunity_tracker.digger.run.websearch.search_domain",
        return_value=[{"url": "https://aggregator.example/found", "title": "Deadlines"}],
    )
    mocker.patch("opportunity_tracker.digger.run.pipeline.fetch", return_value=tier3_doc)

    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _found_response(
        operator="=", value="2027-03-15", raw_text=doc_text, evidence=doc_text, confidence=0.9
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    requirement = dig(
        award_id=7,
        missing_kind=RequirementKind.DEADLINE,
        registrable_domain="aggregator.example",
        conn=conn,
        api_key="sk-test",
    )

    assert requirement is None
    assert conn.execute("SELECT COUNT(*) AS n FROM requirement").fetchone()["n"] == 0
    logged = conn.execute("SELECT raw_text FROM unclassified_rule").fetchall()
    assert logged, "a Tier 3 finding must be logged for review, never silently dropped"
    assert "tier-3" in logged[0]["raw_text"]
    assert "deadline" in logged[0]["raw_text"]
    conn.close()
