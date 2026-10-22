"""The schema checker used for tool arguments and model answers."""

import pytest

from backend.ai.schema import check_schema, to_gemini_schema, validate

ANSWER = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "minLength": 1, "maxLength": 10, "description": "text"},
        "step": {"type": "integer", "minimum": 1, "maximum": 20},
        "tags": {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": ["a", "b"]}},
    },
    "required": ["answer"],
    "additionalProperties": False,
}


def test_a_valid_value_has_no_errors():
    assert validate({"answer": "ok", "step": 3, "tags": ["a", "b"]}, ANSWER) == []


def test_every_problem_is_reported_with_its_path():
    errors = validate({"answer": "", "step": 0, "tags": ["a", "c", "b"], "extra": 1}, ANSWER)
    assert errors == [
        "$.answer: must have at least 1 characters",
        "$.step: must be at least 1",
        "$.tags: must have at most 2 items",
        "$.tags[1]: must be one of ['a', 'b']",
        "$: unexpected field 'extra'",
    ]


def test_missing_fields_and_wrong_types():
    assert validate({}, ANSWER) == ["$: missing required field 'answer'"]
    assert validate("text", ANSWER) == ["$: expected object, got string"]
    assert validate({"answer": 5}, ANSWER) == ["$.answer: expected string, got integer"]


def test_integers_follow_json_rules():
    schema = {"type": "integer"}
    assert validate(3, schema) == [] and validate(3.0, schema) == []  # same number in JSON
    assert validate(3.5, schema) == ["$: expected integer, got number"]
    assert validate(True, schema) == ["$: expected integer, got boolean"]  # bool is not a number


def test_unsupported_keywords_are_refused_not_ignored():
    with pytest.raises(ValueError, match="pattern"):
        check_schema({"type": "object", "properties": {"x": {"type": "string", "pattern": "a+"}}})
    with pytest.raises(ValueError, match="oneOf"):
        validate(1, {"oneOf": []})


def test_gemini_gets_the_schema_without_additional_properties():
    sent = to_gemini_schema(ANSWER)
    assert "additionalProperties" not in sent
    assert sent["properties"]["tags"]["items"] == {"type": "string", "enum": ["a", "b"]}
    assert sent["required"] == ["answer"]
