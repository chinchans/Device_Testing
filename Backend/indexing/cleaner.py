"""Text cleaning without rewriting technical terminology."""

from __future__ import annotations

import re
from collections import Counter

from core.schemas import ParsedBlock
from indexing.chrome_filter import strip_chrome_text
from indexing.parser import ParsedDocument


_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_SOFT_HYPHEN_RE = re.compile(r"(\w)-\n(\w)")


def _normalize_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = _SOFT_HYPHEN_RE.sub(r"\1\2", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln is not None)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def _detect_repeated_lines(pages: list[str], min_ratio: float = 0.4) -> set[str]:
    """Find header/footer lines that repeat across many pages."""
    if len(pages) < 3:
        return set()
    counter: Counter[str] = Counter()
    for page in pages:
        lines = [ln.strip() for ln in page.split("\n") if ln.strip()]
        # Only consider short edge lines as header/footer candidates
        edge = set(lines[:2] + lines[-2:])
        for ln in edge:
            if 3 <= len(ln) <= 80:
                counter[ln] += 1
    threshold = max(2, int(len(pages) * min_ratio))
    return {ln for ln, c in counter.items() if c >= threshold}


def clean_parsed_document(parsed: ParsedDocument) -> ParsedDocument:
    repeated = _detect_repeated_lines(parsed.raw_pages)
    cleaned_blocks: list[ParsedBlock] = []
    for block in parsed.blocks:
        text = strip_chrome_text(_normalize_text(block.text))
        if not text:
            continue
        # Drop pure header/footer noise blocks
        if text in repeated and block.content_type.value in {"paragraph", "heading"}:
            continue
        lines = [ln for ln in text.split("\n") if ln.strip() not in repeated]
        text = "\n".join(lines).strip()
        if not text:
            continue
        data = block.model_dump()
        data["text"] = text
        cleaned_blocks.append(ParsedBlock.model_validate(data))

    cleaned_pages = []
    for page in parsed.raw_pages:
        page = strip_chrome_text(_normalize_text(page))
        lines = [ln for ln in page.split("\n") if ln.strip() not in repeated]
        cleaned_pages.append("\n".join(lines).strip())

    parsed.blocks = cleaned_blocks
    parsed.raw_pages = cleaned_pages
    return parsed
