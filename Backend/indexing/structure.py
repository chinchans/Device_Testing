"""Dynamic document structure discovery — no hard-coded feature taxonomy."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Iterable

from core.schemas import (
    ContentType,
    DocumentSection,
    DocumentStructure,
    ParsedBlock,
)
from indexing.parser import ParsedDocument
from indexing.section_filters import (
    is_nav_or_chrome,
    is_valid_feature_section_title,
    is_value_like_title,
    looks_like_parameter_label,
    looks_like_parameter_value,
)
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger


NON_SPEC_HINTS = re.compile(
    r"^(table of contents|toc|contents|index|revision history|legal|copyright|"
    r"trademark|disclaimer|about this document|preface|introduction to this guide|"
    r"reviews?|specifications)$",
    re.I,
)

# Numbered / outline headings commonly used in product specs
SECTION_LINE_RE = re.compile(
    r"^(?:"
    r"(?P<num>\d+(?:\.\d+){0,4})\.?\s+"
    r"|(?P<xml>[IVXLC]{1,6})\.\s+"
    r"|(?P<letter>[A-Z])\.\s+"
    r")"
    r"(?P<title>[A-Za-z][A-Za-z0-9 /&\-\+\(\)]{1,80})$"
)

# Single-token / short module titles often glued to the next label:
# "Processor\nCPU Speed", "Display\nSize (Main Display)"
MODULE_FIRST_LINE = re.compile(
    r"^[A-Za-z][A-Za-z0-9][A-Za-z0-9 &\-/]{0,40}$"
)


def _section_id() -> str:
    return f"sec_{uuid.uuid4().hex[:10]}"


def _looks_specification_bearing(title: str, blocks: Iterable[ParsedBlock]) -> bool:
    if not is_valid_feature_section_title(title):
        return False
    if NON_SPEC_HINTS.match(title.strip()):
        return False
    block_list = list(blocks)
    for b in block_list:
        if b.content_type in {ContentType.TABLE, ContentType.KEY_VALUE, ContentType.LIST}:
            return True
        if re.search(r"\d", b.text) and (
            ":" in b.text
            or "|" in b.text
            or re.search(r"\b(mm|ghz|mhz|gb|tb|hz|w|v|mah|mp)\b", b.text, re.I)
        ):
            return True
        if ":" in b.text or b.key_values:
            return True
    return bool(block_list)


def _heading_from_line(line: str) -> tuple[str, int] | None:
    line = line.strip()
    if not line or len(line) > 80:
        return None
    if is_value_like_title(line) or is_nav_or_chrome(line):
        return None
    m = SECTION_LINE_RE.match(line)
    if m:
        title = m.group("title").strip()
        if not is_valid_feature_section_title(title):
            return None
        num = m.group("num")
        level = 1 + num.count(".") if num else 1
        return title, min(level, 4)
    # ALL CAPS short labels (e.g. PROCESSOR) — but not REVIEWS / chrome
    if line.isupper() and 3 <= len(line) <= 40 and ":" not in line:
        titled = line.title()
        if is_valid_feature_section_title(titled):
            return titled, 1
    return None


def _demote_invalid_headings(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    out: list[ParsedBlock] = []
    for b in blocks:
        if b.content_type == ContentType.HEADING and not is_valid_feature_section_title(b.text):
            child = b.model_copy(deep=True)
            child.content_type = ContentType.PARAGRAPH
            child.heading_level = None
            out.append(child)
        else:
            out.append(b)
    return out


def _split_glued_module_labels(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    """Turn 'Processor\\nCPU Speed' into HEADING(Processor) + PARAGRAPH(CPU Speed)."""
    out: list[ParsedBlock] = []
    for block in blocks:
        if block.content_type == ContentType.HEADING:
            out.append(block)
            continue
        lines = [ln.strip() for ln in block.text.split("\n") if ln.strip()]
        if len(lines) >= 2 and MODULE_FIRST_LINE.match(lines[0]) and is_valid_feature_section_title(lines[0]):
            # First line is module; rest stay as body (often a parameter label)
            out.append(
                ParsedBlock(
                    block_id=f"blk_{uuid.uuid4().hex[:12]}",
                    content_type=ContentType.HEADING,
                    text=lines[0],
                    page_number=block.page_number,
                    heading_level=1,
                )
            )
            rest = "\n".join(lines[1:])
            child = block.model_copy(deep=True)
            child.block_id = f"blk_{uuid.uuid4().hex[:12]}"
            child.text = rest
            child.content_type = ContentType.PARAGRAPH
            out.append(child)
            continue
        out.append(block)
    return out


def _pair_label_value_blocks(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    """
    Samsung-style stacks:
      CPU Speed
      4.47GHz, 3.5GHz
    → one KEY_VALUE block.
    """
    out: list[ParsedBlock] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if (
            b.content_type == ContentType.PARAGRAPH
            and i + 1 < len(blocks)
            and blocks[i + 1].content_type == ContentType.PARAGRAPH
            and looks_like_parameter_label(b.text)
            and looks_like_parameter_value(blocks[i + 1].text)
        ):
            nxt = blocks[i + 1]
            out.append(
                ParsedBlock(
                    block_id=f"blk_{uuid.uuid4().hex[:12]}",
                    content_type=ContentType.KEY_VALUE,
                    text=f"{b.text.strip()}: {nxt.text.strip()}",
                    page_number=b.page_number,
                    key_values=[{"key": b.text.strip(), "value": nxt.text.strip()}],
                )
            )
            i += 2
            continue
        out.append(b)
        i += 1
    return out


def _explode_blocks_on_inline_headings(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    """Split multi-line paragraph blocks when they contain numbered section headings."""
    out: list[ParsedBlock] = []
    for block in blocks:
        if block.content_type == ContentType.HEADING:
            out.append(block)
            continue
        lines = block.text.split("\n")
        if len(lines) <= 1:
            out.append(block)
            continue

        has_inline = any(_heading_from_line(ln) for ln in lines)
        if not has_inline:
            out.append(block)
            continue

        buf: list[str] = []
        for ln in lines:
            heading = _heading_from_line(ln)
            if heading:
                if buf:
                    text = "\n".join(buf).strip()
                    if text:
                        child = block.model_copy(deep=True)
                        child.block_id = f"blk_{uuid.uuid4().hex[:12]}"
                        child.text = text
                        child.content_type = (
                            ContentType.KEY_VALUE if ":" in text else ContentType.PARAGRAPH
                        )
                        out.append(child)
                    buf = []
                title, level = heading
                out.append(
                    ParsedBlock(
                        block_id=f"blk_{uuid.uuid4().hex[:12]}",
                        content_type=ContentType.HEADING,
                        text=title,
                        page_number=block.page_number,
                        heading_level=level,
                    )
                )
            else:
                buf.append(ln)
        if buf:
            text = "\n".join(buf).strip()
            if text:
                child = block.model_copy(deep=True)
                child.block_id = f"blk_{uuid.uuid4().hex[:12]}"
                child.text = text
                child.content_type = (
                    ContentType.KEY_VALUE if ":" in text else ContentType.PARAGRAPH
                )
                out.append(child)
    return out


def discover_structure(parsed: ParsedDocument) -> DocumentStructure:
    """Build Document → Section → Subsection hierarchy from headings/blocks."""
    blocks = _demote_invalid_headings(parsed.blocks)
    blocks = _split_glued_module_labels(blocks)
    blocks = _explode_blocks_on_inline_headings(blocks)
    blocks = _pair_label_value_blocks(blocks)
    parsed.blocks = blocks

    sections: list[DocumentSection] = []
    section_by_id: dict[str, DocumentSection] = {}

    root = DocumentSection(
        section_id=_section_id(),
        title="Document Root",
        level=0,
        page_start=1,
        is_specification_bearing=False,
    )
    sections.append(root)
    section_by_id[root.section_id] = root
    current: DocumentSection = root
    stack: list[DocumentSection] = [root]

    for block in parsed.blocks:
        is_heading = block.content_type == ContentType.HEADING
        heading_info = None
        if is_heading and block.text.strip():
            title = block.text.strip().split("\n", 1)[0].strip()
            if is_valid_feature_section_title(title):
                heading_info = (title, block.heading_level or 1)
        elif not is_heading:
            first = block.text.strip().split("\n", 1)[0].strip()
            if "\n" not in block.text.strip():
                heading_info = _heading_from_line(first)

        if heading_info:
            title, level = heading_info
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else root
            sec = DocumentSection(
                section_id=_section_id(),
                title=title,
                level=level,
                page_start=block.page_number,
                parent_id=parent.section_id,
            )
            parent.children.append(sec.section_id)
            sections.append(sec)
            section_by_id[sec.section_id] = sec
            stack.append(sec)
            current = sec
            block.content_type = ContentType.HEADING
            block.heading_level = level
            block.section = title
            continue

        current.block_ids.append(block.block_id)
        current.page_end = block.page_number
        if current.level >= 2 and current.parent_id:
            parent = section_by_id.get(current.parent_id)
            block.section = parent.title if parent and parent.level > 0 else current.title
            block.subsection = current.title if parent and parent.level > 0 else None
        else:
            block.section = current.title if current.level > 0 else None
            block.subsection = None

    blocks_by_id = {b.block_id: b for b in parsed.blocks}
    for sec in sections:
        if sec.level == 0:
            sec.is_specification_bearing = False
            continue
        if not is_valid_feature_section_title(sec.title):
            sec.is_specification_bearing = False
            continue
        sec_blocks = [blocks_by_id[bid] for bid in sec.block_ids if bid in blocks_by_id]
        for child_id in sec.children:
            child = section_by_id[child_id]
            sec_blocks.extend(
                blocks_by_id[bid] for bid in child.block_ids if bid in blocks_by_id
            )
        sec.is_specification_bearing = _looks_specification_bearing(sec.title, sec_blocks)

    product_name, product_type = _infer_product_identity(parsed)

    structure = DocumentStructure(
        document_id=parsed.document_id,
        sections=sections,
        product_name=product_name,
        product_type=product_type,
    )
    logger.info(
        "Discovered %d sections (%d specification-bearing) for %s",
        len(sections),
        sum(1 for s in sections if s.is_specification_bearing),
        parsed.document_id,
    )
    return structure


def _infer_product_identity(parsed: ParsedDocument) -> tuple[str | None, str | None]:
    head = "\n".join(parsed.raw_pages[:2])[:2500]
    fallback_name = re.sub(r"[_\-]+", " ", Path(parsed.document_name).stem).strip() or None

    if not is_azure_configured() or len(head) < 40:
        return fallback_name, None

    prompt = (
        "From the following product specification excerpt, extract product_name and "
        "product_type if explicitly stated. product_type should be a short noun phrase "
        "from the document (e.g. as written). Do NOT invent. Return JSON: "
        '{"product_name": str|null, "product_type": str|null}\n\n'
        f"EXCERPT:\n{head}"
    )
    try:
        content, _ = chat_completion(
            [
                {
                    "role": "system",
                    "content": "Extract only explicitly stated product identity. JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        data = parse_json_content(content) or {}
        name = data.get("product_name") or fallback_name
        ptype = data.get("product_type")
        return name, ptype
    except Exception as exc:
        logger.debug("Product identity inference skipped: %s", exc)
        return fallback_name, None


def specification_sections(structure: DocumentStructure) -> list[DocumentSection]:
    """Return discovered specification-bearing sections (excluding root / junk)."""
    return [
        s
        for s in structure.sections
        if s.is_specification_bearing
        and s.level > 0
        and (s.block_ids or s.children)
        and is_valid_feature_section_title(s.title)
    ]
