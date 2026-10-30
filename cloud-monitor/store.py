"""Device monitor storage backends.

Stage 2 default: SQLite (persists across restarts).
Optional: memory | catalyst (Catalyst Data Store when deployed / configured).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Protocol

HEALTH_KEYS = ("network", "storage", "memory", "thermal", "test_execution")


class MonitorStore(Protocol):
    offline_after_sec: float

    def register(
        self,
        device_id: str,
        device_name: str,
        *,
        model: str | None = None,
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def list_devices(self) -> list[dict[str, Any]]: ...

    def get_device(self, device_id: str) -> dict[str, Any] | None: ...


def _public(entry: dict[str, Any], now: float, offline_after_sec: float) -> dict[str, Any]:
    last_seen = float(entry.get("last_seen") or 0)
    age = max(0.0, now - last_seen)
    online = age <= offline_after_sec
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
        "offline_after_sec": offline_after_sec,
    }
    for key in HEALTH_KEYS:
        out[key] = entry.get(key)
    return out


def _merge_heartbeat(
    existing: dict[str, Any],
    *,
    device_id: str,
    device_name: str | None,
    active: bool,
    battery_percent: float | None,
    charging: bool | None,
    app_state: str | None,
    network: dict[str, Any] | None,
    storage: dict[str, Any] | None,
    memory: dict[str, Any] | None,
    thermal: dict[str, Any] | None,
    test_execution: dict[str, Any] | None,
    now: float,
) -> dict[str, Any]:
    health = {
        "network": network,
        "storage": storage,
        "memory": memory,
        "thermal": thermal,
        "test_execution": test_execution,
    }
    entry = {
        **existing,
        "device_id": device_id,
        "device_name": device_name or existing.get("device_name") or device_id,
        "active": bool(active),
        "battery_percent": (
            battery_percent
            if battery_percent is not None
            else existing.get("battery_percent")
        ),
        "charging": charging if charging is not None else existing.get("charging"),
        "app_state": app_state or existing.get("app_state") or "foreground",
        "last_seen": now,
        "heartbeat_count": int(existing.get("heartbeat_count") or 0) + 1,
        "registered_at": existing.get("registered_at") or now,
        "model": existing.get("model"),
    }
    for key, value in health.items():
        entry[key] = value if value is not None else existing.get(key)
    return entry


class MemoryStore:
    """Stage 1 in-memory backend."""

    def __init__(self, offline_after_sec: float = 90.0) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, dict[str, Any]] = {}
        self.offline_after_sec = offline_after_sec
        self.backend = "memory"

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
                entry.setdefault(key, existing.get(key))
            self._devices[device_id] = entry
            return _public(entry, now, self.offline_after_sec)

    def heartbeat(self, device_id: str, **kwargs: Any) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            existing = self._devices.get(device_id) or {"device_id": device_id}
            entry = _merge_heartbeat(existing, device_id=device_id, now=now, **kwargs)
            self._devices[device_id] = entry
            return _public(entry, now, self.offline_after_sec)

    def list_devices(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            devices = [
                _public(entry, now, self.offline_after_sec)
                for entry in self._devices.values()
            ]
        devices.sort(key=lambda d: d.get("device_name") or d["device_id"])
        return devices

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            entry = self._devices.get(device_id)
            if entry is None:
                return None
            return _public(entry, now, self.offline_after_sec)


class SqliteStore:
    """Stage 2 persistent backend — one row per device_id (upsert)."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        offline_after_sec: float = 90.0,
    ) -> None:
        self.offline_after_sec = offline_after_sec
        self.backend = "sqlite"
        root = Path(__file__).resolve().parent
        preferred = Path(
            db_path
            or os.getenv("MONITOR_DB_PATH")
            or (root / "data" / "devices.db")
        )
        # AppSail app dirs can be read-only; fall back to /tmp.
        self.db_path = preferred
        self._lock = threading.Lock()
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
        except OSError:
            self.db_path = Path("/tmp/device-monitor-devices.db")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS devices (
                        device_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _read(self, conn: sqlite3.Connection, device_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT payload FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    def _write(self, conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO devices (device_id, payload) VALUES (?, ?)
            ON CONFLICT(device_id) DO UPDATE SET payload = excluded.payload
            """,
            (entry["device_id"], json.dumps(entry)),
        )

    def register(
        self,
        device_id: str,
        device_name: str,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                existing = self._read(conn, device_id) or {}
                entry = {
                    **existing,
                    "device_id": device_id,
                    "device_name": device_name
                    or existing.get("device_name")
                    or device_id,
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
                    entry.setdefault(key, existing.get(key))
                self._write(conn, entry)
                conn.commit()
                return _public(entry, now, self.offline_after_sec)
            finally:
                conn.close()

    def heartbeat(self, device_id: str, **kwargs: Any) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                existing = self._read(conn, device_id) or {"device_id": device_id}
                entry = _merge_heartbeat(existing, device_id=device_id, now=now, **kwargs)
                self._write(conn, entry)
                conn.commit()
                return _public(entry, now, self.offline_after_sec)
            finally:
                conn.close()

    def list_devices(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT payload FROM devices").fetchall()
            finally:
                conn.close()
        devices = [
            _public(json.loads(row["payload"]), now, self.offline_after_sec)
            for row in rows
        ]
        devices.sort(key=lambda d: d.get("device_name") or d["device_id"])
        return devices

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                entry = self._read(conn, device_id)
            finally:
                conn.close()
        if entry is None:
            return None
        return _public(entry, now, self.offline_after_sec)


def get_store() -> Any:
    """Select backend via MONITOR_STORE=sqlite|memory|catalyst (default sqlite).

    Catalyst init must never block AppSail port bind — fall back to sqlite on failure.
    """
    kind = (os.getenv("MONITOR_STORE") or "sqlite").strip().lower()
    offline = float(os.getenv("MONITOR_OFFLINE_AFTER_SEC") or "90")
    if kind == "memory":
        return MemoryStore(offline_after_sec=offline)
    if kind == "catalyst":
        try:
            from catalyst_store import CatalystStore

            return CatalystStore(offline_after_sec=offline)
        except Exception as exc:  # pragma: no cover - runtime/credential dependent
            import logging

            logging.getLogger(__name__).exception(
                "Catalyst store unavailable (%s); falling back to sqlite", exc
            )
            return SqliteStore(offline_after_sec=offline)
    return SqliteStore(offline_after_sec=offline)


_monitor_store: Any | None = None


def monitor_store() -> Any:
    """Lazy singleton so AppSail can bind the listen port before store init."""
    global _monitor_store
    if _monitor_store is None:
        _monitor_store = get_store()
    return _monitor_store
