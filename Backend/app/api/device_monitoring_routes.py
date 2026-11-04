"""Device monitoring APIs: register, heartbeat, list devices."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from services.device_monitoring import monitor_store
from services.device_monitoring.suite_logs import suite_log_store

router = APIRouter(tags=["device-monitoring"])


class RegisterRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    device_name: str = Field(..., min_length=1, max_length=256)
    model: Optional[str] = Field(None, max_length=256)


class HeartbeatRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    device_name: Optional[str] = Field(None, max_length=256)
    active: bool = True
    battery_percent: Optional[float] = Field(None, ge=0, le=100)
    charging: Optional[bool] = None
    app_state: Optional[str] = Field(None, max_length=64)
    network: Optional[dict[str, Any]] = None
    storage: Optional[dict[str, Any]] = None
    memory: Optional[dict[str, Any]] = None
    thermal: Optional[dict[str, Any]] = None
    test_execution: Optional[dict[str, Any]] = None


@router.post("/api/monitor/register")
def register_device(body: RegisterRequest) -> dict[str, Any]:
    device = monitor_store.register(
        body.device_id.strip(),
        body.device_name.strip(),
        model=(body.model.strip() if body.model else None),
    )
    return {"ok": True, "device": device}


@router.post("/api/monitor/heartbeat")
def device_heartbeat(body: HeartbeatRequest) -> dict[str, Any]:
    device = monitor_store.heartbeat(
        body.device_id.strip(),
        device_name=(body.device_name.strip() if body.device_name else None),
        active=body.active,
        battery_percent=body.battery_percent,
        charging=body.charging,
        app_state=(body.app_state.strip() if body.app_state else None),
        network=body.network,
        storage=body.storage,
        memory=body.memory,
        thermal=body.thermal,
        test_execution=body.test_execution,
    )
    return {"ok": True, "device": device}


@router.post("/api/monitor/logs")
async def upload_suite_log(request: Request) -> dict[str, Any]:
    device_id = (request.headers.get("x-device-id") or "").strip()
    if not device_id:
        raise HTTPException(400, "device_id required")
    feature = (request.headers.get("x-feature") or "").strip()
    suite = (request.headers.get("x-suite-label") or "suite").strip() or "suite"
    file_name = (request.headers.get("x-file-name") or "suite.txt").strip() or "suite.txt"
    try:
        started_at_ms = int(request.headers.get("x-started-at-ms") or "0")
    except ValueError:
        started_at_ms = 0
    raw = await request.body()
    try:
        meta = suite_log_store.save(
            device_id=device_id,
            feature=feature,
            suite=suite,
            file_name=file_name,
            started_at_ms=started_at_ms,
            gzip_bytes=raw,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    device = monitor_store.attach_suite_log(device_id, meta)
    return {"ok": True, "suite_log": meta, "device": device}


@router.get("/api/monitor/logs/{log_id}")
def read_suite_log(log_id: str) -> PlainTextResponse:
    text = suite_log_store.read_text(log_id)
    if text is None:
        raise HTTPException(404, "log not found")
    return PlainTextResponse(text)


@router.get("/api/monitor/devices")
def list_monitored_devices() -> dict[str, Any]:
    devices = monitor_store.list_devices()
    online = sum(1 for d in devices if d.get("online"))
    return {
        "devices": devices,
        "count": len(devices),
        "online_count": online,
        "offline_after_sec": monitor_store.offline_after_sec,
    }


@router.get("/api/monitor/devices/{device_id}")
def get_monitored_device(device_id: str) -> dict[str, Any]:
    device = monitor_store.get_device(device_id)
    if device is None:
        raise HTTPException(404, f"device {device_id} not found")
    return {"device": device}


@router.delete("/api/monitor/devices")
def clear_monitored_devices() -> dict[str, Any]:
    removed = monitor_store.clear()
    return {"ok": True, "removed": removed, "count": 0}
