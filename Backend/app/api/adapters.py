"""API response helpers — map RAG output to UI feature cards."""

from __future__ import annotations

from typing import Any

from agents.feature_classification import ClassifiedFeature, FeatureChecklist, classify_features
from core.config import get_settings
from core.schemas import ExtractionResult, Feature


def missing_standard_count(checklist: dict[str, Any]) -> int:
    """How many default/standard checklist features were not found."""
    total = int(checklist.get("standard_total") or 0)
    found = int(checklist.get("standard_found") or 0)
    return max(0, total - found)


def should_retry_with_ocr(checklist: dict[str, Any]) -> bool:
    """True when too many default features are missing after a normal extract."""
    threshold = get_settings().indexing.ocr_retry_missing_standards
    total = int(checklist.get("standard_total") or 0)
    if total <= 0:
        return False
    return missing_standard_count(checklist) > threshold


def automation_mode_for_feature(feature: Feature, *, name_hint: str | None = None) -> str:
    """Heuristic mode suggestion for the Device Testing UI (not a product claim)."""
    label = name_hint or feature.feature_name
    text = " ".join(
        [label]
        + [s.parameter for s in feature.specifications]
        + [str(s.value) for s in feature.specifications]
    ).lower()
    manual_cues = ("ux", "feel", "ergonomic", "appearance", "design", "color", "aesthetic")
    semi_cues = ("camera", "display", "battery", "audio", "speaker", "mic", "touchscreen")
    if any(c in text for c in manual_cues):
        return "manual"
    if any(c in text for c in semi_cues):
        return "semi"
    return "automated"


def _capability_blurb(feature: Feature, *, found: bool, kind: str) -> str:
    if not found:
        return "Not found in the uploaded product specification."
    params = feature.specifications
    if not params:
        return feature.feature_name
    bits = []
    for s in params[:4]:
        value = s.value
        if s.unit:
            value = f"{value} {s.unit}".strip()
        bits.append(f"{s.parameter}: {value}")
    suffix = " · additional feature" if kind == "extra" else ""
    return "; ".join(bits) + suffix


def classified_to_ui_card(item: ClassifiedFeature) -> dict[str, Any]:
    feat = item.feature
    params = []
    for s in feat.specifications:
        value = s.value
        if s.unit:
            value = f"{value} {s.unit}".strip()
        if s.qualifiers:
            value = f"{value} ({', '.join(s.qualifiers)})"
        params.append({"name": s.parameter, "value": str(value)})

    return {
        "id": item.id,
        "name": item.name,
        "category": "Standard" if item.kind == "standard" else "Extra",
        "kind": item.kind,
        "order": item.order,
        "found": item.found,
        "source_names": item.source_names,
        "capability": _capability_blurb(feat, found=item.found, kind=item.kind),
        "automationMode": automation_mode_for_feature(feat, name_hint=item.name)
        if item.found
        else "manual",
        "status": "extracted" if item.found else "not_found",
        "parameters": params,
        "testCases": [],
        "script": None,
        "score": None,
        "sources": [
            {
                "page": s.source.page,
                "section": s.source.section,
                "chunk_id": s.source.chunk_id,
            }
            for s in feat.specifications
        ],
    }


def checklist_to_ui_features(checklist: FeatureChecklist) -> list[dict[str, Any]]:
    """Ordered UI cards: all standards (found or not), then strong extras."""
    return [classified_to_ui_card(item) for item in checklist.all_features]


def to_ui_features(result: ExtractionResult) -> list[dict[str, Any]]:
    """Legacy open-ended cards (no checklist). Prefer build_feature_response."""
    cards = []
    for idx, feat in enumerate(result.features):
        params = []
        for s in feat.specifications:
            value = s.value
            if s.unit:
                value = f"{value} {s.unit}".strip()
            if s.qualifiers:
                value = f"{value} ({', '.join(s.qualifiers)})"
            params.append({"name": s.parameter, "value": str(value)})
        capability_bits = [f"{p['name']}: {p['value']}" for p in params[:4]]
        capability = "; ".join(capability_bits) if capability_bits else feat.feature_name
        cards.append(
            {
                "id": f"raw_{idx}_{feat.feature_name[:24]}",
                "name": feat.feature_name,
                "category": feat.feature_name,
                "kind": "extra",
                "order": idx,
                "found": True,
                "source_names": [feat.feature_name],
                "capability": capability,
                "automationMode": automation_mode_for_feature(feat),
                "status": "extracted",
                "parameters": params,
                "testCases": [],
                "script": None,
                "score": None,
                "sources": [
                    {
                        "page": s.source.page,
                        "section": s.source.section,
                        "chunk_id": s.source.chunk_id,
                    }
                    for s in feat.specifications
                ],
            }
        )
    return cards


def build_feature_response(
    result: ExtractionResult,
    *,
    device_type: str | None = "mobile",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Classify extraction → mobile checklist ticks + relevant extras."""
    checklist = classify_features(result.features, device_type=device_type or "mobile")
    cards = checklist_to_ui_features(checklist)
    return cards, checklist.to_dict()
