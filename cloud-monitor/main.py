"""Device Monitor API — AppSail-compatible (Flask, Zoho-documented startup).

Startup must match Catalyst docs:
  python3 -u main.py
  listen on X_ZOHO_CATALYST_LISTEN_PORT
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, Optional

# pip install -t . packages live in this folder on AppSail
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request

app = Flask(__name__)

OFFLINE_AFTER_SEC = float(os.getenv("MONITOR_OFFLINE_AFTER_SEC") or "90")
_DEVICES: Dict[str, Dict[str, Any]] = {}


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
    }


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
                "GET /api/monitor/devices",
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


if __name__ == "__main__":
    # Exact Catalyst AppSail pattern from Zoho Flask docs
    listen_port = int(os.getenv("X_ZOHO_CATALYST_LISTEN_PORT", "9000"))
    print(f"[device-monitor] flask listening on 0.0.0.0:{listen_port}", flush=True)
    app.run(host="0.0.0.0", port=listen_port)
