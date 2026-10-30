"""Request-scoped Catalyst app holder for AppSail."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_catalyst_app: ContextVar[Any | None] = ContextVar("catalyst_app", default=None)


def set_catalyst_app(app: Any | None) -> None:
    _catalyst_app.set(app)


def get_catalyst_app() -> Any | None:
    return _catalyst_app.get()
