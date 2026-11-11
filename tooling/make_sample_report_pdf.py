#!/usr/bin/env python
"""Generate the patient-facing sample report PDF from the sample laboratory data.

Content mirrors what the app shows: test, verified value, printed range,
comparison status, one short summary, and the educational disclaimer.
"""
from __future__ import annotations
from pathlib import Path

ROWS = [
    ("HEMOGLOBIN", "9.0 g/dL", "12.0-15.0 g/dL", "Below printed range",
     "Haemoglobin is the iron-rich protein in red blood cells that carries oxygen. "
     "Your reported value is below the range printed on this report."),
    ("TOTAL LEUCOCYTES COUNT", "6.69 X10^3/uL", "4.0-10.0 X10^3/uL", "Within printed range",
     "White blood cells are part of the immune system and help the body fight infection. "
     "Your reported value is within the range printed on this report."),
    ("PLATELET COUNT", "250 X10^3/uL", "150-410 X10^3/uL", "Within printed range",
     "Platelets are small cell fragments that help blood to clot. Your reported value is "
     "within the range printed on this report."),
    ("FASTING BLOOD SUGAR", "92.9 mg/dL", "Not printed", "Range not provided",
     "Glucose is the body's main source of energy. No reference range was printed for this result."),
    ("MYSTERY MARKER", "4.2 U/L", "1.0-2.0 U/L", "Result available",
     "MediRead does not have an explanation for this test yet."),
]

def esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

def wrap(text: str, width: int = 78) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines

ops = ["BT /F2 22 Tf 56 780 Td (MediRead sample report) Tj ET",
       "BT /F1 11 Tf 56 758 Td (Generated from the bundled sample laboratory data. Educational only.) Tj ET",
       "BT /F1 10 Tf 56 744 Td (Source: lab_report.pdf  |  This is not a diagnosis and not medical advice.) Tj ET"]
y = 710
for name, value, rng, status, summary in ROWS:
    ops.append(f"BT /F2 13 Tf 56 {y} Td ({esc(name)}) Tj ET")
    ops.append(f"BT /F2 16 Tf 56 {y-20} Td ({esc(value)}) Tj ET")
    ops.append(f"BT /F1 10 Tf 250 {y-18} Td (Printed range: {esc(rng)}) Tj ET")
    ops.append(f"BT /F1 10 Tf 56 {y-36} Td ({esc(status)}) Tj ET")
    yy = y - 52
    for line in wrap(summary):
        ops.append(f"BT /F1 9.5 Tf 56 {yy} Td ({esc(line)}) Tj ET")
        yy -= 12
    y = yy - 22
    if y < 90:
        break

content = "\n".join(ops)
objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
    "/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
    f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
]
pdf = "%PDF-1.4\n"
offsets = []
for index, obj in enumerate(objects, start=1):
    offsets.append(len(pdf))
    pdf += f"{index} 0 obj\n{obj}\nendobj\n"
xref = len(pdf)
pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n"
for off in offsets:
    pdf += f"{off:010d} 00000 n \n"
pdf += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"

out = Path(__file__).resolve().parents[1] / "docs" / "samples" / "mediread_sample_report.pdf"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(pdf.encode("latin1"))
print(f"wrote {out} ({len(pdf)} bytes)")
