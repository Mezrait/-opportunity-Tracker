from opportunity_tracker.db import get_connection, init_db
from opportunity_tracker.models import (
    Award,
    Bucket,
    DiscoveryRun,
    DiscoveryRunStatus,
    Evaluation,
)
from opportunity_tracker.reporter.markdown import render_report, sort_evaluations


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


def _make_evaluation(
    eval_id: int,
    award_id: int,
    bucket: Bucket,
    unknown_count: int,
    days_until_deadline: int,
    funding_completeness: float,
    per_requirement_outcomes: dict | None = None,
) -> Evaluation:
    return Evaluation(
        id=eval_id,
        award_id=award_id,
        profile_version=1,
        evaluated_at="2026-08-22T00:00:00",
        bucket=bucket,
        sort_keys={
            "unknown_count": unknown_count,
            "days_until_deadline": days_until_deadline,
            "funding_completeness": funding_completeness,
        },
        per_requirement_outcomes=per_requirement_outcomes or {},
    )


# (eval_id, award_id, bucket, unknown_count, days_until_deadline, funding_completeness, institution)
CASES = [
    (1, 1, Bucket.LIKELY_BLOCKED, 0, 40, 0.5, "Zeta University"),
    (2, 2, Bucket.ACT_NOW, 0, 10, 1.0, "Alpha University"),
    (3, 3, Bucket.UNKNOWN_GATED, 1, 20, 0.5, "Beta University"),
    (4, 4, Bucket.ACT_NOW, 0, 5, 0.8, "Gamma University"),
    (5, 5, Bucket.ELIGIBLE_LATER, 0, 200, 0.5, "Delta University"),
    (6, 6, Bucket.UNKNOWN_GATED, 0, 15, 0.5, "Epsilon University"),
    (7, 7, Bucket.COVERAGE_GAP, 0, 999999, 0.0, "Zeta2 University"),
    (8, 8, Bucket.ACT_NOW, 0, 5, 0.9, "Eta University"),
]

EXPECTED_ORDER_BY_AWARD_ID = [8, 4, 2, 5, 6, 3, 1, 7]
EXPECTED_ORDER_BY_INSTITUTION = [
    "Eta University", "Gamma University", "Alpha University",
    "Delta University",
    "Epsilon University", "Beta University",
    "Zeta University",
    "Zeta2 University",
]


def _build_awards_and_evaluations():
    awards_by_id = {
        award_id: _make_award(award_id, institution)
        for _, award_id, _, _, _, _, institution in CASES
    }
    evaluations = [
        _make_evaluation(eval_id, award_id, bucket, unknown_count, days, funding)
        for eval_id, award_id, bucket, unknown_count, days, funding, _ in CASES
    ]
    return awards_by_id, evaluations


def test_sort_evaluations_orders_by_bucket_then_sort_keys():
    _, evaluations = _build_awards_and_evaluations()
    sorted_evals = sort_evaluations(evaluations)
    assert [e.award_id for e in sorted_evals] == EXPECTED_ORDER_BY_AWARD_ID


def test_render_report_lists_buckets_and_institutions_in_correct_order():
    awards_by_id, evaluations = _build_awards_and_evaluations()
    conn = get_connection(":memory:")
    init_db(conn)

    report = render_report(evaluations, awards_by_id, [], conn)

    bucket_headers = [
        "Act Now", "Eligible, Later", "Unknown-Gated", "Likely Blocked", "Coverage Gap",
    ]
    header_positions = [report.index(f"## {title}") for title in bucket_headers]
    assert header_positions == sorted(header_positions)

    institution_positions = [report.index(name) for name in EXPECTED_ORDER_BY_INSTITUTION]
    assert institution_positions == sorted(institution_positions)

    conn.close()


def test_render_report_includes_requirement_source_and_retrieved_at():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO scheme (name, funder, jurisdiction) VALUES ('S', 'F', 'AU')")
    conn.execute(
        "INSERT INTO award (scheme_id, institution, country, degree_levels, "
        "intake_year, canonical_url) VALUES (1, 'UWA', 'AU', '[\"phd\"]', 2027, "
        "'https://uwa.edu.au/award')"
    )
    conn.execute(
        "INSERT INTO document (url, source_tier, fetch_method, content_hash, "
        "text_path, retrieved_at, fetch_status, degraded) VALUES "
        "('https://uwa.edu.au/rules', 1, 'http', 'abc123', 'docs/1.txt', "
        "'2026-08-01T00:00:00', 'ok', 0)"
    )
    conn.execute(
        "INSERT INTO requirement (award_id, document_id, kind, operator, value, "
        "unit, raw_text, evidence, confidence, extracted_at, human_verified) VALUES "
        "(1, 1, 'research_project_fraction', '>=', '0.25', 'fraction', "
        "'at least 25 percent FTE', 'the project must be at least 25 percent FTE', "
        "0.9, '2026-08-22T00:00:00', 0)"
    )
    conn.commit()

    award = _make_award(1, "UWA")
    evaluation = _make_evaluation(
        1, 1, Bucket.LIKELY_BLOCKED, 0, 30, 0.5,
        per_requirement_outcomes={"research_project_fraction": "fail"},
    )

    report = render_report([evaluation], {1: award}, [], conn)

    assert "https://uwa.edu.au/rules" in report
    assert "2026-08-01T00:00:00" in report
    conn.close()


def test_render_report_handles_no_evaluations():
    conn = get_connection(":memory:")
    init_db(conn)
    report = render_report([], {}, [], conn)
    assert "No evaluations yet" in report
    conn.close()


def _make_discovery_run(considered=42, with_candidates=30, available=42, searches_used=90):
    return DiscoveryRun(
        id=1,
        filter_id=1,
        filter_content_hash="hash123",
        started_at="2026-08-22T00:00:00",
        completed_at="2026-08-22T00:10:00",
        institutions_considered=considered,
        institutions_with_candidates=with_candidates,
        searches_used=searches_used,
        status=DiscoveryRunStatus.COMPLETED,
        institutions_available=available,
    )


def test_render_report_discovery_coverage_summary():
    conn = get_connection(":memory:")
    init_db(conn)
    report = render_report([], {}, [_make_discovery_run()], conn)
    assert "## Discovery coverage" in report
    assert "42" in report
    assert "30" in report
    assert "12" in report  # NO_CANDIDATE_FOUND = considered - with_candidates
    conn.close()


# --- Whole-branch review I4: a capped run must not read as complete coverage --------------

def test_coverage_table_flags_a_capped_run_as_partial():
    conn = get_connection(":memory:")
    init_db(conn)
    # institution_cap=50 against a country with 240 listed institutions: 190 were never
    # searched and never recorded as NO_CANDIDATE_FOUND, they are simply absent.
    run = _make_discovery_run(considered=50, with_candidates=12, available=240)

    report = render_report([], {}, [run], conn)

    assert "50 / 240" in report
    assert "partial" in report
    assert "190 institution(s) not searched" in report
    conn.close()


def test_coverage_table_marks_an_uncapped_run_complete():
    conn = get_connection(":memory:")
    init_db(conn)
    run = _make_discovery_run(considered=42, with_candidates=30, available=42)

    report = render_report([], {}, [run], conn)

    assert "42 / 42" in report
    assert "complete" in report
    assert "partial" not in report
    conn.close()
