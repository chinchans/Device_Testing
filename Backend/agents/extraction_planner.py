"""Extraction planner — builds per-section tasks from discovered structure."""

from __future__ import annotations

import re
import uuid

from core.schemas import DocumentSection, DocumentStructure, ExtractionTask, QueryIntent
from indexing.section_filters import is_valid_feature_section_title
from indexing.structure import specification_sections


def _task_id() -> str:
    return f"task_{uuid.uuid4().hex[:10]}"


def _expand_queries_from_title(title: str) -> list[str]:
    """Lightweight expansion from section terminology — no invented device categories."""
    queries = [
        f"{title} specifications",
        title,
    ]
    parts = re.split(r"[\/\|,&]+|\band\b", title, flags=re.I)
    for part in parts:
        part = part.strip()
        if part and part.lower() != title.lower() and len(part) > 1:
            queries.append(part)
            queries.append(f"{part} specifications")
    seen = set()
    out = []
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


_PARAMISH = {
    "resolution", "technology", "refresh", "rate", "brightness", "size",
    "type", "version", "capacity", "speed", "weight", "dimension", "flash",
    "aperture", "pixels", "model", "chipset",
}


def _is_paramish_title(title: str) -> bool:
    words = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", title) if w]
    if len(words) >= 2 and any(w in _PARAMISH for w in words):
        return True
    return False


def _plan_sections_for_full_doc(structure: DocumentStructure) -> list[DocumentSection]:
    """
    Prefer module-level sections over parameter-like subsections.

    If parent "Display" has children "Display Resolution" / "Technology",
    emit one task for Display (not one per child).
    """
    sections = specification_sections(structure)
    by_id = {s.section_id: s for s in structure.sections}
    chosen: list[DocumentSection] = []
    skipped_children: set[str] = set()

    # First pass: parents that have only/mostly paramish children → keep parent
    for sec in sections:
        if sec.section_id in skipped_children:
            continue
        child_secs = [by_id[cid] for cid in sec.children if cid in by_id]
        spec_children = [c for c in child_secs if c.is_specification_bearing]
        if spec_children and all(_is_paramish_title(c.title) or _norm(sec.title) in _norm(c.title) for c in spec_children):
            # Roll children into parent task
            for c in spec_children:
                skipped_children.add(c.section_id)
            # Parent may have no direct blocks — still keep it
            chosen.append(sec)
            continue
        if not sec.block_ids and sec.children:
            # empty organizer — skip unless we already handled above
            continue
        if _is_paramish_title(sec.title) and sec.parent_id and sec.parent_id in by_id:
            parent = by_id[sec.parent_id]
            if parent.level > 0:
                # Will be covered by parent if parent is chosen; mark for skip if parent later chosen
                # Prefer attaching to parent immediately
                if parent.section_id not in {c.section_id for c in chosen} and parent.level > 0:
                    if parent not in chosen:
                        # Only add parent once
                        if all(p.section_id != parent.section_id for p in chosen):
                            chosen.append(parent)
                skipped_children.add(sec.section_id)
                continue
        chosen.append(sec)

    # Deduplicate by section_id preserving order
    seen: set[str] = set()
    out: list[DocumentSection] = []
    for sec in chosen:
        if sec.section_id in seen or sec.section_id in skipped_children:
            continue
        # If this is a paramish child whose parent was chosen, skip
        if sec.parent_id and any(p.section_id == sec.parent_id for p in out) and _is_paramish_title(sec.title):
            continue
        seen.add(sec.section_id)
        out.append(sec)
    return out


def plan_extraction(
    structure: DocumentStructure,
    query: str,
    intent: QueryIntent,
) -> list[ExtractionTask]:
    if intent == QueryIntent.FULL_DOCUMENT_EXTRACTION:
        plan_secs = [
            s for s in _plan_sections_for_full_doc(structure)
            if is_valid_feature_section_title(s.title)
        ]
        tasks = []
        for sec in plan_secs:
            queries = _expand_queries_from_title(sec.title)
            # Include child titles in retrieval queries so param subsections still get retrieved
            by_id = {s.section_id: s for s in structure.sections}
            for cid in sec.children:
                child = by_id.get(cid)
                if child:
                    queries.append(child.title)
                    queries.append(f"{child.title} specifications")
            # dedupe
            seen = set()
            uniq = []
            for q in queries:
                if q.lower() not in seen:
                    seen.add(q.lower())
                    uniq.append(q)
            tasks.append(
                ExtractionTask(
                    task_id=_task_id(),
                    section_title=sec.title,
                    section_id=sec.section_id,
                    queries=uniq,
                )
            )
        if not tasks:
            tasks.append(
                ExtractionTask(
                    task_id=_task_id(),
                    section_title="All Specifications",
                    section_id=None,
                    queries=[query or "product features and specifications", "specifications"],
                )
            )
        return tasks

    sections = specification_sections(structure)

    if intent == QueryIntent.FEATURE_EXTRACTION:
        q_lower = query.lower()
        matched = [
            s
            for s in sections
            if any(tok in s.title.lower() for tok in q_lower.split() if len(tok) > 2)
        ]
        if not matched:
            return [
                ExtractionTask(
                    task_id=_task_id(),
                    section_title=query.strip() or "Requested Feature",
                    queries=[query, f"{query} specifications"],
                )
            ]
        return [
            ExtractionTask(
                task_id=_task_id(),
                section_title=s.title,
                section_id=s.section_id,
                queries=_expand_queries_from_title(s.title),
            )
            for s in matched
        ]

    if intent == QueryIntent.COMPARISON:
        return [
            ExtractionTask(
                task_id=_task_id(),
                section_title=query,
                queries=[query, "specifications"],
            )
        ]

    return [
        ExtractionTask(
            task_id=_task_id(),
            section_title=query.strip()[:80] or "Lookup",
            queries=[query],
        )
    ]
