"""BM25 sparse index aligned to the same chunk IDs as the vector store."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.schemas import Chunk, ChunkMetadata
from observability.logging import logger

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover
    BM25Okapi = None


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\.\+\-/]*")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


class BM25Store:
    def __init__(self, document_id: str, indexes_dir: Path | None = None):
        settings = get_settings()
        self.document_id = document_id
        self.root = (indexes_dir or settings.indexes_path) / document_id / "bm25"
        self.root.mkdir(parents=True, exist_ok=True)
        self._ids: list[str] = []
        self._corpus_tokens: list[list[str]] = []
        self._meta: dict[str, dict[str, Any]] = {}
        self._texts: dict[str, str] = {}
        self._bm25: Any = None

    @property
    def size(self) -> int:
        return len(self._ids)

    def add_chunks(self, chunks: list[Chunk]) -> None:
        self._ids = []
        self._corpus_tokens = []
        self._meta = {}
        self._texts = {}
        for ch in chunks:
            self._ids.append(ch.chunk_id)
            self._corpus_tokens.append(tokenize(ch.text))
            self._meta[ch.chunk_id] = ch.metadata.model_dump()
            self._texts[ch.chunk_id] = ch.text
        self._rebuild()
        self.persist()

    def _rebuild(self) -> None:
        if BM25Okapi is None:
            raise RuntimeError("rank_bm25 is required. pip install rank-bm25")
        if not self._corpus_tokens:
            self._bm25 = None
            return
        self._bm25 = BM25Okapi(self._corpus_tokens)

    def persist(self) -> None:
        (self.root / "ids.json").write_text(json.dumps(self._ids), encoding="utf-8")
        (self.root / "tokens.json").write_text(json.dumps(self._corpus_tokens), encoding="utf-8")
        (self.root / "meta.json").write_text(json.dumps(self._meta), encoding="utf-8")
        (self.root / "texts.json").write_text(json.dumps(self._texts), encoding="utf-8")

    def load(self) -> bool:
        ids_path = self.root / "ids.json"
        if not ids_path.exists():
            return False
        self._ids = json.loads(ids_path.read_text(encoding="utf-8"))
        self._corpus_tokens = json.loads((self.root / "tokens.json").read_text(encoding="utf-8"))
        self._meta = json.loads((self.root / "meta.json").read_text(encoding="utf-8"))
        self._texts = json.loads((self.root / "texts.json").read_text(encoding="utf-8"))
        self._rebuild()
        return True

    def search(
        self,
        query: str,
        top_n: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]:
        if self._bm25 is None or not self._ids:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        candidate_indices = list(range(len(self._ids)))
        if filters:
            candidate_indices = [
                i for i in candidate_indices if self._match_filters(self._ids[i], filters)
            ]
        scored = [(self._ids[i], float(scores[i])) for i in candidate_indices]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Drop zero-score noise unless everything is zero
        nonzero = [s for s in scored if s[1] > 0]
        ranked = nonzero if nonzero else scored
        return ranked[:top_n]

    def _match_filters(self, chunk_id: str, filters: dict[str, Any]) -> bool:
        meta = self._meta.get(chunk_id) or {}
        for k, v in filters.items():
            if v is None:
                continue
            mv = meta.get(k)
            if k == "section" and isinstance(v, str):
                section = ((mv or "") + " " + (meta.get("subsection") or "")).lower()
                vl = v.lower()
                if vl not in section and section.strip() not in vl:
                    if vl != (mv or "").lower() and vl != (meta.get("subsection") or "").lower():
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
