"""Deduplication and hierarchical reconciliation of extracted features."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from core.schemas import Feature, Specification
from indexing.section_filters import is_valid_feature_section_title, is_value_like_title


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _spec_key(spec: Specification) -> str:
    qual = "|".join(sorted(_norm_name(q) for q in spec.qualifiers))
    return f"{_norm_name(spec.parameter)}::{qual}"


def _values_equivalent(a: Any, b: Any) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def _token_words(name: str) -> list[str]:
    return [w for w in re.split(r"[^A-Za-z0-9]+", name or "") if w]


# Words that usually mean a *parameter*, not a top-level feature module
_PARAM_HINTS = {
    "resolution", "technology", "refresh", "rate", "brightness", "size",
    "type", "version", "capacity", "speed", "frequency", "bandwidth",
    "voltage", "current", "weight", "dimension", "dimensions",
    "thickness", "height", "width", "depth", "color", "colour", "flash",
    "aperture", "pixels", "mp", "hz", "nit", "nits", "hdr",
    "ratio", "density", "ppi", "chipset", "cores",
}

# Single-token names that are usually modules, never fold away solely by hint
_MODULE_SINGLETONS = {
    "display", "camera", "battery", "processor", "cpu", "storage", "memory",
    "connectivity", "network", "sensors", "sensor", "audio", "security",
    "power", "thermal", "wireless", "software", "hardware", "chassis",
}


def _looks_like_parameter_feature(name: str) -> bool:
    """True when the feature name itself reads like a parameter label."""
    words = [w.lower() for w in _token_words(name)]
    if not words:
        return False
    if len(words) == 1:
        if words[0] in _MODULE_SINGLETONS:
            return False
        return words[0] in _PARAM_HINTS
    # Multi-word: parameter-ish if any strong hint word present
    if any(w in _PARAM_HINTS for w in words):
        return True
    return False


def _preferred_parent_from_specs(feat: Feature) -> str | None:
    sections = [
        (s.source.section or "").strip()
        for s in feat.specifications
        if (s.source.section or "").strip()
    ]
    if not sections:
        return None
    # majority section label
    counts: dict[str, int] = defaultdict(int)
    for s in sections:
        counts[s] += 1
    best = max(counts.items(), key=lambda kv: kv[1])[0]
    if best and _norm_name(best) != _norm_name(feat.feature_name):
        return best
    return None


def _find_prefix_parent(name: str, known: dict[str, str]) -> str | None:
    """
    If name is 'Display Resolution' and known has 'Display', return 'Display'.
    known: norm -> original display name
    """
    words = _token_words(name)
    if len(words) < 2:
        return None
    # Try progressively shorter prefixes
    for end in range(len(words) - 1, 0, -1):
        prefix = " ".join(words[:end])
        n = _norm_name(prefix)
        if n in known and n != _norm_name(name):
            return known[n]
    return None


def _merge_spec_into(bucket: Feature, spec: Specification) -> None:
    existing_by_key: dict[str, list[Specification]] = {}
    for s in bucket.specifications:
        existing_by_key.setdefault(_spec_key(s), []).append(s)

    sk = _spec_key(spec)
    rivals = existing_by_key.get(sk, [])
    if not rivals:
        bucket.specifications.append(spec)
        return
    if any(
        _values_equivalent(spec.value, r.value) and (spec.unit or "") == (r.unit or "")
        for r in rivals
    ):
        return
    if not spec.qualifiers:
        page = spec.source.page
        other_pages = {r.source.page for r in rivals}
        if page is not None and page not in other_pages:
            spec.qualifiers = [f"page {page}"]
            sk2 = _spec_key(spec)
            if sk2 not in existing_by_key:
                bucket.specifications.append(spec)
                return
    bucket.specifications.append(spec)


def _fold_child_into_parent(parent: Feature, child: Feature) -> None:
    """Move child specs under parent; use child name as parameter when needed."""
    for spec in child.specifications:
        # If the child's feature name is more descriptive than a generic parameter, prefer it
        param = spec.parameter
        child_name = child.feature_name.strip()
        if _looks_like_parameter_feature(child_name):
            # e.g. feature "Display Resolution" + parameter "Resolution" → keep "Resolution"
            # or parameter "Value" → use "Display Resolution" trimmed relative to parent
            if _norm_name(param) in {"value", "val", "spec", "specification"} or not param:
                relative = child_name
                parent_name = parent.feature_name
                if relative.lower().startswith(parent_name.lower()):
                    relative = relative[len(parent_name) :].strip(" -–—:/")
                param = relative or child_name
            elif parent.feature_name.lower() in child_name.lower() and _norm_name(param) == _norm_name(
                child_name
            ):
                pass  # already good
        spec.parameter = param
        if not spec.source.section:
            spec.source.section = parent.feature_name
        _merge_spec_into(parent, spec)


def reconcile_features(features: list[Feature]) -> list[Feature]:
    """
    Merge duplicate features and fold parameter-like features into parents.

    Example:
      Display Resolution + Display Technology + Display
        → Display { Resolution, Technology, ... }
    """
    if not features:
        return []

    # Pass 1: exact-name merge
    exact: dict[str, Feature] = {}
    order: list[str] = []
    for feat in features:
        key = _norm_name(feat.feature_name)
        if not key:
            continue
        if key not in exact:
            exact[key] = Feature(feature_name=feat.feature_name, specifications=[])
            order.append(key)
        for spec in feat.specifications:
            _merge_spec_into(exact[key], spec)

    items = [exact[k] for k in order]

    # Pass 2: fold into source.section parents when section is a known feature
    known = {_norm_name(f.feature_name): f.feature_name for f in items}
    folded_flags = [False] * len(items)
    for i, feat in enumerate(items):
        parent_name = _preferred_parent_from_specs(feat)
        if not parent_name:
            continue
        pn = _norm_name(parent_name)
        if pn not in known or pn == _norm_name(feat.feature_name):
            continue
        if not (
            _looks_like_parameter_feature(feat.feature_name)
            or _norm_name(feat.feature_name).startswith(pn)
        ):
            continue
        parent = next(f for f in items if _norm_name(f.feature_name) == pn)
        _fold_child_into_parent(parent, feat)
        folded_flags[i] = True

    items = [f for f, folded in zip(items, folded_flags) if not folded]
    known = {_norm_name(f.feature_name): f.feature_name for f in items}

    # Pass 3: prefix parents — "Display Resolution" → "Display"
    folded_flags = [False] * len(items)
    # Prefer longer/established module names as parents: process shorter names first as parents
    for i, feat in enumerate(items):
        if folded_flags[i]:
            continue
        parent_label = _find_prefix_parent(feat.feature_name, known)
        if not parent_label:
            # Also: if feature looks parameter-like and a single-token prefix exists
            words = _token_words(feat.feature_name)
            if _looks_like_parameter_feature(feat.feature_name) and len(words) >= 2:
                cand = _norm_name(words[0])
                if cand in known:
                    parent_label = known[cand]
        if not parent_label:
            continue
        if _norm_name(parent_label) == _norm_name(feat.feature_name):
            continue
        parent = next(f for f in items if _norm_name(f.feature_name) == _norm_name(parent_label))
        _fold_child_into_parent(parent, feat)
        folded_flags[i] = True
        # Remove from known so we don't use folded name as parent later
        known.pop(_norm_name(feat.feature_name), None)

    items = [f for f, folded in zip(items, folded_flags) if not folded]

    # Pass 4: create synthetic parents for orphan parameter-like features sharing a prefix
    # e.g. only "Display Resolution" + "Display Technology" exist → create "Display"
    groups: dict[str, list[Feature]] = defaultdict(list)
    for feat in items:
        if not _looks_like_parameter_feature(feat.feature_name):
            continue
        words = _token_words(feat.feature_name)
        if len(words) < 2:
            continue
        groups[_norm_name(words[0])].append(feat)

    consumed: set[str] = set()
    new_parents: list[Feature] = []
    for prefix_norm, children in groups.items():
        if len(children) < 2:
            continue
        if prefix_norm in {_norm_name(f.feature_name) for f in items}:
            continue  # already have parent
        parent_name = _token_words(children[0].feature_name)[0]
        # Title-case gently from original token
        parent = Feature(feature_name=parent_name, specifications=[])
        for child in children:
            _fold_child_into_parent(parent, child)
            consumed.add(_norm_name(child.feature_name))
        new_parents.append(parent)

    if consumed:
        items = [f for f in items if _norm_name(f.feature_name) not in consumed]
        items.extend(new_parents)

    # Final gate: drop junk feature names that are values / chrome / phone numbers
    cleaned: list[Feature] = []
    for feat in items:
        if not is_valid_feature_section_title(feat.feature_name):
            # Try to rescue specs under source.section if that section is valid
            by_section: dict[str, list[Specification]] = {}
            for spec in feat.specifications:
                sec = (spec.source.section or "").strip()
                if sec and is_valid_feature_section_title(sec):
                    by_section.setdefault(sec, []).append(spec)
            for sec, specs in by_section.items():
                existing = next(
                    (c for c in cleaned if _norm_name(c.feature_name) == _norm_name(sec)),
                    None,
                )
                if existing is None:
                    existing = Feature(feature_name=sec, specifications=[])
                    cleaned.append(existing)
                for spec in specs:
                    _merge_spec_into(existing, spec)
            continue
        if is_value_like_title(feat.feature_name):
            continue
        cleaned.append(feat)

    return cleaned
