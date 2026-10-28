"""Test Suite API: upload an Excel test suite for an operator stage and read back its sheet summary."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from services import test_suites

router = APIRouter()


class SuiteUploadRequest(BaseModel):
    file_path: str = Field(min_length=1)


@router.get("/api/test-suites/{stage_id}")
def test_suite_current(stage_id: str) -> dict[str, Any]:
    try:
        saved = test_suites.load_saved(stage_id)
        extracted = test_suites.load_extracted(stage_id) if saved else None
    except test_suites.SuiteUploadError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "saved": saved,
        "extraction": test_suites.extraction_summary(extracted) if extracted else None,
    }


@router.post("/api/test-suites/{stage_id}/extract")
async def test_suite_extract(stage_id: str) -> dict[str, Any]:
    try:
        extracted = await run_in_threadpool(test_suites.extract, stage_id)
    except test_suites.SuiteUploadError as exc:
        raise HTTPException(400, str(exc)) from exc
    return test_suites.extraction_summary(extracted)


@router.get("/api/test-suites/{stage_id}/extracted")
def test_suite_extracted(stage_id: str) -> dict[str, Any]:
    try:
        extracted = test_suites.load_extracted(stage_id)
    except test_suites.SuiteUploadError as exc:
        raise HTTPException(400, str(exc)) from exc
    if extracted is None:
        raise HTTPException(404, "No extraction for this stage yet")
    return extracted


@router.post("/api/test-suites/{stage_id}/upload")
async def test_suite_upload(stage_id: str, req: SuiteUploadRequest) -> dict[str, Any]:
    try:
        return await run_in_threadpool(test_suites.upload, stage_id, req.file_path)
    except test_suites.SuiteUploadError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/api/test-suites/{stage_id}")
def test_suite_clear(stage_id: str) -> dict[str, Any]:
    try:
        test_suites.clear_saved(stage_id)
    except test_suites.SuiteUploadError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"cleared": True}
