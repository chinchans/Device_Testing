"""Device Testing — Agentic RAG API entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure Backend/ is on sys.path when launched as `python main.py` or `uvicorn main:app`
BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from core.config import get_settings
from observability.logging import setup_logging

setup_logging()
settings = get_settings()

app = FastAPI(
    title="Device Testing — Agentic RAG",
    version="1.0.0",
    description=(
        "Generic, device-agnostic Agentic RAG for extracting features and "
        "specifications from arbitrary product specification documents."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
