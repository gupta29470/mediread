"""On-device LLM evaluation harness (Milestone 3.1).

**Evaluation only.** Nothing in this package is imported by the production
explanation pipeline; a test enforces that boundary. It never writes to
``artifacts/results`` or ``src/mediread/explain``.

The deterministic engine remains the source of truth: the harness only asks a
model to rewrite *permitted* explanation text or answer a follow-up from the
*same permitted context*, then validates every response mechanically.
"""

from .dataset import EvalCase, load_dataset
from .schema import validate_response

__all__ = ["EvalCase", "load_dataset", "validate_response"]
