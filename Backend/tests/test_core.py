"""Unit tests for RRF, chunking, grounding, coverage, planner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from agents.coverage_validator import validate_coverage
from agents.extraction_planner import plan_extraction
from agents.grounding_validator import validate_grounding
from agents.query_understanding import classify_query
from agents.reconciliation import reconcile_features
from core.schemas import (
    ChunkMetadata,
    ContentType,
    DocumentSection,
    DocumentStructure,
    Feature,
    QueryIntent,
    RetrievedCandidate,
    SourceRef,
    Specification,
)
from indexing.chunker import estimate_tokens, _split_with_overlap
from retrieval.rrf import reciprocal_rank_fusion


def test_rrf_prefers_agreement():
    a = ["c1", "c2", "c3"]
    b = ["c2", "c1", "c4"]
    fused = reciprocal_rank_fusion([a, b], k=60)
    ids = [cid for cid, _ in fused]
    assert ids[0] in {"c1", "c2"}
    assert len(ids) == 4


def test_chunk_split_keeps_overlap():
    text = "\n\n".join([f"Parameter {i}: value {i}" for i in range(40)])
    parts = _split_with_overlap(text, max_tokens=50, overlap_tokens=10)
    assert len(parts) > 1
    assert all(estimate_tokens(p) <= 80 for p in parts)


def test_query_intent_full_extraction():
    intent, conf, _ = classify_query("Extract all features and specifications")
    assert intent == QueryIntent.FULL_DOCUMENT_EXTRACTION
    assert conf > 0.5


def test_planner_uses_discovered_sections_only():
    structure = DocumentStructure(
        document_id="doc_x",
        sections=[
            DocumentSection(section_id="r", title="Document Root", level=0, is_specification_bearing=False),
            DocumentSection(
                section_id="s1",
                title="Quantum Flux Capacitor",
                level=1,
                block_ids=["b1"],
                is_specification_bearing=True,
            ),
            DocumentSection(
                section_id="s2",
                title="Hydrogel Chassis",
                level=1,
                block_ids=["b2"],
                is_specification_bearing=True,
            ),
        ],
    )
    tasks = plan_extraction(structure, "Extract all features and specifications", QueryIntent.FULL_DOCUMENT_EXTRACTION)
    titles = {t.section_title for t in tasks}
    assert titles == {"Quantum Flux Capacitor", "Hydrogel Chassis"}
    # Must NOT inject smartphone categories
    assert "Camera" not in titles
    assert "Battery" not in titles


def test_grounding_removes_unsupported():
    evidence = [
        RetrievedCandidate(
            chunk_id="chk1",
            text="[Display]\nResolution: 2340 x 1080\nRefresh Rate: 120 Hz",
            metadata=ChunkMetadata(
                document_id="d",
                document_name="x.pdf",
                page_number=1,
                section="Display",
                chunk_id="chk1",
                content_type=ContentType.KEY_VALUE,
            ),
        )
    ]
    features = [
        Feature(
            feature_name="Display",
            specifications=[
                Specification(
                    parameter="Resolution",
                    value="2340 x 1080",
                    source=SourceRef(chunk_id="chk1", page=1, section="Display"),
                ),
                Specification(
                    parameter="Telepathy",
                    value="Yes",
                    source=SourceRef(chunk_id="chk1", page=1, section="Display"),
                ),
            ],
        )
    ]
    kept, report = validate_grounding(features, evidence)
    assert len(kept) == 1
    assert len(kept[0].specifications) == 1
    assert kept[0].specifications[0].parameter == "Resolution"
    assert report["unsupported"] >= 1


def test_coverage_incomplete_when_missed():
    structure = DocumentStructure(
        document_id="d",
        sections=[
            DocumentSection(section_id="r", title="Document Root", level=0),
            DocumentSection(
                section_id="a", title="Alpha", level=1, block_ids=["1"], is_specification_bearing=True
            ),
            DocumentSection(
                section_id="b", title="Beta", level=1, block_ids=["2"], is_specification_bearing=True
            ),
        ],
    )
    coverage = validate_coverage(structure, ["Alpha"], [Feature(feature_name="Alpha", specifications=[])])
    assert coverage.coverage_complete is False
    assert "Beta" in coverage.missed_sections
    assert coverage.status in {"INCOMPLETE", "PARTIAL"}


def test_value_like_titles_rejected():
    from indexing.section_filters import is_valid_feature_section_title, is_value_like_title

    assert is_value_like_title("120 Hz")
    assert is_value_like_title("2340 x 1080 (FHD+)")
    assert is_value_like_title("F1.8, F2.4, F2.2")
    assert is_value_like_title("B41(2500)")
    assert is_value_like_title("1800 40 7267864 (1800 40 Samsung)")
    assert is_value_like_title("50.0 MP + 10.0 MP + 12.0 MP")
    assert not is_valid_feature_section_title("Reviews")
    assert not is_valid_feature_section_title("120 Hz")
    assert is_valid_feature_section_title("Display")
    assert is_valid_feature_section_title("Processor")
    assert is_valid_feature_section_title("Camera")


def test_inline_heading_explosion_discovers_sections():
    from indexing.parser import ParsedDocument
    from indexing.structure import discover_structure
    from core.schemas import ParsedBlock, ContentType

    parsed = ParsedDocument(
        document_id="d1",
        document_name="x.pdf",
        page_count=1,
        blocks=[
            ParsedBlock(
                block_id="b1",
                content_type=ContentType.PARAGRAPH,
                text=(
                    "Product Spec\n"
                    "1. Processor\n"
                    "CPU: A55\n"
                    "2. Connectivity\n"
                    "USB: 3.2 Gen 1\n"
                ),
                page_number=1,
            )
        ],
        raw_pages=["Product Spec\n1. Processor\nCPU: A55\n2. Connectivity\nUSB: 3.2 Gen 1"],
    )
    structure = discover_structure(parsed)
    titles = [s.title for s in structure.sections if s.level > 0]
    assert "Processor" in titles
    assert "Connectivity" in titles
    assert any(s.is_specification_bearing for s in structure.sections)


def test_reconcile_folds_display_parameters_into_parent():
    from core.schemas import SourceRef

    features = [
        Feature(
            feature_name="Display Resolution",
            specifications=[
                Specification(
                    parameter="Resolution",
                    value="2340 x 1080",
                    source=SourceRef(section="Display", page=1, chunk_id="a"),
                )
            ],
        ),
        Feature(
            feature_name="Display Technology",
            specifications=[
                Specification(
                    parameter="Technology",
                    value="Dynamic AMOLED",
                    source=SourceRef(section="Display", page=1, chunk_id="b"),
                )
            ],
        ),
        Feature(
            feature_name="Display",
            specifications=[
                Specification(
                    parameter="Size",
                    value="6.1 inches",
                    source=SourceRef(section="Display", page=1, chunk_id="c"),
                )
            ],
        ),
        Feature(
            feature_name="Max Refresh Rate (Main Display)",
            specifications=[
                Specification(
                    parameter="Refresh Rate",
                    value="120 Hz",
                    source=SourceRef(section="Display", page=1, chunk_id="d"),
                )
            ],
        ),
    ]
    merged = reconcile_features(features)
    names = [f.feature_name for f in merged]
    assert names == ["Display"]
    params = {s.parameter for s in merged[0].specifications}
    assert "Resolution" in params
    assert "Technology" in params
    assert "Size" in params


def test_reconcile_keeps_variant_values():
    features = [
        Feature(
            feature_name="Storage",
            specifications=[
                Specification(parameter="Capacity", value="128 GB", qualifiers=["SKU A"]),
            ],
        ),
        Feature(
            feature_name="storage",
            specifications=[
                Specification(parameter="Capacity", value="256 GB", qualifiers=["SKU B"]),
                Specification(parameter="Capacity", value="128 GB", qualifiers=["SKU A"]),
            ],
        ),
    ]
    merged = reconcile_features(features)
    assert len(merged) == 1
    values = sorted(str(s.value) for s in merged[0].specifications)
    assert values == ["128 GB", "256 GB"]
