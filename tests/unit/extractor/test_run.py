"""Tests for the extractor run: a single (or retried-once) Anthropic tool-use call
per document, with evidence validation gating every insert. anthropic.Anthropic and
evidence.validate_evidence are both mocked -- this suite never calls the real
Anthropic API and never depends on evidence.py's real fuzzy-matching logic (that is
covered separately in test_evidence.py)."""
import pytest

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.extractor.run import extract_requirements
from opportunity_tracker.models import Document, FetchMethod, SourceTier


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    connection.execute(
        "INSERT INTO scheme (name, funder, jurisdiction) VALUES ('S', 'F', 'AU')"
    )
    connection.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, 'UWA', 'AU', '[\"phd\"]', 2027, "
        "'https://uwa.edu.au/award')"
    )
    connection.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES "
        "('https://uwa.edu.au/rules', 1, 'http', 'abc123', 'placeholder', "
        "'2026-08-22T00:00:00', 'ok', 0)"
    )
    connection.commit()
    yield connection
    connection.close()


def _make_document(text_path: str) -> Document:
    return Document(
        id=1,
        url="https://uwa.edu.au/rules",
        source_tier=SourceTier.TIER_1,
        fetch_method=FetchMethod.HTTP,
        content_hash="abc123",
        text_path=text_path,
        retrieved_at="2026-08-22T00:00:00",
        fetch_status="ok",
        degraded=False,
    )


class _FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, content):
        self.content = content


def _good_response(requirements):
    return _FakeResponse(
        content=[_FakeToolUseBlock("record_requirements", {"requirements": requirements})]
    )


def _unparseable_response():
    return _FakeResponse(content=[_FakeTextBlock("sorry, I can't do that")])


def test_clean_single_requirement_response_inserts_one_row(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text(
        "The research project must be at least 25 percent of a full time "
        "equivalent annual enrolment.",
        encoding="utf-8",
    )
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _good_response(
        [
            {
                "kind": "research_project_fraction",
                "operator": ">=",
                "value": "0.25",
                "unit": "fraction",
                "raw_text": "at least 25 percent of a full time equivalent annual enrolment",
                "evidence": "at least 25 percent of a full time equivalent annual enrolment",
                "confidence": 0.95,
            }
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "opportunity_tracker.extractor.evidence.validate_evidence", return_value=True
    )

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert extraction_failed is False
    assert len(requirements) == 1
    assert requirements[0].kind.value == "research_project_fraction"
    fake_client.messages.create.assert_called_once()

    row = conn.execute("SELECT * FROM requirement").fetchone()
    assert row["kind"] == "research_project_fraction"
    assert row["value"] == "0.25"


def test_evidence_validation_failure_produces_zero_rows_no_crash(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Some document text about scholarships.", encoding="utf-8")
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _good_response(
        [
            {
                "kind": "deadline",
                "operator": None,
                "value": "2027-03-15",
                "unit": None,
                "raw_text": "applications close 15 March 2027",
                "evidence": "a completely fabricated evidence string not in the document",
                "confidence": 0.4,
            }
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "opportunity_tracker.extractor.evidence.validate_evidence", return_value=False
    )

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert extraction_failed is False
    assert requirements == []
    row = conn.execute("SELECT COUNT(*) AS n FROM requirement").fetchone()
    assert row["n"] == 0


def test_unparseable_first_response_then_retry_succeeds(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Minimum IELTS overall band score of 6.5.", encoding="utf-8")
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        _unparseable_response(),
        _good_response(
            [
                {
                    "kind": "english_test",
                    "operator": ">=",
                    "value": "6.5",
                    "unit": "IELTS band",
                    "raw_text": "Minimum IELTS overall band score of 6.5.",
                    "evidence": "Minimum IELTS overall band score of 6.5.",
                    "confidence": 0.9,
                }
            ]
        ),
    ]
    mocker.patch("anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "opportunity_tracker.extractor.evidence.validate_evidence", return_value=True
    )

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert extraction_failed is False
    assert len(requirements) == 1
    assert fake_client.messages.create.call_count == 2


def test_both_calls_unparseable_returns_extraction_failed(mocker, conn, tmp_path):
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Some document text.", encoding="utf-8")
    document = _make_document(str(doc_path))

    fake_client = mocker.MagicMock()
    fake_client.messages.create.side_effect = [
        _unparseable_response(),
        _unparseable_response(),
    ]
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    requirements, extraction_failed = extract_requirements(
        document, award_id=1, conn=conn, api_key="sk-test"
    )

    assert requirements == []
    assert extraction_failed is True
    assert fake_client.messages.create.call_count == 2


def test_extract_requirements_raw_returns_validated_candidate_dicts_no_db(mocker):
    document_text = "Minimum IELTS overall band score of 6.5."
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = _good_response(
        [
            {
                "kind": "english_test",
                "operator": ">=",
                "value": "6.5",
                "unit": "IELTS band",
                "raw_text": "Minimum IELTS overall band score of 6.5.",
                "evidence": "Minimum IELTS overall band score of 6.5.",
                "confidence": 0.9,
            }
        ]
    )
    mocker.patch("anthropic.Anthropic", return_value=fake_client)

    from opportunity_tracker.extractor.run import extract_requirements_raw

    results = extract_requirements_raw(document_text, api_key="sk-test")

    assert results == [
        {
            "kind": "english_test",
            "operator": ">=",
            "value": "6.5",
            "unit": "IELTS band",
            "raw_text": "Minimum IELTS overall band score of 6.5.",
            "evidence": "Minimum IELTS overall band score of 6.5.",
            "confidence": 0.9,
        }
    ]
    fake_client.messages.create.assert_called_once()
