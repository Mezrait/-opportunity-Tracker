"""Requirement-extraction JSON schema. Closed `kind` enum sourced from
models.RequirementKind -- never a second hardcoded list, so schema and model can never
drift apart. Shaped as an Anthropic tool's `input_schema` (spec section 6.2)."""
from __future__ import annotations

from opportunity_tracker.models import RequirementKind

REQUIREMENT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "description": (
                "Every discrete admission/scholarship requirement found in the "
                "document, in the order encountered."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [k.value for k in RequirementKind],
                        "description": "The closed requirement category this entry belongs to.",
                    },
                    "operator": {
                        "type": ["string", "null"],
                        "description": (
                            "Comparison symbol attached to a numeric/graded threshold "
                            "(e.g. '>=', '=', '<='), or null if the document states "
                            "no such comparison."
                        ),
                    },
                    "value": {
                        "type": ["string", "null"],
                        "description": "The threshold or stated value, or null if not stated.",
                    },
                    "unit": {
                        "type": ["string", "null"],
                        "description": "The unit for `value` (e.g. 'percent', 'WAM'), or null.",
                    },
                    "raw_text": {
                        "type": "string",
                        "description": "The verbatim clause this requirement was extracted from.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": (
                            "A short quotation copied character-for-character from "
                            "the source document -- never paraphrased."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Extraction confidence, between 0 and 1.",
                    },
                },
                "required": ["kind", "raw_text", "evidence"],
            },
        },
    },
    "required": ["requirements"],
}
