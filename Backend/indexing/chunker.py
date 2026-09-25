"""Hierarchical / semantic chunking with parent-child relationships."""

from __future__ import annotations

import re
import uuid
from typing import Iterable

from core.config import get_settings
from core.schemas import Chunk, ChunkMetadata, ContentType, DocumentStructure, ParsedBlock
from indexing.parser import ParsedDocument


def estimate_tokens(text: str) -> int:
    # Approx: ~4 chars/token for technical English
    return max(1, len(text) // 4)


def _chunk_id() -> str:
    return f"chk_{uuid.uuid4().hex[:12]}"


def _split_with_overlap(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    if estimate_tokens(text) <= max_tokens:
        return [text]
    # Prefer splitting on paragraph / line boundaries
    parts = re.split(r"\n\s*\n|\n", text)
    parts = [p.strip() for p in parts if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for part in parts:
        pt = estimate_tokens(part)
        if buf and buf_tokens + pt > max_tokens:
            chunks.append("\n".join(buf).strip())
            # overlap: keep trailing pieces
            overlap: list[str] = []
            ot = 0
            for prev in reversed(buf):
                t = estimate_tokens(prev)
                if ot + t > overlap_tokens:
                    break
                overlap.insert(0, prev)
                ot += t
            buf = overlap
            buf_tokens = ot
        if pt > max_tokens:
            # hard wrap by words
            words = part.split()
            cur: list[str] = []
            ct = 0
            for w in words:
                wt = estimate_tokens(w) + 1
                if cur and ct + wt > max_tokens:
                    chunks.append(" ".join(cur))
                    # word overlap
                    keep = max(1, int(len(cur) * overlap_tokens / max(max_tokens, 1)))
                    cur = cur[-keep:]
                    ct = estimate_tokens(" ".join(cur))
                cur.append(w)
                ct += wt
            if cur:
                buf = cur
                buf_tokens = ct
            continue
        buf.append(part)
        buf_tokens += pt
    if buf:
        chunks.append("\n".join(buf).strip())
    return [c for c in chunks if c]


def _block_text_for_chunk(block: ParsedBlock) -> str:
    if block.content_type == ContentType.TABLE and block.key_values:
        lines = [f"{kv['key']}: {kv['value']}" for kv in block.key_values]
        return "\n".join(lines) if lines else block.text
    if block.content_type == ContentType.KEY_VALUE and block.key_values:
        return "\n".join(f"{kv['key']}: {kv['value']}" for kv in block.key_values)
    if block.content_type == ContentType.LIST and block.list_items:
        return "\n".join(f"- {item}" for item in block.list_items)
    return block.text


def _group_blocks_by_section(parsed: ParsedDocument, structure: DocumentStructure) -> list[tuple[str, str | None, list[ParsedBlock]]]:
    """Return (section, subsection, blocks) groups preserving order."""
    blocks_by_id = {b.block_id: b for b in parsed.blocks}
    groups: list[tuple[str, str | None, list[ParsedBlock]]] = []

    for sec in structure.sections:
        if sec.level == 0:
            continue
        sec_blocks = [blocks_by_id[bid] for bid in sec.block_ids if bid in blocks_by_id]
        if not sec_blocks:
            continue
        # subsection = self if nested else None
        section_title = sec.title
        subsection = None
        if sec.level >= 2 and sec.parent_id:
            parent = next((s for s in structure.sections if s.section_id == sec.parent_id), None)
            if parent and parent.level > 0:
                section_title = parent.title
                subsection = sec.title
        groups.append((section_title, subsection, sec_blocks))

    # Orphan blocks (no section assignment)
    assigned = {bid for g in groups for b in g[2] for bid in [b.block_id]}
    orphans = [b for b in parsed.blocks if b.block_id not in assigned and b.content_type != ContentType.HEADING]
    if orphans:
        groups.insert(0, ("Document Root", None, orphans))
    return groups


def build_chunks(
    parsed: ParsedDocument,
    structure: DocumentStructure,
    document_name: str,
) -> list[Chunk]:
    settings = get_settings()
    max_tokens = settings.indexing.chunk_max_tokens
    child_max = settings.indexing.child_chunk_max_tokens
    overlap = settings.indexing.chunk_overlap_tokens

    chunks: list[Chunk] = []
    groups = _group_blocks_by_section(parsed, structure)

    for section, subsection, blocks in groups:
        # Keep table / key-value blocks atomic when possible
        atomic: list[ParsedBlock] = []
        prose: list[ParsedBlock] = []
        for b in blocks:
            if b.content_type in {ContentType.TABLE, ContentType.KEY_VALUE, ContentType.LIST}:
                if atomic or prose:
                    chunks.extend(
                        _emit_group_chunks(
                            atomic + prose,
                            parsed.document_id,
                            document_name,
                            section,
                            subsection,
                            max_tokens,
                            child_max,
                            overlap,
                        )
                    )
                    atomic, prose = [], []
                chunks.extend(
                    _emit_group_chunks(
                        [b],
                        parsed.document_id,
                        document_name,
                        section,
                        subsection,
                        max_tokens,
                        child_max,
                        overlap,
                    )
                )
            else:
                prose.append(b)
        if atomic or prose:
            chunks.extend(
                _emit_group_chunks(
                    atomic + prose,
                    parsed.document_id,
                    document_name,
                    section,
                    subsection,
                    max_tokens,
                    child_max,
                    overlap,
                )
            )

    # Link prev/next
    for i, ch in enumerate(chunks):
        if i > 0:
            ch.metadata.prev_chunk_id = chunks[i - 1].chunk_id
        if i < len(chunks) - 1:
            ch.metadata.next_chunk_id = chunks[i + 1].chunk_id
    return chunks


def _emit_group_chunks(
    blocks: list[ParsedBlock],
    document_id: str,
    document_name: str,
    section: str,
    subsection: str | None,
    max_tokens: int,
    child_max: int,
    overlap: int,
) -> list[Chunk]:
    if not blocks:
        return []
    header = section if not subsection else f"{section} > {subsection}"
    body = "\n\n".join(_block_text_for_chunk(b) for b in blocks).strip()
    if not body:
        return []
    text = f"[{header}]\n{body}"
    page = blocks[0].page_number
    content_type = blocks[0].content_type if len(blocks) == 1 else ContentType.MIXED
    block_ids = [b.block_id for b in blocks]
    parent_id = _chunk_id()
    parent_meta = ChunkMetadata(
        document_id=document_id,
        document_name=document_name,
        page_number=page,
        section=section,
        subsection=subsection,
        chunk_id=parent_id,
        parent_chunk_id=None,
        content_type=content_type,
        token_estimate=estimate_tokens(text),
        block_ids=block_ids,
    )
    parent = Chunk(chunk_id=parent_id, text=text, metadata=parent_meta)

    if estimate_tokens(text) <= max_tokens:
        return [parent]

    # Parent retained for context expansion; children are retrievable units
    out = [parent]
    pieces = _split_with_overlap(body, child_max, overlap)
    for piece in pieces:
        cid = _chunk_id()
        child_text = f"[{header}]\n{piece}"
        meta = ChunkMetadata(
            document_id=document_id,
            document_name=document_name,
            page_number=page,
            section=section,
            subsection=subsection,
            chunk_id=cid,
            parent_chunk_id=parent_id,
            content_type=content_type,
            token_estimate=estimate_tokens(child_text),
            block_ids=block_ids,
        )
        out.append(Chunk(chunk_id=cid, text=child_text, metadata=meta))
    return out


def retrievable_chunks(chunks: Iterable[Chunk]) -> list[Chunk]:
    """Prefer child chunks when present; otherwise parents."""
    chunks = list(chunks)
    children = [c for c in chunks if c.metadata.parent_chunk_id]
    if children:
        # Also include parents that have no children
        parent_ids_with_children = {c.metadata.parent_chunk_id for c in children}
        lone_parents = [
            c
            for c in chunks
            if c.metadata.parent_chunk_id is None and c.chunk_id not in parent_ids_with_children
        ]
        return children + lone_parents
    return chunks
