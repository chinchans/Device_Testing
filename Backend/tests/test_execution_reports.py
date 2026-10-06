"""Tests for execution result helpers used by the Test Execution page."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.test_execution.reports import device_values, spec_comparison
from services.test_execution.script_sets import clean_product_name


def test_clean_product_name_collapses_repeated_brand():
    assert clean_product_name("Samsung Samsung Galaxy S25") == "Samsung Galaxy S25"
    assert clean_product_name("samsung  Samsung Galaxy S25") == "samsung Galaxy S25"
    assert clean_product_name("Samsung Galaxy S25") == "Samsung Galaxy S25"
    assert clean_product_name("Pixel Pixelbook") == "Pixel Pixelbook"
    assert clean_product_name(None) is None


def test_device_values_skip_spec_pinned_variables():
    results = [
        {"spec_values": {"SUPPORTED_PHOTO_RESOLUTIONS": "8160x6120"},
         "variables": {"SUPPORTED_PHOTO_RESOLUTIONS": "8160x6120", "MAX_ZOOM_RATIO": "1.0"}},
        {"spec_values": {}, "variables": {"SUPPORTED_PHOTO_RESOLUTIONS": "640x480,320x240"}},
    ]
    assert device_values(results) == {"MAX_ZOOM_RATIO": "1.0", "SUPPORTED_PHOTO_RESOLUTIONS": "640x480,320x240"}


def test_spec_comparison_for_spec_mismatch():
    case = {
        "verdict": "FAIL",
        "reason": "Spec mismatch: device does not support REAR_PRIMARY_PHOTO_RESOLUTION=8160x6120 from "
                  "Samsung Samsung Galaxy S25 (harness: resolution 8160x6120 not supported for JPEG on camera 10)",
        "spec_values": {"REAR_PRIMARY_PHOTO_RESOLUTION": "8160x6120"},
    }
    result = {"spec_values": case["spec_values"],
              "variables": {"REAR_PRIMARY_PHOTO_RESOLUTION": "8160x6120"}}
    sibling = {"spec_values": {}, "variables": {"REAR_PRIMARY_PHOTO_RESOLUTION": "640x480",
                                                 "SUPPORTED_PHOTO_RESOLUTIONS": "640x480,640x360"}}
    out = spec_comparison(case, result, [result, sibling])
    assert out["source"] == "Samsung Galaxy S25"
    assert out["harness"] == "resolution 8160x6120 not supported for JPEG on camera 10"
    row = out["rows"][0]
    assert row["name"] == "REAR_PRIMARY_PHOTO_RESOLUTION"
    assert row["spec"] == "8160x6120"
    assert row["device"] == "640x480"
    assert row["related"] == [{"name": "SUPPORTED_PHOTO_RESOLUTIONS", "value": "640x480,640x360"}]


def test_spec_comparison_ignores_other_causes():
    assert spec_comparison({"verdict": "PASS"}, {}, []) is None
    assert spec_comparison({"verdict": "FAIL", "reason": "main: prepare failed"}, {}, []) is None
