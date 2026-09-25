"""Query rewrite agent for retry loops."""

from __future__ import annotations

from core.config import get_settings
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger


def rewrite_queries(
    section_title: str,
    previous_queries: list[str],
    reason: str,
    missed_hints: list[str] | None = None,
) -> list[str]:
    """Produce refined retrieval queries when extraction/coverage fails."""
    base = [
        f"{section_title} parameters",
        f"{section_title} technical specifications",
        f"{section_title} values",
    ]
    if missed_hints:
        base.extend(missed_hints)

    if not is_azure_configured():
        # Deduplicate against previous
        prev = {q.lower() for q in previous_queries}
        return [q for q in base if q.lower() not in prev] or base

    settings = get_settings()
    prompt = (
        "Rewrite retrieval queries for a product specification RAG system. "
        "Use only terminology related to the section title. Do NOT invent device-specific "
        "feature names that are not implied by the section title.\n"
        "Return JSON: {\"queries\": [\"...\"]}\n\n"
        f"SECTION: {section_title}\n"
        f"PREVIOUS_QUERIES: {previous_queries}\n"
        f"FAILURE_REASON: {reason}\n"
        f"HINTS: {missed_hints or []}"
    )
    try:
        content, _ = chat_completion(
            [
                {"role": "system", "content": "Query rewrite helper. JSON only."},
                {"role": "user", "content": prompt},
            ],
            deployment=settings.cheap_model,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=300,
        )
        data = parse_json_content(content) or {}
        queries = [str(q) for q in data.get("queries", []) if str(q).strip()]
        return queries or base
    except Exception as exc:
        logger.warning("Query rewrite failed: %s", exc)
        return base
