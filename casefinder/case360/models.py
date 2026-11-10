"""Validate the pinned protocol subset; no workflow or approval decisions live here."""

from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = json.loads(Path(__file__).with_name("protocol.json").read_text())


def matches(value: object, schema: dict) -> bool:
    if "$ref" in schema:
        return matches(value, SCHEMA["$defs"][schema["$ref"].split("/")[-1]])
    if "oneOf" in schema:
        return sum(matches(value, child) for child in schema["oneOf"]) == 1
    if "anyOf" in schema:
        return any(matches(value, child) for child in schema["anyOf"])
    if "const" in schema and value != schema["const"]:
        return False
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            return False
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            return False
        return all(matches(value[key], spec) for key, spec in properties.items() if key in value)
    if kind == "string":
        return isinstance(value, str) and ("pattern" not in schema
                                          or re.fullmatch(schema["pattern"], value) is not None)
    if kind == "integer":
        return (type(value) is int and value >= schema.get("minimum", value)
                and value <= schema.get("maximum", value))
    if kind == "boolean":
        return type(value) is bool
    if kind == "null":
        return value is None
    return kind is None


def valid_message(value: object) -> bool:
    return matches(value, SCHEMA)
