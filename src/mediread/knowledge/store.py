"""Deterministic runtime lookup over a built SQLite knowledge package.

Lookup order is fixed and documented:

1. exact ``test_id``;
2. exact normalised alias (a canonical name is an alias of type ``canonical``);
3. SQLite FTS5 lexical search;
4. unsupported.

Two or more candidate tests is *ambiguous*: the result is reported, but it never
permits an automatic explanation. Status gating happens here, not in the UI: a
test whose ``review_status`` is not in ``include_statuses`` can be found but is not
permitted, so a draft entry can never authorise an explanation in production.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .models import REVIEW_STATUSES, normalise_name

DEFAULT_PERMITTED_STATUSES = ("approved",)
_TOKEN = __import__("re").compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Candidate:
    test_id: str
    canonical_name: str
    review_status: str
    score: float | None = None

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "canonical_name": self.canonical_name,
            "review_status": self.review_status,
            "score": self.score,
        }


@dataclass(frozen=True)
class LookupResult:
    query: str
    match_type: str            # canonical_id | alias | fts5 | ambiguous | unsupported
    ambiguous: bool
    permitted: bool
    knowledge_version: str
    rationale: str
    test_id: str | None = None
    review_status: str | None = None
    candidates: tuple[Candidate, ...] = ()
    sources: tuple[dict, ...] = ()
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "match_type": self.match_type,
            "ambiguous": self.ambiguous,
            "permitted": self.permitted,
            "test_id": self.test_id,
            "review_status": self.review_status,
            "knowledge_version": self.knowledge_version,
            "rationale": self.rationale,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "sources": list(self.sources),
        }


class KnowledgeStore:
    """Read-only view over a built package. Safe to share across a process."""

    def __init__(self, connection: sqlite3.Connection, metadata: dict[str, str]) -> None:
        self._connection = connection
        self._metadata = metadata

    @classmethod
    def open(cls, db_path: Path | str) -> "KnowledgeStore":
        path = Path(db_path)
        if not path.exists():
            raise FileNotFoundError(f"knowledge package not found: {path}")
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        metadata = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM metadata")
        }
        if metadata.get("db_schema_version") != "1":
            raise ValueError(
                f"unsupported knowledge database schema {metadata.get('db_schema_version')!r}"
            )
        return cls(connection, metadata)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "KnowledgeStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def metadata(self) -> dict[str, str]:
        return dict(self._metadata)

    @property
    def knowledge_version(self) -> str:
        return self._metadata.get("knowledge_version", "unknown")

    # ---- row helpers ----------------------------------------------------
    def _row(self, test_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM tests WHERE test_id = ?", (test_id,)
        ).fetchone()

    def _candidate(self, test_id: str, score: float | None = None) -> Candidate | None:
        row = self._row(test_id)
        if row is None:
            return None
        return Candidate(
            test_id=row["test_id"],
            canonical_name=row["canonical_name"],
            review_status=row["review_status"],
            score=score,
        )

    def _sources(self, test_id: str) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT DISTINCT s.source_id, s.title, s.publisher, s.source_url, s.access_date, "
            "s.content_license, s.attribution_requirements "
            "FROM evidence e JOIN sources s ON s.source_id = e.source_id "
            "WHERE e.test_id = ? ORDER BY s.source_id",
            (test_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def _result(
        self,
        *,
        query: str,
        match_type: str,
        rationale: str,
        candidates: list[Candidate],
        test_id: str | None,
        permitted_statuses: tuple[str, ...],
        ambiguous: bool = False,
    ) -> LookupResult:
        status = candidates[0].review_status if len(candidates) == 1 else None
        permitted = (
            not ambiguous
            and test_id is not None
            and status in permitted_statuses
        )
        if ambiguous:
            rationale = rationale
        elif test_id is not None and not permitted:
            rationale = f"{rationale}; entry review_status is {status!r}, which is not permitted"
        return LookupResult(
            query=query,
            match_type=match_type,
            ambiguous=ambiguous,
            permitted=permitted,
            test_id=test_id,
            review_status=status,
            candidates=tuple(candidates),
            sources=self._sources(test_id) if test_id else (),
            knowledge_version=self.knowledge_version,
            rationale=rationale,
        )

    # ---- lookup ---------------------------------------------------------
    def lookup(
        self,
        query: str,
        *,
        include_statuses: tuple[str, ...] = DEFAULT_PERMITTED_STATUSES,
    ) -> LookupResult:
        permitted_statuses = tuple(status for status in include_statuses if status in REVIEW_STATUSES)
        raw = (query or "").strip()
        if not raw:
            return self._result(
                query=query, match_type="unsupported", rationale="empty query",
                candidates=[], test_id=None, permitted_statuses=permitted_statuses,
            )

        # 1. exact canonical id
        candidate = self._candidate(raw.lower())
        if candidate is not None:
            return self._result(
                query=query, match_type="canonical_id", rationale="exact test_id match",
                candidates=[candidate], test_id=candidate.test_id,
                permitted_statuses=permitted_statuses,
            )

        # 2. exact normalised alias
        normalized = normalise_name(raw)
        rows = self._connection.execute(
            "SELECT test_id, alias_type FROM aliases WHERE normalized_alias = ? ORDER BY test_id",
            (normalized,),
        ).fetchall()
        test_ids = sorted({row["test_id"] for row in rows})
        if len(test_ids) == 1:
            candidate = self._candidate(test_ids[0])
            if candidate is not None:
                return self._result(
                    query=query, match_type="alias",
                    rationale=f"exact alias match ({rows[0]['alias_type']})",
                    candidates=[candidate], test_id=candidate.test_id,
                    permitted_statuses=permitted_statuses,
                )
        if len(test_ids) > 1:
            candidates = [item for item in (self._candidate(test_id) for test_id in test_ids) if item]
            return self._result(
                query=query, match_type="ambiguous",
                rationale=(
                    f"alias {normalized!r} matches {len(candidates)} tests; no automatic "
                    "explanation is permitted"
                ),
                candidates=candidates, test_id=None, permitted_statuses=permitted_statuses,
                ambiguous=True,
            )

        # 3. FTS5 lexical search
        tokens = _TOKEN.findall(normalized)
        if tokens:
            match = " AND ".join(f'"{token}"' for token in tokens)
            rows = self._connection.execute(
                "SELECT test_id, bm25(tests_fts) AS score FROM tests_fts "
                "WHERE tests_fts MATCH ? ORDER BY score LIMIT 8",
                (match,),
            ).fetchall()
            if rows:
                best: dict[str, float] = {}
                for row in rows:
                    score = float(row["score"])
                    if row["test_id"] not in best or score < best[row["test_id"]]:
                        best[row["test_id"]] = score
                ranked = sorted(best.items(), key=lambda item: item[1])
                candidates = [
                    item for item in (self._candidate(test_id, score) for test_id, score in ranked) if item
                ]
                if len(candidates) == 1:
                    return self._result(
                        query=query, match_type="fts5",
                        rationale=f"single lexical candidate for {match!r}",
                        candidates=candidates, test_id=candidates[0].test_id,
                        permitted_statuses=permitted_statuses,
                    )
                return self._result(
                    query=query, match_type="ambiguous",
                    rationale=(
                        f"lexical search for {match!r} returned {len(candidates)} tests; "
                        "no automatic explanation is permitted"
                    ),
                    candidates=candidates, test_id=None, permitted_statuses=permitted_statuses,
                    ambiguous=True,
                )

        return self._result(
            query=query, match_type="unsupported",
            rationale=f"{raw!r} is not in the MediRead knowledge package",
            candidates=[], test_id=None, permitted_statuses=permitted_statuses,
        )

    # ---- accessors ------------------------------------------------------
    def get(self, test_id: str) -> dict | None:
        row = self._row(test_id.lower())
        if row is None:
            return None
        data = dict(row)
        data["limitations"] = json.loads(data["limitations"])
        data["related_test_ids"] = json.loads(data["related_test_ids"])
        data["sources"] = self._sources(data["test_id"])
        data["aliases"] = [
            row["alias"]
            for row in self._connection.execute(
                "SELECT alias FROM aliases WHERE test_id = ? ORDER BY alias_type, alias",
                (data["test_id"],),
            )
        ]
        return data

    def stats(self) -> dict:
        def count(sql: str) -> int:
            return int(self._connection.execute(sql).fetchone()[0])

        by_status = {
            row["review_status"]: row["count"]
            for row in self._connection.execute(
                "SELECT review_status, COUNT(*) AS count FROM tests GROUP BY review_status"
            )
        }
        by_category = {
            row["category"]: row["count"]
            for row in self._connection.execute(
                "SELECT category, COUNT(*) AS count FROM tests GROUP BY category ORDER BY category"
            )
        }
        return {
            "tests": count("SELECT COUNT(*) FROM tests"),
            "sources": count("SELECT COUNT(*) FROM sources"),
            "aliases": count("SELECT COUNT(*) FROM aliases"),
            "evidence": count("SELECT COUNT(*) FROM evidence"),
            "terminology": count("SELECT COUNT(*) FROM terminology"),
            "by_status": {status: by_status.get(status, 0) for status in REVIEW_STATUSES},
            "by_category": by_category,
            "knowledge_version": self.knowledge_version,
        }


def lookup_test(db_path: Path | str, query: str, **kwargs) -> LookupResult:
    """One-shot convenience wrapper: ``lookup_test('hemoglobin')``."""
    with KnowledgeStore.open(db_path) as store:
        return store.lookup(query, **kwargs)
