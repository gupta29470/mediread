"""Internal consistency checks for a :class:`ResultDocument`.

These invariants are the ones a downstream consumer is entitled to assume:

* ``stats.results`` equals the number of result records;
* every result carries each of the four mandatory fields exactly once;
* field-status counts add up to the result count;
* section result counts add up to the result count;
* ``result_id`` values are unique within a document.

They are checked by the test suite and by ``tooling/audit_results.py`` so a
counting regression cannot silently reach the evaluation report again.
"""

from __future__ import annotations

from collections import Counter

from .schema import ResultDocument


def audit_document(document: ResultDocument) -> dict[str, object]:
    """Return a machine-readable consistency report for one document."""
    results = document.results
    total = len(results)
    problems: list[str] = []

    ids = [r.result_id for r in results]
    if len(ids) != len(set(ids)):
        duplicated = [rid for rid, n in Counter(ids).items() if n > 1]
        problems.append(f"duplicate result_id values: {duplicated[:5]}")

    field_counts: dict[str, Counter] = {}
    for name in ("test", "value", "unit", "reference"):
        counter: Counter = Counter()
        for result in results:
            field = getattr(result, name)
            if field is None:
                problems.append(f"result {result.result_id} has no {name} field")
                continue
            counter[field.status.value] += 1
        field_counts[name] = counter
        counted = sum(counter.values())
        if counted != total:
            problems.append(f"{name} field count {counted} != result count {total}")

    # Section summaries are optional metadata: when present they must reconcile
    # with the results; when omitted (older or trimmed payloads) that is not an
    # inconsistency, because every result still carries its own section name.
    section_total = sum(s.result_count for s in document.sections)
    if document.sections and section_total != total:
        problems.append(f"section result counts {section_total} != result count {total}")

    declared = document.stats.get("results")
    if declared != total:
        problems.append(f"stats.results {declared} != result count {total}")

    for name, counter in field_counts.items():
        declared_fields = document.stats.get("field_statuses", {}).get(name, {})
        if dict(counter) != declared_fields:
            problems.append(
                f"stats.field_statuses[{name}] {declared_fields} != actual {dict(counter)}"
            )

    return {
        "report_id": document.report_id,
        "results": total,
        "field_counts": {name: dict(c) for name, c in field_counts.items()},
        "section_total": section_total,
        "problems": problems,
        "consistent": not problems,
    }


def assert_consistent(document: ResultDocument) -> dict[str, object]:
    """Raise ``AssertionError`` if a document violates the counting contract."""
    report = audit_document(document)
    if not report["consistent"]:
        raise AssertionError(f"{document.report_id}: " + "; ".join(report["problems"]))
    return report
