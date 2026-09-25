"""Hybrid dense + BM25 retrieval with RRF fusion."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.config import get_settings
from core.schemas import RetrievedCandidate
from indexing.embedder import Embedder, get_embedder
from observability.logging import logger
from retrieval.bm25_store import BM25Store
from retrieval.rrf import reciprocal_rank_fusion
from retrieval.vector_store import VectorStore


class HybridRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        bm25_store: BM25Store,
        embedder: Embedder | None = None,
    ):
        self.vector_store = vector_store
        self.bm25_store = bm25_store
        self.embedder = embedder or get_embedder()
        self.settings = get_settings()

    def retrieve(
        self,
        queries: list[str],
        *,
        filters: dict[str, Any] | None = None,
        vector_top_n: int | None = None,
        bm25_top_n: int | None = None,
        rrf_k: int | None = None,
    ) -> tuple[list[RetrievedCandidate], dict[str, Any]]:
        """Run vector + BM25 in parallel for each query, fuse with RRF."""
        cfg = self.settings.retrieval
        vector_top_n = vector_top_n or cfg.vector_top_n
        bm25_top_n = bm25_top_n or cfg.bm25_top_n
        rrf_k = rrf_k or cfg.rrf_k

        all_vector_lists: list[list[str]] = []
        all_bm25_lists: list[list[str]] = []
        debug_vector: list[dict[str, Any]] = []
        debug_bm25: list[dict[str, Any]] = []

        for query in queries:
            q_emb = self.embedder.embed([query])[0]

            def _vec() -> list[tuple[str, float]]:
                return self.vector_store.search(q_emb, top_n=vector_top_n, filters=filters)

            def _bm() -> list[tuple[str, float]]:
                return self.bm25_store.search(query, top_n=bm25_top_n, filters=filters)

            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_v = pool.submit(_vec)
                fut_b = pool.submit(_bm)
                vec_hits = fut_v.result()
                bm_hits = fut_b.result()

            all_vector_lists.append([cid for cid, _ in vec_hits])
            all_bm25_lists.append([cid for cid, _ in bm_hits])
            debug_vector.append({"query": query, "hits": [{"chunk_id": c, "score": s} for c, s in vec_hits]})
            debug_bm25.append({"query": query, "hits": [{"chunk_id": c, "score": s} for c, s in bm_hits]})

        fused = reciprocal_rank_fusion(all_vector_lists + all_bm25_lists, k=rrf_k)

        # Build rank maps for first query pair (informative)
        vector_rank = {cid: i + 1 for i, cid in enumerate(all_vector_lists[0] if all_vector_lists else [])}
        bm25_rank = {cid: i + 1 for i, cid in enumerate(all_bm25_lists[0] if all_bm25_lists else [])}

        candidates: list[RetrievedCandidate] = []
        for cid, score in fused:
            meta = self.vector_store.get_metadata(cid) or self.bm25_store.get_metadata(cid)
            text = self.vector_store.get_text(cid) or self.bm25_store.get_text(cid)
            if not meta or not text:
                continue
            candidates.append(
                RetrievedCandidate(
                    chunk_id=cid,
                    text=text,
                    metadata=meta,
                    vector_rank=vector_rank.get(cid),
                    bm25_rank=bm25_rank.get(cid),
                    rrf_score=score,
                )
            )

        debug = {
            "queries": queries,
            "filters": filters,
            "vector": debug_vector,
            "bm25": debug_bm25,
            "rrf": [{"chunk_id": c, "score": s} for c, s in fused[:50]],
        }
        logger.debug("Hybrid retrieve queries=%s candidates=%d", queries, len(candidates))
        return candidates, debug
