"""Example schema and validation for the SFT dataset."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

EXAMPLE_SCHEMA_VERSION = "mediread.sft-example/1"

CATEGORIES = (
    "test_explanation",        # A
    "result_explanation",      # B
    "high_low",                # C
    "missing_information",     # D
    "qualitative",             # E
    "unsupported_test",        # F
    "follow_up",               # G
    "safety_refusal",          # H
    "adversarial",             # I
    "extraction_uncertainty",  # J
)

SPLITS = ("train", "validation", "test")

REQUIRED_FIELDS = (
    "example_id", "schema_version", "category", "messages", "output",
    "knowledge_ids", "evidence_ids", "safety_behaviour", "permitted_numbers",
    "split", "provenance", "validation",
)

# Words that must never appear in a generated answer: they assert a diagnosis,
# treatment, medication change or urgency.
_FORBIDDEN = re.compile(
    r"\b(diagnos\w*|prescri\w*|medicat\w*|dosage|\bdose\b|treat\w*|cure|urgent\w*|"
    r"emergency|you (?:have|definitely have))\b",
    re.IGNORECASE,
)
_RANGE = re.compile(r"\b\d+(?:\.\d+)?\s*[-\u2013]\s*\d+(?:\.\d+)?\b|\b[<>]\s*=?\s*\d+(?:\.\d+)?\b")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PII = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b|\b\d{10,}\b")


@dataclass
class ExampleCheck:
    example_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


_NEGATION = re.compile(r"\b(?:not|cannot|can't|won't|will not|does not|do not|no)\b", re.IGNORECASE)


def _asserts_unsafe(text: str) -> bool:
    """True only for affirmative statements about diagnosis/treatment/urgency.

    The refusal templates say "does not diagnose" and "does not recommend … medication";
    a blanket word match would reject exactly the examples we want to teach.
    """
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _NEGATION.search(sentence):
            continue
        if _FORBIDDEN.search(sentence):
            return True
    return False


def validate_example(example: dict[str, Any]) -> ExampleCheck:
    check = ExampleCheck(example_id=str(example.get("example_id", "?")))
    for name in REQUIRED_FIELDS:
        if name not in example:
            check.errors.append(f"missing field {name}")
    if check.errors:
        return check
    if example["schema_version"] != EXAMPLE_SCHEMA_VERSION:
        check.errors.append("wrong schema_version")
    if example["category"] not in CATEGORIES:
        check.errors.append(f"unknown category {example['category']}")
    if example["split"] not in SPLITS:
        check.errors.append(f"unknown split {example['split']}")

    output = str(example["output"])
    if not output.strip():
        check.errors.append("empty output")
    if len(output) > 800:
        check.errors.append("output longer than 800 characters")
    if _asserts_unsafe(output):
        check.errors.append("output asserts diagnosis/treatment/urgency")
    if _PII.search(output):
        check.errors.append("output contains something that looks like PII")

    permitted = [str(value) for value in example.get("permitted_numbers", [])]
    allowed = set(permitted)
    # A number in the answer must be one of the facts we supplied.
    for number in _NUMBER.findall(output):
        if number not in allowed:
            check.errors.append(f"unsupported number {number!r} in output")
    # Ranges are only allowed if that exact range text was permitted.
    for span in _RANGE.findall(output):
        if span not in permitted:
            check.errors.append(f"unsupported range {span!r} in output")

    messages = example["messages"]
    if not isinstance(messages, list) or len(messages) < 2:
        check.errors.append("messages must contain a user and an assistant turn")
    else:
        roles = [message.get("role") for message in messages]
        if roles[-1] != "assistant":
            check.errors.append("last message must be the assistant")
        if "user" not in roles:
            check.errors.append("no user message")
        if messages[-1].get("content") != output:
            check.errors.append("assistant message does not match output")

    for knowledge_id in example.get("knowledge_ids", []):
        if not isinstance(knowledge_id, str) or not knowledge_id:
            check.errors.append("bad knowledge id")
    return check


def is_valid(example: dict[str, Any]) -> bool:
    return validate_example(example).ok
