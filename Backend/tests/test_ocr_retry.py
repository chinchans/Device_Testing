"""Tests for OCR retry trigger when too many default features are missing."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.adapters import missing_standard_count, should_retry_with_ocr
from core.config import get_settings


def test_missing_standard_count():
    assert missing_standard_count({"standard_total": 8, "standard_found": 2}) == 6
    assert missing_standard_count({"standard_total": 8, "standard_found": 8}) == 0
    assert missing_standard_count({}) == 0


def test_should_retry_with_ocr_threshold():
    threshold = get_settings().indexing.ocr_retry_missing_standards
    assert threshold == 3
    # More than 3 missing → retry
    assert should_retry_with_ocr({"standard_total": 8, "standard_found": 4}) is True
    assert should_retry_with_ocr({"standard_total": 8, "standard_found": 2}) is True
    # Exactly 3 missing → no retry
    assert should_retry_with_ocr({"standard_total": 8, "standard_found": 5}) is False
    # Fewer than 3 missing → no retry
    assert should_retry_with_ocr({"standard_total": 8, "standard_found": 7}) is False
    # Empty checklist → no retry
    assert should_retry_with_ocr({}) is False
