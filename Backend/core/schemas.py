"""Pydantic schemas for document indexing and structured extraction output."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class QueryIntent(str, Enum):
    SPECIFIC_LOOKUP = "SPECIFIC_LOOKUP"
    FEATURE_EXTRACTION = "FEATURE_EXTRACTION"
    FULL_DOCUMENT_EXTRACTION = "FULL_DOCUMENT_EXTRACTION"
    COMPARISON = "COMPARISON"
    OTHER = "OTHER"


class GroundingStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class ContentType(str, Enum):
    TABLE = "table"
    PARAGRAPH = "paragraph"
    LIST = "list"
    KEY_VALUE = "key_value"
    HEADING = "heading"
    FOOTNOTE = "footnote"
    CAPTION = "caption"
    MIXED = "mixed"


# ── Parsed document structures ──────────────────────────────────────────────


class TableCell(BaseModel):
    row: int
    col: int
    text: str
    header: bool = False


class ParsedBlock(BaseModel):
    block_id: str
    content_type: ContentType
    text: str
    page_number: int
    section: str | None = None
    subsection: str | None = None
    heading_level: int | None = None
    table_cells: list[TableCell] = Field(default_factory=list)
    list_items: list[str] = Field(default_factory=list)
    key_values: list[dict[str, str]] = Field(default_factory=list)
    footnote: bool = False
    caption: bool = False
    bbox: list[float] | None = None


class DocumentSection(BaseModel):
    section_id: str
    title: str
    level: int = 1
    page_start: int | None = None
    page_end: int | None = None
    parent_id: str | None = None
    children: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    is_specification_bearing: bool = True


class DocumentStructure(BaseModel):
    document_id: str
    sections: list[DocumentSection] = Field(default_factory=list)
    product_name: str | None = None
    product_type: str | None = None


class ChunkMetadata(BaseModel):
    document_id: str
    document_name: str
    page_number: int | None = None
    section: str | None = None
    subsection: str | None = None
    chunk_id: str
    parent_chunk_id: str | None = None
    content_type: ContentType = ContentType.PARAGRAPH
    source_type: str = "product_specification"
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
    token_estimate: int = 0
    block_ids: list[str] = Field(default_factory=list)


class Chunk(BaseModel):
    chunk_id: str
    text: str
    metadata: ChunkMetadata
    embedding: list[float] | None = None


class IndexedDocument(BaseModel):
    document_id: str
    document_name: str
    document_hash: str
    product_name: str | None = None
    product_type: str | None = None
    page_count: int = 0
    structure: DocumentStructure
    chunk_ids: list[str] = Field(default_factory=list)
    indexed_at: str | None = None
    pipeline_version: int = 1
    rag_normalized: bool = False


# ── Extraction output ───────────────────────────────────────────────────────


class SourceRef(BaseModel):
    document_id: str | None = None
    page: int | None = None
    section: str | None = None
    chunk_id: str | None = None


class Specification(BaseModel):
    parameter: str
    value: Any
    unit: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    source: SourceRef = Field(default_factory=SourceRef)
    grounding_status: GroundingStatus | None = None


class Feature(BaseModel):
    feature_name: str
    specifications: list[Specification] = Field(default_factory=list)


class CoverageReport(BaseModel):
    sections_discovered: int = 0
    sections_processed: int = 0
    sections_with_features: int = 0
    coverage_complete: bool = False
    missed_sections: list[str] = Field(default_factory=list)
    status: Literal["COMPLETE", "INCOMPLETE", "PARTIAL"] = "INCOMPLETE"


class DocumentInfo(BaseModel):
    document_id: str
    document_name: str
    product_name: str | None = None
    product_type: str | None = None


class ExtractionResult(BaseModel):
    document: DocumentInfo
    features: list[Feature] = Field(default_factory=list)
    coverage: CoverageReport = Field(default_factory=CoverageReport)
    query_intent: QueryIntent | None = None
    retries: int = 0
    debug: dict[str, Any] | None = None


class ExtractionTask(BaseModel):
    task_id: str
    section_title: str
    section_id: str | None = None
    queries: list[str] = Field(default_factory=list)
    status: Literal["pending", "running", "done", "failed", "retry"] = "pending"
    retries: int = 0


class RetrievedCandidate(BaseModel):
    chunk_id: str
    text: str
    metadata: ChunkMetadata
    vector_rank: int | None = None
    bm25_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


class StageMetrics(BaseModel):
    stage: str
    latency_ms: float = 0.0
    token_usage: dict[str, int] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
