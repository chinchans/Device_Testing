"""LangGraph / fallback state-machine for agentic extraction."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from agents.coverage_validator import validate_coverage
from agents.extraction_planner import plan_extraction
from agents.grounding_validator import validate_grounding
from agents.query_rewrite import rewrite_queries
from agents.query_understanding import understand_query
from agents.reconciliation import reconcile_features
from agents.structured_extraction import extract_features_from_evidence
from core.config import get_settings
from core.schemas import (
    CoverageReport,
    DocumentInfo,
    ExtractionResult,
    ExtractionTask,
    Feature,
    QueryIntent,
)
from core.state import AgentState
from indexing.pipeline import IndexingPipeline
from indexing.structure import specification_sections
from observability.logging import TraceRecorder, logger
from retrieval.context_expansion import ContextExpander
from retrieval.hybrid import HybridRetriever
from retrieval.reranker import get_reranker
from storage.document_store import DocumentStore

try:
    from langgraph.graph import END, StateGraph

    HAS_LANGGRAPH = True
except ImportError:  # pragma: no cover
    HAS_LANGGRAPH = False
    END = "END"
    StateGraph = None  # type: ignore


def _process_single_task(
    task: ExtractionTask,
    document_id: str,
    query: str,
    retriever: HybridRetriever,
    expander: ContextExpander,
    reranker: Any,
    trace: TraceRecorder,
    extraction_policy: str = "",
) -> tuple[ExtractionTask, list[Feature], dict[str, Any]]:
    settings = get_settings()
    cfg = settings.retrieval
    filters = {"document_id": document_id, "section": task.section_title}
    # First try with section filter; if too few hits, retry without section filter
    candidates, debug = retriever.retrieve(task.queries, filters=filters)
    if len(candidates) < 3:
        candidates2, debug2 = retriever.retrieve(task.queries, filters={"document_id": document_id})
        debug["unfiltered_fallback"] = debug2
        # Prefer filtered, append unique unfiltered
        seen = {c.chunk_id for c in candidates}
        for c in candidates2:
            if c.chunk_id not in seen:
                candidates.append(c)
                seen.add(c.chunk_id)

    # Trim to rerank window
    rrf_top = candidates[: cfg.rerank_input_n]
    query_for_rerank = task.queries[0] if task.queries else task.section_title
    reranked = reranker.rerank(query_for_rerank, rrf_top, cfg.rerank_top_k)
    expanded = expander.expand(reranked)

    features, usage = extract_features_from_evidence(
        feature_hint=task.section_title,
        document_id=document_id,
        candidates=expanded,
        query=query,
        extraction_policy=extraction_policy,
    )
    features, grounding = validate_grounding(features, expanded)

    task.status = "done"
    trace.log(
        "task_complete",
        {
            "task_id": task.task_id,
            "section": task.section_title,
            "features": len(features),
            "grounding": grounding,
            "reranked": [c.chunk_id for c in reranked],
        },
    )
    return task, features, {"retrieval": debug, "grounding": grounding, "usage": usage}


def run_extraction(
    document_id: str,
    query: str = "Extract all features and specifications",
    *,
    debug_mode: bool | None = None,
) -> ExtractionResult:
    settings = get_settings()
    debug_mode = settings.observability.debug_mode if debug_mode is None else debug_mode
    trace = TraceRecorder(query=query, document_id=document_id)
    store = DocumentStore()
    indexed = store.get(document_id)
    if indexed is None:
        raise FileNotFoundError(f"Document not indexed: {document_id}")

    structure = store.load_structure(document_id) or indexed.structure
    pipeline = IndexingPipeline()
    vs, bm = pipeline.get_retrievers(document_id)
    retriever = HybridRetriever(vs, bm)
    expander = ContextExpander(vs, bm)
    reranker = get_reranker()

    with trace.timed("query_understanding"):
        understanding = understand_query(query)
        intent = understanding.intent
        confidence = understanding.confidence
        notes = understanding.notes
        extraction_policy = understanding.extraction_policy
    trace.log(
        "query_intent",
        {
            "intent": intent.value,
            "confidence": confidence,
            "notes": notes,
            "has_hierarchy_policy": bool(extraction_policy),
        },
    )

    with trace.timed("extraction_planner"):
        tasks = plan_extraction(structure, query, intent)
    trace.log(
        "extraction_plan",
        {"tasks": [{"id": t.task_id, "section": t.section_title, "queries": t.queries} for t in tasks]},
    )

    all_features: list[Feature] = []
    processed_sections: list[str] = []
    task_debug: list[dict[str, Any]] = []
    retry_count = 0

    def _run_tasks(task_list: list[ExtractionTask]) -> None:
        nonlocal all_features, processed_sections
        concurrency = max(1, settings.agents.section_concurrency)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {
                pool.submit(
                    _process_single_task,
                    task,
                    document_id,
                    query,
                    retriever,
                    expander,
                    reranker,
                    trace,
                    extraction_policy,
                ): task
                for task in task_list
            }
            for fut in as_completed(futs):
                task, features, dbg = fut.result()
                processed_sections.append(task.section_title)
                all_features.extend(features)
                task_debug.append({"task": task.section_title, **dbg})

    with trace.timed("section_extraction", task_count=len(tasks)):
        _run_tasks(tasks)

    all_features = reconcile_features(all_features)
    coverage = validate_coverage(structure, processed_sections, all_features)
    trace.log("coverage", coverage.model_dump())

    # Agentic retry loop for missed sections / incomplete coverage
    max_retries = settings.agents.max_retries
    while (
        not coverage.coverage_complete
        and coverage.missed_sections
        and retry_count < max_retries
        and intent == QueryIntent.FULL_DOCUMENT_EXTRACTION
    ):
        retry_count += 1
        missed = coverage.missed_sections[:8]
        trace.log("retry", {"attempt": retry_count, "missed": missed})
        retry_tasks: list[ExtractionTask] = []
        for title in missed:
            new_q = rewrite_queries(title, [title], reason="coverage_miss", missed_hints=missed)
            retry_tasks.append(
                ExtractionTask(
                    task_id=f"retry_{retry_count}_{title[:20]}",
                    section_title=title,
                    queries=new_q,
                    status="retry",
                    retries=retry_count,
                )
            )
        with trace.timed(f"retry_{retry_count}", missed=len(missed)):
            _run_tasks(retry_tasks)
        all_features = reconcile_features(all_features)
        coverage = validate_coverage(structure, processed_sections, all_features)
        trace.log("coverage_after_retry", coverage.model_dump())

    # If still incomplete, mark explicitly — never silently claim complete
    if coverage.missed_sections and not coverage.coverage_complete:
        coverage.status = "INCOMPLETE"
        coverage.coverage_complete = False

    result = ExtractionResult(
        document=DocumentInfo(
            document_id=indexed.document_id,
            document_name=indexed.document_name,
            product_name=indexed.product_name or structure.product_name,
            product_type=indexed.product_type or structure.product_type,
        ),
        features=all_features,
        coverage=coverage,
        query_intent=intent,
        retries=retry_count,
        debug={
            "intent_confidence": confidence,
            "intent_notes": notes,
            "tasks": task_debug,
            "trace_id": trace.query_id,
        }
        if debug_mode
        else None,
    )
    trace_path = trace.persist()
    logger.info(
        "Extraction complete doc=%s features=%d coverage=%s trace=%s",
        document_id,
        len(all_features),
        coverage.status,
        trace_path.name,
    )
    return result


def build_langgraph():
    """Optional LangGraph compilation for tooling / visualization."""
    if not HAS_LANGGRAPH:
        raise RuntimeError("langgraph is not installed")

    graph = StateGraph(AgentState)

    def node_structure(state: AgentState) -> AgentState:
        store = DocumentStore()
        indexed = store.get(state["document_id"])
        structure = store.load_structure(state["document_id"])
        state["indexed_document"] = indexed
        state["structure_summary"] = [
            {"title": s.title, "spec": s.is_specification_bearing}
            for s in (structure.sections if structure else [])
        ]
        return state

    def node_intent(state: AgentState) -> AgentState:
        understanding = understand_query(state.get("query", ""))
        state["query_intent"] = understanding.intent
        state["intent_confidence"] = understanding.confidence
        state["intent_notes"] = understanding.notes
        return state

    def node_plan(state: AgentState) -> AgentState:
        store = DocumentStore()
        structure = store.load_structure(state["document_id"])
        state["extraction_tasks"] = plan_extraction(
            structure, state.get("query", ""), state["query_intent"]
        )
        return state

    def node_extract_all(state: AgentState) -> AgentState:
        result = run_extraction(state["document_id"], state.get("query", ""))
        state["result"] = result
        state["coverage"] = result.coverage
        state["all_features"] = result.features
        state["needs_retry"] = not result.coverage.coverage_complete
        return state

    graph.add_node("DocumentStructureAgent", node_structure)
    graph.add_node("QueryUnderstandingAgent", node_intent)
    graph.add_node("ExtractionPlannerAgent", node_plan)
    graph.add_node("ExtractValidate", node_extract_all)
    graph.set_entry_point("DocumentStructureAgent")
    graph.add_edge("DocumentStructureAgent", "QueryUnderstandingAgent")
    graph.add_edge("QueryUnderstandingAgent", "ExtractionPlannerAgent")
    graph.add_edge("ExtractionPlannerAgent", "ExtractValidate")
    graph.add_edge("ExtractValidate", END)
    return graph.compile()
