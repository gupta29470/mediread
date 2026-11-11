"""Ground-truth construction and loading.

Ground truth for MediRead evaluation is deliberately *not* another OCR engine's
output.

* For digital pages the reference is the PDF's own authored text layer — the
  string the laboratory information system wrote, which is the source of truth
  for that page. It is spot-checked against a rendered crop during curation.
* For raster-only pages the reference is a hand transcription of the image.

Both are restricted to **laboratory content** (table rows, headers, methods).
Patient identifiers, addresses, accession numbers and dates are excluded before
the reference is stored, so the ground-truth corpus contains no personal data.

The on-disk format is one JSON file per page under ``data/ground_truth``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from ..config import GROUND_TRUTH_DIR
from ..errors import GroundTruthError
from ..privacy import redact_text

# Lines that describe the patient/sample rather than the results.
_PII_LINE = re.compile(
    r"^\s*(?:name|patient|ref\.?\s*by|referred|address|a\s*\d|barcode|labcode|"
    r"sample\s*(?:collected|received|type)|report\s*released|test\s*date|"
    r"report\s*status|home\s*collection|dr\.?\s|consultant|doctor)\b",
    re.IGNORECASE,
)
_ID_LIKE = re.compile(r"\b(?:[A-Z]{2}\d{5,}|\d{7,})\b")
_ADDRESS_WORDS = re.compile(
    r"\b(?:society|nagar|road|street|lane|apartment|co-?op|housing|plot|flat|"
    r"sector|building|tower|block|marg|colony|village|taluka|district|pin)\b",
    re.IGNORECASE,
)


@dataclass
class GroundTruthPage:
    report_id: str
    page_number: int
    source: str            # "embedded_text_layer" | "hand_transcription"
    provenance: str        # how the reference was produced / verified
    lines: list[str]
    exclude_patterns: list[str]
    # Page-space boxes of the reference lines. OCR hypotheses are filtered to
    # these regions before scoring, so page furniture and patient metadata are
    # neither rewarded nor penalised.
    regions: list[list[float]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["text"] = self.text
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "GroundTruthPage":
        return cls(
            report_id=data["report_id"],
            page_number=int(data["page_number"]),
            source=data["source"],
            provenance=data.get("provenance", ""),
            lines=list(data["lines"]),
            exclude_patterns=list(data.get("exclude_patterns", [])),
            regions=[list(map(float, r)) for r in data.get("regions", [])],
        )


_ORG = re.compile(
    r"\b(?:ltd|limited|pvt|inc|industrial|area|mumbai|navi|road|nagar|society|"
    r"colony|hospital|clinic|laborator|diagnostic|centre|center)\b",
    re.IGNORECASE,
)
_NON_RESULT_LABEL = re.compile(
    r"^\s*(?:technology|method|note|comments?|clinical\s*significance|interpretation|"
    r"page\s*:|sample|report\s*released|end\s*of\s*report|please\s*correlate|"
    r"bio\.?\s*ref|test\s*asked|alert|impression|clinical\s*information|"
    r"reference\s*range\s*:|trimester|with\s*normal\s*pregnancy)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d")


def looks_like_result_row(line: str, *, max_tokens: int = 18) -> bool:
    """True for laboratory header/result/range rows; False for prose and metadata.

    The reference corpus must contain *data*, not the surrounding explanation
    paragraphs: CER over prose would reward engines for reading English and say
    nothing about whether a measured value survived.
    """
    text = line.strip()
    if not text or len(text.split()) > max_tokens:
        return False
    if is_identifying(text) or redact_text(text) != text:
        return False
    if _ORG.search(text) or _NON_RESULT_LABEL.match(text):
        return False
    if re.match(r"^\s*(?:test\s*name|investigation|parameter)\b", text, re.IGNORECASE):
        return True
    return bool(_NUMBER.search(text))


def is_identifying(line: str) -> bool:
    """True when a line is patient/sample metadata rather than laboratory content."""
    if _PII_LINE.match(line):
        return True
    if _ADDRESS_WORDS.search(line) and sum(c.isalpha() for c in line) > 12:
        return True
    if _ID_LIKE.search(line) and len(line.strip()) < 40:
        return True
    return False


def filter_laboratory_lines(lines: Iterable[str]) -> list[str]:
    """Drop identifiers, blanks and pure page furniture from a page's lines."""
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if is_identifying(stripped):
            continue
        out.append(stripped)
    return out


def save_page_ground_truth(page: GroundTruthPage, root: Path | None = None) -> Path:
    root = root or GROUND_TRUTH_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{page.report_id}_p{page.page_number:03d}.json"
    path.write_text(json.dumps(page.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_page_ground_truth(path: str | Path) -> GroundTruthPage:
    path = Path(path)
    if not path.exists():
        raise GroundTruthError(f"ground truth not found: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GroundTruthError(f"invalid ground truth JSON {path.name}: {exc}") from exc
    return GroundTruthPage.from_dict(data)


def load_all_ground_truth(root: Path | None = None) -> list[GroundTruthPage]:
    root = root or GROUND_TRUTH_DIR
    if not root.exists():
        return []
    return [
        load_page_ground_truth(path)
        for path in sorted(root.glob("*_p*.json"))
    ]
