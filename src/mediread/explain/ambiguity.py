"""Deterministic responses for knowledge that must not be explained.

Ambiguity is decided by the retrieval layer, never by the model: if two tests share
a name, the response says so, names the candidates, and asks the user to check the
report. The model only ever receives this text as ``deterministic_response``.
"""

from __future__ import annotations

from typing import Sequence


def ambiguity_response(query: str, candidates: Sequence[str]) -> str:
    names = ", ".join(candidates)
    return (
        f'The name "{query}" matches more than one test in MediRead\'s knowledge '
        f"library: {names}. MediRead cannot safely choose between them, so it will not "
        "explain one of them. Check the test name printed on your original report, or "
        "ask the laboratory which test was ordered."
    )


def unsupported_response(query: str) -> str:
    return (
        f'"{query}" is not currently covered by MediRead\'s knowledge library. The '
        "extracted name and reported result are shown for reference, but MediRead cannot "
        "provide a reliable explanation for this test yet."
    )


def not_approved_response(query: str, status: str) -> str:
    return (
        f'MediRead has information about "{query}", but it has not completed review '
        f"(status: {status}), so it is not used in explanations yet. The extracted name "
        "and reported result are shown for reference."
    )
