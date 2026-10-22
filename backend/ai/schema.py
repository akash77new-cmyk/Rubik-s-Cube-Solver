"""A small JSON Schema checker for tool arguments and model answers.

AI rule 3 and rule 6: everything the model sends us - the arguments of a tool call
and its final answer - is checked in code before it is used. This module supports
exactly the JSON Schema keywords the app uses:

    type, properties, required, additionalProperties (false only), enum,
    minimum / maximum, minLength / maxLength, items, minItems / maxItems

``description`` is allowed anywhere (it is for the model, not for checking).
Any other keyword raises an error, so a schema can never silently check less
than it seems to.
"""

from __future__ import annotations

from typing import Any, Dict, List

#: Keywords validate() understands.
SUPPORTED = {
    "type", "description", "properties", "required", "additionalProperties", "enum",
    "minimum", "maximum", "minLength", "maxLength", "items", "minItems", "maxItems",
}

#: Keywords Gemini accepts in a function declaration (a subset of OpenAPI 3).
#: Gemini rejects ``additionalProperties``, so it is checked here but not sent.
GEMINI_KEYWORDS = SUPPORTED - {"additionalProperties"}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        # JSON has one number type: 3 and 3.0 are the same integer.
        if isinstance(value, bool):
            return False
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ValueError(f"Unsupported schema type: {expected!r}")


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    return {dict: "object", list: "array", str: "string", int: "integer", float: "number"}.get(
        type(value), type(value).__name__
    )


def validate(value: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """All the ways ``value`` breaks ``schema``, as readable messages ([] = valid)."""
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise ValueError(f"Unsupported schema keyword(s) at {path}: {sorted(unknown)}")

    expected = schema.get("type")
    if expected is not None and not _type_ok(value, expected):
        return [f"{path}: expected {expected}, got {_type_name(value)}"]

    errors: List[str] = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must have at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: must have at most {schema['maxLength']} characters")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: must be at most {schema['maximum']}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: must have at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: must have at most {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{index}]"))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing required field '{name}'")
        for name, item in value.items():
            if name in properties:
                errors.extend(validate(item, properties[name], f"{path}.{name}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected field '{name}'")
    return errors


def check_schema(schema: Dict[str, Any], path: str = "$") -> None:
    """Raise ValueError if the schema (or a part of it) uses an unsupported keyword."""
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise ValueError(f"Unsupported schema keyword(s) at {path}: {sorted(unknown)}")
    for name, sub in schema.get("properties", {}).items():
        check_schema(sub, f"{path}.{name}")
    if "items" in schema:
        check_schema(schema["items"], f"{path}[]")


def to_gemini_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """The same schema, with only the keywords Gemini accepts (recursively)."""
    result: Dict[str, Any] = {}
    for key, value in schema.items():
        if key not in GEMINI_KEYWORDS:
            continue
        if key == "properties":
            value = {name: to_gemini_schema(sub) for name, sub in value.items()}
        elif key == "items":
            value = to_gemini_schema(value)
        result[key] = value
    return result
