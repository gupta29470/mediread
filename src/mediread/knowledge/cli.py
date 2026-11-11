"""Command-line interface for authoring, validating and building the package.

    python -m mediread.knowledge.cli migrate-legacy --out knowledge/mediread-knowledge.json
    python -m mediread.knowledge.cli validate --package knowledge/mediread-knowledge.json
    python -m mediread.knowledge.cli build --package ... --out artifacts/knowledge/....
    python -m mediread.knowledge.cli stats --db artifacts/knowledge/....
    python -m mediread.knowledge.cli lookup --db ... "haemoglobin"
    python -m mediread.knowledge.cli report --package ...
    python -m mediread.knowledge.cli set-status --package ... --test-id ... --status reviewed \\
        --reviewer "Name (role)" --note "..."
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .builder import build_database, read_metadata
from .migrate import build_from_legacy
from .package import KnowledgePackageError, load_package, save_package
from .store import KnowledgeStore
from .validate import validate_package

_TRANSITIONS = {
    ("draft", "reviewed"),
    ("reviewed", "approved"),
    ("reviewed", "draft"),
    ("approved", "draft"),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: Path):
    return load_package(path)


def cmd_migrate(args: argparse.Namespace) -> int:
    package = build_from_legacy(knowledge_version=args.knowledge_version)
    from .package import compute_content_hash

    package.content_hash = compute_content_hash(package.to_json())
    save_package(package, args.out)
    print(f"wrote {args.out}: {len(package.tests)} tests, {len(package.sources)} sources, "
          f"{len(package.evidence)} evidence rows (all draft)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        package, report = _load(args.package)
    except KnowledgePackageError as error:
        for item in error.errors:
            print(f"ERROR {item}", file=sys.stderr)
        return 1
    print(f"OK schema_version={package.knowledge_version} content_hash={package.content_hash[:12]}…")
    print(f"tests={len(package.tests)} sources={len(package.sources)} "
          f"aliases={len(package.all_aliases())} evidence={len(package.evidence)}")
    print(f"status={report.stats['by_status']}")
    for warning in report.warnings:
        print(f"WARN {warning}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    package, _report = _load(args.package)
    manifest = build_database(package, args.out)
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    if args.db:
        with KnowledgeStore.open(args.db) as store:
            print(json.dumps({"metadata": store.metadata, "stats": store.stats()}, indent=2))
        return 0
    package, report = _load(args.package)
    payload = {
        "knowledge_version": package.knowledge_version,
        "content_hash": package.content_hash,
        "stats": report.stats,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_lookup(args: argparse.Namespace) -> int:
    with KnowledgeStore.open(args.db) as store:
        statuses = ("draft", "reviewed", "approved") if args.include_draft else ("approved",)
        result = store.lookup(args.query, include_statuses=statuses)
        print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.permitted or result.match_type != "unsupported" else 1


def cmd_report(args: argparse.Namespace) -> int:
    package, report = _load(args.package)
    payload = {"knowledge_version": package.knowledge_version, "content_hash": package.content_hash,
               "stats": report.stats, "warnings": report.warnings}
    print(json.dumps(payload, indent=2))
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    package, _report = _load(args.package)
    tests = {test.test_id: test for test in package.tests}
    test = tests.get(args.test_id)
    if test is None:
        print(f"ERROR unknown test_id {args.test_id!r}", file=sys.stderr)
        return 1
    if args.status not in ("draft", "reviewed", "approved"):
        print(f"ERROR invalid status {args.status!r}", file=sys.stderr)
        return 1
    if (test.review_status, args.status) not in _TRANSITIONS:
        print(
            f"ERROR illegal transition {test.review_status!r} -> {args.status!r}; "
            f"allowed: {sorted(_TRANSITIONS)}",
            file=sys.stderr,
        )
        return 1
    if not args.reviewer.strip():
        print("ERROR a reviewer identity is required for a status change", file=sys.stderr)
        return 1

    from .models import KnowledgeTest

    updated = KnowledgeTest(
        test_id=test.test_id, canonical_name=test.canonical_name, category=test.category,
        what_it_measures=test.what_it_measures, why_it_is_ordered=test.why_it_is_ordered,
        limitations=test.limitations, review_status=args.status,
        content_version=test.content_version + 1,
        general_interpretation_high=test.general_interpretation_high,
        general_interpretation_low=test.general_interpretation_low,
        related_test_ids=test.related_test_ids, synonyms=test.synonyms, language=test.language,
    )
    package.tests = [updated if item.test_id == test.test_id else item for item in package.tests]
    for item in package.evidence:
        if item.test_id == test.test_id:
            pass  # evidence status is reviewed separately; see docs
    save_package(package, args.package)
    log_path = Path(args.package).parent / "review_log.jsonl"
    entry = {
        "entity_type": "test",
        "entity_id": test.test_id,
        "from_status": test.review_status,
        "to_status": args.status,
        "reviewer": args.reviewer,
        "reviewed_at": _now(),
        "note": args.note,
        "package_content_hash": package.content_hash,
    }
    with log_path.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    print(f"{test.test_id}: {test.review_status} -> {args.status} (logged to {log_path})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mediread-knowledge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("migrate-legacy", help="build the package from the legacy catalogue")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--knowledge-version", default="2026.11.1")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("validate", help="validate schema, semantics and content hash")
    p.add_argument("--package", type=Path, required=True)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("build", help="build the SQLite package")
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("stats", help="print corpus statistics")
    p.add_argument("--package", type=Path)
    p.add_argument("--db", type=Path)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("lookup", help="look a test up in a built package")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("query")
    p.add_argument("--include-draft", action="store_true")
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("report", help="corpus report as JSON")
    p.add_argument("--package", type=Path, required=True)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("set-status", help="review transition (draft -> reviewed -> approved)")
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--test-id", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_set_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
