"""Application settings loaded from YAML + environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


class IndexingConfig(BaseModel):
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 64
    child_chunk_max_tokens: int = 256
    embedding_batch_size: int = 32
    ocr_enabled: bool = True
    ocr_min_chars_per_page: int = 40
    # If checklist standard_total − standard_found exceeds this, reindex with force OCR.
    ocr_retry_missing_standards: int = 3
    # After parse/OCR + chrome strip, LLM reframes text into RAG-friendly modules.
    llm_rag_normalize: bool = True
    llm_normalize_max_chars_per_call: int = 10000
    # Bump when index semantics change so content-hash cache is invalidated.
    index_pipeline_version: int = 4


class RetrievalConfig(BaseModel):
    vector_top_n: int = 20
    bm25_top_n: int = 20
    rrf_k: int = 60
    rerank_input_n: int = 30
    rerank_top_k: int = 8
    neighbor_window: int = 1
    expand_parent: bool = True


class AgentsConfig(BaseModel):
    max_retries: int = 2
    section_concurrency: int = 4
    cheap_model_temperature: float = 0.0
    extraction_temperature: float = 0.0
    max_evidence_chars: int = 12000


class ObservabilityConfig(BaseModel):
    debug_mode: bool = True
    log_dir: str = "data/logs"
    trace_dir: str = "data/traces"


class PathsConfig(BaseModel):
    uploads_dir: str = "data/uploads"
    documents_dir: str = "data/documents"
    cache_dir: str = "data/cache"
    indexes_dir: str = "data/indexes"


class ModelsConfig(BaseModel):
    extraction_deployment: str | None = None
    cheap_deployment: str | None = None
    embedding_provider: str = "azure"
    embedding_dimensions: int = 1536
    reranker_provider: str = "llm"


class Settings(BaseModel):
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_api_version: str = "2024-10-21"
    azure_deployment: str = "gpt-4.1-mini"
    azure_embedding_deployment: str = ""

    def resolve_path(self, relative: str) -> Path:
        p = Path(relative)
        if p.is_absolute():
            return p
        return (BACKEND_ROOT / p).resolve()

    @property
    def uploads_path(self) -> Path:
        return self.resolve_path(self.paths.uploads_dir)

    @property
    def documents_path(self) -> Path:
        return self.resolve_path(self.paths.documents_dir)

    @property
    def cache_path(self) -> Path:
        return self.resolve_path(self.paths.cache_dir)

    @property
    def indexes_path(self) -> Path:
        return self.resolve_path(self.paths.indexes_dir)

    @property
    def logs_path(self) -> Path:
        return self.resolve_path(self.observability.log_dir)

    @property
    def traces_path(self) -> Path:
        return self.resolve_path(self.observability.trace_dir)

    @property
    def extraction_model(self) -> str:
        return self.models.extraction_deployment or self.azure_deployment

    @property
    def cheap_model(self) -> str:
        return self.models.cheap_deployment or self.azure_deployment


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml() -> dict[str, Any]:
    cfg_path = BACKEND_ROOT / "config" / "default.yaml"
    if not cfg_path.exists():
        return {}
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(BACKEND_ROOT / ".env")

    raw = _load_yaml()
    settings = Settings.model_validate(raw)

    settings.api_host = os.getenv("API_HOST", settings.api_host)
    settings.api_port = int(os.getenv("API_PORT", str(settings.api_port)))
    settings.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", settings.azure_endpoint).rstrip("/")
    settings.azure_api_key = os.getenv("AZURE_OPENAI_API_KEY", settings.azure_api_key)
    settings.azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", settings.azure_api_version)
    settings.azure_deployment = (
        os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_MODEL_NAME")
        or settings.azure_deployment
    )
    settings.azure_embedding_deployment = os.getenv(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", settings.azure_embedding_deployment
    )
    if os.getenv("EMBEDDING_PROVIDER"):
        settings.models.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "azure")
    if os.getenv("RERANKER_PROVIDER"):
        settings.models.reranker_provider = os.getenv("RERANKER_PROVIDER", "llm")
    if os.getenv("DEBUG_MODE", "").lower() in {"1", "true", "yes"}:
        settings.observability.debug_mode = True

    for path in (
        settings.uploads_path,
        settings.documents_path,
        settings.cache_path,
        settings.indexes_path,
        settings.logs_path,
        settings.traces_path,
    ):
        path.mkdir(parents=True, exist_ok=True)

    return settings
