"""Fixed evaluation dataset: cases, expected outcomes, and context bundles.

A case carries only what the deterministic engine *permits*:

* ``facts``            verified values, units and printed reference text;
* ``allowed_sections`` explanation text the engine emitted;
* ``blocked_sections`` section key -> reason (the hidden text is never included);
* ``approved_sources`` the only source ids a response may cite.

No patient identifiers, no page images, no hidden/blocked content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATASET_VERSION = "mediread.llm-eval/1"


@dataclass(frozen=True)
class Expected:
    answerable: bool
    must_include_any: tuple[str, ...] = ()
    must_not_include: tuple[str, ...] = ()
    required_source_ids: tuple[str, ...] = ()
    forbidden_categories: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    task: str                     # "rewrite" | "followup"
    scenario: str
    source: str                   # "corpus" | "synthetic" | "ocr"
    facts: dict[str, Any]
    allowed_sections: dict[str, str]
    blocked_sections: dict[str, str]
    approved_sources: list[dict[str, str]]
    expected: Expected
    question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "task": self.task,
            "scenario": self.scenario,
            "source": self.source,
            "facts": self.facts,
            "allowed_sections": self.allowed_sections,
            "blocked_sections": self.blocked_sections,
            "approved_sources": self.approved_sources,
            "question": self.question,
            "expected": {
                "answerable": self.expected.answerable,
                "must_include_any": list(self.expected.must_include_any),
                "must_not_include": list(self.expected.must_not_include),
                "required_source_ids": list(self.expected.required_source_ids),
                "forbidden_categories": list(self.expected.forbidden_categories),
                "note": self.expected.note,
            },
        }


@dataclass
class Dataset:
    version: str
    knowledge_version: str
    cases: list[EvalCase] = field(default_factory=list)

    def by_id(self, case_id: str) -> EvalCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.version,
            "knowledge_version": self.knowledge_version,
            "cases": [case.to_dict() for case in self.cases],
        }


def load_dataset(path: str | Path) -> Dataset:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = []
    for raw in payload["cases"]:
        expected = raw["expected"]
        cases.append(
            EvalCase(
                case_id=raw["case_id"],
                task=raw["task"],
                scenario=raw["scenario"],
                source=raw["source"],
                facts=raw["facts"],
                allowed_sections=raw["allowed_sections"],
                blocked_sections=raw["blocked_sections"],
                approved_sources=raw["approved_sources"],
                question=raw.get("question"),
                expected=Expected(
                    answerable=expected["answerable"],
                    must_include_any=tuple(expected.get("must_include_any", ())),
                    must_not_include=tuple(expected.get("must_not_include", ())),
                    required_source_ids=tuple(expected.get("required_source_ids", ())),
                    forbidden_categories=tuple(expected.get("forbidden_categories", ())),
                    note=expected.get("note", ""),
                ),
            )
        )
    return Dataset(
        version=payload["dataset_version"],
        knowledge_version=payload["knowledge_version"],
        cases=cases,
    )
