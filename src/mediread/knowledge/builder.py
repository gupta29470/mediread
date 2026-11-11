"""Build the runtime SQLite knowledge package from an authoring package."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .models import SCHEMA_VERSION, KnowledgePackage

BUILDER_VERSION = "mediread.knowledge-builder/1"
DB_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
PRAGMA journal_mode = DELETE;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_url TEXT NOT NULL,
    publication_date TEXT,
    access_date TEXT NOT NULL,
    content_license TEXT NOT NULL,
    attribution_requirements TEXT,
    source_type TEXT NOT NULL,
    source_notes TEXT
);
CREATE TABLE tests (
    test_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    category TEXT NOT NULL,
    what_it_measures TEXT NOT NULL,
    why_it_is_ordered TEXT NOT NULL,
    general_interpretation_high TEXT,
    general_interpretation_low TEXT,
    limitations TEXT NOT NULL,
    related_test_ids TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('draft', 'reviewed', 'approved')),
    content_version INTEGER NOT NULL,
    language TEXT NOT NULL
);
CREATE TABLE aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id TEXT NOT NULL REFERENCES tests(test_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    language TEXT NOT NULL,
    source TEXT,
    UNIQUE (test_id, normalized_alias)
);
CREATE INDEX aliases_normalized ON aliases(normalized_alias);
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    test_id TEXT NOT NULL REFERENCES tests(test_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    claim_field TEXT NOT NULL,
    supporting_excerpt_or_reference TEXT NOT NULL,
    review_status TEXT NOT NULL
);
CREATE INDEX evidence_test ON evidence(test_id);
CREATE TABLE terminology (
    term_id TEXT PRIMARY KEY,
    technical_term TEXT NOT NULL,
    plain_language_explanation TEXT NOT NULL,
    language TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id)
);
CREATE TABLE review_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    note TEXT
);
CREATE VIRTUAL TABLE tests_fts USING fts5(
    test_id UNINDEXED,
    canonical_name,
    aliases,
    category,
    tokenize = 'porter unicode61'
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_database(package: KnowledgePackage, out_path: Path | str, *, built_at: str | None = None) -> dict:
    """Write a SQLite package atomically and return its manifest."""
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = built_at or _utc_now()
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".sqlite", dir=target.parent)
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        connection = sqlite3.connect(tmp_path)
        try:
            connection.executescript(_SCHEMA_SQL)
            connection.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
            for source in package.sources:
                connection.execute(
                    "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        source.source_id, source.title, source.publisher, source.source_url,
                        source.publication_date, source.access_date, source.content_license,
                        source.attribution_requirements, source.source_type, source.source_notes,
                    ),
                )
            aliases = package.all_aliases()
            for test in package.tests:
                connection.execute(
                    "INSERT INTO tests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        test.test_id, test.canonical_name, test.category, test.what_it_measures,
                        test.why_it_is_ordered, test.general_interpretation_high,
                        test.general_interpretation_low, json.dumps(list(test.limitations)),
                        json.dumps(list(test.related_test_ids)), test.review_status,
                        test.content_version, test.language,
                    ),
                )
                test_aliases = [alias.alias for alias in aliases if alias.test_id == test.test_id]
                connection.execute(
                    "INSERT INTO tests_fts (test_id, canonical_name, aliases, category) VALUES (?,?,?,?)",
                    (test.test_id, test.canonical_name, " ".join(test_aliases), test.category),
                )
            for alias in aliases:
                connection.execute(
                    "INSERT INTO aliases (test_id, alias, normalized_alias, alias_type, language, source) "
                    "VALUES (?,?,?,?,?,?)",
                    (alias.test_id, alias.alias, alias.normalized, alias.alias_type, alias.language, alias.source),
                )
            for item in package.evidence:
                connection.execute(
                    "INSERT INTO evidence VALUES (?,?,?,?,?,?)",
                    (
                        item.evidence_id, item.test_id, item.source_id, item.claim_field,
                        item.supporting_excerpt_or_reference, item.review_status,
                    ),
                )
            for term in package.terminology:
                connection.execute(
                    "INSERT INTO terminology VALUES (?,?,?,?,?)",
                    (term.term_id, term.technical_term, term.plain_language_explanation,
                     term.language, term.source_id),
                )
            metadata = {
                "schema_version": SCHEMA_VERSION,
                "db_schema_version": str(DB_SCHEMA_VERSION),
                "knowledge_version": package.knowledge_version,
                "content_hash": package.content_hash,
                "built_at": stamp,
                "builder": BUILDER_VERSION,
                "test_count": str(len(package.tests)),
                "alias_count": str(len(aliases)),
                "evidence_count": str(len(package.evidence)),
                "source_count": str(len(package.sources)),
                "approved_count": str(sum(1 for test in package.tests if test.review_status == "approved")),
            }
            connection.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)", sorted(metadata.items())
            )
            connection.commit()
        finally:
            connection.close()
        payload = tmp_path.read_bytes()
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    manifest = {
        "database": str(target),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "built_at": stamp,
        "knowledge_version": package.knowledge_version,
        "content_hash": package.content_hash,
        "builder": BUILDER_VERSION,
        "tests": len(package.tests),
        "aliases": len(package.all_aliases()),
        "evidence": len(package.evidence),
        "sources": len(package.sources),
        "by_status": package.status_counts(),
    }
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def read_metadata(db_path: Path | str) -> dict[str, str]:
    connection = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT key, value FROM metadata").fetchall()
    finally:
        connection.close()
    return {key: value for key, value in rows}
