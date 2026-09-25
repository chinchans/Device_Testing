"""Tests for chrome strip and RAG-normalize block building."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.schemas import ContentType
from indexing.chrome_filter import is_chrome_line, is_chrome_heavy, strip_chrome_text
from indexing.rag_normalize import normalized_payload_to_parsed


def test_strip_cookie_and_nav_chrome():
    raw = """
POCO M7 Pro 5G
Cookie Settings | Accept All
Decline All
Xiaomi may use first and third-party cookies to maintain the essential functionality
Display
Resolution: 2400 x 1080
Overview
Support
1 of 4
""".strip()
    cleaned = strip_chrome_text(raw)
    assert "Cookie Settings" not in cleaned
    assert "Accept All" not in cleaned
    assert "third-party cookies" not in cleaned
    assert "Overview" not in cleaned
    assert "1 of 4" not in cleaned
    assert "Display" in cleaned
    assert "2400 x 1080" in cleaned
    assert "POCO M7 Pro 5G" in cleaned


def test_chrome_line_detection():
    assert is_chrome_line("Cookie Settings | Accept All")
    assert is_chrome_line("About Us.")
    assert not is_chrome_line("Refresh rate: Up to 120Hz")
    assert not is_chrome_line("Display")


def test_chrome_heavy_banner_page():
    banner = "\n".join(
        [
            "Mobile",
            "Wearables",
            "Cookie Settings | Accept All",
            "Decline All",
            "Learn More",
            "Privacy Policy",
            "Display",
            "120Hz",
        ]
    )
    assert is_chrome_heavy(banner)


def test_normalized_payload_to_parsed_builds_kv_sections():
    payload = {
        "product_name": "POCO M7 Pro 5G",
        "modules": [
            {
                "name": "Display",
                "specs": [
                    {"key": "Size", "value": '6.67" AMOLED'},
                    {"key": "Resolution", "value": "2400 x 1080"},
                ],
                "notes": ["Sunlight display"],
            },
            {
                "name": "Battery",
                "specs": [{"key": "Capacity", "value": "5110 mAh"}],
                "notes": [],
            },
        ],
    }
    parsed = normalized_payload_to_parsed(
        payload, document_id="doc_test", document_name="test.pdf"
    )
    headings = [b.text for b in parsed.blocks if b.content_type == ContentType.HEADING]
    assert "POCO M7 Pro 5G" in headings
    assert "Display" in headings
    assert "Battery" in headings
    kv = [b for b in parsed.blocks if b.content_type == ContentType.KEY_VALUE]
    assert any("2400 x 1080" in b.text for b in kv)
    assert any(b.key_values for b in kv)
