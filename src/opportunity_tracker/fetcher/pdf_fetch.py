"""PDF text extraction. Not optional -- binding scholarship conditions are commonly
PDFs linked from an HTML page (the UWA case this whole tool exists to catch: the
25%-FTE research-project rule lives in a PDF, not the scholarship page itself). See
spec §6.1."""
from __future__ import annotations

import pdfplumber


def extract_pdf_text(path: str) -> str:
    """Extract all text from the PDF at `path`.

    Each page's extracted text is joined with a single newline between pages. A
    page with no extractable text (e.g. a scanned image page with no text layer)
    contributes an empty string for that page rather than raising.
    """
    pages_text: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    return "\n".join(pages_text)
