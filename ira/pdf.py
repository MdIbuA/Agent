"""PDF input: read the text layer of digital PDFs; render scanned PDFs for OCR.

Uses pypdfium2 (PDFium, Apache-2.0/BSD). No API keys, runs offline.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

MAX_PAGES = 10          # invoices are short; refuse giant documents
MIN_TEXT_CHARS = 40     # less text than this on a page means it's a scan


def _open(path: Path):
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        raise ValueError(f"Not a readable PDF: {e}") from e
    if len(doc) > MAX_PAGES:
        raise ValueError(f"PDF has {len(doc)} pages; invoices up to {MAX_PAGES} pages are supported.")
    return doc


def pdf_text(path: Path) -> tuple[str, bool]:
    """Return (text, is_digital). Digital = every page has a real text layer."""
    doc = _open(path)
    pages = []
    for page in doc:
        pages.append(page.get_textpage().get_text_bounded())
    digital = bool(pages) and all(len(p.strip()) >= MIN_TEXT_CHARS for p in pages)
    return "\n".join(pages), digital


def pdf_to_text(path: Path, ocr_engine) -> tuple[str, str]:
    """Text of a PDF and how it was obtained ("text-layer" or "ocr").

    `ocr_engine` is a callable(image_path) -> text, used only for scanned PDFs.
    """
    text, digital = pdf_text(path)
    if digital:
        return text, "text-layer"
    doc = _open(path)
    parts = []
    with tempfile.TemporaryDirectory() as td:
        for i, page in enumerate(doc):
            img = page.render(scale=200 / 72).to_pil()  # ~200 dpi is enough for OCR
            out = Path(td) / f"p{i}.png"
            img.save(out)
            parts.append(ocr_engine(out))
    return "\n".join(parts), "ocr"
