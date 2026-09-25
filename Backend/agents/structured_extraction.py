"""Structured specification extraction agent — evidence-grounded only."""

from __future__ import annotations

from typing import Any

from agents.query_understanding import FEATURE_HIERARCHY_POLICY
from core.config import get_settings
from core.schemas import Feature, RetrievedCandidate, SourceRef, Specification
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger


EXTRACTION_SYSTEM = f"""You extract product features and specifications from provided evidence ONLY.

Rules:
- Extract ONLY features and specifications explicitly supported by the supplied context.
- Do NOT use prior knowledge about products or device categories.
- Do NOT invent missing specifications.
- Preserve source terminology and exact values/units.
- If a value is unavailable, omit it — never guess.
- Never convert absence of information into "No" or false.
- Preserve Yes/No exactly when stated.
- Preserve variant/configuration/region qualifiers in the qualifiers array.
- Preserve footnotes that change interpretation as qualifiers.
- Every specification MUST include source.chunk_id from the evidence block ids provided.
- Return JSON only matching the schema.

{FEATURE_HIERARCHY_POLICY}
"""


def _format_evidence(candidates: list[RetrievedCandidate], max_chars: int) -> str:
    parts: list[str] = []
    total = 0
    for c in candidates:
        block = (
            f"---\nchunk_id={c.chunk_id}\npage={c.metadata.page_number}\n"
            f"section={c.metadata.section}\nsubsection={c.metadata.subsection}\n"
            f"content_type={c.metadata.content_type}\n{c.text}\n"
        )
        if total + len(block) > max_chars and parts:
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts)


def extract_features_from_evidence(
    *,
    feature_hint: str,
    document_id: str,
    candidates: list[RetrievedCandidate],
    query: str | None = None,
    extraction_policy: str | None = None,
) -> tuple[list[Feature], dict[str, int]]:
    settings = get_settings()
    if not candidates:
        return [], {}

    evidence = _format_evidence(candidates, settings.agents.max_evidence_chars)
    policy = extraction_policy or FEATURE_HIERARCHY_POLICY
    user_prompt = (
        f"Feature/section focus (this MUST be the only feature_name): {feature_hint}\n"
        f"User query: {query or 'Extract features and specifications'}\n\n"
        f"{policy}\n\n"
        "Return JSON with shape:\n"
        "{\n"
        '  "features": [\n'
        "    {\n"
        f'      "feature_name": "{feature_hint}",\n'
        '      "specifications": [\n'
        "        {\n"
        '          "parameter": "...",\n'
        '          "value": "...",\n'
        '          "unit": null,\n'
        '          "qualifiers": [],\n'
        '          "source": {"document_id": "...", "page": 0, "section": "...", "chunk_id": "..."}\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "CRITICAL: Return exactly ONE object in features[], named exactly as the "
        f'section focus "{feature_hint}". Put each measured attribute in '
        "specifications[].parameter with its value — never invent separate "
        "features for individual parameters, and never add facts absent from evidence.\n\n"
        f"EVIDENCE:\n{evidence}"
    )

    if not is_azure_configured():
        return _heuristic_extract(feature_hint, document_id, candidates), {}

    try:
        content, usage = chat_completion(
            [
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            deployment=settings.extraction_model,
            temperature=settings.agents.extraction_temperature,
            response_format={"type": "json_object"},
            max_tokens=4000,
        )
        data = parse_json_content(content) or {}
        features = _parse_features(data, document_id, candidates)
        features = _collapse_to_section_feature(features, feature_hint, document_id)
        return features, usage
    except Exception as exc:
        logger.error("Structured extraction failed: %s", exc)
        return _heuristic_extract(feature_hint, document_id, candidates), {}


def _collapse_to_section_feature(
    features: list[Feature],
    feature_hint: str,
    document_id: str,
) -> list[Feature]:
    """Force all extracted specs under the section focus feature name."""
    if not feature_hint.strip():
        return features
    if not features:
        return []

    merged_specs: list[Specification] = []
    for feat in features:
        for spec in feat.specifications:
            # If model used the parameter name as feature_name with a weak parameter,
            # promote a clearer parameter label.
            if (
                feat.feature_name.strip().lower() != feature_hint.strip().lower()
                and (
                    not spec.parameter
                    or spec.parameter.strip().lower() in {"value", "val", "specification"}
                )
            ):
                spec.parameter = feat.feature_name.strip()
            if not spec.source.section:
                spec.source.section = feature_hint
            if not spec.source.document_id:
                spec.source.document_id = document_id
            merged_specs.append(spec)

    if not merged_specs:
        return []
    return [Feature(feature_name=feature_hint.strip(), specifications=merged_specs)]


def _parse_features(
    data: dict[str, Any],
    document_id: str,
    candidates: list[RetrievedCandidate],
) -> list[Feature]:
    by_id = {c.chunk_id: c for c in candidates}
    features: list[Feature] = []
    for raw in data.get("features") or []:
        name = str(raw.get("feature_name") or "").strip()
        if not name:
            continue
        specs: list[Specification] = []
        for s in raw.get("specifications") or []:
            parameter = str(s.get("parameter") or "").strip()
            if not parameter:
                continue
            if "value" not in s or s.get("value") is None or s.get("value") == "":
                continue
            src_raw = s.get("source") or {}
            chunk_id = src_raw.get("chunk_id")
            cand = by_id.get(chunk_id) if chunk_id else None
            if cand is None and candidates:
                cand = candidates[0]
                chunk_id = cand.chunk_id
            source = SourceRef(
                document_id=document_id,
                page=(
                    src_raw.get("page")
                    if src_raw.get("page") is not None
                    else (cand.metadata.page_number if cand else None)
                ),
                section=src_raw.get("section") or (cand.metadata.section if cand else None),
                chunk_id=chunk_id,
            )
            specs.append(
                Specification(
                    parameter=parameter,
                    value=s.get("value"),
                    unit=s.get("unit"),
                    qualifiers=[str(q) for q in (s.get("qualifiers") or [])],
                    source=source,
                )
            )
        if specs:
            features.append(Feature(feature_name=name, specifications=specs))
    return features


def _heuristic_extract(
    feature_hint: str,
    document_id: str,
    candidates: list[RetrievedCandidate],
) -> list[Feature]:
    """Offline key:value scraper for tests without LLM."""
    import re

    specs: list[Specification] = []
    kv_re = re.compile(r"^([^:\|]{2,80})\s*[:\|]\s*(.+)$")
    for c in candidates:
        for line in c.text.split("\n"):
            line = line.strip()
            m = kv_re.match(line)
            if not m:
                continue
            key, val = m.group(1).strip(), m.group(2).strip()
            if key.startswith("["):
                continue
            specs.append(
                Specification(
                    parameter=key,
                    value=val,
                    unit=None,
                    source=SourceRef(
                        document_id=document_id,
                        page=c.metadata.page_number,
                        section=c.metadata.section or feature_hint,
                        chunk_id=c.chunk_id,
                    ),
                )
            )
    if not specs:
        return []
    return [Feature(feature_name=feature_hint, specifications=specs)]
