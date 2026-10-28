"""Plain-text extraction from certificate documents (PDF, scanned PDF, images, DOCX, TXT)."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from observability.logging import logger

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    try:
        import fitz  # type: ignore
    except ImportError:  # pragma: no cover
        fitz = None

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
MAX_PAGES = 10
MIN_CHARS_PER_PAGE = 40
MAX_TEXT_CHARS = 60_000

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class ExtractedText:
    text: str
    method: str
    error: str = ""


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _ocr_page(page) -> str:
    try:
        tp = page.get_textpage_ocr(language="eng", dpi=200, full=True)
        return page.get_text(textpage=tp).strip()
    except Exception as exc:
        logger.debug("Certificate OCR unavailable: %s", exc)
        return ""


def _pdf_text(doc) -> ExtractedText:
    parts: list[str] = []
    used_ocr = False
    for index, page in enumerate(doc):
        if index >= MAX_PAGES:
            break
        text = page.get_text().strip()
        if len(text) < MIN_CHARS_PER_PAGE:
            ocr = _ocr_page(page)
            if len(ocr) > len(text):
                text = ocr
                used_ocr = True
        parts.append(text)
    return ExtractedText("\n".join(parts), "ocr" if used_ocr else "text")


def _from_pdf(path: Path) -> ExtractedText:
    with fitz.open(str(path)) as doc:
        return _pdf_text(doc)


def _from_image(path: Path) -> ExtractedText:
    with fitz.open(str(path)) as img:
        pdf_bytes = img.convert_to_pdf()
    with fitz.open("pdf", pdf_bytes) as doc:
        result = _pdf_text(doc)
    return ExtractedText(result.text, "ocr")


def _from_docx(path: Path) -> ExtractedText:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs = []
    for para in root.iter(f"{_W_NS}p"):
        runs = [node.text or "" for node in para.iter(f"{_W_NS}t")]
        line = "".join(runs).strip()
        if line:
            paragraphs.append(line)
    return ExtractedText("\n".join(paragraphs), "docx")


def extract_text(path: Path) -> ExtractedText:
    """Return the document text; never raises — failures are reported in ``error``."""
    path = Path(path)
    suffix = path.suffix.lower()
    if not path.is_file():
        return ExtractedText("", "none", "File not found")
    if suffix not in SUPPORTED_EXTENSIONS:
        return ExtractedText("", "none", f"Unsupported file type {suffix or '(none)'}")
    try:
        if suffix == ".txt":
            result = ExtractedText(path.read_text(encoding="utf-8", errors="ignore"), "text")
        elif suffix == ".docx":
            result = _from_docx(path)
        elif fitz is None:
            return ExtractedText("", "none", "PyMuPDF is not installed")
        elif suffix in IMAGE_EXTENSIONS:
            result = _from_image(path)
        else:
            result = _from_pdf(path)
    except Exception as exc:
        logger.warning("Certificate text extraction failed for %s: %s", path.name, exc)
        return ExtractedText("", "none", f"Could not read document: {exc}")
    text = re.sub(r"[ \t]+", " ", result.text).strip()[:MAX_TEXT_CHARS]
    return ExtractedText(text, result.method, result.error)
