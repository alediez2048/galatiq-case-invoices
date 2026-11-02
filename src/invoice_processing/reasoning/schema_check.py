"""Guard for JSON schemas sent to the model as structured-output or tool schemas.

xAI structured outputs reject some JSON-schema keywords; this lists any that appear so a
test fails before a live call does.
"""

from typing import Any

_FORBIDDEN = ("not", "if", "then", "else")
# Keys whose values are maps of name -> subschema (names there are not keywords).
_SCHEMA_MAPS = ("properties", "$defs", "definitions", "patternProperties")
# Keys whose values are data, not schemas.
_DATA_KEYS = ("default", "const", "enum", "examples")


def unsupported_keywords(schema: dict[str, Any]) -> list[str]:
    found: list[str] = []
    if schema.get("type") != "object":
        found.append("root_not_object")
    _walk(schema, found)
    return found


def _walk(node: Any, found: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, found)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in _DATA_KEYS:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            for subschema in value.values():
                _walk(subschema, found)
            continue
        if key in _FORBIDDEN:
            found.append(key)
        elif key == "allOf" and isinstance(value, list) and len(value) > 1:
            found.append("allOf")
        _walk(value, found)
