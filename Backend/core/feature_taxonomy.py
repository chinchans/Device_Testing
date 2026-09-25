"""Device-type standard feature checklists.

Extraction still discovers evidence from the document; classification maps
that evidence onto these stable labels so the UI can tick found items and
only surface strong, relevant extras.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StandardFeatureDef:
    id: str
    name: str
    order: int
    synonyms: tuple[str, ...]


MOBILE_STANDARD_FEATURES: tuple[StandardFeatureDef, ...] = (
    StandardFeatureDef(
        id="camera",
        name="Camera",
        order=1,
        synonyms=(
            "camera", "cameras", "rear camera", "front camera", "selfie",
            "photography", "video recording", "main camera", "ultrawide",
            "telephoto", "macro camera", "depth camera",
        ),
    ),
    StandardFeatureDef(
        id="connectivity",
        name="Connectivity",
        order=2,
        synonyms=(
            "connectivity", "wireless", "wireless connectivity",
            "wifi", "wi-fi", "wi fi", "bluetooth", "nfc", "wlan",
            "hotspot", "cast",
        ),
    ),
    StandardFeatureDef(
        id="cellular",
        name="Cellular & SIM",
        order=3,
        synonyms=(
            "cellular", "cellular & sim", "cellular and sim", "sim", "network",
            "networks", "bearer", "5g", "4g", "lte", "gsm", "umts", "wcdma",
            "bands", "network bands", "dual sim", "esa", "volte", "vowifi",
        ),
    ),
    StandardFeatureDef(
        id="display",
        name="Display & Touchscreen",
        order=4,
        synonyms=(
            "display", "display & touchscreen", "display and touchscreen",
            "screen", "touchscreen", "touch screen", "panel", "amoled", "lcd",
            "refresh rate", "resolution", "brightness",
        ),
    ),
    StandardFeatureDef(
        id="battery",
        name="Battery & Charging",
        order=5,
        synonyms=(
            "battery", "battery & charging", "battery and charging", "charging",
            "fast charging", "power", "charger", "wireless charging", "mah",
            "power and battery", "power & battery",
        ),
    ),
    StandardFeatureDef(
        id="sensors",
        name="Sensors",
        order=6,
        synonyms=(
            "sensors", "sensor", "fingerprint", "accelerometer", "gyroscope",
            "proximity", "ambient light", "compass", "barometer", "hall",
            "biometric", "biometrics", "face id", "touch id", "lidar",
            "magnetometer",
        ),
    ),
    StandardFeatureDef(
        id="audio",
        name="Audio",
        order=7,
        synonyms=(
            "audio", "speaker", "speakers", "microphone", "mic", "headphone",
            "3.5mm", "jack", "dolby", "stereo",
        ),
    ),
    StandardFeatureDef(
        id="usb",
        name="USB",
        order=8,
        synonyms=(
            "usb", "type-c", "type c", "usb-c", "usb c", "ports",
            "usb 3", "usb 2", "displayport",
        ),
    ),
)

# Reserved for later device types — empty means checklist disabled (extras only).
LAPTOP_STANDARD_FEATURES: tuple[StandardFeatureDef, ...] = ()
TABLET_STANDARD_FEATURES: tuple[StandardFeatureDef, ...] = ()
WEARABLE_STANDARD_FEATURES: tuple[StandardFeatureDef, ...] = ()

_TAXONOMIES: dict[str, tuple[StandardFeatureDef, ...]] = {
    "mobile": MOBILE_STANDARD_FEATURES,
    "phone": MOBILE_STANDARD_FEATURES,
    "smartphone": MOBILE_STANDARD_FEATURES,
    "laptop": LAPTOP_STANDARD_FEATURES,
    "tablet": TABLET_STANDARD_FEATURES,
    "wearable": WEARABLE_STANDARD_FEATURES,
}


def normalize_device_type(device_type: str | None) -> str | None:
    if not device_type:
        return None
    key = device_type.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "mobile_phone": "mobile",
        "smart_phone": "mobile",
        "smartphones": "mobile",
    }
    return aliases.get(key, key)


def get_taxonomy(device_type: str | None) -> tuple[StandardFeatureDef, ...]:
    """Return the standard checklist for a device type (default: mobile)."""
    key = normalize_device_type(device_type) or "mobile"
    return _TAXONOMIES.get(key, MOBILE_STANDARD_FEATURES)


def taxonomy_has_standards(device_type: str | None) -> bool:
    return bool(get_taxonomy(device_type))
