"""Grounding validation — drop unsupported claims."""

from __future__ import annotations

import re
from typing import Any

from core.config import get_settings
from core.schemas import Feature, GroundingStatus, RetrievedCandidate, Specification
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def _value_supported(value: Any, evidence_text: str) -> GroundingStatus:
    if value is None:
        return GroundingStatus.UNSUPPORTED
    ev = _normalize(evidence_text)
    val = _normalize(value)
    if not val:
        return GroundingStatus.UNSUPPORTED
    if val in ev:
        return GroundingStatus.SUPPORTED
    # Numeric loose match
    nums = re.findall(r"\d+(?:\.\d+)?", val)
    if nums and all(n in ev for n in nums):
        return GroundingStatus.PARTIALLY_SUPPORTED
    # Token overlap
    tokens = [t for t in re.split(r"[^a-z0-9]+", val) if len(t) > 1]
    if tokens:
        hit = sum(1 for t in tokens if t in ev)
        ratio = hit / len(tokens)
        if ratio >= 0.8:
            return GroundingStatus.SUPPORTED
        if ratio >= 0.5:
            return GroundingStatus.PARTIALLY_SUPPORTED
    return GroundingStatus.UNSUPPORTED


def validate_grounding(
    features: list[Feature],
    evidence: list[RetrievedCandidate],
    *,
    use_llm: bool = False,
) -> tuple[list[Feature], dict[str, Any]]:
    evidence_by_id = {c.chunk_id: c.text for c in evidence}
    all_evidence = "\n".join(c.text for c in evidence)

    kept: list[Feature] = []
    report = {
        "supported": 0,
        "partially_supported": 0,
        "unsupported": 0,
        "removed": [],
    }

    for feat in features:
        ok_specs: list[Specification] = []
        for spec in feat.specifications:
            text = evidence_by_id.get(spec.source.chunk_id or "", all_evidence)
            # Also require parameter mention loosely
            param_ok = _normalize(spec.parameter)[:20] in _normalize(text) or any(
                tok in _normalize(text)
                for tok in _normalize(spec.parameter).split()
                if len(tok) > 3
            )
            status = _value_supported(spec.value, text)
            if status == GroundingStatus.SUPPORTED and not param_ok:
                status = GroundingStatus.PARTIALLY_SUPPORTED
            if status == GroundingStatus.UNSUPPORTED:
                # Try against full evidence pool once
                status = _value_supported(spec.value, all_evidence)
                if status == GroundingStatus.UNSUPPORTED:
                    report["unsupported"] += 1
                    report["removed"].append(
                        {"feature": feat.feature_name, "parameter": spec.parameter, "value": spec.value}
                    )
                    continue
            spec.grounding_status = status
            if status == GroundingStatus.SUPPORTED:
                report["supported"] += 1
            else:
                report["partially_supported"] += 1
            ok_specs.append(spec)
        if ok_specs:
            kept.append(Feature(feature_name=feat.feature_name, specifications=ok_specs))

    if use_llm and is_azure_configured() and features:
        kept, report = _llm_refine(kept, evidence, report)

    return kept, report


def _llm_refine(
    features: list[Feature],
    evidence: list[RetrievedCandidate],
    report: dict[str, Any],
) -> tuple[list[Feature], dict[str, Any]]:
    settings = get_settings()
    payload = {
        "features": [f.model_dump() for f in features],
        "evidence_chunk_ids": [c.chunk_id for c in evidence],
    }
    # Keep prompt small — lexical filter already applied
    try:
        content, _ = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "Validate each specification against evidence. "
                        "Mark UNSUPPORTED if not explicitly supported. JSON: "
                        '{"results":[{"feature_name":"...","parameter":"...","status":"SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED"}]}'
                    ),
                },
                {"role": "user", "content": str(payload)[:10000]},
            ],
            deployment=settings.cheap_model,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=1500,
        )
        data = parse_json_content(content) or {}
        status_map = {
            (r.get("feature_name"), r.get("parameter")): r.get("status")
            for r in data.get("results", [])
        }
        refined: list[Feature] = []
        for feat in features:
            specs = []
            for spec in feat.specifications:
                st = status_map.get((feat.feature_name, spec.parameter))
                if st == "UNSUPPORTED":
                    report["unsupported"] += 1
                    report["removed"].append(
                        {"feature": feat.feature_name, "parameter": spec.parameter, "value": spec.value}
                    )
                    continue
                if st == "SUPPORTED":
                    spec.grounding_status = GroundingStatus.SUPPORTED
                elif st == "PARTIALLY_SUPPORTED":
                    spec.grounding_status = GroundingStatus.PARTIALLY_SUPPORTED
                specs.append(spec)
            if specs:
                refined.append(Feature(feature_name=feat.feature_name, specifications=specs))
        return refined, report
    except Exception as exc:
        logger.debug("LLM grounding refine skipped: %s", exc)
        return features, report
