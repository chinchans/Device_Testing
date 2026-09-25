"""Reranking: LLM-based (default) or optional cross-encoder."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.config import get_settings
from core.schemas import RetrievedCandidate
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger


class Reranker(ABC):
    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[RetrievedCandidate],
        top_k: int,
    ) -> list[RetrievedCandidate]:
        raise NotImplementedError


class LLMReranker(Reranker):
    """Cheap LLM scoring of candidates — no extra model download required."""

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedCandidate],
        top_k: int,
    ) -> list[RetrievedCandidate]:
        if not candidates:
            return []
        if not is_azure_configured():
            # Fallback: keep RRF order
            return candidates[:top_k]

        settings = get_settings()
        # Cap payload size
        payload = []
        for i, c in enumerate(candidates[: max(top_k * 3, 15)]):
            payload.append(
                {
                    "id": c.chunk_id,
                    "section": c.metadata.section,
                    "text": c.text[:800],
                }
            )
        prompt = (
            "Score each passage for relevance to the extraction query on a 0-10 scale. "
            "Prefer passages that contain explicit parameter/value specifications for the queried feature/section. "
            "Return JSON: {\"scores\": [{\"id\": \"...\", \"score\": 0-10}]}\n\n"
            f"QUERY: {query}\n\nPASSAGES:\n{payload}"
        )
        try:
            content, _ = chat_completion(
                [
                    {"role": "system", "content": "You are a precise reranker for technical product specs. JSON only."},
                    {"role": "user", "content": prompt},
                ],
                deployment=settings.cheap_model,
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=800,
            )
            data = parse_json_content(content) or {}
            score_map = {s["id"]: float(s["score"]) for s in data.get("scores", []) if "id" in s}
            for c in candidates:
                if c.chunk_id in score_map:
                    c.rerank_score = score_map[c.chunk_id]
            candidates = sorted(
                candidates,
                key=lambda c: (c.rerank_score if c.rerank_score is not None else c.rrf_score),
                reverse=True,
            )
        except Exception as exc:
            logger.warning("LLM rerank failed, using RRF order: %s", exc)
        return candidates[:top_k]


class LexicalReranker(Reranker):
    """Offline fallback using token overlap with the query."""

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedCandidate],
        top_k: int,
    ) -> list[RetrievedCandidate]:
        q_tokens = set(query.lower().split())
        for c in candidates:
            c_tokens = set(c.text.lower().split())
            overlap = len(q_tokens & c_tokens) / max(1, len(q_tokens))
            section_boost = 0.2 if c.metadata.section and c.metadata.section.lower() in query.lower() else 0.0
            c.rerank_score = overlap + section_boost + c.rrf_score
        candidates = sorted(candidates, key=lambda c: c.rerank_score or 0.0, reverse=True)
        return candidates[:top_k]


def get_reranker() -> Reranker:
    settings = get_settings()
    provider = (settings.models.reranker_provider or "llm").lower()
    if provider == "lexical":
        return LexicalReranker()
    return LLMReranker()
