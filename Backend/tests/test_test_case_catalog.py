"""Smoke tests for default Camera test-case catalog."""

from __future__ import annotations

from services.test_cases import (
    get_feature_catalog,
    get_full_suite,
    get_test_case,
    list_features,
)


def test_list_features_includes_camera():
    features = list_features()
    ids = {f["feature"] for f in features}
    assert "camera" in ids
    cam = next(f for f in features if f["feature"] == "camera")
    assert cam["total_cases"] == 80
    assert cam["categories"]["functionality"] == 20


def test_camera_catalog_ids():
    catalog = get_feature_catalog("camera")
    assert catalog is not None
    fun = catalog["categories"]["functionality"]
    assert fun[0]["id"] == "cam_fun_001"
    assert fun[-1]["id"] == "cam_fun_020"
    assert "Rear Primary" in fun[0]["title"]
    assert fun[0]["brief"]

    assert catalog["categories"]["performance"][0]["id"] == "cam_per_001"
    assert catalog["categories"]["reliability"][0]["id"] == "cam_rel_001"
    assert catalog["categories"]["security"][0]["id"] == "cam_sec_001"


def test_full_suite_and_lookup():
    suite = get_full_suite("camera", "functionality")
    assert suite is not None
    assert suite["test_case_count"] == 20
    case = get_test_case("camera", "functionality", "cam_fun_001")
    assert case is not None
    assert case.get("ui_id") == "cam_fun_001"
    assert case.get("source_id") == "TC_CAM_FUNC_001"
    by_source = get_test_case("camera", "performance", "TC_CAM_PERF_001")
    assert by_source is not None
    assert by_source.get("ui_id") == "cam_per_001"
