"""LLM normalization: dirty page text → RAG-friendly structured ParsedDocument."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.schemas import ContentType, ParsedBlock
from indexing.chrome_filter import is_chrome_heavy, strip_chrome_text
from indexing.module_remap import remap_normalized_modules
from indexing.parser import ParsedDocument, _ocr_page
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger

try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    try:
        import fitz  # type: ignore
    except ImportError:  # pragma: no cover
        fitz = None

NORMALIZE_SYSTEM = """You convert messy product-specification page text (often from OCR or webpage PDFs)
into clean, RAG-friendly structured JSON.

Rules:
- Use ONLY facts present in the provided text. Never invent specifications.
- Remove website chrome: cookies, nav, footers, ads, email signup, legal boilerplate.
- Fix obvious OCR typos when unambiguous (e.g. 5OMP→50MP, mAnItyp→mAh (typ), A5W→45W).
- Group EVERY spec under the ONE correct module. Never mix domains in one module.
  Critical placement rules:
  - Storage sizes (GB/TB SKUs, Capacity) → Memory & Storage (NOT Battery)
  - Face ID, Touch ID, LiDAR, magnets, magnetometer, gyros → Sensors (NOT Battery)
  - mAh, charging watts, MagSafe/Qi charge times, battery life hours → Battery & Charging
  - Wi-Fi / Bluetooth / NFC → Connectivity
  - SIM / 5G / LTE bands → Cellular & SIM
  - Speakers / mics / jack / Dolby → Audio
  - USB-C / USB ports → USB (separate from Audio)
- Prefer these module titles when they fit:
  Camera, Connectivity, Cellular & SIM, Display & Touchscreen,
  Battery & Charging, Sensors, Audio, USB,
  Operating System, Processor & Performance, Memory & Storage.
  Always include OS / Processor (CPU/chipset) / Memory & Storage (RAM + internal storage)
  when those facts appear in the text — they are needed for device classification.
- Prefer key/value specs. Use notes for short bullet features without a clear value.
- Skip marketing-only sections (Built-in Apps lists, Sustainability, Support and Services,
  Environmental copy) unless they contain measurable device specs.
- If a page has no product specs, return empty modules for that page.
- Output JSON only, matching the schema exactly.
"""

NORMALIZE_SCHEMA_HINT = """
Return JSON:
{
  "product_name": "string or null",
  "modules": [
    {
      "name": "Module title",
      "specs": [{"key": "Parameter", "value": "Value"}],
      "notes": ["optional short feature lines"]
    }
  ]
}
"""


def _block_id() -> str:
    return f"blk_{uuid.uuid4().hex[:12]}"


def prepare_clear_page_texts(
    path: Path | None,
    parsed: ParsedDocument,
    *,
    force_full_ocr: bool = False,
) -> tuple[list[str], list[int]]:
    """
    Build one chrome-stripped text string per page.
    Re-OCR pages when native text is thin or chrome-heavy so image content is included.
    """
    settings = get_settings()
    pages_out: list[str] = []
    ocr_used: list[int] = list(parsed.used_ocr_pages or [])
    doc = None
    if path is not None and fitz is not None and settings.indexing.ocr_enabled:
        try:
            doc = fitz.open(path)
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not open PDF for OCR refresh: %s", exc)
            doc = None

    for i, raw in enumerate(parsed.raw_pages):
        page_no = i + 1
        text = strip_chrome_text(raw or "")
        need_ocr = force_full_ocr or (
            settings.indexing.ocr_enabled
            and (
                len(text) < settings.indexing.ocr_min_chars_per_page
                or is_chrome_heavy(raw or "")
                or is_chrome_heavy(text)
            )
        )
        if need_ocr and doc is not None and i < len(doc):
            try:
                ocr_text = _ocr_page(doc[i])
                ocr_clean = strip_chrome_text(ocr_text)
                if ocr_clean and (
                    force_full_ocr
                    or len(ocr_clean) > len(text) * 0.8
                    or is_chrome_heavy(raw or "")
                ):
                    text = ocr_clean
                    if page_no not in ocr_used:
                        ocr_used.append(page_no)
            except Exception as exc:  # pragma: no cover
                logger.debug("OCR refresh failed page %s: %s", page_no, exc)
        pages_out.append(text)

    if doc is not None:
        doc.close()
    return pages_out, sorted(ocr_used)


def _merge_module_maps(
    base: dict[str, dict[str, Any]], incoming: list[dict[str, Any]]
) -> None:
    for mod in incoming:
        if not isinstance(mod, dict):
            continue
        name = str(mod.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        slot = base.setdefault(
            key, {"name": name, "specs": [], "notes": [], "_spec_keys": set()}
        )
        for sp in mod.get("specs") or []:
            if not isinstance(sp, dict):
                continue
            k = str(sp.get("key") or "").strip()
            v = str(sp.get("value") or "").strip()
            if not k or not v:
                continue
            sk = k.lower()
            if sk in slot["_spec_keys"]:
                continue
            slot["_spec_keys"].add(sk)
            slot["specs"].append({"key": k, "value": v})
        for note in mod.get("notes") or []:
            n = str(note).strip()
            if n and n not in slot["notes"]:
                slot["notes"].append(n)


def _normalize_chunk(text: str, *, page_hint: str) -> dict[str, Any]:
    settings = get_settings()
    user = (
        f"{NORMALIZE_SCHEMA_HINT}\n"
        f"Source context: {page_hint}\n\n"
        f"--- PAGE TEXT ---\n{text}\n--- END ---"
    )
    content, usage = chat_completion(
        [
            {"role": "system", "content": NORMALIZE_SYSTEM},
            {"role": "user", "content": user},
        ],
        deployment=settings.cheap_model,
        temperature=0.0,
        response_format={"type": "json_object"},
        max_tokens=4096,
    )
    logger.debug("rag_normalize tokens=%s page=%s", usage, page_hint)
    data = parse_json_content(content) or {}
    if not isinstance(data, dict):
        return {"product_name": None, "modules": []}
    modules = data.get("modules") or []
    if not isinstance(modules, list):
        modules = []
    return {
        "product_name": data.get("product_name"),
        "modules": modules,
    }


def normalize_pages_with_llm(
    page_texts: list[str],
    *,
    document_name: str = "",
) -> dict[str, Any]:
    """Call Azure page-by-page (or batched) and merge modules."""
    settings = get_settings()
    max_chars = int(getattr(settings.indexing, "llm_normalize_max_chars_per_call", 10000))
    merged: dict[str, dict[str, Any]] = {}
    product_name: str | None = None

    # Prefer batching consecutive pages while under budget
    batch: list[tuple[int, str]] = []
    batch_chars = 0

    def flush() -> None:
        nonlocal product_name, batch, batch_chars
        if not batch:
            return
        parts = []
        pages = []
        for pno, txt in batch:
            if not txt.strip():
                continue
            parts.append(f"### Page {pno}\n{txt}")
            pages.append(str(pno))
        batch = []
        batch_chars = 0
        if not parts:
            return
        blob = "\n\n".join(parts)
        hint = f"document={document_name}; pages={','.join(pages)}"
        try:
            result = _normalize_chunk(blob, page_hint=hint)
        except Exception as exc:
            logger.exception("LLM normalize failed for %s: %s", hint, exc)
            return
        if result.get("product_name") and not product_name:
            product_name = str(result["product_name"]).strip() or None
        _merge_module_maps(merged, result.get("modules") or [])

    for i, text in enumerate(page_texts):
        t = (text or "").strip()
        if not t:
            continue
        if batch and batch_chars + len(t) > max_chars:
            flush()
        batch.append((i + 1, t))
        batch_chars += len(t)
    flush()

    modules = []
    for slot in merged.values():
        modules.append(
            {
                "name": slot["name"],
                "specs": slot["specs"],
                "notes": slot["notes"],
            }
        )
    # Stable-ish order: common mobile modules first, then alpha
    priority = {
        "colours": 0,
        "colors": 0,
        "processor": 1,
        "storage & ram": 2,
        "storage": 2,
        "ram": 2,
        "physical": 3,
        "display": 4,
        "rear camera": 5,
        "front camera": 6,
        "camera": 5,
        "battery & charging": 7,
        "battery": 7,
        "charging": 7,
        "security": 8,
        "network & connectivity": 9,
        "network": 9,
        "connectivity": 9,
        "audio": 10,
        "sensors": 11,
        "operating system": 12,
        "package contents": 13,
    }
    modules.sort(key=lambda m: (priority.get(m["name"].lower(), 50), m["name"].lower()))
    payload = {"product_name": product_name, "modules": modules}
    return remap_normalized_modules(payload)


def normalized_payload_to_parsed(
    payload: dict[str, Any],
    *,
    document_id: str,
    document_name: str,
    used_ocr_pages: list[int] | None = None,
) -> ParsedDocument:
    """Convert LLM normalize JSON into heading + key_value ParsedBlocks."""
    blocks: list[ParsedBlock] = []
    raw_parts: list[str] = []
    product = payload.get("product_name")
    if product:
        raw_parts.append(str(product))
        blocks.append(
            ParsedBlock(
                block_id=_block_id(),
                content_type=ContentType.HEADING,
                text=str(product).strip(),
                page_number=1,
                heading_level=1,
            )
        )

    page = 1
    for mod in payload.get("modules") or []:
        if not isinstance(mod, dict):
            continue
        name = str(mod.get("name") or "").strip()
        if not name:
            continue
        specs = mod.get("specs") or []
        notes = mod.get("notes") or []
        if not specs and not notes:
            continue

        blocks.append(
            ParsedBlock(
                block_id=_block_id(),
                content_type=ContentType.HEADING,
                text=name,
                page_number=page,
                heading_level=2,
                section=name,
            )
        )
        section_lines = [name]

        kv_pairs: list[dict[str, str]] = []
        for sp in specs:
            if not isinstance(sp, dict):
                continue
            k = str(sp.get("key") or "").strip()
            v = str(sp.get("value") or "").strip()
            if not k or not v:
                continue
            kv_pairs.append({"key": k, "value": v})
            section_lines.append(f"{k}: {v}")

        if kv_pairs:
            text = "\n".join(f"{p['key']}: {p['value']}" for p in kv_pairs)
            blocks.append(
                ParsedBlock(
                    block_id=_block_id(),
                    content_type=ContentType.KEY_VALUE,
                    text=text,
                    page_number=page,
                    section=name,
                    key_values=kv_pairs,
                )
            )

        note_items = [str(n).strip() for n in notes if str(n).strip()]
        if note_items:
            for n in note_items:
                section_lines.append(n)
            blocks.append(
                ParsedBlock(
                    block_id=_block_id(),
                    content_type=ContentType.LIST,
                    text="\n".join(f"- {n}" for n in note_items),
                    page_number=page,
                    section=name,
                    list_items=note_items,
                )
            )

        raw_parts.append("\n".join(section_lines))
        page += 1

    raw_pages = ["\n\n".join(raw_parts)] if raw_parts else [""]
    return ParsedDocument(
        document_id=document_id,
        document_name=document_name,
        page_count=max(1, len(payload.get("modules") or [])),
        blocks=blocks,
        raw_pages=raw_pages,
        used_ocr_pages=list(used_ocr_pages or []),
    )


def apply_rag_normalize(
    parsed: ParsedDocument,
    *,
    source_path: Path | None = None,
    force_full_ocr: bool = False,
) -> tuple[ParsedDocument, dict[str, Any] | None]:
    """
    Chrome-strip + clear OCR refresh + LLM reframe → RAG-friendly ParsedDocument.
    Returns (parsed, payload_or_None). On failure / Azure off, returns original parsed.
    """
    settings = get_settings()
    if not getattr(settings.indexing, "llm_rag_normalize", True):
        return parsed, None
    if not is_azure_configured():
        logger.warning("llm_rag_normalize skipped: Azure not configured")
        return parsed, None

    page_texts, ocr_pages = prepare_clear_page_texts(
        source_path, parsed, force_full_ocr=force_full_ocr
    )
    # Drop empty pages
    nonempty = [t for t in page_texts if t.strip()]
    if not nonempty:
        logger.warning("llm_rag_normalize: no page text after chrome strip/OCR")
        return parsed, None

    payload = normalize_pages_with_llm(
        page_texts, document_name=parsed.document_name
    )
    if not payload.get("modules"):
        logger.warning(
            "llm_rag_normalize produced no modules for %s; keeping original parse",
            parsed.document_name,
        )
        return parsed, payload

    rebuilt = normalized_payload_to_parsed(
        payload,
        document_id=parsed.document_id,
        document_name=parsed.document_name,
        used_ocr_pages=ocr_pages,
    )
    logger.info(
        "RAG-normalized %s: modules=%d ocr_pages=%s",
        parsed.document_name,
        len(payload.get("modules") or []),
        ocr_pages,
    )
    return rebuilt, payload
