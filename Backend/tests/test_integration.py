"""Integration-style test: index a generated PDF and extract with heuristic path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _make_sample_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    content = """
Acme Sensor Gateway X200 — Product Specification

1. Processor
CPU Architecture: Dual-core ARM Cortex-A53
Clock Speed: 1.4 GHz
NPU: 2 TOPS

2. Connectivity
Ethernet: 2x Gigabit RJ45
Wi-Fi: 802.11ac
Bluetooth: 5.2
USB: USB 3.2 Gen 1

3. Power
Input Voltage: 12-48 V DC
Power Consumption: 8 W typical
PoE: 802.3at

4. Environmental
Operating Temperature: -20 to 60 C
Ingress Protection: IP67
"""
    page.insert_text((50, 50), content, fontsize=11)
    doc.save(path)
    doc.close()


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    root = tmp_path_factory.mktemp("pdfs")
    path = root / "acme_sensor_gateway.pdf"
    _make_sample_pdf(path)
    return path


def test_index_and_heuristic_extract(sample_pdf, monkeypatch, tmp_path):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")
    from core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.models.embedding_provider = "hashing"
    settings.paths.uploads_dir = str(tmp_path / "uploads")
    settings.paths.documents_dir = str(tmp_path / "documents")
    settings.paths.cache_dir = str(tmp_path / "cache")
    settings.paths.indexes_dir = str(tmp_path / "indexes")
    for p in (
        settings.uploads_path,
        settings.documents_path,
        settings.cache_path,
        settings.indexes_path,
    ):
        p.mkdir(parents=True, exist_ok=True)

    from indexing.pipeline import IndexingPipeline
    from graph.workflow import run_extraction

    pipeline = IndexingPipeline()
    indexed = pipeline.index_file(sample_pdf, force_reindex=True)
    assert indexed.page_count >= 1
    assert len(indexed.chunk_ids) >= 1

    result = run_extraction(
        indexed.document_id,
        "Extract all features and specifications",
        debug_mode=True,
    )
    assert result.document.document_id == indexed.document_id
    assert result.coverage.sections_discovered >= 0
    params = [s.parameter for f in result.features for s in f.specifications]
    for p in params:
        assert "Telepathy" not in p
