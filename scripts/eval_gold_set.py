#!/usr/bin/env python
"""Gold-set evaluation harness. Spec §9.2, §9.3, §10 (Milestone 1 kill criterion).

NOT a pytest suite — spec §9.2 is explicit that the extractor gets evaluation, not tests.
This script reads real fixture files from tests/fixtures/gold_set/ and calls the real
Anthropic API via extractor.run.extract_requirements_raw. It is meant to be run by the
operator once that directory holds real hand-annotated documents:

    uv run python scripts/eval_gold_set.py

Prints per-kind recall/precision, never aggregated (spec §9.2: "aggregate accuracy hides
the single field that ruins a cycle"), and exits non-zero with a loud warning if any of the
three Milestone-1 kill-criterion kinds (deadline, thesis_required,
research_project_fraction) falls below config.TRUST_THRESHOLD_DEFAULT recall.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from opportunity_tracker import config
from opportunity_tracker.extractor.run import extract_requirements_raw
from opportunity_tracker.models import RequirementKind

GOLD_SET_DIR = Path("tests/fixtures/gold_set")

KILL_CRITERION_KINDS = {
    RequirementKind.DEADLINE.value,
    RequirementKind.THESIS_REQUIRED.value,
    RequirementKind.RESEARCH_PROJECT_FRACTION.value,
}


def _normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.strip().lower().split())


def compute_recall_precision(extracted: list[dict], annotations: list[dict]) -> dict[str, dict]:
    """Per-kind recall/precision. `extracted` and `annotations` are lists of dicts, each
    with at least a 'kind' key (str) and a 'value' key (str | None). Never aggregates
    across kinds (spec §9.2). Value comparison is simple normalized-string equality
    (case-insensitive, whitespace-collapsed) — this is the "simple equality" half of the
    spec's matching rule; fuzzy text matching is instead what the evidence validator
    (extractor/evidence.py, Task 17) applies to evidence spans against source document
    text, a different comparison than value-to-value scoring here."""
    kinds = {item["kind"] for item in extracted} | {item["kind"] for item in annotations}
    results: dict[str, dict] = {}
    for kind in kinds:
        gold = [a for a in annotations if a["kind"] == kind]
        found = [e for e in extracted if e["kind"] == kind]
        gold_values = [_normalize_value(a.get("value")) for a in gold]
        found_values = [_normalize_value(e.get("value")) for e in found]

        true_positives = 0
        remaining_found = list(found_values)
        for gold_value in gold_values:
            if gold_value in remaining_found:
                remaining_found.remove(gold_value)
                true_positives += 1

        total_gold = len(gold_values)
        total_found = len(found_values)
        recall = true_positives / total_gold if total_gold else 1.0
        precision = (
            true_positives / total_found if total_found else (1.0 if total_gold == 0 else 0.0)
        )

        results[kind] = {
            "recall": recall,
            "precision": precision,
            "true_positives": true_positives,
            "gold_count": total_gold,
            "found_count": total_found,
        }
    return results


def _load_gold_set(directory: Path) -> list[dict]:
    documents = []
    for file_path in sorted(directory.glob("*.json")):
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        documents.append({
            "name": file_path.name,
            "document_text": payload["document_text"],
            "annotations": payload["annotations"],
        })
    return documents


def _merge_kind_results(accumulated: dict[str, dict], new: dict[str, dict]) -> dict[str, dict]:
    for kind, stats in new.items():
        if kind not in accumulated:
            accumulated[kind] = {"true_positives": 0, "gold_count": 0, "found_count": 0}
        accumulated[kind]["true_positives"] += stats["true_positives"]
        accumulated[kind]["gold_count"] += stats["gold_count"]
        accumulated[kind]["found_count"] += stats["found_count"]
    return accumulated


def main() -> int:
    if not GOLD_SET_DIR.exists() or not any(GOLD_SET_DIR.glob("*.json")):
        print(
            f"No gold-set fixtures found at {GOLD_SET_DIR}. Populating it is a manual "
            "operator step (spec §9.2: run discovery for real, hand-annotate the results) "
            "and is not part of the automated test suite."
        )
        return 0

    api_key = config.get_anthropic_api_key()
    documents = _load_gold_set(GOLD_SET_DIR)

    accumulated: dict[str, dict] = {}
    for doc in documents:
        extracted = extract_requirements_raw(doc["document_text"], api_key)
        per_doc_results = compute_recall_precision(extracted, doc["annotations"])
        accumulated = _merge_kind_results(accumulated, per_doc_results)
        print(f"Scored {doc['name']}: {len(extracted)} requirement(s) extracted.")

    print()
    print(f"{'Kind':<32}{'Recall':>10}{'Precision':>12}{'TP/Gold':>12}{'Found':>8}")
    print("-" * 74)

    kill_criterion_failed: list[str] = []
    recall_by_kind: dict[str, float] = {}
    for kind in sorted(k.value for k in RequirementKind):
        stats = accumulated.get(kind, {"true_positives": 0, "gold_count": 0, "found_count": 0})
        gold_count = stats["gold_count"]
        found_count = stats["found_count"]
        true_positives = stats["true_positives"]
        recall = true_positives / gold_count if gold_count else float("nan")
        recall_display = f"{recall:.2%}" if gold_count else "n/a"
        precision_display = (
            f"{(true_positives / found_count):.2%}" if found_count else "n/a"
        )
        print(
            f"{kind:<32}{recall_display:>10}{precision_display:>12}"
            f"{f'{true_positives}/{gold_count}':>12}{found_count:>8}"
        )
        if gold_count:
            # Only kinds with at least one gold example get a recorded recall -- a kind
            # absent here (no gold examples yet) stays untrusted by default when the CLI's
            # evaluator.trust.is_trusted reads this file (missing key -> 0.0), matching
            # principle 6: trust is measured, never assumed.
            recall_by_kind[kind] = recall
        if kind in KILL_CRITERION_KINDS and gold_count and recall < config.TRUST_THRESHOLD_DEFAULT:
            kill_criterion_failed.append(kind)

    recall_path = Path("data/gold_set_recall.json")
    recall_path.write_text(json.dumps(recall_by_kind, indent=2), encoding="utf-8")
    print(f"\nPer-kind recall written to {recall_path} for `optrack evaluate-all` to use.")

    print()
    if kill_criterion_failed:
        print(
            "!!! KILL CRITERION FAILED !!!\n"
            f"Recall below trust threshold ({config.TRUST_THRESHOLD_DEFAULT:.0%}) for: "
            f"{', '.join(kill_criterion_failed)}.\n"
            "Per spec §10 (Milestone 1): stop and reconsider the extraction approach — "
            "everything downstream is worthless without these three kinds passing."
        )
        return 1

    print("All kill-criterion kinds cleared the trust threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
