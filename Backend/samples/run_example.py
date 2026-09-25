#!/usr/bin/env python3
"""Generate a sample multi-category product specification PDF and run extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def make_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    text = """NovaEdge IoT Hub H7 — Product Specification Sheet

Document ID: NES-H7-SPEC-2026
Product Type: Industrial IoT Gateway

1. Processor
Architecture: Quad-core ARM Cortex-A55
Clock Speed: 2.0 GHz
AI Accelerator: 4 TOPS NPU
Memory: 4 GB LPDDR4

2. Storage
eMMC: 32 GB
MicroSD: Up to 1 TB
NVMe Slot: M.2 Key-M

3. Network Interfaces
Ethernet Ports: 4x 1GbE RJ45
SFP Cage: 1x 1G/10G
Cellular: 5G Sub-6 optional module
Wi-Fi: Wi-Fi 6 (802.11ax)
Bluetooth: Bluetooth 5.3

4. I/O and Expansion
USB: USB 3.2 Gen 1 Type-A x2
Serial: RS-485 x2, RS-232 x1
Digital I/O: 8 DI / 8 DO
CAN Bus: CAN FD x1

5. Power and Thermal
Input Voltage: 9–36 V DC
Typical Power: 12 W
PoE Input: 802.3at supported
Operating Temperature: -40 to 70 °C

6. Security
Secure Element: ATECC608
TPM: TPM 2.0
Secure Boot: Yes
"""
    page.insert_text((48, 48), text, fontsize=10)
    doc.save(path)
    doc.close()


def main() -> None:
    samples = BACKEND / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    pdf = samples / "novaedge_iot_hub_h7.pdf"
    make_pdf(pdf)
    print(f"Wrote sample PDF: {pdf}")

    from indexing.pipeline import IndexingPipeline
    from graph.workflow import run_extraction

    pipeline = IndexingPipeline()
    indexed = pipeline.index_file(pdf, force_reindex=True)
    print(
        f"Indexed document_id={indexed.document_id} pages={indexed.page_count} "
        f"chunks={len(indexed.chunk_ids)}"
    )

    result = run_extraction(
        indexed.document_id,
        "Extract all features and specifications",
        debug_mode=True,
    )
    out = samples / "novaedge_iot_hub_h7_extraction.json"
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"Features extracted: {len(result.features)}")
    print(f"Coverage: {result.coverage.model_dump()}")
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
