"""Reciprocal Rank Fusion for hybrid retrieval."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def reciprocal_rank_fusion(
    ranked_lists: Iterable[list[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """
    RRF(d) = Σ 1 / (k + rank(d))
    ranked_lists: each list is chunk IDs in rank order (best first, rank starts at 1).
    """
    scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
