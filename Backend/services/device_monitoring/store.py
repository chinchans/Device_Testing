"""Thread-safe in-memory store for device heartbeats and health metrics."""

from __future__ import annotations

import threading
import time
from typing import Any


HEALTH_KEYS = ("network", "storage", "memory", "thermal", "test_execution")


class DeviceMonitorStore:
    """Keeps the latest status for each enrolled device."""

    def __init__(self, offline_after_sec: float = 90.0) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, dict[str, Any]] = {}
        self.offline_after_sec = offline_after_sec

    def register(
        self,
        device_id: str,
        device_name: str,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            existing = self._devices.get(device_id) or {}
            entry = {
                **existing,
                "device_id": device_id,
                "device_name": device_name or existing.get("device_name") or device_id,
                "model": model if model is not None else existing.get("model"),
                "active": True,
                "battery_percent": existing.get("battery_percent"),
                "charging": existing.get("charging"),
                "app_state": existing.get("app_state") or "registered",
                "registered_at": existing.get("registered_at") or now,
                "last_seen": now,
                "heartbeat_count": int(existing.get("heartbeat_count") or 0),
            }
            for key in HEALTH_KEYS:
                if key not in entry:
                    entry[key] = existing.get(key)
            self._devices[device_id] = entry
            return self._public(entry, now)

    def heartbeat(
        self,
        device_id: str,
        *,
        device_name: str | None = None,
        active: bool = True,
        battery_percent: float | None = None,
        charging: bool | None = None,
        app_state: str | None = None,
        network: dict[str, Any] | None = None,
        storage: dict[str, Any] | None = None,
        memory: dict[str, Any] | None = None,
        thermal: dict[str, Any] | None = None,
        test_execution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        health = {
            "network": network,
            "storage": storage,
            "memory": memory,
            "thermal": thermal,
            "test_execution": test_execution,
        }
        with self._lock:
            existing = self._devices.get(device_id) or {
                "device_id": device_id,
                "registered_at": now,
                "heartbeat_count": 0,
            }
            entry = {
                **existing,
                "device_id": device_id,
                "device_name": device_name
                or existing.get("device_name")
                or device_id,
                "active": bool(active),
                "battery_percent": (
                    battery_percent
                    if battery_percent is not None
                    else existing.get("battery_percent")
                ),
                "charging": (
                    charging if charging is not None else existing.get("charging")
                ),
                "app_state": app_state or existing.get("app_state") or "foreground",
                "last_seen": now,
                "heartbeat_count": int(existing.get("heartbeat_count") or 0) + 1,
            }
            for key, value in health.items():
                entry[key] = value if value is not None else existing.get(key)
            self._devices[device_id] = entry
            return self._public(entry, now)

    def list_devices(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            devices = [self._public(entry, now) for entry in self._devices.values()]
        devices.sort(key=lambda d: d.get("device_name") or d["device_id"])
        return devices

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            entry = self._devices.get(device_id)
            if entry is None:
                return None
            return self._public(entry, now)

    def _public(self, entry: dict[str, Any], now: float) -> dict[str, Any]:
        last_seen = float(entry.get("last_seen") or 0)
        age = max(0.0, now - last_seen)
        online = age <= self.offline_after_sec
        out: dict[str, Any] = {
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
            "offline_after_sec": self.offline_after_sec,
        }
        for key in HEALTH_KEYS:
            out[key] = entry.get(key)
        return out


monitor_store = DeviceMonitorStore()
