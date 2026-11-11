"""Privacy redaction: must mask identifiers, must never mask laboratory data."""

from __future__ import annotations

import logging

import pytest

from mediread.privacy import RedactingFilter, redact_text, report_key

MUST_REDACT = [
    "Patient Name : Geeta Gupta",
    "NAME                : GEETA GUPTA(49Y/F)",
    "Report for   Adit Gupta(20Y/F)",
    "Dr Sachin Patil MD(Path)",
    "Barcode : 8123456789012",
    "Labcode : 1234567/DG007",
    "Sample Collected on (SCT) : 25/02/2024 09:37",
    "Contact: 9820012345",
    "email: someone@example.com",
    "A 104 MOONLIGHT COOPERATIVE HOUSING SOCIETY UNITECH WEST END VIRAR",
]

MUST_PRESERVE = [
    "  ALKALINE PHOSPHATASE   PHOTOMETRY   65.63   U/L   45-129",
    "   0.8-1.2",
    " Bio. Ref. Interval. :   11.0 - 13.1 Seconds",
    "Reference Range: Adults - Hb A = 96.8 - 97.8% Hb F = 0.0 - 0.5 %",
    "  INTERNATIONAL NORMALIZED RATIO   CALCULATED   0.9   Ratio",
    "HEMOGLOBIN 9.2 g/dL 12.0-15.0",
]


@pytest.mark.parametrize("line", MUST_REDACT)
def test_identifiers_are_masked(line):
    redacted = redact_text(line)
    assert redacted != line, f"identifier leaked: {line!r}"


@pytest.mark.parametrize("line", MUST_PRESERVE)
def test_laboratory_content_is_preserved(line):
    assert redact_text(line) == line


def test_reference_ranges_survive():
    assert "45-129" in redact_text("ALKALINE PHOSPHATASE 65.63 U/L 45-129")
    assert "0.3-1.2" in redact_text("BILIRUBIN 0.58 mg/dL 0.3-1.2")
    assert "11.0 - 13.1" in redact_text("Bio. Ref. Interval. : 11.0 - 13.1 Seconds")


def test_numeric_values_survive():
    text = "TOTAL LEUCOCYTES 6.02 x10^3/uL 4.0-10.0"
    assert redact_text(text) == text


def test_sensitive_lines_are_fully_masked():
    out = redact_text("NAME : GEETA GUPTA(49Y/F)")
    assert "GEETA" not in out
    assert "49Y" not in out or "REDACTED" in out


def test_multi_line_input():
    text = "NAME : Alex Doe\nHAEMOGLOBIN 13.5 g/dL 12.0-15.0"
    out = redact_text(text)
    assert "Alex" not in out
    assert "13.5" in out


def test_report_key_is_stable_and_opaque():
    assert report_key("a.pdf") == report_key("a.pdf")
    assert report_key("a.pdf") != report_key("b.pdf")
    assert len(report_key("a.pdf")) == 16


def test_logging_filter_masks_records():
    record = logging.LogRecord(
        "mediread", logging.INFO, __file__, 1,
        "patient %s", ("Geeta Gupta",), None,
    )
    assert RedactingFilter().filter(record)
    assert "Geeta" not in record.getMessage()


def test_configure_logging_attaches_redacting_handler():
    import io

    from mediread.privacy import configure_logging

    stream = io.StringIO()
    logger = configure_logging(logging.INFO, stream=stream)
    logger.info("NAME : Alex Doe")
    assert "Alex" not in stream.getvalue()
    logger.handlers.clear()
