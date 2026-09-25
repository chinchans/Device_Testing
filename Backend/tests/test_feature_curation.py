"""Tests for document-native feature curation helper (noise gate).

Primary UI path uses checklist classification via build_feature_response;
curation remains available as a reusable filter for document-native modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from agents.feature_curation import curate_document_features
from core.schemas import Feature, SourceRef, Specification


def _spec(param: str, value: str, section: str = "General") -> Specification:
    return Specification(
        parameter=param,
        value=value,
        source=SourceRef(section=section, page=1),
    )


def test_curate_keeps_document_features_with_specs():
    features = [
        Feature(
            feature_name="Camera",
            specifications=[
                _spec("Rear", "64 MP", "Camera"),
                _spec("Front", "32 MP", "Camera"),
            ],
        ),
        Feature(
            feature_name="Battery",
            specifications=[_spec("Capacity", "4300 mAh", "Battery")],
        ),
    ]
    catalog = curate_document_features(features)
    names = {f.name for f in catalog.features}
    assert names == {"Camera", "Battery"}
    assert all(f.found for f in catalog.features)


def test_curate_drops_chrome_and_empty():
    features = [
        Feature(
            feature_name="Buy Now",
            specifications=[_spec("CTA", "Shop", "Buy Now")],
        ),
        Feature(
            feature_name="Operating System",
            specifications=[_spec("Operating System", "Android", "Operating System")],
        ),
        Feature(feature_name="Display", specifications=[]),
    ]
    catalog = curate_document_features(features)
    names = {f.name for f in catalog.features}
    assert names == {"Operating System"}
