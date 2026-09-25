"""Embedding generation with batching and content-hash caching."""

from __future__ import annotations

import hashlib
import json
import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from core.config import get_settings
from core.schemas import Chunk
from llm.azure_client import embed_texts
from observability.logging import logger


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimensions(self) -> int:
        raise NotImplementedError


class HashingEmbedder(Embedder):
    """Deterministic local embedder for offline/dev when Azure embeddings are unavailable."""

    def __init__(self, dimensions: int = 384):
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dimensions
        tokens = text.lower().split()
        if not tokens:
            return vec
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dimensions
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
            # bigrams
        for i in range(len(tokens) - 1):
            bigram = f"{tokens[i]}_{tokens[i+1]}"
            h = int(hashlib.md5(bigram.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dimensions
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += 0.5 * sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class AzureEmbedder(Embedder):
    def __init__(self, deployment: str, dimensions: int = 1536):
        self.deployment = deployment
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return embed_texts(texts, deployment=self.deployment)


def get_embedder() -> Embedder:
    settings = get_settings()
    provider = (settings.models.embedding_provider or "azure").lower()
    if provider == "hashing" or not settings.azure_embedding_deployment:
        if provider != "hashing":
            logger.warning(
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT not set — using HashingEmbedder. "
                "Set EMBEDDING_PROVIDER=azure and AZURE_OPENAI_EMBEDDING_DEPLOYMENT for production."
            )
        return HashingEmbedder(dimensions=min(384, settings.models.embedding_dimensions))
    return AzureEmbedder(
        deployment=settings.azure_embedding_deployment,
        dimensions=settings.models.embedding_dimensions,
    )


class EmbeddingCache:
    def __init__(self, cache_dir: Path | None = None):
        settings = get_settings()
        self.cache_dir = cache_dir or (settings.cache_path / "embeddings")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, text: str, provider: str) -> str:
        h = hashlib.sha256(f"{provider}::{text}".encode("utf-8")).hexdigest()
        return h

    def get(self, text: str, provider: str) -> list[float] | None:
        path = self.cache_dir / f"{self._key(text, provider)}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def set(self, text: str, provider: str, embedding: list[float]) -> None:
        path = self.cache_dir / f"{self._key(text, provider)}.json"
        path.write_text(json.dumps(embedding), encoding="utf-8")


def embed_chunks(chunks: list[Chunk], embedder: Embedder | None = None) -> list[Chunk]:
    settings = get_settings()
    embedder = embedder or get_embedder()
    cache = EmbeddingCache()
    provider = type(embedder).__name__
    batch_size = settings.indexing.embedding_batch_size

    pending_idx: list[int] = []
    pending_texts: list[str] = []

    for i, chunk in enumerate(chunks):
        cached = cache.get(chunk.text, provider)
        if cached is not None:
            chunk.embedding = cached
        else:
            pending_idx.append(i)
            pending_texts.append(chunk.text)

    for start in range(0, len(pending_texts), batch_size):
        batch_texts = pending_texts[start : start + batch_size]
        batch_idx = pending_idx[start : start + batch_size]
        vectors = embedder.embed(batch_texts)
        for j, vec in enumerate(vectors):
            chunks[batch_idx[j]].embedding = vec
            cache.set(batch_texts[j], provider, vec)

    logger.info(
        "Embedded %d chunks (%d cache hits, %d new)",
        len(chunks),
        len(chunks) - len(pending_texts),
        len(pending_texts),
    )
    return chunks
