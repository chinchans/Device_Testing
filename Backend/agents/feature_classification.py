"""Map free-form extracted features onto a device-type standard checklist.

Pipeline position: after reconcile_features / grounding.
- Tick standard features when evidence maps to them.
- Keep only strong, relevant extra features (reject chrome / thin noise).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.feature_taxonomy import StandardFeatureDef, get_taxonomy, normalize_device_type
from core.schemas import Feature, Specification
from indexing.section_filters import is_nav_or_chrome, is_valid_feature_section_title, is_value_like_title

# Names that should never become standalone "extra" features
# Former defaults — keep out of the standard checklist AND extras list
_RETIRED_DEFAULT_FEATURES = re.compile(
    r"^(operating\s*system|os|throughput|"
    r"processor(\s*(&|and)?\s*performance)?|chipset|cpu|gpu|"
    r"memory(\s*(&|and)?\s*storage)?|storage(\s*(&|and)?\s*ram)?|"
    r"capacity|ram|rom)$",
    re.I,
)

# Names that should never become standalone "extra" features
_BLOCKED_EXTRA_NAMES = re.compile(
    r"^(document\s*root|general(\s*information)?|overview|introduction|about|"
    r"specifications?|contents?|table\s*of\s*contents|toc|summary|"
    r"price|pricing|reviews?|buy\s*now|compare|warranty|legal|"
    r"manufactured\s*by|support|contact|product\s*name|model\s*name|"
    r"launch\s*date|announced|availability|"
    r"built[- ]?in\s*apps?|support\s*(and|&)?\s*services?|"
    r"sustainability(.*)?"
    r"|materials\s*(and|&)?\s*environmental(.*)?|"
    r"environmental\s*(and|&)?\s*regulatory|system\s*requirements(.*)?"
    r"|design\s*(and|&)?\s*finish|safety\s*(and|&)?\s*emergency)$",
    re.I,
)

# Clickbait / article chrome often scraped into 91mobiles-style PDFs
_NOISE_EXTRA_TITLE = re.compile(
    r"\b(who|what|when|where|why|how|living\s+in|intercepts|heart\s+attack|"
    r"actors?\s+who|signs\s+that|strange|young\s+woman|coast\s+guard)\b",
    re.I,
)

# Accessibility / peripheral rows that appear under OS sections in web specs
# but are not OS identity (name / version / UI skin).
_OS_NON_IDENTITY = re.compile(
    r"\b(asha|hearing\s*aid|^aid$|java\s*support|browser|widget|wallpaper)\b",
    re.I,
)

# Sections that are footnotes / legal / support — never promote their "Battery"-named
# rows onto hardware standard cards just because the parameter mentions the word.
_FOOTNOTE_OR_SUPPORT_SECTION = re.compile(
    r"(software\s*support|disclaimer|footnote|legal|warranty|terms\b|"
    r"^notes?$|additional\s*information|important\s*notes?)",
    re.I,
)

# Mixed / catch-all sections where param cues are still useful
_CATCHALL_SECTION = re.compile(
    r"^(document\s*root|general(\s*information)?|overview|summary|"
    r"specifications?|contents?|product\s*specs?)$",
    re.I,
)

# Disclaimer / multi-SKU marketing values — not measurable specs
_NOISY_SPEC_VALUE = re.compile(
    r"(varies\s+by|other\s+factors|may\s+vary|depending\s+on|"
    r"rated\s+typical\s+capacity\s+is\b.*\bfor\b.*\band\b|"
    r"actual\s+battery\s+life|"
    r"galaxy\s+s\d+\+|galaxy\s+s\d+\s+ultra)",
    re.I,
)

# Parameter / section cues that help split mixed bags (e.g. Document Root)
# Specs are routed by these cues — parent feature name alone must not force mismatched params.
_PARAM_CUES: dict[str, tuple[str, ...]] = {
    "camera": ("camera", "megapixel", "mp", "aperture", "flash", "video", "selfie", "rear", "front"),
    "connectivity": ("wi-fi", "wifi", "wlan", "bluetooth", "nfc", "hotspot", "802.11", "connectivity", "wireless"),
    "cellular": ("sim", "5g", "4g", "lte", "gsm", "band", "network", "volte", "dual sim"),
    "display": ("display", "screen", "resolution", "refresh", "brightness", "touch", "amoled", "lcd", "hz"),
    "battery": (
        "battery", "mah", "charging", "charger", "fast charge", "watt",
        "battery life", "battery capacity", "magsafe", "qi2", "wireless charging",
        "video playback", "audio playback", "talk time", "removable", "playback time",
        "typical use", "power adapter",
    ),
    "sensors": ("sensor", "fingerprint", "accelerometer", "gyro", "proximity", "compass", "face id", "touch id", "lidar", "magnetometer", "magnet array"),
    "audio": ("audio", "speaker", "microphone", "mic", "jack", "headphone", "dolby", "stereo"),
    "usb": ("usb", "type-c", "type c", "usb-c", "displayport", "usb 3", "usb 2"),
}

_MIN_EXTRA_SPECS = 2
_MIN_FOUND_SPECS = 1


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 1}


def _synonym_patterns(defn: StandardFeatureDef) -> list[str]:
    pats = [_norm(defn.name)]
    pats.extend(_norm(s) for s in defn.synonyms)
    # longest first for substring preference
    return sorted({p for p in pats if p}, key=len, reverse=True)


def _name_match_score(text: str, defn: StandardFeatureDef) -> float:
    """Return 0..1 score for how well text maps onto a standard feature."""
    n = _norm(text)
    if not n or len(n) < 2:
        return 0.0
    best = 0.0
    for syn in _synonym_patterns(defn):
        if not syn:
            continue
        if n == syn:
            return 1.0
        # Substring matches need enough characters to avoid "a"∈"camera"
        if len(syn) >= 3 and syn in n:
            best = max(best, 0.92 if len(syn) >= 4 else 0.75)
            continue
        if len(n) >= 3 and n in syn:
            best = max(best, 0.75 if len(n) >= 4 else 0.6)
            continue
        # token overlap
        st = set(syn.split())
        nt = _tokens(text)
        if not st or not nt:
            continue
        overlap = len(st & nt) / len(st)
        if overlap >= 0.6:
            best = max(best, 0.55 + 0.4 * overlap)
    return best


def _cue_match_score(text: str, feature_id: str) -> float:
    cues = _PARAM_CUES.get(feature_id, ())
    n = _norm(text)
    if not n:
        return 0.0
    tokens = set(n.split())
    best = 0.0
    for cue in cues:
        c = _norm(cue)
        if not c:
            continue
        # Short cues (e.g. "mp", "hz") must match as whole tokens — avoid
        # false hits like "mp" inside "temp".
        if len(c) < 4:
            compound = any(
                re.fullmatch(rf"\d+{re.escape(c)}", t) or re.fullmatch(rf"{re.escape(c)}\d+", t)
                for t in tokens
            )
            if c in tokens or compound:
                best = max(best, 0.8)
            continue
        if c in n:
            best = max(best, 0.85)
        elif len(n) >= 3 and n in c:
            best = max(best, 0.7)
        elif set(c.split()) <= tokens:
            best = max(best, 0.75)
    return best


def _best_standard_for_text(
    text: str,
    taxonomy: tuple[StandardFeatureDef, ...],
    *,
    threshold: float = 0.55,
) -> tuple[StandardFeatureDef | None, float]:
    best_def: StandardFeatureDef | None = None
    best_score = 0.0
    for defn in taxonomy:
        score = max(_name_match_score(text, defn), _cue_match_score(text, defn.id))
        if score > best_score:
            best_score = score
            best_def = defn
    if best_score < threshold:
        return None, best_score
    return best_def, best_score


def _spec_text_blob(spec: Specification) -> str:
    parts = [
        spec.parameter or "",
        str(spec.value or ""),
        spec.source.section or "",
    ]
    return " ".join(parts)


def _spec_affinity_to_standard(
    spec: Specification,
    defn: StandardFeatureDef,
) -> float:
    """Score how well a spec belongs under a standard feature.

    Routing priority (user requirement):
      1) Chunk/source section tag
      2) Parameter cues only for catch-all / untagged sections
      3) Never promote footnote/support-section rows by keyword alone
    """
    param = (spec.parameter or "").strip()
    value = str(spec.value or "").strip()
    section = ""
    if spec.source and spec.source.section:
        section = str(spec.source.section).strip()

    if value and _NOISY_SPEC_VALUE.search(value):
        return 0.0
    if param and _NOISY_SPEC_VALUE.search(param) and len(param) > 40:
        return 0.0

    # Keep OS card to identity only (Android / One UI / version) — not ASHA, etc.
    if defn.id == "os":
        blob = f"{param} {value}"
        if _OS_NON_IDENTITY.search(blob):
            return 0.0

    section_score = max(
        _name_match_score(section, defn),
        _cue_match_score(section, defn.id),
    )
    param_score = max(
        _name_match_score(param, defn),
        _cue_match_score(param, defn.id),
        _cue_match_score(value, defn.id) if value and len(value) <= 48 else 0.0,
    )

    # Footnote / Software Support: never attach to hardware standards by keyword
    if section and _FOOTNOTE_OR_SUPPORT_SECTION.search(section):
        return 0.0

    # Strong section match → this standard owns the row (param reinforces)
    if section_score >= 0.55:
        if param_score >= 0.4 or not param:
            return max(section_score, 0.55 * section_score + 0.45 * max(param_score, 0.5))
        # Param clearly belongs to a *different* standard — leave for that feature
        # (handled in _best_standard_for_spec). Weak local score here.
        return section_score * 0.45

    # Catch-all / missing section → allow parameter cues (Document Root bags)
    if not section or _CATCHALL_SECTION.match(section):
        return param_score

    # Section is some other real module (e.g. Display) — do not steal into
    # Battery/Camera/etc. merely because the value text mentions "mAh"/"battery".
    return 0.0


def _best_standard_for_spec(
    spec: Specification,
    taxonomy: tuple[StandardFeatureDef, ...],
    *,
    threshold: float = 0.55,
) -> tuple[StandardFeatureDef | None, float]:
    """Route a specification primarily by its source.section tag."""
    param = (spec.parameter or "").strip()
    value = str(spec.value or "").strip()
    section = ""
    if spec.source and spec.source.section:
        section = str(spec.source.section).strip()

    # Hard block footnote/support sections + disclaimer values
    if section and _FOOTNOTE_OR_SUPPORT_SECTION.search(section):
        return None, 0.0
    if value and _NOISY_SPEC_VALUE.search(value):
        return None, 0.0

    section_def, section_score = _best_standard_for_text(section, taxonomy, threshold=0.55)
    if section_def is not None and section_score >= 0.55:
        affinity = _spec_affinity_to_standard(spec, section_def)

        # Storage SKUs (256GB, …) never belong under Battery
        if section_def.id == "battery" and re.search(
            r"\b\d+(\.\d+)?\s*(gb|tb)\b", value or "", re.I
        ):
            if not re.search(r"\b(mah|wh)\b", value or "", re.I):
                return None, 0.0

        # If the parameter/value clearly names a *different* standard module,
        # re-home the row there (fixes storage/Face ID stuck under Battery).
        best_other: StandardFeatureDef | None = None
        best_other_score = 0.0
        for defn in taxonomy:
            if defn.id == section_def.id:
                continue
            ps = max(
                _name_match_score(param, defn),
                _cue_match_score(param, defn.id),
                _cue_match_score(value, defn.id) if value and len(value) <= 64 else 0.0,
            )
            if ps > best_other_score:
                best_other_score = ps
                best_other = defn
        if (
            best_other is not None
            and best_other_score >= 0.7
            and best_other_score > max(affinity, 0.0) + 0.1
        ):
            return best_other, best_other_score

        if section_def.id == "os":
            if affinity < 0.55:
                return None, 0.0
            return section_def, affinity

        # Strong section match owns the row unless a *different* standard
        # clearly claims the parameter (handled above) or affinity is zero
        # from noisy/disclaimer values.
        if affinity >= 0.5:
            return section_def, max(affinity, section_score)
        if affinity > 0.0 or best_other_score < 0.55:
            # Keep section-local rows like Battery → "Removable" / "Video Playback"
            return section_def, max(section_score * 0.75, affinity, 0.55)
        return None, affinity

    # Section is missing, catch-all, OR a former/non-standard label
    # (Operating System, Processor, Capacity, …) → route by param/value cues.
    best_def: StandardFeatureDef | None = None
    best_score = 0.0
    for defn in taxonomy:
        score = _spec_affinity_to_standard(spec, defn)
        # When section isn't a current standard, allow direct cue scoring
        if not section or _CATCHALL_SECTION.match(section) or section_def is None:
            score = max(
                score,
                _name_match_score(param, defn),
                _cue_match_score(param, defn.id),
                _cue_match_score(value, defn.id) if value and len(value) <= 64 else 0.0,
            )
        if score > best_score:
            best_score = score
            best_def = defn
    if best_score < threshold:
        return None, best_score
    return best_def, best_score


def _clone_spec(spec: Specification) -> Specification:
    return Specification(
        parameter=spec.parameter,
        value=spec.value,
        unit=spec.unit,
        qualifiers=list(spec.qualifiers),
        source=spec.source.model_copy() if spec.source else spec.source,
        grounding_status=spec.grounding_status,
    )


def _merge_specs(dst: list[Specification], incoming: list[Specification]) -> None:
    seen = {
        (_norm(s.parameter), _norm(str(s.value)), _norm("|".join(s.qualifiers)))
        for s in dst
    }
    for spec in incoming:
        key = (_norm(spec.parameter), _norm(str(spec.value)), _norm("|".join(spec.qualifiers)))
        if key in seen:
            continue
        dst.append(_clone_spec(spec))
        seen.add(key)


def _is_strong_extra(name: str, specs: list[Specification], *, min_specs: int) -> bool:
    if not name or _BLOCKED_EXTRA_NAMES.match(name.strip()):
        return False
    if _RETIRED_DEFAULT_FEATURES.match(name.strip()):
        return False
    if _NOISE_EXTRA_TITLE.search(name):
        return False
    if is_nav_or_chrome(name) or is_value_like_title(name):
        return False
    if not is_valid_feature_section_title(name):
        return False
    # Prefer short engineering module labels over long sentence-like titles
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    if len(words) > 5:
        return False
    if len(specs) < min_specs:
        return False
    # Require at least one non-empty parameter name
    meaningful = [
        s for s in specs
        if (s.parameter or "").strip() and str(s.value or "").strip()
    ]
    return len(meaningful) >= min_specs


@dataclass
class ClassifiedFeature:
    id: str
    name: str
    kind: str  # standard | extra
    order: int
    found: bool
    source_names: list[str] = field(default_factory=list)
    feature: Feature = field(default_factory=lambda: Feature(feature_name=""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "order": self.order,
            "found": self.found,
            "source_names": self.source_names,
            "spec_count": len(self.feature.specifications),
        }


@dataclass
class FeatureChecklist:
    device_type: str
    standard_features: list[ClassifiedFeature]
    extra_features: list[ClassifiedFeature]
    rejected_extras: list[dict[str, str]] = field(default_factory=list)

    @property
    def all_features(self) -> list[ClassifiedFeature]:
        return list(self.standard_features) + list(self.extra_features)

    def to_dict(self) -> dict[str, Any]:
        found_n = sum(1 for f in self.standard_features if f.found)
        return {
            "device_type": self.device_type,
            "standard_total": len(self.standard_features),
            "standard_found": found_n,
            "extra_count": len(self.extra_features),
            "rejected_extras": self.rejected_extras,
            "standard_features": [f.to_dict() for f in self.standard_features],
            "extra_features": [f.to_dict() for f in self.extra_features],
        }


def classify_features(
    features: list[Feature],
    device_type: str | None = "mobile",
    *,
    min_extra_specs: int = _MIN_EXTRA_SPECS,
    min_found_specs: int = _MIN_FOUND_SPECS,
) -> FeatureChecklist:
    """Classify extracted features into standard ticks + relevant extras."""
    device = normalize_device_type(device_type) or "mobile"
    taxonomy = get_taxonomy(device)

    buckets: dict[str, list[Specification]] = {d.id: [] for d in taxonomy}
    source_names: dict[str, list[str]] = {d.id: [] for d in taxonomy}
    residuals: list[Feature] = []
    rejected: list[dict[str, str]] = []

    if not taxonomy:
        # No checklist for this device type — promote valid modules as extras only.
        extras: list[ClassifiedFeature] = []
        for idx, feat in enumerate(features):
            name = (feat.feature_name or "").strip() or f"Feature {idx + 1}"
            specs = list(feat.specifications)
            if _is_strong_extra(name, specs, min_specs=min_extra_specs):
                extras.append(
                    ClassifiedFeature(
                        id=f"extra_{_norm(name).replace(' ', '_')[:40] or idx}",
                        name=name,
                        kind="extra",
                        order=100 + idx,
                        found=True,
                        source_names=[name],
                        feature=Feature(feature_name=name, specifications=specs),
                    )
                )
            else:
                rejected.append({"candidate": name, "reason": "weak_or_noisy_extra"})
        return FeatureChecklist(
            device_type=device,
            standard_features=[],
            extra_features=extras,
            rejected_extras=rejected,
        )

    for feat in features:
        fname = (feat.feature_name or "").strip()
        feat_def, feat_score = _best_standard_for_text(fname, taxonomy, threshold=0.55)

        # Spec-level routing only — parent feature name must not force mismatched params
        # onto a standard card (e.g. Wi-Fi / Battery under "Operating System").
        routed_any = False
        leftover: list[Specification] = []
        for spec in feat.specifications:
            spec_def, spec_score = _best_standard_for_spec(spec, taxonomy, threshold=0.55)
            chosen = None
            if spec_def is not None and spec_score >= 0.55:
                chosen = spec_def
            elif feat_def is not None and feat_score >= 0.55:
                # Parent is a known standard feature: keep only params that also
                # belong to that feature (cue / synonym match on the parameter itself).
                affinity = _spec_affinity_to_standard(spec, feat_def)
                if affinity >= 0.55:
                    chosen = feat_def

            if chosen is not None:
                buckets[chosen.id].append(_clone_spec(spec))
                if fname and fname not in source_names[chosen.id]:
                    source_names[chosen.id].append(fname)
                routed_any = True
            else:
                leftover.append(_clone_spec(spec))

        if leftover:
            # Do NOT dump uncued leftovers into the parent standard feature.
            # Keep them as residuals only when they form a strong extra module.
            if len(leftover) >= min_extra_specs and _is_strong_extra(
                fname or "Unknown", leftover, min_specs=min_extra_specs
            ):
                residuals.append(Feature(feature_name=fname or "Unknown", specifications=leftover))
            elif not routed_any and len(leftover) >= min_extra_specs:
                residuals.append(Feature(feature_name=fname or "Unknown", specifications=leftover))
            else:
                rejected.append(
                    {
                        "candidate": fname or "unnamed",
                        "reason": "unmapped_or_unrelated_to_feature",
                    }
                )

    standard_out: list[ClassifiedFeature] = []
    for defn in sorted(taxonomy, key=lambda d: d.order):
        specs = buckets.get(defn.id, [])
        found = len(specs) >= min_found_specs
        standard_out.append(
            ClassifiedFeature(
                id=defn.id,
                name=defn.name,
                kind="standard",
                order=defn.order,
                found=found,
                source_names=list(source_names.get(defn.id, [])),
                feature=Feature(
                    feature_name=defn.name,
                    specifications=specs if found else [],
                ),
            )
        )

    extras_out: list[ClassifiedFeature] = []
    for idx, feat in enumerate(residuals):
        name = (feat.feature_name or "").strip() or f"Extra {idx + 1}"
        # Avoid duplicating something already covered by a standard —
        # but only merge specs that actually belong to that standard.
        mapped, score = _best_standard_for_text(name, taxonomy, threshold=0.7)
        if mapped and score >= 0.7:
            relevant = [
                s for s in feat.specifications
                if _spec_affinity_to_standard(s, mapped) >= 0.55
            ]
            unrelated = [
                s for s in feat.specifications
                if _spec_affinity_to_standard(s, mapped) < 0.55
            ]
            if relevant:
                _merge_specs(buckets[mapped.id], relevant)
                for i, cf in enumerate(standard_out):
                    if cf.id == mapped.id:
                        specs = buckets[mapped.id]
                        standard_out[i] = ClassifiedFeature(
                            id=cf.id,
                            name=cf.name,
                            kind="standard",
                            order=cf.order,
                            found=len(specs) >= min_found_specs,
                            source_names=list(
                                dict.fromkeys(cf.source_names + ([name] if name else []))
                            ),
                            feature=Feature(feature_name=cf.name, specifications=specs),
                        )
                        break
            if unrelated:
                rejected.append(
                    {
                        "candidate": name or "unnamed",
                        "reason": "unrelated_specs_dropped_from_standard",
                    }
                )
            continue

        if _is_strong_extra(name, feat.specifications, min_specs=min_extra_specs):
            extras_out.append(
                ClassifiedFeature(
                    id=f"extra_{_norm(name).replace(' ', '_')[:40] or idx}",
                    name=name,
                    kind="extra",
                    order=100 + idx,
                    found=True,
                    source_names=[name],
                    feature=Feature(feature_name=name, specifications=list(feat.specifications)),
                )
            )
        else:
            rejected.append({"candidate": name, "reason": "not_relevant_or_insufficient_detail"})

    # LLM + heuristic: keep only extras that need real device testing
    if extras_out:
        from agents.extra_testability import filter_testable_extras

        kept_feats, drop_meta = filter_testable_extras(
            [cf.feature for cf in extras_out],
            use_llm=True,
        )
        keep_names = {(f.feature_name or "").strip().lower() for f in kept_feats}
        filtered_extras: list[ClassifiedFeature] = []
        for cf in extras_out:
            if (cf.name or "").strip().lower() in keep_names:
                filtered_extras.append(cf)
            else:
                reason = next(
                    (
                        d["reason"]
                        for d in drop_meta
                        if (d.get("candidate") or "").strip().lower()
                        == (cf.name or "").strip().lower()
                    ),
                    "not_device_test_target",
                )
                rejected.append({"candidate": cf.name, "reason": reason})
        extras_out = filtered_extras

    return FeatureChecklist(
        device_type=device,
        standard_features=standard_out,
        extra_features=extras_out,
        rejected_extras=rejected,
    )
