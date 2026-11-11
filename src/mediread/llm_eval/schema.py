"""Strict response-schema validation (no external dependency)."""

from __future__ import annotations

from typing import Any

_FIELDS = {
    "rewrite": {
        "rewritten_explanation": str,
        "used_source_ids": list,
        "limitations_acknowledged": bool,
    },
    "followup": {
        "answer": str,
        "answerable_from_context": bool,
        "used_source_ids": list,
        "limitation": str,
    },
}


class SchemaError(ValueError):
    pass


def parse_json(text: str) -> Any:
    """Extract a JSON object from model text, tolerating stray fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise SchemaError("no JSON object in response")
    import json

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON: {exc}") from exc


def validate_response(task: str, payload: Any) -> dict:
    expected = _FIELDS[task]
    if not isinstance(payload, dict):
        raise SchemaError("response is not an object")
    missing = [key for key in expected if key not in payload]
    if missing:
        raise SchemaError(f"missing fields: {missing}")
    extra = [key for key in payload if key not in expected]
    if extra:
        raise SchemaError(f"unexpected fields: {extra}")
    for key, kind in expected.items():
        value = payload[key]
        if kind is bool:
            if not isinstance(value, bool):
                raise SchemaError(f"{key} must be boolean")
        elif not isinstance(value, kind):
            raise SchemaError(f"{key} must be {kind.__name__}")
    if not isinstance(payload["used_source_ids"], list) or not all(
        isinstance(item, str) for item in payload["used_source_ids"]
    ):
        raise SchemaError("used_source_ids must be a list of strings")
    text_key = "rewritten_explanation" if task == "rewrite" else "answer"
    if not payload[text_key].strip():
        raise SchemaError(f"{text_key} is empty")
    if task == "followup":
        if not payload["answerable_from_context"] and not payload["limitation"].strip():
            raise SchemaError("limitation is required when the question is not answerable")
        # A non-empty limitation on an answerable question is acceptable: models
        # commonly append a lab-specific caveat. Only the missing-limitation case
        # is an error.
    return payload
