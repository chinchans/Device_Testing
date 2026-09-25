"""Query understanding agent — intent classification + extraction policy."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import get_settings
from core.schemas import QueryIntent
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger

_RULES = [
    (QueryIntent.FULL_DOCUMENT_EXTRACTION, (
        "extract all", "all features", "all specifications", "full document",
        "complete extraction", "every feature", "entire spec", "all specs",
    )),
    (QueryIntent.COMPARISON, ("compare", "difference", "vs ", "versus")),
    (QueryIntent.FEATURE_EXTRACTION, ("extract", "list features", "specifications for", "feature")),
    (QueryIntent.SPECIFIC_LOOKUP, ("what ", "which ", "does it support", "how many", "version")),
]

# Shared policy injected into planner/extractor for FULL_DOCUMENT_EXTRACTION
FEATURE_HIERARCHY_POLICY = """
EXTRACTION GRANULARITY POLICY (mandatory):
- A FEATURE is a major capability/module using the document's own section or heading name.
- A SPECIFICATION is a parameter/value pair under that feature (document terminology).
- NEVER promote a parameter into its own feature.
  Wrong: feature_name="<Parameter Label>" with one value.
  Right: feature_name="<Document Section>", parameter="<Parameter Label>", value="...".
- When a section focus is provided, emit ONE feature named exactly as that focus
  and put every related parameter under specifications[].
- Deduplicate synonymous parameters; keep source terminology for parameter names.
- Do not invent marketing, price, review, or navigation content as features.
- Do not add facts that are not present in the supplied evidence.
""".strip()


@dataclass
class QueryUnderstanding:
    intent: QueryIntent
    confidence: float
    notes: str
    extraction_policy: str = ""


def classify_query(query: str) -> tuple[QueryIntent, float, str]:
    """Backward-compatible wrapper → (intent, confidence, notes)."""
    result = understand_query(query)
    return result.intent, result.confidence, result.notes


def understand_query(query: str) -> QueryUnderstanding:
    q = (query or "").strip()
    q_lower = q.lower()

    intent: QueryIntent | None = None
    confidence = 0.5
    notes = ""

    for candidate, cues in _RULES:
        if any(c in q_lower for c in cues):
            if candidate == QueryIntent.FEATURE_EXTRACTION and any(
                c in q_lower for c in _RULES[0][1]
            ):
                continue
            intent = candidate
            confidence = 0.85
            notes = f"matched cues for {candidate.value}"
            break

    if intent is None and is_azure_configured():
        settings = get_settings()
        prompt = (
            "Classify the user query about a product specification document.\n"
            "Labels: SPECIFIC_LOOKUP | FEATURE_EXTRACTION | FULL_DOCUMENT_EXTRACTION | COMPARISON | OTHER\n"
            "Also confirm whether the user wants major feature modules (not individual parameters as features).\n"
            "Return JSON: {\"intent\": \"...\", \"confidence\": 0-1, \"notes\": \"...\", "
            "\"wants_feature_modules\": true}\n\n"
            f"QUERY: {q}"
        )
        try:
            content, _ = chat_completion(
                [
                    {"role": "system", "content": "Query intent classifier. JSON only."},
                    {"role": "user", "content": prompt},
                ],
                deployment=settings.cheap_model,
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=250,
            )
            data = parse_json_content(content) or {}
            intent_raw = str(data.get("intent", "FULL_DOCUMENT_EXTRACTION")).upper()
            try:
                intent = QueryIntent(intent_raw)
            except ValueError:
                intent = QueryIntent.FULL_DOCUMENT_EXTRACTION
            confidence = float(data.get("confidence", 0.7))
            notes = str(data.get("notes", ""))
        except Exception as exc:
            logger.warning("Intent classification LLM failed: %s", exc)
            intent = QueryIntent.FULL_DOCUMENT_EXTRACTION
            confidence = 0.4
            notes = "fallback"

    if intent is None:
        intent = QueryIntent.FULL_DOCUMENT_EXTRACTION
        confidence = 0.5
        notes = "default"

    policy = ""
    if intent in {
        QueryIntent.FULL_DOCUMENT_EXTRACTION,
        QueryIntent.FEATURE_EXTRACTION,
        QueryIntent.COMPARISON,
    }:
        policy = FEATURE_HIERARCHY_POLICY

    return QueryUnderstanding(
        intent=intent,
        confidence=confidence,
        notes=notes,
        extraction_policy=policy,
    )
