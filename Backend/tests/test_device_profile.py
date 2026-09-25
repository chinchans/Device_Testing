"""Tests for Device Classification profile mapping."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.device_profile import derive_device_classification
from core.schemas import (
    DocumentInfo,
    ExtractionResult,
    Feature,
    SourceRef,
    Specification,
)


def test_derive_maps_samsung_style_specs():
    result = ExtractionResult(
        document=DocumentInfo(
            document_id="d1",
            document_name="Product_spec.pdf",
            product_name="Samsung Galaxy S25",
        ),
        features=[
            Feature(
                feature_name="Operating System",
                specifications=[
                    Specification(
                        parameter="OS",
                        value="Android",
                        source=SourceRef(section="Operating System"),
                    ),
                    Specification(
                        parameter="One UI Version",
                        value="One UI 7.0",
                        source=SourceRef(section="Operating System"),
                    ),
                ],
            ),
            Feature(
                feature_name="Memory & Storage",
                specifications=[
                    Specification(
                        parameter="Storage Memory (GB)",
                        value="12",
                        source=SourceRef(section="Memory & Storage"),
                    ),
                    Specification(
                        parameter="Storage (GB)",
                        value="256",
                        source=SourceRef(section="Memory & Storage"),
                    ),
                ],
            ),
            Feature(
                feature_name="Processor & Performance",
                specifications=[
                    Specification(
                        parameter="Processor CPU Type",
                        value="Octa-Core",
                        source=SourceRef(section="Processor & Performance"),
                    ),
                    Specification(
                        parameter="Chipset",
                        value="Snapdragon 8 Elite",
                        source=SourceRef(section="Processor & Performance"),
                    ),
                ],
            ),
        ],
    )
    profile = derive_device_classification(result, device_type="mobile")
    assert profile["category"] == "mobile"
    assert profile["manufacturer"] == "Samsung"
    assert "Galaxy S25" in profile["model"]
    assert profile["os"] == "Android"
    assert "12" in profile["ram"]
    assert "256" in profile["storage"]
    assert "Snapdragon" in profile["cpu"]


def test_derive_uses_normalized_when_extraction_thin():
    result = ExtractionResult(
        document=DocumentInfo(document_id="d1", document_name="x.pdf", product_name="POCO M7 Pro 5G"),
        features=[],
    )
    normalized = {
        "product_name": "POCO M7 Pro 5G",
        "modules": [
            {
                "name": "Operating System",
                "specs": [{"key": "OS", "value": "Xiaomi HyperOS"}],
            },
            {
                "name": "Memory & Storage",
                "specs": [
                    {"key": "RAM", "value": "8GB"},
                    {"key": "Storage", "value": "256GB"},
                ],
            },
            {
                "name": "Processor & Performance",
                "specs": [{"key": "Chipset", "value": "Dimensity 7025-Ultra"}],
            },
        ],
    }
    profile = derive_device_classification(
        result, device_type="mobile", normalized=normalized
    )
    assert profile["os"] == "Xiaomi HyperOS"
    assert profile["ram"] == "8GB"
    assert profile["storage"] == "256GB"
    assert "Dimensity" in profile["cpu"]
    assert profile["manufacturer"] == "POCO"
