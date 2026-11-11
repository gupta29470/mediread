"""Catalogue lookup and integrity checks.

Lookup order is deliberately strict:

1. exact ``test_id`` from the extraction vocabulary;
2. exact normalised *alias* from the entry list (e.g. ``NEUTROPHILS``);
3. otherwise **unsupported** — never a fuzzy or "looks similar" match.

A section hint disambiguates names that occur in more than one panel (the urine
``RED BLOOD CELLS`` versus the blood ``Red blood cell count``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .entries import ENTRIES, ENTRIES_BY_ID, KnowledgeEntry
from .sources import EXCLUDED_SOURCES, KNOWLEDGE_VERSION, SOURCES, get_source

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalise_name(text: str) -> str:
    lowered = text.lower().replace("µ", "u")
    lowered = _PUNCT.sub(" ", lowered)
    return _WS.sub(" ", lowered).strip()


@dataclass(frozen=True)
class LookupResult:
    entry: KnowledgeEntry | None
    match: str          # "test_id" | "alias" | "unsupported"
    reason: str = ""


class KnowledgeCatalogue:
    """Immutable view over the bundled knowledge data."""

    def __init__(self) -> None:
        self._by_alias: dict[str, list[KnowledgeEntry]] = {}
        for entry in ENTRIES:
            for alias in (entry.canonical_name,) + entry.aliases:
                self._by_alias.setdefault(normalise_name(alias), []).append(entry)
        self._errors = _validate()

    @property
    def version(self) -> str:
        return KNOWLEDGE_VERSION

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors)

    def lookup(
        self,
        test_id: str | None,
        test_name: str,
        section: str | None = None,
    ) -> LookupResult:
        if test_id and test_id in ENTRIES_BY_ID:
            return LookupResult(ENTRIES_BY_ID[test_id], "test_id")

        key = normalise_name(test_name)
        candidates = self._by_alias.get(key, [])
        if len(candidates) == 1:
            return LookupResult(candidates[0], "alias")
        if len(candidates) > 1:
            if section:
                for candidate in candidates:
                    if candidate.category == section:
                        return LookupResult(candidate, "alias")
            return LookupResult(
                None, "unsupported",
                f"the name '{test_name}' matches more than one knowledge entry and the "
                "page section did not disambiguate it",
            )
        return LookupResult(
            None, "unsupported",
            f"'{test_name}' is not in the MediRead knowledge base",
        )

    def get(self, test_id: str) -> KnowledgeEntry | None:
        return ENTRIES_BY_ID.get(test_id)

    def entries(self) -> tuple[KnowledgeEntry, ...]:
        return ENTRIES

    def sources_for(self, entry: KnowledgeEntry) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for source_id in entry.sources:
            source = get_source(source_id)
            if source:
                out.append(
                    {
                        "source_id": source.source_id,
                        "title": source.title,
                        "organization": source.organization,
                        "url": source.url,
                        "accessed": source.accessed,
                        "licence": source.licence,
                    }
                )
        return out


def _validate() -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for entry in ENTRIES:
        if entry.test_id in seen:
            errors.append(f"duplicate test_id: {entry.test_id}")
        seen.add(entry.test_id)
        if entry.status not in ("complete", "partial"):
            errors.append(f"{entry.test_id}: invalid status {entry.status!r}")
        if not entry.sources:
            errors.append(f"{entry.test_id}: no sources")
        for source_id in entry.sources:
            if source_id not in SOURCES:
                errors.append(f"{entry.test_id}: unknown source {source_id!r}")
        if entry.kind not in ("numeric", "qualitative"):
            errors.append(f"{entry.test_id}: invalid kind {entry.kind!r}")
        if not entry.measures.strip():
            errors.append(f"{entry.test_id}: empty measures text")
        if entry.kind == "qualitative" and not entry.qualitative_note:
            errors.append(f"{entry.test_id}: qualitative entry without a qualitative note")
    for source in SOURCES.values():
        if not source.url.startswith("https://"):
            errors.append(f"{source.source_id}: source URL must be https")
    if not EXCLUDED_SOURCES:
        errors.append("excluded-source decisions are not recorded")
    return errors


CATALOGUE = KnowledgeCatalogue()
