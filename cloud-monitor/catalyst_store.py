"""Catalyst Data Store backend (optional).

Used when MONITOR_STORE=catalyst inside Catalyst AppSail / Functions.
Requires table `Devices` created in Cloud Scale → Data Store (see DATASTORE_SETUP.md).

Local PC without Catalyst credentials should keep MONITOR_STORE=sqlite.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from store import HEALTH_KEYS, _merge_heartbeat, _public

logger = logging.getLogger(__name__)

TABLE_NAME = os.getenv("MONITOR_DEVICES_TABLE") or os.getenv(
    "CATALYST_DEVICES_TABLE", "Devices"
)


class CatalystStore:
    """Upsert device snapshots into Catalyst Data Store table `Devices`."""

    def __init__(self, offline_after_sec: float = 90.0) -> None:
        self.offline_after_sec = offline_after_sec
        self.backend = "catalyst"
        try:
            import zcatalyst_sdk

            self._app = zcatalyst_sdk.initialize()
            self._table = self._app.datastore().table(TABLE_NAME)
        except Exception as exc:  # pragma: no cover - depends on Catalyst runtime
            raise RuntimeError(
                "Catalyst Data Store unavailable. Use MONITOR_STORE=sqlite locally, "
                "or deploy to AppSail after creating the Devices table."
            ) from exc

    def _find_row(self, device_id: str) -> dict[str, Any] | None:
        # Prefer ZCQL when available; fall back to scanning get_paged_rows if present.
        try:
            zcql = self._app.zcql()
            safe_id = device_id.replace("'", "''")
            result = zcql.execute_query(
                f"SELECT ROWID, device_id, payload FROM {TABLE_NAME} "
                f"WHERE device_id = '{safe_id}'"
            )
            if result:
                row = result[0].get(TABLE_NAME) or result[0]
                return row
        except Exception as exc:
            logger.warning("ZCQL lookup failed: %s", exc)
        return None

    def _payload_from_row(self, row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        raw = row.get("payload")
        if isinstance(raw, str) and raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        if isinstance(raw, dict):
            return raw
        return {}

    def _upsert(self, entry: dict[str, Any], existing_row: dict[str, Any] | None) -> None:
        body = {
            "device_id": entry["device_id"],
            "device_name": entry.get("device_name") or entry["device_id"],
            "last_seen": float(entry.get("last_seen") or 0),
            "payload": json.dumps(entry),
        }
        if existing_row and existing_row.get("ROWID"):
            body["ROWID"] = existing_row["ROWID"]
            self._table.update_row(body)
        else:
            self._table.insert_row(body)

    def register(
        self,
        device_id: str,
        device_name: str,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        row = self._find_row(device_id)
        existing = self._payload_from_row(row)
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
        self._upsert(entry, row)
        return _public(entry, now, self.offline_after_sec)

    def heartbeat(self, device_id: str, **kwargs: Any) -> dict[str, Any]:
        now = time.time()
        row = self._find_row(device_id)
        existing = self._payload_from_row(row) or {"device_id": device_id}
        entry = _merge_heartbeat(existing, device_id=device_id, now=now, **kwargs)
        self._upsert(entry, row)
        return _public(entry, now, self.offline_after_sec)

    def list_devices(self) -> list[dict[str, Any]]:
        now = time.time()
        devices: list[dict[str, Any]] = []
        try:
            zcql = self._app.zcql()
            result = zcql.execute_query(
                f"SELECT ROWID, device_id, payload FROM {TABLE_NAME}"
            )
            for item in result or []:
                row = item.get(TABLE_NAME) or item
                entry = self._payload_from_row(row)
                if entry.get("device_id"):
                    devices.append(_public(entry, now, self.offline_after_sec))
        except Exception as exc:
            logger.warning("list_devices failed: %s", exc)
        devices.sort(key=lambda d: d.get("device_name") or d["device_id"])
        return devices

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        now = time.time()
        row = self._find_row(device_id)
        entry = self._payload_from_row(row)
        if not entry:
            return None
        return _public(entry, now, self.offline_after_sec)
