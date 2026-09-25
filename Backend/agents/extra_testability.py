"""Verify non-default (extra) features are worth actual device testing."""

from __future__ import annotations

import re
from typing import Any

from core.config import get_settings
from core.schemas import Feature
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger

# Marketing / legal / catalog extras that are not device lab test targets
_NON_TESTABLE_EXTRA = re.compile(
    r"(?:"
    r"^general$|overview|introduction|about\b|document\s*root|"
    r"built[- ]?in\s*apps?|preinstalled\s*apps?|app\s*list|"
    r"support\s*(and|&)?\s*services?|^support$|^services?$|"
    r"sustainability|manufacturing|environmental(\s*impact)?|"
    r"materials\s*(and|&)?\s*environmental|regulatory|"
    r"system\s*requirements|"
    r"design\s*(and|&)?\s*finish|^design$|^finish$|"
    r"appearance|colours?|colors?|form\s*factor|"
    r"packaging|package\s*contents|accessories|"
    r"warranty|legal|disclaimer|privacy|compliance|"
    r"price|pricing|reviews?|buy\s*now|compare|"
    r"safety\s*(and|&)?\s*emergency|"  # policy/copy, not HW sensor tests
    r"footnote|additional\s*information|^notes?$|"
    # Removed from default checklist — do not resurface as extras
    r"operating\s*system|^os$|throughput|"
    r"processor(\s*(&|and)?\s*performance)?|"
    r"memory(\s*(&|and)?\s*storage)?|storage(\s*(&|and)?\s*ram)?|"
    r"^capacity$|^chipset$"
    r")",
    re.I,
)

# Domains that usually warrant lab / field testing on the device
_TESTABLE_HINT = re.compile(
    r"(?:"
    r"camera|display|touch|battery|charg|processor|chipset|cpu|gpu|"
    r"memory|storage|ram|sensor|fingerprint|face\s*id|lidar|"
    r"audio|speaker|microphone|usb|wifi|wi-?fi|bluetooth|nfc|"
    r"cellular|network|sim|5g|4g|lte|throughput|gps|gnss|"
    r"button|connector|port|haptic|thermal|performance|"
    r"wireless|magsafe|qi\b|biometric|os\b|operating\s*system|"
    r"accessibility"  # a11y features can be tested
    r")",
    re.I,
)

_TESTABILITY_SYSTEM = """You decide which EXTRA (non-default checklist) product features
deserve actual device testing in a QA/lab context.

Keep a feature ONLY if engineers would run device tests against it
(hardware, radio, sensors, OS behavior, ports/buttons, measurable performance).

Drop features that are:
- marketing / brand / sustainability / environmental copy
- legal, regulatory boilerplate, support/services, warranty
- built-in app catalogs / software store lists
- packaging, accessories lists, design/finish colour stories
- general overview sections without measurable device behavior

Do NOT invent features. Use only the provided candidates.
Return JSON: {"keep": ["Feature Name", ...], "drop": [{"name": "...", "reason": "..."}]}
"""


def heuristic_is_testable_extra(name: str, specs_blob: str = "") -> bool:
    """Fast gate before/without LLM."""
    n = (name or "").strip()
    if not n:
        return False
    if _NON_TESTABLE_EXTRA.search(n):
        return False
    blob = f"{n} {specs_blob}"
    if _TESTABLE_HINT.search(blob):
        return True
    # Unknown short engineering-looking labels with numeric specs → keep
    if re.search(r"\d", specs_blob) and len(n.split()) <= 4:
        return True
    return False


def filter_testable_extras(
    extras: list[Feature],
    *,
    use_llm: bool = True,
) -> tuple[list[Feature], list[dict[str, str]]]:
    """
    Keep only extras that need real device testing.
    Returns (kept_features, rejected[{candidate, reason}]).
    """
    if not extras:
        return [], []

    rejected: list[dict[str, str]] = []
    candidates: list[Feature] = []

    for feat in extras:
        name = (feat.feature_name or "").strip()
        specs_blob = " ".join(
            f"{s.parameter} {s.value}" for s in feat.specifications[:12]
        )
        if not heuristic_is_testable_extra(name, specs_blob):
            rejected.append(
                {"candidate": name or "unnamed", "reason": "not_device_test_target"}
            )
            continue
        candidates.append(feat)

    if not candidates:
        return [], rejected

    if not use_llm or not is_azure_configured():
        return candidates, rejected

    settings = get_settings()
    payload = []
    for feat in candidates:
        payload.append(
            {
                "name": feat.feature_name,
                "sample_specs": [
                    {"key": s.parameter, "value": str(s.value)}
                    for s in feat.specifications[:8]
                ],
            }
        )
    try:
        content, _usage = chat_completion(
            [
                {"role": "system", "content": _TESTABILITY_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        "Candidates (JSON):\n"
                        + str(payload)
                        + "\n\nReturn keep/drop JSON."
                    ),
                },
            ],
            deployment=settings.cheap_model,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=1500,
        )
        data = parse_json_content(content) or {}
    except Exception as exc:
        logger.warning("extra testability LLM failed; keeping heuristic set: %s", exc)
        return candidates, rejected

    keep_names = {
        str(x).strip().lower()
        for x in (data.get("keep") or [])
        if str(x).strip()
    }
    drop_map = {}
    for item in data.get("drop") or []:
        if isinstance(item, dict):
            drop_map[str(item.get("name") or "").strip().lower()] = str(
                item.get("reason") or "llm_not_testable"
            )
        elif isinstance(item, str):
            drop_map[item.strip().lower()] = "llm_not_testable"

    # If LLM returned nothing usable, keep heuristic candidates
    if not keep_names and not drop_map:
        return candidates, rejected

    kept: list[Feature] = []
    for feat in candidates:
        key = (feat.feature_name or "").strip().lower()
        if keep_names and key in keep_names:
            kept.append(feat)
        elif keep_names and key not in keep_names:
            rejected.append(
                {
                    "candidate": feat.feature_name or "unnamed",
                    "reason": drop_map.get(key, "llm_not_testable"),
                }
            )
        elif key in drop_map:
            rejected.append(
                {
                    "candidate": feat.feature_name or "unnamed",
                    "reason": drop_map[key],
                }
            )
        else:
            kept.append(feat)

    logger.info(
        "extra_testability: kept=%d dropped=%d",
        len(kept),
        len(rejected),
    )
    return kept, rejected
