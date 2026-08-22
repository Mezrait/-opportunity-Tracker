"""Tests for PDF text extraction. Builds a minimal, valid, single-page PDF from raw
bytes at test time (byte offsets computed from the actual serialized objects, not
hardcoded) rather than depending on a binary fixture file or any extra PDF-writing
dependency."""
from pathlib import Path

from opportunity_tracker.fetcher.pdf_fetch import extract_pdf_text

EXPECTED_TEXT = "SCHOLARSHIP CONDITIONS: minimum 25% FTE research project"


def _build_minimal_pdf(text: str) -> bytes:
    """Construct a minimal, syntactically valid, single-page PDF whose only content
    is `text`, drawn via a single Tj operator in Helvetica. The xref table's byte
    offsets are computed from len(buf) as each object is written, so the file is
    guaranteed structurally valid regardless of the exact text length."""
    content_stream = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n"
        + content_stream + b"\nendstream",
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj_body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode("ascii") + obj_body + b"\nendobj\n"

    xref_offset = len(buf)
    n = len(objects) + 1  # +1 for the free-list head entry (object 0)
    buf += f"xref\n0 {n}\n".encode("ascii")
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode("ascii")
    buf += (
        f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode("ascii")
    return bytes(buf)


def test_extract_pdf_text_reads_single_page_content(tmp_path: Path):
    pdf_bytes = _build_minimal_pdf(EXPECTED_TEXT)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(pdf_bytes)

    text = extract_pdf_text(str(pdf_path))

    assert EXPECTED_TEXT in text
