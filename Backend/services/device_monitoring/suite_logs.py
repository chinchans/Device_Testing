"""Finished suite logs uploaded by the phone. The file stays on disk; the device record keeps only a pointer."""

from __future__ import annotations

import gzip
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any


MAX_GZIP_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 1_500_000


def default_dir() -> Path:
    raw = os.getenv("MONITOR_LOG_DIR")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "data" / "monitor_logs"


class SuiteLogStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(
        self,
        *,
        device_id: str,
        feature: str,
        suite: str,
        file_name: str,
        started_at_ms: int,
        gzip_bytes: bytes,
    ) -> dict[str, Any]:
        if not gzip_bytes:
            raise ValueError("empty log")
        if len(gzip_bytes) > MAX_GZIP_BYTES:
            raise ValueError("log is too large")
        text = _gunzip(gzip_bytes)
        log_id = uuid.uuid4().hex
        path = self.root / f"{log_id}.gz"
        path.write_bytes(gzip_bytes)
        meta = {
            "id": log_id,
            "device_id": device_id,
            "feature": feature or "",
            "suite": suite or "suite",
            "file_name": file_name or f"{log_id}.txt",
            "bytes": len(text.encode("utf-8")),
            "saved_at": time.time(),
            "started_at_ms": started_at_ms,
        }
        return meta

    def read_text(self, log_id: str) -> str | None:
        if not log_id or "/" in log_id or ".." in log_id:
            return None
        path = self.root / f"{log_id}.gz"
        if not path.is_file():
            return None
        with self._lock:
            raw = path.read_bytes()
        text = _gunzip(raw)
        if len(text) > MAX_TEXT_CHARS:
            return text[:MAX_TEXT_CHARS] + "\n\n… log truncated for display …\n"
        return text


def _gunzip(raw: bytes) -> str:
    try:
        data = gzip.decompress(raw)
    except OSError as exc:
        raise ValueError("log is not gzip") from exc
    return data.decode("utf-8", errors="replace")


suite_log_store = SuiteLogStore()
