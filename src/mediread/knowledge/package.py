"""Load, validate and save the authoring package; compute the content hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .models import SCHEMA_VERSION, KnowledgePackage
from .validate import ValidationReport, validate_package

SCHEMA_PATH = Path(__file__).parent / "schema" / "knowledge-package.schema.json"
_CONTENT_KEYS = ("sources", "tests", "aliases", "evidence", "terminology")
_ID_KEYS = {
    "sources": "source_id",
    "tests": "test_id",
    "aliases": "test_id",
    "evidence": "evidence_id",
    "terminology": "term_id",
}


class KnowledgePackageError(ValueError):
    """Raised when a package file is malformed, invalid or internally inconsistent."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid knowledge package: " + "; ".join(errors))


_DEFAULTS = {
    "sources": {
        "publication_date": None,
        "attribution_requirements": None,
        "source_notes": None,
    },
    "tests": {
        "general_interpretation_high": None,
        "general_interpretation_low": None,
        "related_test_ids": [],
        "synonyms": [],
        "language": "en",
    },
    "aliases": {"alias_type": "synonym", "language": "en", "source": None},
    "evidence": {},
    "terminology": {},
}


def _normalise_entry(key: str, item: dict) -> dict:
    """Give every entry the same shape, so omitting an optional field cannot
    change the content hash."""
    normalised = dict(item)
    for field_name, default in _DEFAULTS.get(key, {}).items():
        if normalised.get(field_name) is None:
            normalised[field_name] = default
        elif field_name not in normalised:
            normalised[field_name] = default
    return normalised


def _canonical_entries(data: dict) -> dict:
    """Deterministic content subset: no build metadata, lists sorted by id."""
    canonical: dict = {}
    for key in _CONTENT_KEYS:
        items = [_normalise_entry(key, item) for item in data.get(key, [])]
        id_key = _ID_KEYS[key]
        if key == "aliases":
            items.sort(key=lambda item: (item.get("test_id", ""), item.get("alias", "")))
        else:
            items.sort(key=lambda item: str(item.get(id_key, "")))
        canonical[key] = items
    return canonical


def compute_content_hash(data: dict) -> str:
    payload = json.dumps(_canonical_entries(data), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def schema_errors(data: dict) -> list[str]:
    validator = Draft202012Validator(load_schema())
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        errors.append(f"schema {location}: {error.message}")
    return errors


def load_package(path: Path | str, *, verify_hash: bool = True) -> tuple[KnowledgePackage, ValidationReport]:
    """Parse and validate a package file.

    Returns the typed package and the validation report (errors empty on success).
    Raises :class:`KnowledgePackageError` when the schema, the semantic rules or the
    content hash fail, because a package that does not verify must never be built.
    """
    raw = Path(path).read_text()
    data = json.loads(raw)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise KnowledgePackageError(
            [f"schema_version must be {SCHEMA_VERSION!r}, got {data.get('schema_version')!r}"]
        )
    errors = schema_errors(data)
    if errors:
        raise KnowledgePackageError(errors)
    report = validate_package(data)
    if report.errors:
        raise KnowledgePackageError(report.errors)
    if verify_hash:
        expected = data.get("package", {}).get("content_hash")
        actual = compute_content_hash(data)
        if expected != actual:
            raise KnowledgePackageError(
                [
                    "content_hash does not match the package content "
                    f"(recorded {expected}, computed {actual}); re-save the package to refresh it"
                ]
            )
    return KnowledgePackage.from_json(data), report


def save_package(package: KnowledgePackage, path: Path | str) -> str:
    """Write a package, refreshing the content hash. Returns the new hash."""
    data = package.to_json()
    data["package"]["content_hash"] = compute_content_hash(data)
    package.content_hash = data["package"]["content_hash"]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return package.content_hash


def package_from_dict(data: dict) -> KnowledgePackage:
    return KnowledgePackage.from_json(data)
