"""LangGraph shared state for the agentic extraction workflow."""

from __future__ import annotations

from typing import Any, TypedDict

from core.schemas import (
    CoverageReport,
    ExtractionResult,
    ExtractionTask,
    Feature,
    IndexedDocument,
    QueryIntent,
    RetrievedCandidate,
    StageMetrics,
)


class AgentState(TypedDict, total=False):
    # Inputs
    document_id: str
    query: str
    debug_mode: bool

    # Document context
    indexed_document: IndexedDocument
    structure_summary: list[dict[str, Any]]

    # Query understanding
    query_intent: QueryIntent
    intent_confidence: float
    intent_notes: str

    # Planning
    extraction_tasks: list[ExtractionTask]
    current_task_index: int

    # Retrieval / extraction working memory
    current_task: ExtractionTask | None
    retrieval_queries: list[str]
    vector_hits: list[dict[str, Any]]
    bm25_hits: list[dict[str, Any]]
    rrf_candidates: list[RetrievedCandidate]
    reranked_candidates: list[RetrievedCandidate]
    expanded_context: list[RetrievedCandidate]
    task_features: list[Feature]
    all_features: list[Feature]

    # Validation
    grounding_report: dict[str, Any]
    coverage: CoverageReport
    needs_retry: bool
    retry_reason: str
    retry_count: int
    max_retries: int
    rewrite_queries: list[str]

    # Output
    result: ExtractionResult
    metrics: list[StageMetrics]
    trace: list[dict[str, Any]]
    error: str | None
