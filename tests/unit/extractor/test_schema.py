"""Regression test against schema/model drift: REQUIREMENT_JSON_SCHEMA's closed `kind`
enum must always match models.RequirementKind exactly, since schema.py builds it from
that enum rather than hardcoding a second list."""
from opportunity_tracker.extractor.schema import REQUIREMENT_JSON_SCHEMA
from opportunity_tracker.models import RequirementKind


def test_schema_kind_enum_matches_requirement_kind_exactly():
    kind_schema = (
        REQUIREMENT_JSON_SCHEMA["properties"]["requirements"]["items"]["properties"]["kind"]
    )
    assert set(kind_schema["enum"]) == {k.value for k in RequirementKind}


def test_schema_requires_kind_raw_text_evidence():
    item_schema = REQUIREMENT_JSON_SCHEMA["properties"]["requirements"]["items"]
    assert set(item_schema["required"]) == {"kind", "raw_text", "evidence"}


def test_schema_top_level_requires_requirements_array():
    assert REQUIREMENT_JSON_SCHEMA["required"] == ["requirements"]
    assert REQUIREMENT_JSON_SCHEMA["properties"]["requirements"]["type"] == "array"
