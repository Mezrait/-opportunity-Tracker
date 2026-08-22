"""Unit test of the gold-set harness's SCORING logic only — compute_recall_precision, a
pure function over small synthetic in-memory extracted/annotation pairs. This does NOT run
the full scripts/eval_gold_set.py script against tests/fixtures/gold_set/: that directory
is empty until the operator populates it with real hand-annotated documents (spec §9.2),
and running the script for real is a manual step, not part of the automated test suite."""
import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_gold_set.py"
_spec = importlib.util.spec_from_file_location("eval_gold_set", SCRIPT_PATH)
eval_gold_set = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_gold_set)

compute_recall_precision = eval_gold_set.compute_recall_precision


def test_compute_recall_precision_perfect_match():
    extracted = [
        {"kind": "deadline", "value": "2027-03-31"},
        {"kind": "thesis_required", "value": "true"},
    ]
    annotations = [
        {"kind": "deadline", "value": "2027-03-31", "operator": None},
        {"kind": "thesis_required", "value": "true", "operator": None},
    ]
    results = compute_recall_precision(extracted, annotations)
    assert results["deadline"]["recall"] == 1.0
    assert results["deadline"]["precision"] == 1.0
    assert results["thesis_required"]["recall"] == 1.0


def test_compute_recall_precision_missed_requirement_hurts_recall_not_precision():
    # Gold set has two research_project_fraction annotations, extractor only found one.
    extracted = [
        {"kind": "research_project_fraction", "value": "0.25"},
    ]
    annotations = [
        {"kind": "research_project_fraction", "value": "0.25", "operator": ">="},
        {"kind": "research_project_fraction", "value": "0.10", "operator": ">="},
    ]
    results = compute_recall_precision(extracted, annotations)
    assert results["research_project_fraction"]["recall"] == 0.5
    assert results["research_project_fraction"]["precision"] == 1.0
    assert results["research_project_fraction"]["true_positives"] == 1
    assert results["research_project_fraction"]["gold_count"] == 2


def test_compute_recall_precision_hallucinated_value_hurts_precision_not_recall():
    # Extractor found a value with no matching gold annotation for that kind at all.
    extracted = [
        {"kind": "min_grade", "value": "distinction"},
    ]
    annotations = []
    results = compute_recall_precision(extracted, annotations)
    assert results["min_grade"]["recall"] == 1.0  # no gold requirement to miss
    assert results["min_grade"]["precision"] == 0.0
    assert results["min_grade"]["found_count"] == 1
    assert results["min_grade"]["gold_count"] == 0


def test_compute_recall_precision_value_matching_is_case_and_whitespace_insensitive():
    extracted = [{"kind": "english_test", "value": "  IELTS 6.5  "}]
    annotations = [{"kind": "english_test", "value": "ielts 6.5", "operator": None}]
    results = compute_recall_precision(extracted, annotations)
    assert results["english_test"]["recall"] == 1.0
    assert results["english_test"]["true_positives"] == 1
