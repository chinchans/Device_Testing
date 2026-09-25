"""Reassign mis-bucketed specs into the correct product modules after LLM normalize."""

from __future__ import annotations

import re
from typing import Any


# Canonical module titles used for RAG-friendly indexing / extraction.
CANONICAL_MODULES = {
    "operating system": "Operating System",
    "os": "Operating System",
    "camera": "Camera",
    "rear camera": "Camera",
    "front camera": "Camera",
    "connectivity": "Connectivity",
    "wireless connectivity": "Connectivity",
    "wireless": "Connectivity",
    "wifi": "Connectivity",
    "wi-fi": "Connectivity",
    "bluetooth": "Connectivity",
    "cellular & sim": "Cellular & SIM",
    "cellular and sim": "Cellular & SIM",
    "cellular": "Cellular & SIM",
    "network": "Cellular & SIM",
    "cellular and wireless": "Cellular & SIM",
    "display & touchscreen": "Display & Touchscreen",
    "display and touchscreen": "Display & Touchscreen",
    "display": "Display & Touchscreen",
    "processor & performance": "Processor & Performance",
    "processor and performance": "Processor & Performance",
    "processor": "Processor & Performance",
    "chipset": "Processor & Performance",
    "memory & storage": "Memory & Storage",
    "memory and storage": "Memory & Storage",
    "memory": "Memory & Storage",
    "storage": "Memory & Storage",
    "storage & ram": "Memory & Storage",
    "capacity": "Memory & Storage",  # Apple "Capacity" = storage SKUs
    "battery & charging": "Battery & Charging",
    "battery and charging": "Battery & Charging",
    "battery": "Battery & Charging",
    "charging": "Battery & Charging",
    "power and battery": "Battery & Charging",
    "power & battery": "Battery & Charging",
    "sensors": "Sensors",
    "sensor": "Sensors",
    "biometrics": "Sensors",
    "audio & usb": "Audio",
    "audio and usb": "Audio",
    "audio": "Audio",
    "usb": "USB",
    "throughput": "Throughput",
}

_STORAGE_VALUE = re.compile(
    r"\b\d+(\.\d+)?\s*(gb|tb)\b(?:\s*,\s*\d+(\.\d+)?\s*(gb|tb)\b)*",
    re.I,
)
_BATTERY_VALUE = re.compile(
    r"\b\d+(\.\d+)?\s*(mah|wh|w)\b|\b(charging|magsafe|qi2?|battery\s*life|video\s*playback)\b",
    re.I,
)

# Spec text → target canonical module (checked against key + value)
_SPEC_ROUTES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(face\s*id|touch\s*id|lidar|magnetometer|magnet\s*array|"
                r"alignment\s*magnet|accelerometer|gyroscope|barometer|"
                r"proximity|ambient\s*light|fingerprint|compass)\b", re.I),
     "Sensors"),
    (re.compile(r"\b(storage|capacity|ram|rom|ufs|microsd|micro\s*sd|"
                r"internal\s*storage|user\s*available)\b", re.I),
     "Memory & Storage"),
    (re.compile(r"\b(battery|charging|charger|magsafe|qi2?|mah|watt\s*charge|"
                r"fast[- ]?charge|wireless\s*charg|video\s*playback|"
                r"audio\s*playback|talk\s*time)\b", re.I),
     "Battery & Charging"),
    (re.compile(r"\b(display|screen|refresh|brightness|oled|amoled|lcd|"
                r"resolution|ppi|nits|true\s*tone|pro\s*motion)\b", re.I),
     "Display & Touchscreen"),
    (re.compile(r"\b(camera|megapixel|\bmp\b|aperture|optical\s*zoom|"
                r"ultra\s*wide|telephoto|selfie|video\s*recording)\b", re.I),
     "Camera"),
    (re.compile(r"\b(wi-?fi|wlan|bluetooth|nfc|hotspot|802\.11)\b", re.I),
     "Connectivity"),
    (re.compile(r"\b(sim|5g|4g|lte|gsm|umts|cellular|volte|band)\b", re.I),
     "Cellular & SIM"),
    (re.compile(r"\b(processor|chipset|cpu|gpu|soc|a\d+\s*pro|snapdragon|"
                r"dimensity|exynos|tensor|core)\b", re.I),
     "Processor & Performance"),
    (re.compile(r"\b(speaker|microphone|\bmic\b|audio|jack|headphone|dolby|stereo)\b", re.I),
     "Audio"),
    (re.compile(r"\b(usb|type-?c|displayport)\b", re.I),
     "USB"),
    (re.compile(r"\b(ios|ipados|android|hyperos|one\s*ui|operating\s*system|"
                r"os\s*version)\b", re.I),
     "Operating System"),
]


def canonicalize_module_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return n
    key = re.sub(r"\s+", " ", n.lower())
    return CANONICAL_MODULES.get(key, n)


def _infer_module_for_spec(key: str, value: str, current_module: str) -> str:
    """Pick the best module for a single key/value; prefer current if compatible."""
    blob = f"{key} {value}".strip()
    current = canonicalize_module_name(current_module)

    # Storage SKU values (256GB, 512GB, …) never belong under Battery
    if _STORAGE_VALUE.search(value) and not _BATTERY_VALUE.search(blob):
        return "Memory & Storage"
    if _STORAGE_VALUE.search(key) and "battery" not in key.lower():
        return "Memory & Storage"

    for pattern, target in _SPEC_ROUTES:
        if pattern.search(blob):
            # If current module already matches this family, keep it
            if canonicalize_module_name(current) == target:
                return target
            # Battery module must not keep storage/sensor rows
            if current == "Battery & Charging" and target in {
                "Memory & Storage",
                "Sensors",
                "Camera",
                "Display & Touchscreen",
                "Processor & Performance",
                "Audio",
                "USB",
                "Connectivity",
            }:
                return target
            # Capacity / Memory mislabeled sections
            if current in {"Memory & Storage", "Capacity"} or "capacity" in current.lower():
                if target == "Memory & Storage":
                    return target
            return target

    return current


def remap_normalized_modules(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Rename modules to canonical titles and move mis-placed specs
    (e.g. storage SKUs / Face ID under Battery → correct modules).
    """
    product_name = payload.get("product_name")
    buckets: dict[str, dict[str, Any]] = {}

    def slot_for(name: str) -> dict[str, Any]:
        canon = canonicalize_module_name(name)
        key = canon.lower()
        if key not in buckets:
            buckets[key] = {
                "name": canon,
                "specs": [],
                "notes": [],
                "_spec_keys": set(),
            }
        return buckets[key]

    for mod in payload.get("modules") or []:
        if not isinstance(mod, dict):
            continue
        raw_name = str(mod.get("name") or "").strip()
        if not raw_name:
            continue
        for sp in mod.get("specs") or []:
            if not isinstance(sp, dict):
                continue
            k = str(sp.get("key") or "").strip()
            v = str(sp.get("value") or "").strip()
            if not k or not v:
                continue
            target = _infer_module_for_spec(k, v, raw_name)
            dest = slot_for(target)
            sk = k.lower()
            if sk in dest["_spec_keys"]:
                continue
            dest["_spec_keys"].add(sk)
            dest["specs"].append({"key": k, "value": v})
        for note in mod.get("notes") or []:
            n = str(note).strip()
            if not n:
                continue
            # Notes follow module rename; if note looks like storage under battery, rehome
            target = _infer_module_for_spec(n, "", raw_name)
            dest = slot_for(target)
            if n not in dest["notes"]:
                dest["notes"].append(n)

    modules = []
    for slot in buckets.values():
        if not slot["specs"] and not slot["notes"]:
            continue
        modules.append(
            {
                "name": slot["name"],
                "specs": slot["specs"],
                "notes": slot["notes"],
            }
        )

    priority = {
        "operating system": 0,
        "camera": 1,
        "connectivity": 2,
        "cellular & sim": 3,
        "display & touchscreen": 4,
        "processor & performance": 5,
        "memory & storage": 6,
        "battery & charging": 7,
        "sensors": 8,
        "audio": 9,
        "usb": 10,
    }
    # Kept in the index for Device Classification (OS/CPU/RAM/Storage) even though
    # they are not default Feature Extraction checklist cards.
    modules.sort(key=lambda m: (priority.get(m["name"].lower(), 50), m["name"].lower()))
    return {"product_name": product_name, "modules": modules}
