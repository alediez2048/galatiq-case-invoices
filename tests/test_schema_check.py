import pytest

from invoice_processing import schemas
from invoice_processing.reasoning.schema_check import unsupported_keywords

MODEL_FACING = [
    schemas.ApprovalRecommendation,
    schemas.Critique,
    schemas.ExtractionProposals,
    schemas.RecommendationOutput,
    schemas.CritiqueOutput,
]


@pytest.mark.parametrize("model", MODEL_FACING, ids=lambda m: m.__name__)
def test_model_facing_schemas_use_only_supported_keywords(model):
    schema = model.model_json_schema()
    assert schema["type"] == "object"
    assert unsupported_keywords(schema) == []


def test_reports_not_nested_anywhere():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "array", "items": {"not": {"type": "string"}}}},
    }
    assert unsupported_keywords(schema) == ["not"]


def test_reports_conditionals_and_multi_allof_in_defs():
    schema = {
        "type": "object",
        "$defs": {
            "X": {"if": {"type": "string"}, "then": {}, "else": {}},
            "Y": {"allOf": [{"type": "object"}, {"type": "object"}]},
            "Z": {"allOf": [{"$ref": "#/$defs/X"}]},  # single-subschema allOf is fine
        },
    }
    assert sorted(unsupported_keywords(schema)) == ["allOf", "else", "if", "then"]


def test_property_named_like_a_keyword_is_not_reported():
    schema = {"type": "object", "properties": {"not": {"type": "string"}}}
    assert unsupported_keywords(schema) == []


def test_root_must_be_an_object():
    assert unsupported_keywords({"type": "array", "items": {}}) == ["root_not_object"]
