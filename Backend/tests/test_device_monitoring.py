"""Tests for device monitoring store and API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from services.device_monitoring.store import DeviceMonitorStore


def test_store_register_and_heartbeat_online() -> None:
    store = DeviceMonitorStore(offline_after_sec=90)
    reg = store.register("dev-1", "Phone A", model="Pixel")
    assert reg["device_id"] == "dev-1"
    assert reg["online"] is True
    assert reg["active"] is True

    hb = store.heartbeat(
        "dev-1",
        device_name="Phone A",
        active=True,
        battery_percent=85.0,
        charging=True,
        app_state="foreground",
    )
    assert hb["heartbeat_count"] == 1
    assert hb["battery_percent"] == 85.0
    assert hb["charging"] is True
    assert hb["online"] is True

    devices = store.list_devices()
    assert len(devices) == 1
    assert devices[0]["device_name"] == "Phone A"


def test_store_marks_offline_after_timeout() -> None:
    store = DeviceMonitorStore(offline_after_sec=1)
    store.heartbeat("dev-2", device_name="Phone B", active=True, battery_percent=40)
    entry = store._devices["dev-2"]
    entry["last_seen"] = entry["last_seen"] - 5
    listed = store.list_devices()[0]
    assert listed["online"] is False
    assert listed["active"] is False


def test_monitor_api_register_heartbeat_list() -> None:
    client = TestClient(app)
    reg = client.post(
        "/api/monitor/register",
        json={"device_id": "api-1", "device_name": "Test Phone", "model": "SM-A"},
    )
    assert reg.status_code == 200
    assert reg.json()["ok"] is True

    hb = client.post(
        "/api/monitor/heartbeat",
        json={
            "device_id": "api-1",
            "device_name": "Test Phone",
            "active": True,
            "battery_percent": 72.5,
            "charging": False,
            "app_state": "foreground",
            "network": {
                "connected": True,
                "transport": "wifi",
                "internet": True,
                "validated_internet": True,
            },
            "storage": {
                "total_bytes": 64_000_000_000,
                "free_bytes": 8_000_000_000,
                "used_bytes": 56_000_000_000,
                "free_percent": 12.5,
                "low_storage": False,
            },
            "memory": {
                "total_bytes": 4_000_000_000,
                "available_bytes": 1_200_000_000,
                "available_percent": 30.0,
                "low_memory": False,
                "app_used_bytes": 80_000_000,
            },
            "thermal": {
                "battery_temp_c": 32.5,
                "thermal_status": "none",
                "overheating": False,
            },
            "test_execution": {
                "state": "idle",
                "current_test": None,
                "current_suite": None,
                "failures": 0,
                "duration_sec": 0,
            },
        },
    )
    assert hb.status_code == 200
    body = hb.json()["device"]
    assert body["battery_percent"] == 72.5
    assert body["online"] is True
    assert body["network"]["transport"] == "wifi"
    assert body["storage"]["low_storage"] is False
    assert body["memory"]["low_memory"] is False
    assert body["thermal"]["battery_temp_c"] == 32.5
    assert body["test_execution"]["state"] == "idle"

    listed = client.get("/api/monitor/devices")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["count"] >= 1
    ids = {d["device_id"] for d in payload["devices"]}
    assert "api-1" in ids
