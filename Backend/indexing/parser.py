"""Layout-aware PDF parsing with optional OCR for scanned pages."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.schemas import ContentType, ParsedBlock, TableCell
from indexing.section_filters import is_valid_feature_section_title, is_value_like_title
from observability.logging import logger

try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    try:
        import fitz  # type: ignore
    except ImportError:  # pragma: no cover
        fitz = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


HEADING_RE = re.compile(
    r"^(?P<title>[A-Z][A-Za-z0-9 /&\-\+\(\)]{2,80})$"
)
NUMBERED_HEADING_RE = re.compile(
    r"^(?P<num>\d+(\.\d+){0,4})\s+(?P<title>.{2,100})$"
)
KV_RE = re.compile(
    r"^(?P<key>[^:\|]{2,80})\s*[:\|]\s*(?P<value>.{1,200})$"
)


@dataclass
class ParsedDocument:
    document_id: str
    document_name: str
    page_count: int
    blocks: list[ParsedBlock] = field(default_factory=list)
    raw_pages: list[str] = field(default_factory=list)
    used_ocr_pages: list[int] = field(default_factory=list)


def _new_block_id() -> str:
    return f"blk_{uuid.uuid4().hex[:12]}"


def _estimate_heading_level(text: str, font_size: float | None = None) -> int:
    m = NUMBERED_HEADING_RE.match(text.strip())
    if m:
        return min(1 + m.group("num").count("."), 4)
    if font_size and font_size >= 16:
        return 1
    if font_size and font_size >= 13:
        return 2
    if HEADING_RE.match(text.strip()) and len(text.strip()) < 60:
        return 2
    return 3


def _blocks_from_pymupdf(
    path: Path, document_id: str, *, force_ocr: bool = False
) -> ParsedDocument:
    assert fitz is not None
    settings = get_settings()
    doc = fitz.open(path)
    blocks: list[ParsedBlock] = []
    raw_pages: list[str] = []
    ocr_pages: list[int] = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_no = page_index + 1
        page_dict = page.get_text("dict")
        page_text_parts: list[str] = []
        page_block_start = len(blocks)

        # Text spans grouped into lines
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines_text: list[str] = []
            max_size = 0.0
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                lines_text.append(line_text)
                for s in spans:
                    max_size = max(max_size, float(s.get("size") or 0))
            if not lines_text:
                continue
            text = "\n".join(lines_text).strip()
            page_text_parts.append(text)

            content_type = ContentType.PARAGRAPH
            heading_level = None
            key_values: list[dict[str, str]] = []
            list_items: list[str] = []

            if len(lines_text) == 1 and (
                NUMBERED_HEADING_RE.match(text)
                or (max_size >= 12.5 and len(text) < 90 and is_valid_feature_section_title(text))
            ):
                # Never promote specification *values* (120 Hz, F2.2, resolutions) to headings
                if is_value_like_title(text):
                    content_type = ContentType.PARAGRAPH
                else:
                    content_type = ContentType.HEADING
                    heading_level = _estimate_heading_level(text, max_size)
            elif all(KV_RE.match(ln) for ln in lines_text if ln):
                content_type = ContentType.KEY_VALUE
                for ln in lines_text:
                    m = KV_RE.match(ln)
                    if m:
                        key_values.append({"key": m.group("key").strip(), "value": m.group("value").strip()})
            elif all(re.match(r"^[\-\•\*]\s+", ln) or re.match(r"^\d+[\.\)]\s+", ln) for ln in lines_text):
                content_type = ContentType.LIST
                for ln in lines_text:
                    list_items.append(re.sub(r"^([\-\•\*]|\d+[\.\)])\s+", "", ln).strip())

            blocks.append(
                ParsedBlock(
                    block_id=_new_block_id(),
                    content_type=content_type,
                    text=text,
                    page_number=page_no,
                    heading_level=heading_level,
                    key_values=key_values,
                    list_items=list_items,
                    bbox=list(block.get("bbox") or []) or None,
                )
            )

        # Tables via find_tables when available
        try:
            finder = page.find_tables()
            tables = finder.tables if finder else []
        except Exception:
            tables = []

        for table in tables:
            try:
                raw = table.extract()
            except Exception:
                continue
            if not raw:
                continue
            cells: list[TableCell] = []
            rendered_rows: list[str] = []
            for r_i, row in enumerate(raw):
                vals = [str(c).strip() if c is not None else "" for c in row]
                rendered_rows.append(" | ".join(vals))
                for c_i, val in enumerate(vals):
                    if not val:
                        continue
                    cells.append(TableCell(row=r_i, col=c_i, text=val, header=(r_i == 0)))
            table_text = "\n".join(rendered_rows)
            page_text_parts.append(table_text)
            # Derive key-values when first column looks like field names
            key_values = []
            if len(raw) > 1 and raw[0] and len(raw[0]) >= 2:
                # header row + data, or field|value layout
                if len(raw[0]) == 2:
                    for row in raw:
                        if row and len(row) >= 2 and row[0] and row[1]:
                            key_values.append(
                                {"key": str(row[0]).strip(), "value": str(row[1]).strip()}
                            )
            blocks.append(
                ParsedBlock(
                    block_id=_new_block_id(),
                    content_type=ContentType.TABLE,
                    text=table_text,
                    page_number=page_no,
                    table_cells=cells,
                    key_values=key_values,
                )
            )

        page_text = "\n".join(page_text_parts).strip()
        need_ocr = settings.indexing.ocr_enabled and (
            force_ocr or len(page_text) < settings.indexing.ocr_min_chars_per_page
        )
        if need_ocr:
            ocr_text = _ocr_page(page)
            if ocr_text and (force_ocr or len(ocr_text) > len(page_text)):
                ocr_pages.append(page_no)
                page_text = ocr_text
                if force_ocr:
                    # Drop thin/chrome text layer; OCR becomes the page content
                    del blocks[page_block_start:]
                    ocr_paras = [
                        para.strip()
                        for para in re.split(r"\n\s*\n", ocr_text)
                        if para.strip()
                    ] or [ocr_text]
                    for para in ocr_paras:
                        blocks.append(
                            ParsedBlock(
                                block_id=_new_block_id(),
                                content_type=ContentType.PARAGRAPH,
                                text=para,
                                page_number=page_no,
                            )
                        )
                else:
                    blocks.append(
                        ParsedBlock(
                            block_id=_new_block_id(),
                            content_type=ContentType.PARAGRAPH,
                            text=ocr_text,
                            page_number=page_no,
                        )
                    )
        raw_pages.append(page_text)

    doc.close()
    return ParsedDocument(
        document_id=document_id,
        document_name=path.name,
        page_count=len(raw_pages),
        blocks=blocks,
        raw_pages=raw_pages,
        used_ocr_pages=ocr_pages,
    )


def _ocr_page(page: Any) -> str:
    """OCR a page using PyMuPDF's built-in OCR if Tesseract is available."""
    try:
        tp = page.get_textpage_ocr(language="eng", dpi=200, full=True)
        return page.get_text(textpage=tp).strip()
    except Exception as exc:
        logger.debug("OCR unavailable for page: %s", exc)
        return ""


def _blocks_from_pypdf(path: Path, document_id: str) -> ParsedDocument:
    assert PdfReader is not None
    reader = PdfReader(str(path))
    blocks: list[ParsedBlock] = []
    raw_pages: list[str] = []
    for i, page in enumerate(reader.pages):
        page_no = i + 1
        text = (page.extract_text() or "").strip()
        raw_pages.append(text)
        if not text:
            continue
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            content_type = ContentType.PARAGRAPH
            heading_level = None
            key_values: list[dict[str, str]] = []
            first_line = para.split("\n", 1)[0].strip()
            if NUMBERED_HEADING_RE.match(first_line) or (
                HEADING_RE.match(first_line) and len(para) < 120
            ):
                content_type = ContentType.HEADING
                heading_level = _estimate_heading_level(first_line)
            elif KV_RE.match(first_line):
                content_type = ContentType.KEY_VALUE
                for ln in para.split("\n"):
                    m = KV_RE.match(ln.strip())
                    if m:
                        key_values.append({"key": m.group("key").strip(), "value": m.group("value").strip()})
            blocks.append(
                ParsedBlock(
                    block_id=_new_block_id(),
                    content_type=content_type,
                    text=para,
                    page_number=page_no,
                    heading_level=heading_level,
                    key_values=key_values,
                )
            )
    return ParsedDocument(
        document_id=document_id,
        document_name=path.name,
        page_count=len(raw_pages),
        blocks=blocks,
        raw_pages=raw_pages,
    )


def parse_pdf(
    path: Path,
    document_id: str,
    document_name: str | None = None,
    *,
    force_ocr: bool = False,
) -> ParsedDocument:
    """Parse a PDF preserving layout blocks, tables, and headings."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    if fitz is not None:
        parsed = _blocks_from_pymupdf(path, document_id, force_ocr=force_ocr)
    elif PdfReader is not None:
        logger.warning("PyMuPDF not installed; falling back to pypdf (less layout-aware)")
        parsed = _blocks_from_pypdf(path, document_id)
        if force_ocr:
            logger.warning("force_ocr requested but pypdf fallback cannot OCR")
    else:
        raise RuntimeError("Install pymupdf or pypdf for PDF parsing")

    parsed.document_name = document_name or path.name
    logger.info(
        "Parsed %s: %d pages, %d blocks, OCR pages=%s force_ocr=%s",
        parsed.document_name,
        parsed.page_count,
        len(parsed.blocks),
        parsed.used_ocr_pages,
        force_ocr,
    )
    return parsed
