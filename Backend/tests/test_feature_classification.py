"""Tests for standard feature checklist classification."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from agents.feature_classification import classify_features
from app.api.adapters import build_feature_response
from core.feature_taxonomy import MOBILE_STANDARD_FEATURES, get_taxonomy
from core.schemas import (
    DocumentInfo,
    ExtractionResult,
    Feature,
    SourceRef,
    Specification,
)


def _spec(param: str, value: str, section: str = "General") -> Specification:
    return Specification(
        parameter=param,
        value=value,
        source=SourceRef(section=section, page=1),
    )


def test_mobile_taxonomy_defaults():
    tax = get_taxonomy("mobile")
    names = [t.name for t in tax]
    assert len(tax) == 8
    assert len(MOBILE_STANDARD_FEATURES) == 8
    assert names == [
        "Camera",
        "Connectivity",
        "Cellular & SIM",
        "Display & Touchscreen",
        "Battery & Charging",
        "Sensors",
        "Audio",
        "USB",
    ]
    assert "Operating System" not in names
    assert "Throughput" not in names
    assert "Processor & Performance" not in names
    assert "Memory & Storage" not in names
    assert "Audio & USB" not in names
    assert "Wireless Connectivity" not in names


def test_classify_ticks_matched_standards():
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
        Feature(
            feature_name="Display",
            specifications=[
                _spec("Resolution", "1080x2400", "Display"),
                _spec("Refresh Rate", "120 Hz", "Display"),
            ],
        ),
        Feature(
            feature_name="Audio",
            specifications=[_spec("Speakers", "Stereo", "Audio")],
        ),
        Feature(
            feature_name="USB",
            specifications=[_spec("Port", "USB-C", "USB")],
        ),
    ]
    checklist = classify_features(features, device_type="mobile")
    by_id = {f.id: f for f in checklist.standard_features}
    assert len(checklist.standard_features) == 8
    assert by_id["camera"].found is True
    assert by_id["battery"].found is True
    assert by_id["display"].found is True
    assert by_id["audio"].found is True
    assert by_id["usb"].found is True
    assert by_id["connectivity"].found is False


def test_classify_routes_connectivity_from_wifi():
    features = [
        Feature(
            feature_name="Document Root",
            specifications=[
                _spec("Wi-Fi", "802.11ax", "Document Root"),
                _spec("Bluetooth", "5.3", "Document Root"),
            ],
        ),
    ]
    checklist = classify_features(features, device_type="mobile")
    by_id = {f.id: f for f in checklist.standard_features}
    assert by_id["connectivity"].found is True
    assert by_id["connectivity"].name == "Connectivity"
    assert all(e.name.lower() != "document root" for e in checklist.extra_features)


def test_wifi_under_os_section_rehomes_to_connectivity():
    """Wi-Fi tagged under OS still routes to Connectivity when cues are clear."""
    features = [
        Feature(
            feature_name="Operating System",
            specifications=[
                _spec("Operating System", "Android", "Operating System"),
                _spec("Wi-Fi", "802.11ax", "Operating System"),
                _spec("Battery Capacity (Typical)", "3885 mAh", "Operating System"),
            ],
        ),
    ]
    checklist = classify_features(features, device_type="mobile")
    by_id = {f.id: f for f in checklist.standard_features}
    assert by_id["connectivity"].found is True
    assert by_id["battery"].found is True
    # OS is no longer a default — may appear as extra only if strong/testable
    assert "os" not in by_id


def test_battery_uses_section_not_software_support_keywords():
    """Only Battery-section capacity is kept; Software Support disclaimers are dropped."""
    features = [
        Feature(
            feature_name="Battery",
            specifications=[
                _spec("Battery Capacity (mAh, Typical)", "4000", "Battery"),
            ],
        ),
        Feature(
            feature_name="Software Support",
            specifications=[
                _spec(
                    "Battery",
                    "Actual battery life varies by network environment, features and apps used, "
                    "frequency of calls and messages, number of times charged, and other factors.",
                    "Software Support",
                ),
                _spec(
                    "Battery Capacity (Typical)",
                    "Rated typical capacity is 3885 mAh for Galaxy S25, 4755 mAh for Galaxy S25+ "
                    "and 4855 mAh for Galaxy S25 Ultra",
                    "Software Support",
                ),
            ],
        ),
    ]
    checklist = classify_features(features, device_type="mobile")
    by_id = {f.id: f for f in checklist.standard_features}
    assert by_id["battery"].found is True
    specs = by_id["battery"].feature.specifications
    assert len(specs) == 1
    assert specs[0].parameter.startswith("Battery Capacity")
    assert "4000" in str(specs[0].value)
    assert not any("3885" in str(s.value) for s in specs)
    assert not any("varies" in str(s.value).lower() for s in specs)


def test_battery_section_keeps_playback_and_removable():
    """Battery section rows without the word 'battery' in the param still count."""
    features = [
        Feature(
            feature_name="Battery & Charging",
            specifications=[
                _spec("Video Playback Time (Hours)", "Up to 29", "Battery & Charging"),
                _spec("Removable", "No", "Battery & Charging"),
                _spec(
                    "Note",
                    "Actual battery life varies by network environment and other factors.",
                    "Battery & Charging",
                ),
            ],
        )
    ]
    checklist = classify_features(features, device_type="mobile")
    by_id = {f.id: f for f in checklist.standard_features}
    assert by_id["battery"].found is True
    params = {s.parameter for s in by_id["battery"].feature.specifications}
    assert "Video Playback Time (Hours)" in params
    assert "Removable" in params
    assert not any("varies" in str(s.value).lower() for s in by_id["battery"].feature.specifications)


def test_classify_rejects_noisy_extra():
    features = [
        Feature(
            feature_name="Buy Now",
            specifications=[_spec("CTA", "Shop", "Buy Now")],
        ),
        Feature(
            feature_name="Price",
            specifications=[_spec("MRP", "₹25,000", "Price")],
        ),
    ]
    checklist = classify_features(features, device_type="mobile")
    assert checklist.extra_features == []
    assert checklist.rejected_extras


def test_classify_accepts_strong_extra():
    features = [
        Feature(
            feature_name="Thermal",
            specifications=[
                _spec("Cooling", "Vapor chamber", "Thermal"),
                _spec("Max Temp", "42 C", "Thermal"),
                _spec("Throttling", "Adaptive", "Thermal"),
            ],
        ),
    ]
    checklist = classify_features(features, device_type="mobile")
    assert any(e.name == "Thermal" for e in checklist.extra_features)
    assert all(not f.found for f in checklist.standard_features)


def test_ui_cards_include_not_found_standards():
    result = ExtractionResult(
        document=DocumentInfo(document_id="d1", document_name="spec.pdf"),
        features=[
            Feature(
                feature_name="Camera",
                specifications=[_spec("Main", "50 MP", "Camera")],
            )
        ],
    )
    cards, summary = build_feature_response(result, device_type="mobile")
    assert summary["standard_total"] == 8
    assert summary["standard_found"] >= 1
    assert len(cards) == 8  # all standards, no extras
    found = [c for c in cards if c["found"]]
    missing = [c for c in cards if not c["found"]]
    assert found
    assert missing
    assert all(c["kind"] == "standard" for c in cards)
    assert any(c["status"] == "not_found" for c in cards)
    assert any(c["name"] == "Connectivity" for c in cards)
    assert any(c["name"] == "Audio" for c in cards)
    assert any(c["name"] == "USB" for c in cards)
