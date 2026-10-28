"""Match uploaded files to certificate types: filename first, document content second."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .definitions import CERTIFICATES

MIN_CONTENT_SCORE = 3


@dataclass
class Classification:
    cert_id: str | None
    detected_by: str  # "filename" | "content" | "none"


def _filename_matches(name: str) -> list[str]:
    stem = Path(name).stem.lower()
    tokens = set(re.split(r"[^a-z0-9]+", stem)) - {""}
    compact = re.sub(r"[^a-z0-9]", "", stem)
    hits = []
    for cert in CERTIFICATES:
        if tokens.intersection(cert.filename_tokens) or any(c in compact for c in cert.filename_compact):
            hits.append(cert.id)
    return hits


def content_scores(text: str) -> dict[str, int]:
    lowered = (text or "").lower()
    scores: dict[str, int] = {}
    for cert in CERTIFICATES:
        score = 0
        for phrase, weight in cert.content_keywords:
            pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
            if re.search(pattern, lowered):
                score += weight
        scores[cert.id] = score
    return scores


def classify_by_content(text: str) -> str | None:
    scores = content_scores(text)
    best = max(scores.items(), key=lambda kv: kv[1], default=(None, 0))
    if best[1] < MIN_CONTENT_SCORE:
        return None
    if sum(1 for s in scores.values() if s == best[1]) > 1:
        return None
    return best[0]


def classify_by_filename(name: str) -> str | None:
    hits = _filename_matches(name)
    return hits[0] if len(hits) == 1 else None


def classify(name: str, text: str) -> Classification:
    by_name = classify_by_filename(name)
    if by_name:
        return Classification(by_name, "filename")
    by_content = classify_by_content(text)
    if by_content:
        return Classification(by_content, "content")
    return Classification(None, "none")
