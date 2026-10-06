"""Test Execution API: devices, script sets, executions (live event stream), results and reports."""

from __future__ import annotations

import json
import mimetypes
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from services.test_execution import devices, reports
from services.test_execution.runner import ExecutionError, ExecutionNotFound, manager
from services.test_execution.script_sets import (
    ScriptSetNotFound,
    list_script_sets,
    script_set_detail,
    script_source,
)

router = APIRouter()


class StartExecutionRequest(BaseModel):
    run_id: str
    case_ids: list[str]
    serial: str
    overrides: dict[str, str] = Field(default_factory=dict)
    case_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    case_timeout_min: float = Field(60, gt=0, le=24 * 60)


class ControlRequest(BaseModel):
    action: Literal["stop", "skip", "pause", "resume"]


class ReviewRequest(BaseModel):
    decision: Literal["PASS", "FAIL"]
    note: str = ""


def _adb_error(exc: Exception) -> HTTPException:
    return HTTPException(503, str(exc))


# ── Devices ──

@router.get("/api/execution/devices")
def execution_devices() -> dict[str, Any]:
    try:
        return {"adb_available": True, "devices": devices.list_devices()}
    except devices.AdbUnavailable as exc:
        return {"adb_available": False, "devices": [], "error": str(exc)}


@router.get("/api/execution/devices/{serial}/health")
def execution_device_health(serial: str) -> dict[str, Any]:
    try:
        return devices.health(serial)
    except devices.AdbUnavailable as exc:
        raise _adb_error(exc) from exc


@router.get("/api/execution/devices/{serial}/packages")
def execution_device_packages(serial: str) -> dict[str, Any]:
    if serial not in devices.online_serials():
        raise HTTPException(404, f"device {serial} is not connected")
    try:
        result = devices.installed_packages(serial)
    except devices.AdbUnavailable as exc:
        raise _adb_error(exc) from exc
    return {**result, "device": devices.device_info(serial)}


@router.get("/api/execution/devices/{serial}/screenshot")
def execution_device_screenshot(serial: str) -> Response:
    try:
        png = devices.screenshot(serial)
    except devices.AdbUnavailable as exc:
        raise _adb_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


# ── Script sets ──

@router.get("/api/execution/script-sets")
def execution_script_sets() -> dict[str, Any]:
    return {"script_sets": list_script_sets()}


@router.get("/api/execution/script-sets/{run_id}")
def execution_script_set(run_id: str, serial: str | None = None) -> dict[str, Any]:
    packages = None
    if serial:
        try:
            packages = devices.harness_packages(serial)
        except devices.AdbUnavailable:
            packages = None
    try:
        return script_set_detail(run_id, packages)
    except ScriptSetNotFound as exc:
        raise HTTPException(404, f"Script set '{run_id}' not found") from exc


@router.get("/api/execution/script-sets/{run_id}/scripts/{filename}", response_class=PlainTextResponse)
def execution_script_source(run_id: str, filename: str) -> str:
    try:
        return script_source(run_id, filename)
    except ScriptSetNotFound as exc:
        raise HTTPException(404, f"Script '{filename}' not found in {run_id}") from exc


# ── Executions ──

@router.post("/api/executions")
def start_execution(req: StartExecutionRequest) -> dict[str, Any]:
    try:
        return manager.start(req.run_id, req.case_ids, req.serial, overrides=req.overrides,
                             case_overrides=req.case_overrides, case_timeout_min=req.case_timeout_min)
    except ScriptSetNotFound as exc:
        raise HTTPException(404, f"Script set '{req.run_id}' not found") from exc
    except ExecutionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/executions")
def list_executions(run_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    return {"executions": manager.list(run_id, limit)}


@router.get("/api/executions/compare")
def compare_executions(a: str, b: str) -> dict[str, Any]:
    try:
        return reports.compare(manager.record(a), manager.record(b))
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"Execution not found: {exc}") from exc


@router.get("/api/executions/{exec_id}")
def get_execution(exec_id: str) -> dict[str, Any]:
    try:
        return {**manager.record(exec_id), "causes": reports.CAUSES}
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"Execution '{exec_id}' not found") from exc


@router.delete("/api/executions/{exec_id}")
def delete_execution(exec_id: str) -> dict[str, Any]:
    try:
        manager.delete(exec_id)
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"Execution '{exec_id}' not found") from exc
    except ExecutionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": exec_id}


@router.get("/api/executions/{exec_id}/events")
async def execution_events(exec_id: str, request: Request, after: int = 0) -> StreamingResponse:
    try:
        manager.record(exec_id)
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"Execution '{exec_id}' not found") from exc
    last = int(request.headers.get("last-event-id") or after)

    async def stream():
        nonlocal last
        while not await request.is_disconnected():
            events, over = await run_in_threadpool(manager.wait_events, exec_id, last, 10)
            for event in events:
                last = event["seq"]
                yield f"id: {last}\ndata: {json.dumps(event)}\n\n"
            if over:
                yield "event: end\ndata: {}\n\n"
                return
            if not events:
                yield ": keep-alive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/executions/{exec_id}/control")
def control_execution(exec_id: str, req: ControlRequest) -> dict[str, Any]:
    try:
        return manager.control(exec_id, req.action)
    except ExecutionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/executions/{exec_id}/cases/{case_id}")
def execution_case(exec_id: str, case_id: str) -> dict[str, Any]:
    try:
        return manager.case_detail(exec_id, case_id)
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"Not found: {exc}") from exc


@router.get("/api/executions/{exec_id}/cases/{case_id}/files/{name}")
def execution_case_file(exec_id: str, case_id: str, name: str, download: bool = False) -> FileResponse:
    try:
        path = manager.case_file(exec_id, case_id, name)
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"File not found: {exc}") from exc
    media = mimetypes.guess_type(path.name)[0]
    if not media or media.startswith("text/"):
        media = "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media, filename=path.name if download else None)


@router.post("/api/executions/{exec_id}/cases/{case_id}/review")
def review_execution_case(exec_id: str, case_id: str, req: ReviewRequest) -> dict[str, Any]:
    try:
        return manager.review(exec_id, case_id, req.decision, req.note)
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"Not found: {exc}") from exc
    except ExecutionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/executions/{exec_id}/report")
def execution_report(exec_id: str, format: Literal["html", "junit", "json"] = "html") -> Response:
    try:
        record = manager.record(exec_id)
    except ExecutionNotFound as exc:
        raise HTTPException(404, f"Execution '{exec_id}' not found") from exc
    name = f"test_execution_{exec_id}"
    if format == "junit":
        return Response(reports.junit_xml(record), media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xml"'})
    details = manager.result_details(exec_id)
    if format == "json":
        body = json.dumps({"execution": record, "results": details}, indent=2)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    return HTMLResponse(reports.html_report(record, details),
                        headers={"Content-Disposition": f'attachment; filename="{name}.html"'})
