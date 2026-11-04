"""Device Monitor API — AppSail-compatible (Flask, Zoho-documented startup).

Startup must match Catalyst docs:
  python3 -u main.py
  listen on X_ZOHO_CATALYST_LISTEN_PORT
"""

from __future__ import annotations

import gzip
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# pip install -t . packages live in this folder on AppSail
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request

app = Flask(__name__)

OFFLINE_AFTER_SEC = float(os.getenv("MONITOR_OFFLINE_AFTER_SEC") or "90")
MAX_GZIP_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 1_500_000
_DEVICES: Dict[str, Dict[str, Any]] = {}
_LOG_DIR = Path(os.getenv("MONITOR_LOG_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "monitor_logs"))
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _public(entry: Dict[str, Any], now: float) -> Dict[str, Any]:
    last_seen = float(entry.get("last_seen") or 0)
    age = max(0.0, now - last_seen)
    online = age <= OFFLINE_AFTER_SEC
    return {
        "device_id": entry["device_id"],
        "device_name": entry.get("device_name") or entry["device_id"],
        "model": entry.get("model"),
        "active": bool(entry.get("active")) and online,
        "online": online,
        "battery_percent": entry.get("battery_percent"),
        "charging": entry.get("charging"),
        "app_state": entry.get("app_state"),
        "registered_at": entry.get("registered_at"),
        "last_seen": last_seen,
        "last_seen_ago_sec": round(age, 1),
        "heartbeat_count": int(entry.get("heartbeat_count") or 0),
        "offline_after_sec": OFFLINE_AFTER_SEC,
        "network": entry.get("network"),
        "storage": entry.get("storage"),
        "memory": entry.get("memory"),
        "thermal": entry.get("thermal"),
        "test_execution": entry.get("test_execution"),
        "suite_logs": _public_logs(entry),
        "suite_log": (_public_logs(entry)[:1] or [None])[0],
    }


def _public_logs(entry: Dict[str, Any]):
    logs = entry.get("suite_logs")
    if isinstance(logs, list):
        return logs
    one = entry.get("suite_log")
    return [one] if isinstance(one, dict) else []


def _upsert(device_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    existing = _DEVICES.get(device_id) or {
        "device_id": device_id,
        "registered_at": now,
        "heartbeat_count": 0,
    }
    entry = {**existing, **patch, "device_id": device_id, "last_seen": now}
    if "heartbeat_count" in patch:
        entry["heartbeat_count"] = int(patch["heartbeat_count"])
    _DEVICES[device_id] = entry
    return _public(entry, now)


@app.get("/")
def root():
    return jsonify(
        {
            "service": "device-monitor",
            "ok": True,
            "framework": "flask",
            "endpoints": [
                "POST /api/monitor/register",
                "POST /api/monitor/heartbeat",
                "POST /api/monitor/logs",
                "GET /api/monitor/logs/<id>",
                "GET /api/monitor/devices",
                "DELETE /api/monitor/devices",
                "GET /health",
            ],
        }
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "store": "memory",
            "device_count": len(_DEVICES),
            "offline_after_sec": OFFLINE_AFTER_SEC,
        }
    )


@app.post("/api/monitor/register")
def register_device():
    body = request.get_json(silent=True) or {}
    device_id = str(body.get("device_id") or "").strip()
    device_name = str(body.get("device_name") or "").strip()
    if not device_id or not device_name:
        return jsonify({"ok": False, "error": "device_id and device_name required"}), 400
    model = body.get("model")
    existing = _DEVICES.get(device_id) or {}
    now = time.time()
    device = _upsert(
        device_id,
        {
            "device_name": device_name,
            "model": (str(model).strip() if model else existing.get("model")),
            "active": True,
            "app_state": existing.get("app_state") or "registered",
            "battery_percent": existing.get("battery_percent"),
            "charging": existing.get("charging"),
            "registered_at": existing.get("registered_at") or now,
            "heartbeat_count": int(existing.get("heartbeat_count") or 0),
            "network": existing.get("network"),
            "storage": existing.get("storage"),
            "memory": existing.get("memory"),
            "thermal": existing.get("thermal"),
            "test_execution": existing.get("test_execution"),
        },
    )
    return jsonify({"ok": True, "device": device})


@app.post("/api/monitor/heartbeat")
def device_heartbeat():
    body = request.get_json(silent=True) or {}
    device_id = str(body.get("device_id") or "").strip()
    if not device_id:
        return jsonify({"ok": False, "error": "device_id required"}), 400
    existing = _DEVICES.get(device_id) or {}
    name = body.get("device_name") or existing.get("device_name") or device_id
    device = _upsert(
        device_id,
        {
            "device_name": str(name).strip(),
            "model": existing.get("model"),
            "active": bool(body.get("active", True)),
            "battery_percent": body.get("battery_percent", existing.get("battery_percent")),
            "charging": body.get("charging", existing.get("charging")),
            "app_state": body.get("app_state") or existing.get("app_state") or "foreground",
            "registered_at": existing.get("registered_at") or time.time(),
            "heartbeat_count": int(existing.get("heartbeat_count") or 0) + 1,
            "network": body.get("network", existing.get("network")),
            "storage": body.get("storage", existing.get("storage")),
            "memory": body.get("memory", existing.get("memory")),
            "thermal": body.get("thermal", existing.get("thermal")),
            "test_execution": body.get(
                "test_execution", existing.get("test_execution")
            ),
        },
    )
    return jsonify({"ok": True, "device": device})


@app.post("/api/monitor/logs")
def upload_suite_log():
    device_id = (request.headers.get("X-Device-Id") or "").strip()
    if not device_id:
        return jsonify({"ok": False, "error": "device_id required"}), 400
    feature = (request.headers.get("X-Feature") or "").strip()
    suite = (request.headers.get("X-Suite-Label") or "suite").strip() or "suite"
    file_name = (request.headers.get("X-File-Name") or "suite.txt").strip() or "suite.txt"
    try:
        started_at_ms = int(request.headers.get("X-Started-At-Ms") or "0")
    except ValueError:
        started_at_ms = 0
    raw = request.get_data() or b""
    if not raw:
        return jsonify({"ok": False, "error": "empty log"}), 400
    if len(raw) > MAX_GZIP_BYTES:
        return jsonify({"ok": False, "error": "log is too large"}), 400
    try:
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
    except OSError:
        return jsonify({"ok": False, "error": "log is not gzip"}), 400
    log_id = uuid.uuid4().hex
    (_LOG_DIR / f"{log_id}.gz").write_bytes(raw)
    meta = {
        "id": log_id,
        "device_id": device_id,
        "feature": feature,
        "suite": suite,
        "file_name": file_name,
        "bytes": len(text.encode("utf-8")),
        "saved_at": time.time(),
        "started_at_ms": started_at_ms,
    }
    existing = _DEVICES.get(device_id) or {}
    device = _upsert(
        device_id,
        {
            "device_name": existing.get("device_name") or device_id,
            "model": existing.get("model"),
            "active": existing.get("active", True),
            "battery_percent": existing.get("battery_percent"),
            "charging": existing.get("charging"),
            "app_state": existing.get("app_state") or "foreground",
            "registered_at": existing.get("registered_at") or time.time(),
            "heartbeat_count": int(existing.get("heartbeat_count") or 0),
            "network": existing.get("network"),
            "storage": existing.get("storage"),
            "memory": existing.get("memory"),
            "thermal": existing.get("thermal"),
            "test_execution": existing.get("test_execution"),
            "suite_logs": [meta] + [
                item for item in _public_logs(existing) if item.get("id") != meta["id"]
            ][:29],
            "suite_log": meta,
        },
    )
    return jsonify({"ok": True, "suite_log": meta, "device": device})


@app.get("/api/monitor/logs/<log_id>")
def read_suite_log(log_id: str):
    if not log_id or "/" in log_id or ".." in log_id:
        return jsonify({"error": "log not found"}), 404
    path = _LOG_DIR / f"{log_id}.gz"
    if not path.is_file():
        return jsonify({"error": "log not found"}), 404
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")
    except OSError:
        return jsonify({"error": "log is not gzip"}), 400
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n… log truncated for display …\n"
    return text, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.get("/api/monitor/devices")
def list_devices():
    now = time.time()
    devices = [_public(e, now) for e in _DEVICES.values()]
    devices.sort(key=lambda d: d.get("device_name") or d["device_id"])
    online = sum(1 for d in devices if d.get("online"))
    return jsonify(
        {
            "devices": devices,
            "count": len(devices),
            "online_count": online,
            "offline_after_sec": OFFLINE_AFTER_SEC,
        }
    )


@app.get("/api/monitor/devices/<device_id>")
def get_device(device_id: str):
    entry = _DEVICES.get(device_id)
    if not entry:
        return jsonify({"error": f"device {device_id} not found"}), 404
    return jsonify({"device": _public(entry, time.time())})


@app.delete("/api/monitor/devices")
def clear_devices():
    removed = len(_DEVICES)
    _DEVICES.clear()
    return jsonify({"ok": True, "removed": removed, "count": 0})


if __name__ == "__main__":
    # Exact Catalyst AppSail pattern from Zoho Flask docs
    listen_port = int(os.getenv("X_ZOHO_CATALYST_LISTEN_PORT", "9000"))
    print(f"[device-monitor] flask listening on 0.0.0.0:{listen_port}", flush=True)
    app.run(host="0.0.0.0", port=listen_port)
