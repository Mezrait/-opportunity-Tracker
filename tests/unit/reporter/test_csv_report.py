import csv
import io

from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.models import Award, Bucket, Evaluation
from opportunity_tracker.reporter.csv_report import render_csv


def _make_award(award_id: int, institution: str) -> Award:
    return Award(
        id=award_id,
        scheme_id=None,
        institution=institution,
        country="AU",
        degree_levels=["phd"],
        intake_year=2027,
        canonical_url=f"https://example.edu/{award_id}",
    )


def _make_evaluation(eval_id, award_id, bucket, unknown_count, days, funding, outcomes=None):
    return Evaluation(
        id=eval_id,
        award_id=award_id,
        profile_version=1,
        evaluated_at="2026-08-22T00:00:00",
        bucket=bucket,
        sort_keys={
            "unknown_count": unknown_count,
            "days_until_deadline": days,
            "funding_completeness": funding,
        },
        per_requirement_outcomes=outcomes or {},
    )


def test_render_csv_header_row():
    conn = get_connection(":memory:")
    init_db(conn)
    csv_text = render_csv([], {}, conn)
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == [
        "institution", "bucket", "days_remaining", "unknown_count",
        "min_grade", "research_project_fraction", "thesis_required", "english_test",
        "nationality", "deadline", "degree_level", "intake_year",
    ]
    conn.close()


def test_render_csv_row_values_match_evaluation_fields():
    conn = get_connection(":memory:")
    init_db(conn)
    award = _make_award(1, "UWA")
    evaluation = _make_evaluation(
        1, 1, Bucket.LIKELY_BLOCKED, 1, 45, 0.6,
        outcomes={"research_project_fraction": "fail", "deadline": "pass"},
    )
    csv_text = render_csv([evaluation], {1: award}, conn)
    reader = csv.DictReader(io.StringIO(csv_text))
    row = next(reader)
    assert row["institution"] == "UWA"
    assert row["bucket"] == "LIKELY_BLOCKED"
    assert row["days_remaining"] == "45"
    assert row["unknown_count"] == "1"
    assert row["research_project_fraction"] == "fail"
    assert row["deadline"] == "pass"
    assert row["min_grade"] == "unknown"
    conn.close()


def test_render_csv_sort_order_matches_markdown_reporter():
    conn = get_connection(":memory:")
    init_db(conn)
    awards_by_id = {
        1: _make_award(1, "Zeta University"),
        2: _make_award(2, "Alpha University"),
        3: _make_award(3, "Gamma University"),
    }
    evaluations = [
        _make_evaluation(1, 1, Bucket.LIKELY_BLOCKED, 0, 40, 0.5),
        _make_evaluation(2, 2, Bucket.ACT_NOW, 0, 10, 1.0),
        _make_evaluation(3, 3, Bucket.ACT_NOW, 0, 5, 0.8),
    ]
    csv_text = render_csv(evaluations, awards_by_id, conn)
    reader = csv.DictReader(io.StringIO(csv_text))
    institutions = [row["institution"] for row in reader]
    assert institutions == ["Gamma University", "Alpha University", "Zeta University"]
    conn.close()
