"""Parent / neighbor context expansion after reranking."""

from __future__ import annotations

from core.config import get_settings
from core.schemas import RetrievedCandidate
from retrieval.bm25_store import BM25Store
from retrieval.vector_store import VectorStore


class ContextExpander:
    def __init__(self, vector_store: VectorStore, bm25_store: BM25Store):
        self.vector_store = vector_store
        self.bm25_store = bm25_store
        self.settings = get_settings()

    def _lookup(self, chunk_id: str | None) -> RetrievedCandidate | None:
        if not chunk_id:
            return None
        meta = self.vector_store.get_metadata(chunk_id) or self.bm25_store.get_metadata(chunk_id)
        text = self.vector_store.get_text(chunk_id) or self.bm25_store.get_text(chunk_id)
        if not meta or not text:
            return None
        return RetrievedCandidate(chunk_id=chunk_id, text=text, metadata=meta)

    def expand(self, ranked: list[RetrievedCandidate]) -> list[RetrievedCandidate]:
        cfg = self.settings.retrieval
        seen: set[str] = set()
        out: list[RetrievedCandidate] = []

        def _add(c: RetrievedCandidate | None) -> None:
            if c is None or c.chunk_id in seen:
                return
            seen.add(c.chunk_id)
            out.append(c)

        for c in ranked:
            _add(c)
            if cfg.expand_parent and c.metadata.parent_chunk_id:
                _add(self._lookup(c.metadata.parent_chunk_id))
            # neighbors
            cur = c
            for _ in range(cfg.neighbor_window):
                nxt = self._lookup(cur.metadata.next_chunk_id)
                if nxt:
                    _add(nxt)
                    cur = nxt
                else:
                    break
            cur = c
            for _ in range(cfg.neighbor_window):
                prev = self._lookup(cur.metadata.prev_chunk_id)
                if prev:
                    _add(prev)
                    cur = prev
                else:
                    break

        return out
