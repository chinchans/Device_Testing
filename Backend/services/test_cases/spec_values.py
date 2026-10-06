"""Map product-spec values extracted from the PDF onto test-case ${VAR} placeholders.

Values are derived per request from the feature cards the UI already holds (name +
parameters). Nothing is written back to the curated test-case files, so they keep
their placeholders for the next session.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")

Row = tuple[str, str, str]

_MP = re.compile(r"(\d+(?:\.\d+)?)\s*(?:MP|megapixels?)\b", re.I)
_FRONT = re.compile(r"front|selfie|center stage|truedepth|facetime", re.I)
_CAMERA = re.compile(r"camera|photo|selfie|lens|telephoto|ultra\s*-?\s*wide", re.I)
_DIMS = re.compile(r"(\d{3,5})\s*[x×]\s*(\d{3,5})")
_RES_TOKEN = re.compile(
    r"(\d{3,4})\s*[x×]\s*(\d{3,4})|\b(8K|4K|UHD|2160p|1440p|QHD|1080p|FHD|720p|HD)\b", re.I
)
_TOKEN_SIZE = {
    "8k": "7680x4320", "4k": "3840x2160", "uhd": "3840x2160", "2160p": "3840x2160",
    "1440p": "2560x1440", "qhd": "2560x1440", "1080p": "1920x1080", "fhd": "1920x1080",
    "720p": "1280x720", "hd": "1280x720",
}
_VIDEO_KEY = re.compile(r"video|recording", re.I)
_VIDEO_EXCLUDE = re.compile(
    r"\bplay|slow|time-?lapse|prores|spatial|macro|output|mirror|facetime|quicktake|still|"
    r"stabili|format|codec|zoom|night|log\b|academy|hdr support",
    re.I,
)
_STILL_EXCLUDE = re.compile(r"video|record|playback|still photos|features|panorama", re.I)
_PRIMARY_KEY = re.compile(r"rear|back|main|primary|wide|camera|\bMP\b", re.I)
_DISPLAY = re.compile(r"display|screen|panel", re.I)
_NOT_DISPLAY = re.compile(r"camera|video|record|selfie|photo|facetime|mirror|output|\bplay", re.I)

# Full-resolution 4:3 output of common sensors; other sizes are computed.
_MP_SIZES = {
    200: "16320x12240", 108: "12000x9000", 64: "9248x6936", 50: "8160x6120",
    48: "8000x6000", 32: "6528x4896", 20: "5184x3888", 16: "4608x3456",
    13: "4160x3120", 12: "4000x3000", 10: "3648x2736", 8: "3264x2448",
    5: "2592x1944", 2: "1600x1200",
}


def spec_rows(spec_features: list[dict[str, Any]] | None) -> list[Row]:
    """Flatten UI feature cards ({name, parameters:[{name, value}]}) into (section, key, value)."""
    rows: list[Row] = []
    for card in spec_features or []:
        if not isinstance(card, dict):
            continue
        section = str(card.get("name") or "")
        for p in card.get("parameters") or card.get("specs") or []:
            if not isinstance(p, dict):
                continue
            key = str(p.get("name") or p.get("key") or p.get("parameter") or "").strip()
            value = str(p.get("value") or "").strip()
            if key or value:
                rows.append((section, key, value))
    return rows


def mp_to_resolution(mp: float) -> str:
    for known, size in _MP_SIZES.items():
        if abs(mp - known) < 0.6:
            return size
    w = int(round(math.sqrt(mp * 1e6 * 4 / 3) / 16) * 16)
    return f"{w}x{int(round(w * 3 / 4))}"


class _Values:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, str]] = {}

    def put(self, var: str, value: Any, row: Row | None, note: str = "") -> None:
        if var in self.data or value in (None, ""):
            return
        source = f"{row[0]} › {row[1]}: {row[2]}" if row else ""
        if note:
            source = f"{source} ({note})" if source else note
        self.data[var] = {"value": str(value), "source": source.strip(" ›:")}


def _fps(text: str) -> list[int]:
    out: list[int] = []
    for group in re.findall(r"((?:\d+\s*[,/]\s*)*\d+)\s*fps", text, re.I):
        out += [int(n) for n in re.split(r"\s*[,/]\s*", group) if n.isdigit() and 0 < int(n) <= 960]
    return out


def _tok_size(m: re.Match[str]) -> str:
    if m.group(1):
        a, b = int(m.group(1)), int(m.group(2))
        return f"{max(a, b)}x{min(a, b)}"
    return _TOKEN_SIZE[m.group(3).lower()]


def _area(size: str) -> int:
    w, h = size.split("x")
    return int(w) * int(h)


def _video_modes(key: str, value: str) -> list[tuple[str, list[int]]]:
    """[(WxH, [fps...])] from e.g. '4K@30fps, 1080p@30/60/120fps' or key '4K Video' + value fps."""
    toks = list(_RES_TOKEN.finditer(value))
    if not toks:
        key_toks = list(_RES_TOKEN.finditer(key))
        if not key_toks:
            return []
        return [(max((_tok_size(m) for m in key_toks), key=_area), _fps(value))]
    groups: list[list[Any]] = []
    for m in toks:
        if groups and re.fullmatch(r"[\s()]*", value[groups[-1][1]:m.start()]):
            groups[-1][1] = m.end()
            groups[-1][2].append(_tok_size(m))
        else:
            groups.append([m.start(), m.end(), [_tok_size(m)]])
    modes = []
    for i, (_start, end, sizes) in enumerate(groups):
        stop = groups[i + 1][0] if i + 1 < len(groups) else len(value)
        modes.append((max(sizes, key=_area), _fps(value[end:stop])))
    return modes


def _camera_values(rows: list[Row], v: _Values) -> None:
    rear: list[tuple[float, Row]] = []
    front: list[tuple[float, Row]] = []
    for row in rows:
        section, key, value = row
        if _STILL_EXCLUDE.search(key):
            continue
        mps = [float(x) for x in _MP.findall(f"{key} {value}")]
        if not mps:
            continue
        target = front if _FRONT.search(f"{section} {key} {value}") else rear
        target.append((max(mps), row))

    rear = [t for t in rear if _PRIMARY_KEY.search(t[1][1])] or rear
    if rear:
        mp, row = max(rear, key=lambda t: t[0])
        size = mp_to_resolution(mp)
        note = f"{mp:g} MP as 4:3 {size}"
        v.put("REAR_PRIMARY_CAMERA", f"{mp:g} MP rear primary camera", row)
        v.put("REAR_PRIMARY_CAMERA_SUPPORTED", "true", row)
        for var in ("REAR_PRIMARY_PHOTO_RESOLUTION", "PHOTO_RESOLUTION",
                    "MAX_SUPPORTED_PHOTO_RESOLUTION", "SUPPORTED_PHOTO_RESOLUTIONS"):
            v.put(var, size, row, note)
    if front:
        mp, row = max(front, key=lambda t: t[0])
        size = mp_to_resolution(mp)
        v.put("FRONT_PRIMARY_CAMERA", f"{mp:g} MP front camera", row)
        v.put("FRONT_PRIMARY_CAMERA_SUPPORTED", "true", row)
        v.put("FRONT_PRIMARY_PHOTO_RESOLUTION", size, row, f"{mp:g} MP as 4:3 {size}")

    modes: dict[str, set[int]] = {}
    video_row: Row | None = None
    for row in rows:
        section, key, value = row
        if not _VIDEO_KEY.search(key) or _VIDEO_EXCLUDE.search(key) or _FRONT.search(f"{section} {key}"):
            continue
        for size, fps in _video_modes(key, value):
            modes.setdefault(size, set()).update(fps)
            if video_row is None or _area(size) >= max(_area(s) for s in modes):
                video_row = row
    if modes:
        sizes = sorted(modes, key=_area, reverse=True)
        top = sizes[0]
        v.put("VIDEO_RECORDING_SUPPORTED", "true", video_row)
        v.put("VIDEO_RESOLUTION", top, video_row)
        if modes[top]:
            v.put("VIDEO_FPS", max(modes[top]), video_row)
        v.put("SUPPORTED_VIDEO_RESOLUTIONS", ",".join(sizes), video_row)
        profiles = [f"{s}@{f}" for s in sizes for f in sorted(modes[s])]
        v.put("SUPPORTED_VIDEO_PROFILES", ",".join(profiles), video_row)

    digital: list[tuple[float, Row]] = []
    optical: list[tuple[float, Row]] = []
    for row in rows:
        section, key, value = row
        text = f"{key}: {value}"
        if not re.search(r"zoom|telephoto|periscope", text, re.I):
            continue
        digital += [(float(x), row) for x in
                    re.findall(r"digital\s+zoom\D{0,15}?(\d+(?:\.\d+)?)\s*x", text, re.I)]
        found = re.findall(r"optical(?:[- ]quality)?\s+zoom\s*(?:of\s*|up to\s*)?(\d+(?:\.\d+)?)\s*x", text, re.I)
        found += re.findall(r"(\d+(?:\.\d+)?)\s*x\s+(?:optical|telephoto)(?![^,;]*\b(?:out|range)\b)", text, re.I)
        if re.search(r"telephoto|periscope", text, re.I):
            found += re.findall(r"\((\d+(?:\.\d+)?)\s*x\)", text)
        optical += [(float(x), row) for x in found if float(x) > 1]
        out = re.search(r"(\d+(?:\.\d+)?)\s*x\s+optical(?:[- ]quality)?\s+zoom\s+out", text, re.I)
        if out and float(out.group(1)) > 1:
            v.put("MIN_ZOOM_RATIO", f"{1 / float(out.group(1)):g}", row)
    if digital:
        ratio, row = max(digital, key=lambda t: t[0])
        v.put("MAX_DIGITAL_ZOOM_RATIO", f"{ratio:g}", row)
        v.put("MAX_ZOOM_RATIO", f"{ratio:g}", row)
    if optical:
        v.put("SUPPORTED_OPTICAL_ZOOM_RATIOS", ",".join(f"{r:g}" for r in sorted({r for r, _ in optical})),
              optical[0][1])
        v.put("TELEPHOTO_CAMERA_SUPPORTED", "true", optical[0][1])

    for row in rows:
        section, key, value = row
        text = f"{key} {value}"
        camera_row = bool(_CAMERA.search(f"{section} {key}") or _MP.search(value))
        if re.search(r"ultra\s*-?\s*wide", text, re.I):
            v.put("ULTRAWIDE_CAMERA_SUPPORTED", "true", row)
            if re.search(r"ultra\s*-?\s*wide", key, re.I):
                mp = _MP.search(value)
            else:
                mp = re.search(r"(\d+(?:\.\d+)?)\s*MP\b[^+;]*?ultra\s*-?\s*wide", text, re.I)
            if mp:
                v.put("ULTRAWIDE_CAMERA", f"{float(mp.group(1)):g} MP ultra-wide camera", row)
        if re.search(r"telephoto|periscope", text, re.I):
            v.put("TELEPHOTO_CAMERA_SUPPORTED", "true", row)
        if (re.search(r"\bflash\b", key, re.I) and not re.fullmatch(r"(no|none|n/?a|-)", value, re.I)) or (
            camera_row and re.search(r"\bflash\b", value, re.I)
        ):
            v.put("FLASH_SUPPORTED", "true", row)
        if (re.search(r"auto\s*-?\s*focus", key, re.I) and not re.fullmatch(r"(no|none)", value, re.I)) or (
            camera_row and re.search(r"PDAF|auto\s*-?\s*focus|focus pixels", value, re.I)
        ):
            v.put("AUTOFOCUS_SUPPORTED", "true", row)
        if camera_row and not re.search(r"display|video|dolby|support", key, re.I):
            hdr = re.search(r"\b(smart\s+hdr(?:\s*\d+)?|hdr)\b", value, re.I)
            if hdr:
                v.put("SUPPORTED_HDR_MODE", hdr.group(1), row)
            if re.search(r"\bnight\b", value, re.I):
                v.put("NIGHT_MODE", "Night mode", row)
        if re.search(r"codec|video format", key, re.I):
            codec = re.search(r"\b(HEVC|H\.?265|H\.?264|AV1|VP9)\b", value, re.I)
            if codec:
                v.put("VIDEO_CODEC", codec.group(1), row)


def _display_values(rows: list[Row], v: _Values) -> None:
    disp = [r for r in rows
            if _DISPLAY.search(f"{r[0]} {r[1]}") and not _NOT_DISPLAY.search(r[1])
            and not _MP.search(r[2])]
    for row in disp:
        _section, key, value = row
        text = f"{key} {value}"
        dims = _DIMS.search(value)
        if dims and re.search(r"resolution|pixels|ppi|FHD|QHD|HD\+", text, re.I):
            a, b = int(dims.group(1)), int(dims.group(2))
            v.put("SPEC_RESOLUTION", f"{min(a, b)}x{max(a, b)}", row)
        ppi = re.search(r"(\d{3})\s*ppi", value, re.I)
        if ppi:
            v.put("SPEC_PPI", ppi.group(1), row)
        ratio = re.search(r"\b(\d{1,2}(?:\.\d)?)\s*:\s*(\d{1,2})\b", value)
        if ratio and re.search(r"ratio|aspect", text, re.I) and not re.search(r"contrast|body", key, re.I):
            v.put("SPEC_ASPECT_RATIO", f"{ratio.group(1)}:{ratio.group(2)}", row)
        if re.search(r"size|diagonal", text, re.I):
            inch = re.search(r"(\d+(?:\.\d+)?)\s*(?:-\s*)?(?:inch(?:es)?|in\b|″|\")", value, re.I)
            cm = re.search(r"(\d+(?:\.\d+)?)\s*cm\b", value, re.I)
            if inch:
                v.put("SPEC_SCREEN_SIZE_IN", inch.group(1), row)
            elif cm:
                v.put("SPEC_SCREEN_SIZE_IN", f"{float(cm.group(1)) / 2.54:.2f}", row, "converted from cm")
        for m in re.finditer(r"(\d{2,4})\s*Hz", value, re.I):
            around = value[max(0, m.start() - 25):m.end() + 8]
            hz = int(m.group(1))
            if re.search(r"touch|sampling", f"{key} {around}", re.I):
                v.put("SPEC_TOUCH_SAMPLING_HZ", hz, row)
            elif not re.search(r"pwm|dimming", around, re.I) and hz <= 240:
                cur = v.data.get("SPEC_PEAK_REFRESH_HZ")
                if cur is None or hz > int(cur["value"]):
                    v.data.pop("SPEC_PEAK_REFRESH_HZ", None)
                    v.put("SPEC_PEAK_REFRESH_HZ", hz, row)
        if not re.search(r"measured|min", key, re.I):
            for m in re.finditer(r"(\d[\d,]*)\s*nits", value, re.I):
                if re.search(r"measured", value[m.end():m.end() + 14], re.I):
                    continue
                nits = int(m.group(1).replace(",", ""))
                cur = v.data.get("SPEC_PEAK_BRIGHTNESS_NITS")
                if cur is None or nits > int(cur["value"]):
                    v.data.pop("SPEC_PEAK_BRIGHTNESS_NITS", None)
                    v.put("SPEC_PEAK_BRIGHTNESS_NITS", nits, row)
        panel = re.search(r"(LTPO\s*)?((?:Super|Dynamic|Fluid)\s+)?(AMOLED(?:\s*2X)?|P?OLED|LCD|IPS)", value, re.I)
        if panel and re.search(r"type|technology|panel", key, re.I):
            v.put("SPEC_PANEL_TYPE", panel.group(0).strip(), row)

    if "SPEC_ASPECT_RATIO" not in v.data and "SPEC_RESOLUTION" in v.data:
        w, h = (int(x) for x in v.data["SPEC_RESOLUTION"]["value"].split("x"))
        v.put("SPEC_ASPECT_RATIO", f"{round(h / w * 9 * 2) / 2:g}:9", None,
              f"derived from resolution {w}x{h}")
    cutout = re.compile(r"punch[- ]?hole|notch|dynamic island|water\s*drop", re.I)
    for row in rows:
        cut = cutout.search(row[2]) or cutout.search(row[1])
        if cut:
            v.put("SPEC_CUTOUT_TYPE", re.sub(r"punch[- ]?hole", "punch-hole", cut.group(0).lower()), row)
            break


def derive_spec_values(spec_features: list[dict[str, Any]] | None) -> dict[str, dict[str, str]]:
    """{VAR: {"value": str, "source": "section › parameter: value"}} for every mappable placeholder."""
    rows = spec_rows(spec_features)
    v = _Values()
    if rows:
        _camera_values(rows, v)
        _display_values(rows, v)
    return v.data


def fill_placeholders(obj: Any, values: dict[str, str]) -> Any:
    """Copy of obj with every ${VAR} that has a value replaced; unknown placeholders stay."""
    if isinstance(obj, str):
        return PLACEHOLDER_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, dict):
        return {k: fill_placeholders(val, values) for k, val in obj.items()}
    if isinstance(obj, list):
        return [fill_placeholders(val, values) for val in obj]
    return obj


def placeholders_in(obj: Any) -> set[str]:
    return set(PLACEHOLDER_RE.findall(json.dumps(obj, default=str)))
