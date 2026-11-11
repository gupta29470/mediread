"""Reproducible fine-tuning dataset factory (Phase 4).

Examples are generated from deterministic templates over *reviewed* knowledge (plus
templates that need no knowledge at all for safety/refusal categories), validated,
split by family to prevent leakage, and written as JSONL with provenance.
"""

from .factory import build_dataset, write_dataset
from .schema import EXAMPLE_SCHEMA_VERSION, validate_example

__all__ = ["build_dataset", "write_dataset", "EXAMPLE_SCHEMA_VERSION", "validate_example"]
