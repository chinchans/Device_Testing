"""Load curated default test-case catalogs from Backend/data/test_cases/.

UI catalog (catalog.json) exposes short briefs + stable IDs like cam_fun_001.
Full suite files (functionality.json, …) keep codegen-ready payloads for
script generation later.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.config import BACKEND_ROOT

TEST_CASES_ROOT = BACKEND_ROOT / "data" / "test_cases"

# Map UI category id → suite filename stem
CATEGORY_FILES = {
    "functionality": "functionality",
    "performance": "performance",
    "reliability": "reliability",
    "security": "security",
}

FEATURE_ALIASES = {
    "camera": "camera",
    "cam": "camera",
}


def _normalize_feature(feature: str) -> str:
    key = (feature or "").strip().lower().replace(" ", "_").replace("-", "_")
    return FEATURE_ALIASES.get(key, key)


def _feature_dir(feature: str) -> Path:
    return TEST_CASES_ROOT / _normalize_feature(feature)


@lru_cache(maxsize=32)
def _load_json(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def list_features() -> list[dict[str, Any]]:
    """Return available default feature catalogs."""
    if not TEST_CASES_ROOT.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(TEST_CASES_ROOT.iterdir()):
        catalog_path = d / "catalog.json"
        if not catalog_path.is_file():
            continue
        try:
            data = _load_json(str(catalog_path))
        except (OSError, json.JSONDecodeError):
            continue
        cats = data.get("categories") or {}
        out.append(
            {
                "feature": data.get("feature") or d.name,
                "feature_name": data.get("feature_name") or d.name.title(),
                "categories": {
                    k: len(v) if isinstance(v, list) else 0 for k, v in cats.items()
                },
                "total_cases": sum(
                    len(v) for v in cats.values() if isinstance(v, list)
                ),
            }
        )
    return out


def get_feature_catalog(feature: str) -> dict[str, Any] | None:
    """UI-facing catalog: id, title, brief per category."""
    path = _feature_dir(feature) / "catalog.json"
    if not path.is_file():
        return None
    return _load_json(str(path))


def get_full_suite(feature: str, category: str) -> dict[str, Any] | None:
    """Full codegen-ready suite for a feature × category."""
    stem = CATEGORY_FILES.get((category or "").strip().lower())
    if not stem:
        return None
    path = _feature_dir(feature) / f"{stem}.json"
    if not path.is_file():
        return None
    return _load_json(str(path))


def get_test_case(
    feature: str, category: str, case_id: str
) -> dict[str, Any] | None:
    """Resolve one case by UI id (cam_fun_001) or source id (TC_CAM_FUNC_001)."""
    suite = get_full_suite(feature, category)
    if not suite:
        return None
    needle = (case_id or "").strip()
    for tc in suite.get("test_cases") or []:
        if tc.get("ui_id") == needle or tc.get("source_id") == needle:
            return tc
        meta = tc.get("test_metadata") or {}
        if meta.get("test_id") == needle or tc.get("test_case_id") == needle:
            return tc
    return None
