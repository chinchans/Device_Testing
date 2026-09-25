"""Tests for module remapping and extra testability heuristics."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.extra_testability import filter_testable_extras, heuristic_is_testable_extra
from agents.feature_classification import classify_features
from core.schemas import Feature, SourceRef, Specification
from indexing.module_remap import remap_normalized_modules


def test_remap_moves_storage_and_sensors_out_of_battery():
    payload = {
        "product_name": "iPhone 18 Pro",
        "modules": [
            {
                "name": "Battery and Charging",
                "specs": [
                    {"key": "Battery Type", "value": "Built-in rechargeable lithium-ion"},
                    {"key": "iPhone 18 Pro", "value": "256GB, 512GB, 1TB, 2TB"},
                    {"key": "Face ID", "value": "Included"},
                    {"key": "LiDAR Scanner", "value": "Included"},
                    {"key": "MagSafe Wireless Charging", "value": "Up to 25W"},
                ],
                "notes": [],
            },
            {
                "name": "Capacity",
                "specs": [
                    {"key": "iPhone 18 Pro Max", "value": "256GB, 512GB, 1TB, 2TB"},
                ],
                "notes": [],
            },
            {
                "name": "Processor & Performance",
                "specs": [{"key": "Chip", "value": "A19 Pro"}],
                "notes": [],
            },
        ],
    }
    out = remap_normalized_modules(payload)
    by_name = {m["name"]: m for m in out["modules"]}
    assert "Battery & Charging" in by_name
    assert "Sensors" in by_name
    assert "Memory & Storage" in by_name
    assert "Processor & Performance" in by_name

    batt_keys = {s["key"] for s in by_name["Battery & Charging"]["specs"]}
    assert "Battery Type" in batt_keys
    assert "MagSafe Wireless Charging" in batt_keys
    assert "iPhone 18 Pro" not in batt_keys
    assert "Face ID" not in batt_keys

    mem_vals = " ".join(s["value"] for s in by_name["Memory & Storage"]["specs"])
    assert "256GB" in mem_vals

    sensor_keys = {s["key"] for s in by_name["Sensors"]["specs"]}
    assert "Face ID" in sensor_keys
    assert "LiDAR Scanner" in sensor_keys


def test_heuristic_drops_non_testable_extras():
    assert not heuristic_is_testable_extra("Built-in Apps")
    assert not heuristic_is_testable_extra("Sustainability and Manufacturing")
    assert not heuristic_is_testable_extra("Support and Services")
    assert not heuristic_is_testable_extra("Materials and Environmental Impact")
    assert heuristic_is_testable_extra("Buttons and Connectors", "USB-C 10 Gbps")
    assert heuristic_is_testable_extra("Accessibility", "VoiceOver Voice Control")


def test_filter_testable_extras_heuristic_only():
    feats = [
        Feature(feature_name="Built-in Apps", specifications=[
            Specification(parameter="App Store", value="Included"),
            Specification(parameter="Maps", value="Included"),
        ]),
        Feature(feature_name="Buttons and Connectors", specifications=[
            Specification(parameter="USB-C", value="USB 3"),
            Specification(parameter="Action Button", value="Included"),
        ]),
    ]
    kept, rejected = filter_testable_extras(feats, use_llm=False)
    names = {f.feature_name for f in kept}
    assert "Buttons and Connectors" in names
    assert "Built-in Apps" not in names
    assert any(r["candidate"] == "Built-in Apps" for r in rejected)


def test_classify_rehouses_storage_off_battery_section():
    features = [
        Feature(
            feature_name="Battery & Charging",
            specifications=[
                Specification(
                    parameter="Battery Type",
                    value="Li-ion",
                    source=SourceRef(section="Battery & Charging", page=8),
                ),
                Specification(
                    parameter="iPhone 18 Pro",
                    value="256GB, 512GB, 1TB",
                    source=SourceRef(section="Battery & Charging", page=8),
                ),
                Specification(
                    parameter="Face ID",
                    value="Included",
                    source=SourceRef(section="Battery & Charging", page=8),
                ),
            ],
        )
    ]
    checklist = classify_features(features, device_type="mobile")
    by_id = {f.id: f for f in checklist.standard_features}
    batt_params = {s.parameter for s in by_id["battery"].feature.specifications}
    sensor_params = {s.parameter for s in by_id["sensors"].feature.specifications}
    assert "Battery Type" in batt_params
    assert "iPhone 18 Pro" not in batt_params  # storage SKU not on battery
    assert "Face ID" in sensor_params
    # Memory/storage is no longer a default — must not appear as a standard id
    assert "memory" not in by_id
    assert "os" not in by_id
    assert "processor" not in by_id
    assert "throughput" not in by_id
    extra_names = {e.name.lower() for e in checklist.extra_features}
    assert "built-in apps" not in extra_names
