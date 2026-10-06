"""FastAPI routes for document upload and agentic extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.adapters import build_feature_response, should_retry_with_ocr
from app.api.device_profile import derive_device_classification
from core.config import get_settings
from core.schemas import IndexedDocument
from graph.workflow import run_extraction
from indexing.pipeline import IndexingPipeline
from llm.azure_client import is_azure_configured
from observability.logging import TraceRecorder, logger
from services.test_cases import (
    derive_spec_values,
    fill_placeholders,
    get_feature_catalog,
    get_full_suite,
    get_test_case,
    list_features as list_test_case_features,
    placeholders_in,
)
from services.test_scripts import FeatureDisabledError, generate_scripts
from storage.document_store import DocumentStore

router = APIRouter()

MISSING_STANDARDS_OCR_HINT = (
    "More than 3 default features missing after text extract; reindexing with OCR"
)


def _upload_path_for(indexed: IndexedDocument) -> Path | None:
    """Locate the persisted upload PDF for a previously indexed document."""
    settings = get_settings()
    uploads = settings.uploads_path
    candidate = uploads / f"{indexed.document_id}_{indexed.document_name}"
    if candidate.exists():
        return candidate
    matches = sorted(uploads.glob(f"{indexed.document_id}_*"))
    return matches[0] if matches else None


def _extract_and_maybe_ocr(
    pipeline: IndexingPipeline,
    indexed: IndexedDocument,
    query: str,
    device_type: str | None,
    *,
    source_path: Path | None = None,
    upload_bytes: bytes | None = None,
    upload_filename: str | None = None,
) -> tuple[IndexedDocument, Any, list[dict[str, Any]], dict[str, Any], bool]:
    """Run extraction; if >3 standard features missing, force-OCR reindex once and retry."""
    result = run_extraction(indexed.document_id, query, debug_mode=True)
    features, checklist = build_feature_response(
        result, device_type=device_type or "mobile"
    )
    used_ocr_retry = False

    if should_retry_with_ocr(checklist) and get_settings().indexing.ocr_enabled:
        missing = int(checklist.get("standard_total") or 0) - int(
            checklist.get("standard_found") or 0
        )
        logger.info(
            "%s (missing=%s document_id=%s)",
            MISSING_STANDARDS_OCR_HINT,
            missing,
            indexed.document_id,
        )
        try:
            if upload_bytes is not None and upload_filename:
                indexed = pipeline.index_bytes(
                    upload_bytes,
                    upload_filename,
                    force_reindex=True,
                    force_ocr=True,
                )
            else:
                path = source_path or _upload_path_for(indexed)
                if path is None:
                    logger.warning(
                        "OCR retry skipped: upload path not found for %s",
                        indexed.document_id,
                    )
                    return indexed, result, features, checklist, used_ocr_retry
                indexed = pipeline.index_file(
                    path,
                    original_name=indexed.document_name,
                    force_reindex=True,
                    force_ocr=True,
                )
            result = run_extraction(indexed.document_id, query, debug_mode=True)
            features, checklist = build_feature_response(
                result, device_type=device_type or "mobile"
            )
            used_ocr_retry = True
            checklist = {**checklist, "ocr_retry_used": True}
        except Exception:
            logger.exception("OCR retry failed; returning original extraction")

    return indexed, result, features, checklist, used_ocr_retry


def _extract_response(
    indexed: IndexedDocument,
    result: Any,
    features: list[dict[str, Any]],
    checklist: dict[str, Any],
    *,
    device_type: str | None,
    used_ocr: bool,
) -> dict[str, Any]:
    store = DocumentStore()
    normalized = store.load_normalized(indexed.document_id)
    profile = derive_device_classification(
        result,
        device_type=device_type or "mobile",
        product_name=result.document.product_name or indexed.product_name,
        document_name=indexed.document_name,
        ui_features=features,
        normalized=normalized,
    )
    return {
        "document_id": indexed.document_id,
        "document_name": indexed.document_name,
        "product_name": result.document.product_name,
        "product_type": result.document.product_type,
        "device_type": device_type or "mobile",
        "query_intent": result.query_intent.value if result.query_intent else None,
        "coverage": result.coverage.model_dump(),
        "feature_checklist": checklist,
        "features": features,
        "device_classification": profile,
        "ocr_retry_used": used_ocr,
        "extraction": result.model_dump(),
    }


class ExtractRequest(BaseModel):
    document_id: str
    query: str = "Extract all features and specifications"
    debug: bool = False
    device_type: Optional[str] = None


class ExtractFromPathRequest(BaseModel):
    file_path: str = Field(min_length=1)
    query: str = "Extract all features and specifications"
    device_type: Optional[str] = None
    force_reindex: bool = False


class GenerateScriptsRequest(BaseModel):
    feature: str = "camera"
    case_ids: list[str] = Field(min_length=1)
    frameworks: list[str] = Field(default_factory=list)
    use_llm: bool = True
    # UI feature cards ({name, parameters:[{name, value}]}) of the current extraction;
    # empty keeps the ${VAR} placeholders for runtime discovery.
    spec_features: list[dict[str, Any]] = Field(default_factory=list)
    product_name: Optional[str] = None


class FillTestCaseRequest(BaseModel):
    spec_features: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "azure_configured": is_azure_configured(),
        "embedding_provider": settings.models.embedding_provider,
        "reranker_provider": settings.models.reranker_provider,
    }


@router.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    force_reindex: bool = Form(False),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(400, "filename required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF uploads are supported in this version")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    pipeline = IndexingPipeline()
    trace = TraceRecorder(query="index", document_id="")
    try:
        indexed = pipeline.index_bytes(
            data, file.filename, force_reindex=force_reindex, trace=trace
        )
    except Exception as exc:
        logger.exception("Indexing failed")
        raise HTTPException(500, f"Indexing failed: {exc}") from exc
    trace.document_id = indexed.document_id
    trace.persist()
    structure = indexed.structure
    return {
        "document_id": indexed.document_id,
        "document_name": indexed.document_name,
        "document_hash": indexed.document_hash,
        "page_count": indexed.page_count,
        "product_name": indexed.product_name,
        "product_type": indexed.product_type,
        "sections_discovered": len(
            [s for s in structure.sections if s.is_specification_bearing and s.level > 0]
        ),
        "chunk_count": len(indexed.chunk_ids),
        "cached": False,
    }


@router.get("/api/documents")
def list_documents() -> dict[str, Any]:
    store = DocumentStore()
    docs = store.list_documents()
    return {
        "documents": [
            {
                "document_id": d.document_id,
                "document_name": d.document_name,
                "product_name": d.product_name,
                "page_count": d.page_count,
                "indexed_at": d.indexed_at,
            }
            for d in docs
        ]
    }


@router.get("/api/documents/{document_id}/structure")
def get_structure(document_id: str) -> dict[str, Any]:
    store = DocumentStore()
    structure = store.load_structure(document_id)
    if structure is None:
        raise HTTPException(404, "Document structure not found")
    return structure.model_dump()


@router.post("/api/extract")
def extract(req: ExtractRequest) -> dict[str, Any]:
    try:
        result = run_extraction(req.document_id, req.query, debug_mode=req.debug)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        logger.exception("Extraction failed")
        raise HTTPException(500, f"Extraction failed: {exc}") from exc
    return result.model_dump()


@router.post("/api/extract-features")
async def extract_features(
    file: Optional[UploadFile] = File(None),
    query: str = Form("Extract all features and specifications"),
    device_type: Optional[str] = Form(None),
    document_id: Optional[str] = Form(None),
    force_reindex: bool = Form(False),
) -> dict[str, Any]:
    """
    Convenience endpoint for the Device Testing UI:
    upload (or reuse document_id) → index → full extraction → UI feature cards.
    Retries once with full-page OCR when more than 3 default features are missing.
    """
    pipeline = IndexingPipeline()
    indexed = None
    upload_bytes: bytes | None = None
    upload_filename: str | None = None

    if document_id:
        store = DocumentStore()
        indexed = store.get(document_id)
        if indexed is None:
            raise HTTPException(404, f"Unknown document_id={document_id}")
    elif file is not None:
        if not file.filename:
            raise HTTPException(400, "filename required")
        upload_bytes = await file.read()
        if not upload_bytes:
            raise HTTPException(400, "Empty file")
        upload_filename = file.filename
        try:
            indexed = pipeline.index_bytes(
                upload_bytes, upload_filename, force_reindex=force_reindex
            )
        except Exception as exc:
            logger.exception("Indexing failed")
            raise HTTPException(500, f"Indexing failed: {exc}") from exc
    else:
        raise HTTPException(400, "Provide file or document_id")

    try:
        indexed, result, features, checklist, used_ocr = _extract_and_maybe_ocr(
            pipeline,
            indexed,
            query,
            device_type,
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
        )
    except Exception as exc:
        logger.exception("Extraction failed")
        raise HTTPException(500, f"Extraction failed: {exc}") from exc

    return _extract_response(
        indexed,
        result,
        features,
        checklist,
        device_type=device_type,
        used_ocr=used_ocr,
    )


@router.post("/api/extract-from-path")
def extract_from_path(req: ExtractFromPathRequest) -> dict[str, Any]:
    path = Path(req.file_path)
    if not path.exists():
        raise HTTPException(404, f"File not found: {req.file_path}")
    pipeline = IndexingPipeline()
    try:
        indexed = pipeline.index_file(path, force_reindex=req.force_reindex)
        indexed, result, features, checklist, used_ocr = _extract_and_maybe_ocr(
            pipeline,
            indexed,
            req.query,
            req.device_type,
            source_path=path,
        )
    except Exception as exc:
        logger.exception("extract-from-path failed")
        raise HTTPException(500, str(exc)) from exc
    return _extract_response(
        indexed,
        result,
        features,
        checklist,
        device_type=req.device_type,
        used_ocr=used_ocr,
    )


# ── Default test-case catalogs (UI briefs + codegen suites) ──────────────


@router.get("/api/test-cases")
def list_default_test_case_features() -> dict[str, Any]:
    """List features that have curated default test-case catalogs."""
    return {"features": list_test_case_features()}


@router.get("/api/test-cases/{feature}")
def get_default_test_cases(feature: str) -> dict[str, Any]:
    """UI catalog: short briefs + IDs (e.g. cam_fun_001) per category."""
    catalog = get_feature_catalog(feature)
    if catalog is None:
        raise HTTPException(404, f"No default test cases for feature '{feature}'")
    return catalog


@router.get("/api/test-cases/{feature}/{category}")
def get_default_test_suite(feature: str, category: str) -> dict[str, Any]:
    """Full codegen-ready suite for a feature × category."""
    suite = get_full_suite(feature, category)
    if suite is None:
        raise HTTPException(
            404, f"No suite for feature '{feature}' category '{category}'"
        )
    return suite


@router.get("/api/test-cases/{feature}/{category}/{case_id}")
def get_default_test_case(
    feature: str, category: str, case_id: str
) -> dict[str, Any]:
    """One full test case by UI id (cam_fun_001) or source id (TC_CAM_FUNC_001)."""
    case = get_test_case(feature, category, case_id)
    if case is None:
        raise HTTPException(
            404,
            f"Test case '{case_id}' not found for {feature}/{category}",
        )
    return case


@router.post("/api/test-cases/{feature}/{category}/{case_id}/fill")
def fill_test_case(
    feature: str, category: str, case_id: str, req: FillTestCaseRequest
) -> dict[str, Any]:
    """Preview one test case with ${VAR} placeholders filled from extracted spec values."""
    case = get_test_case(feature, category, case_id)
    if case is None:
        raise HTTPException(
            404,
            f"Test case '{case_id}' not found for {feature}/{category}",
        )
    derived = derive_spec_values(req.spec_features)
    used = placeholders_in(case)
    values = {k: v["value"] for k, v in derived.items() if k in used}
    return {
        "test_case": fill_placeholders(case, values),
        "spec_values": {k: derived[k] for k in values},
        "unfilled_placeholders": sorted(used - values.keys()),
    }


# ── Test script generation (test case + harness operation → Python script) ──


@router.post("/api/test-scripts/generate")
def generate_test_scripts(req: GenerateScriptsRequest) -> dict[str, Any]:
    """One script per selected case; the LLM writes run(h), the runtime does the rest."""
    try:
        return generate_scripts(
            req.feature,
            req.case_ids,
            use_llm=req.use_llm,
            frameworks=req.frameworks,
            spec_features=req.spec_features,
            product_name=req.product_name,
        )
    except FeatureDisabledError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(500, f"Missing generation input: {exc}") from exc
    except Exception as exc:
        logger.exception("Test script generation failed")
        raise HTTPException(500, f"Test script generation failed: {exc}") from exc
