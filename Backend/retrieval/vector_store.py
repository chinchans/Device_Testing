"""Dense vector index (numpy cosine) shared chunk IDs with BM25."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from core.config import get_settings
from core.schemas import Chunk, ChunkMetadata
from observability.logging import logger


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return mat / norms


class VectorStore:
    def __init__(self, document_id: str, indexes_dir: Path | None = None):
        settings = get_settings()
        self.document_id = document_id
        self.root = (indexes_dir or settings.indexes_path) / document_id / "vector"
        self.root.mkdir(parents=True, exist_ok=True)
        self._matrix: np.ndarray | None = None
        self._ids: list[str] = []
        self._meta: dict[str, dict[str, Any]] = {}
        self._texts: dict[str, str] = {}

    @property
    def size(self) -> int:
        return len(self._ids)

    def add_chunks(self, chunks: list[Chunk]) -> None:
        vectors: list[list[float]] = []
        ids: list[str] = []
        for ch in chunks:
            if not ch.embedding:
                continue
            ids.append(ch.chunk_id)
            vectors.append(ch.embedding)
            self._meta[ch.chunk_id] = ch.metadata.model_dump()
            self._texts[ch.chunk_id] = ch.text
        if not vectors:
            logger.warning("No embeddings to index for %s", self.document_id)
            return
        mat = _l2_normalize(np.asarray(vectors, dtype=np.float32))
        self._matrix = mat
        self._ids = ids
        self.persist()

    def persist(self) -> None:
        if self._matrix is None:
            return
        np.save(self.root / "embeddings.npy", self._matrix)
        (self.root / "ids.json").write_text(json.dumps(self._ids), encoding="utf-8")
        (self.root / "meta.json").write_text(json.dumps(self._meta), encoding="utf-8")
        (self.root / "texts.json").write_text(json.dumps(self._texts), encoding="utf-8")

    def load(self) -> bool:
        emb_path = self.root / "embeddings.npy"
        if not emb_path.exists():
            return False
        self._matrix = np.load(emb_path)
        self._ids = json.loads((self.root / "ids.json").read_text(encoding="utf-8"))
        self._meta = json.loads((self.root / "meta.json").read_text(encoding="utf-8"))
        self._texts = json.loads((self.root / "texts.json").read_text(encoding="utf-8"))
        return True

    def search(
        self,
        query_embedding: list[float],
        top_n: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]:
        if self._matrix is None or not self._ids:
            return []
        q = np.asarray(query_embedding, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        scores = self._matrix @ q
        # Apply metadata filters by masking
        candidate_indices = list(range(len(self._ids)))
        if filters:
            candidate_indices = [
                i for i in candidate_indices if self._match_filters(self._ids[i], filters)
            ]
        if not candidate_indices:
            return []
        scored = [(self._ids[i], float(scores[i])) for i in candidate_indices]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    def _match_filters(self, chunk_id: str, filters: dict[str, Any]) -> bool:
        meta = self._meta.get(chunk_id) or {}
        for k, v in filters.items():
            if v is None:
                continue
            mv = meta.get(k)
            if k == "section" and isinstance(v, str):
                # Case-insensitive containment for section filtering
                section = (mv or "") + " " + (meta.get("subsection") or "")
                if v.lower() not in section.lower() and section.lower() not in v.lower():
                    # allow exact-ish match on either field
                    if v.lower() != (mv or "").lower() and v.lower() != (meta.get("subsection") or "").lower():
                        return False
            elif mv != v:
                return False
        return True

    def get_text(self, chunk_id: str) -> str:
        return self._texts.get(chunk_id, "")

    def get_metadata(self, chunk_id: str) -> ChunkMetadata | None:
        raw = self._meta.get(chunk_id)
        if not raw:
            return None
        return ChunkMetadata.model_validate(raw)
