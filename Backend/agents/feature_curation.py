"""Curate RAG-extracted features for UI — document-native, device-agnostic.

No fixed product taxonomy. Keep only grounded feature modules that came from
the document, with their own specifications. Drop chrome / empty / value-like
titles and thin parameter noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.schemas import Feature, Specification
from indexing.section_filters import (
    is_nav_or_chrome,
    is_valid_feature_section_title,
    is_value_like_title,
    looks_like_parameter_label,
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _clone_spec(spec: Specification) -> Specification:
    return Specification(
        parameter=spec.parameter,
        value=spec.value,
        unit=spec.unit,
        qualifiers=list(spec.qualifiers),
        source=spec.source.model_copy() if spec.source else spec.source,
        grounding_status=spec.grounding_status,
    )


def _is_meaningful_spec(spec: Specification) -> bool:
    param = (spec.parameter or "").strip()
    value = str(spec.value if spec.value is not None else "").strip()
    if not param or not value:
        return False
    if is_nav_or_chrome(param) or is_value_like_title(param):
        return False
    if not looks_like_parameter_label(param) and len(param) > 80:
        return False
    return True


def _merge_specs(dst: list[Specification], incoming: list[Specification]) -> None:
    seen = {
        (_norm(s.parameter), _norm(str(s.value)), _norm("|".join(s.qualifiers)))
        for s in dst
    }
    for spec in incoming:
        key = (_norm(spec.parameter), _norm(str(spec.value)), _norm("|".join(spec.qualifiers)))
        if key in seen:
            continue
        dst.append(_clone_spec(spec))
        seen.add(key)


@dataclass
class CuratedFeature:
    id: str
    name: str
    order: int
    feature: Feature
    source_names: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return True

    @property
    def kind(self) -> str:
        return "extracted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "order": self.order,
            "found": True,
            "source_names": self.source_names,
            "spec_count": len(self.feature.specifications),
        }


@dataclass
class ExtractionCatalog:
    """Document-native feature catalog (no checklist placeholders)."""

    device_type: str | None
    features: list[CuratedFeature]
    rejected: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "document_native",
            "device_type": self.device_type,
            "feature_count": len(self.features),
            "standard_total": len(self.features),
            "standard_found": len(self.features),
            "extra_count": 0,
            "rejected": self.rejected,
            "features": [f.to_dict() for f in self.features],
        }


def curate_document_features(
    features: list[Feature],
    *,
    device_type: str | None = None,
    min_specs: int = 1,
) -> ExtractionCatalog:
    """Filter and merge RAG features into UI-ready document-native modules."""
    buckets: dict[str, Feature] = {}
    order_keys: list[str] = []
    rejected: list[dict[str, str]] = []

    for feat in features:
        name = (feat.feature_name or "").strip()
        if not name:
            rejected.append({"candidate": "", "reason": "empty_name"})
            continue
        if is_nav_or_chrome(name) or is_value_like_title(name):
            rejected.append({"candidate": name, "reason": "chrome_or_value_like"})
            continue
        if not is_valid_feature_section_title(name):
            rejected.append({"candidate": name, "reason": "invalid_feature_title"})
            continue

        specs = [s for s in feat.specifications if _is_meaningful_spec(s)]
        if len(specs) < min_specs:
            rejected.append({"candidate": name, "reason": "no_meaningful_specifications"})
            continue

        key = _norm(name)
        if not key:
            rejected.append({"candidate": name, "reason": "empty_normalized_name"})
            continue

        if key not in buckets:
            buckets[key] = Feature(feature_name=name, specifications=[])
            order_keys.append(key)
        _merge_specs(buckets[key].specifications, specs)
        # Prefer the longer/clearer display name
        if len(name) > len(buckets[key].feature_name):
            buckets[key].feature_name = name

    curated: list[CuratedFeature] = []
    for idx, key in enumerate(order_keys):
        feat = buckets[key]
        if len(feat.specifications) < min_specs:
            continue
        slug = key.replace(" ", "_")[:48] or f"feat_{idx}"
        curated.append(
            CuratedFeature(
                id=f"doc_{slug}",
                name=feat.feature_name,
                order=idx + 1,
                feature=feat,
                source_names=[feat.feature_name],
            )
        )

    return ExtractionCatalog(
        device_type=device_type,
        features=curated,
        rejected=rejected,
    )
