"""Observability: structured logging and per-query traces."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.config import get_settings


def setup_logging() -> logging.Logger:
    settings = get_settings()
    settings.logs_path.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("agentic_rag")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if settings.observability.debug_mode else logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    fh = logging.FileHandler(settings.logs_path / "agentic_rag.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


logger = setup_logging()


@dataclass
class TraceRecorder:
    query_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    query: str = ""
    document_id: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def log(self, stage: str, payload: dict[str, Any] | None = None) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "payload": payload or {},
        }
        self.events.append(event)
        logger.debug("[%s] %s %s", self.query_id[:8], stage, json.dumps(payload or {}, default=str)[:500])

    def add_metric(
        self,
        stage: str,
        latency_ms: float,
        token_usage: dict[str, int] | None = None,
        **extra: Any,
    ) -> None:
        self.metrics.append(
            {
                "stage": stage,
                "latency_ms": latency_ms,
                "token_usage": token_usage or {},
                "extra": extra,
            }
        )

    @contextmanager
    def timed(self, stage: str, **extra: Any) -> Iterator[dict[str, Any]]:
        box: dict[str, Any] = {"token_usage": {}}
        t0 = time.perf_counter()
        try:
            yield box
        finally:
            latency = (time.perf_counter() - t0) * 1000
            self.add_metric(stage, latency, box.get("token_usage"), **extra)
            self.log(stage, {"latency_ms": latency, **extra, "token_usage": box.get("token_usage")})

    def persist(self) -> Path:
        settings = get_settings()
        settings.traces_path.mkdir(parents=True, exist_ok=True)
        path = settings.traces_path / f"trace_{self.query_id}.json"
        payload = {
            "query_id": self.query_id,
            "query": self.query,
            "document_id": self.document_id,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "events": self.events,
            "metrics": self.metrics,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path
