"""Regulatory Certifications API: definitions, file scan, validation and saved results."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from services import certifications

router = APIRouter()


class ScanRequest(BaseModel):
    file_paths: list[str] = Field(default_factory=list)
    folder_paths: list[str] = Field(default_factory=list)


class CertificateFile(BaseModel):
    path: str
    name: str = ""
    size: int = 0
    supported: bool = True
    cert_id: Optional[str] = None
    detected_by: str = "none"
    error: str = ""


class DeviceIdentity(BaseModel):
    manufacturer: str = ""
    model: str = ""


class ValidateRequest(BaseModel):
    files: list[CertificateFile] = Field(default_factory=list)
    device: DeviceIdentity = Field(default_factory=DeviceIdentity)


@router.get("/api/certifications")
def certification_definitions() -> dict[str, Any]:
    return {"certificates": certifications.list_definitions()}


@router.post("/api/certifications/scan")
async def certification_scan(req: ScanRequest) -> dict[str, Any]:
    try:
        files = await run_in_threadpool(certifications.scan, req.file_paths, req.folder_paths)
    except certifications.CertificationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"files": files}


@router.post("/api/certifications/validate")
async def certification_validate(req: ValidateRequest) -> dict[str, Any]:
    for f in req.files:
        if f.cert_id and certifications.get_definition(f.cert_id) is None:
            raise HTTPException(400, f"Unknown certificate id: {f.cert_id}")
    return await run_in_threadpool(
        certifications.validate,
        [f.model_dump() for f in req.files],
        req.device.model_dump(),
    )


@router.get("/api/certifications/results")
def certification_results() -> dict[str, Any]:
    return {"saved": certifications.load_saved()}


@router.delete("/api/certifications/results")
def certification_clear_results() -> dict[str, Any]:
    certifications.clear_saved()
    return {"cleared": True}
