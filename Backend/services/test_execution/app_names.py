"""Human-readable app names derived from Android package names.

adb cannot read an app's label without pulling and decoding its APK, so names come from
a table of well-known packages (AOSP, Google, common OEM skins, popular apps) and, for
anything else, from the package name itself:

    com.google.android.apps.youtube.music -> "YouTube Music"   (known)
    com.coloros.weather2                  -> "Weather"         (known)
    com.acme.fieldsurvey                  -> "Fieldsurvey"     (derived: last meaningful segment)
    com.acme.android.trip_planner         -> "Trip Planner"    (derived: underscores / camelCase split)
"""

from __future__ import annotations

import re

KNOWN_APPS: dict[str, str] = {
    # AOSP
    "com.android.camera": "Camera",
    "com.android.camera2": "Camera",
    "com.android.chrome": "Chrome",
    "com.android.settings": "Settings",
    "com.android.stk": "SIM Toolkit",
    "com.android.vending": "Play Store",
    "com.android.contacts": "Contacts",
    "com.android.dialer": "Phone",
    "com.android.mms": "Messages",
    "com.android.messaging": "Messages",
    "com.android.deskclock": "Clock",
    "com.android.calculator2": "Calculator",
    "com.android.calendar": "Calendar",
    "com.android.gallery3d": "Gallery",
    "com.android.documentsui": "Files",
    "com.android.email": "Email",
    "com.android.music": "Music",
    "com.android.soundrecorder": "Sound Recorder",
    "com.android.fmradio": "FM Radio",
    "com.android.browser": "Browser",
    "com.android.thememanager": "Themes",
    # Google
    "com.google.android.dialer": "Phone",
    "com.google.android.contacts": "Contacts",
    "com.google.android.apps.messaging": "Messages",
    "com.google.android.deskclock": "Clock",
    "com.google.android.calculator": "Calculator",
    "com.google.android.calendar": "Calendar",
    "com.google.android.documentsui": "Files",
    "com.google.android.apps.nbu.files": "Files by Google",
    "com.google.android.gm": "Gmail",
    "com.google.android.googlequicksearchbox": "Google",
    "com.google.android.youtube": "YouTube",
    "com.google.android.apps.youtube.music": "YouTube Music",
    "com.google.android.apps.docs": "Drive",
    "com.google.android.apps.docs.editors.docs": "Docs",
    "com.google.android.apps.docs.editors.sheets": "Sheets",
    "com.google.android.apps.docs.editors.slides": "Slides",
    "com.google.android.apps.maps": "Maps",
    "com.google.android.apps.photos": "Photos",
    "com.google.android.keep": "Keep Notes",
    "com.google.android.apps.tachyon": "Meet",
    "com.google.android.apps.walletnfcrel": "Wallet",
    "com.google.android.apps.nbu.paisa.user": "Google Pay",
    "com.google.android.apps.googleassistant": "Assistant",
    "com.google.android.apps.recorder": "Recorder",
    "com.google.android.GoogleCamera": "Camera",
    "com.google.android.apps.magazines": "Google News",
    "com.google.android.videos": "Google TV",
    "com.google.android.apps.podcasts": "Podcasts",
    "com.google.android.apps.fitness": "Fit",
    "com.google.android.apps.subscriptions.red": "Google One",
    "com.google.android.apps.chromecast.app": "Google Home",
    "com.google.android.apps.translate": "Translate",
    "com.google.ar.lens": "Lens",
    "com.google.android.apps.wellbeing": "Digital Wellbeing",
    "com.google.android.apps.safetyhub": "Personal Safety",
    # realme / OPPO / OnePlus (ColorOS)
    "com.oplus.camera": "Camera",
    "com.oppo.camera": "Camera",
    "com.coloros.gallery3d": "Photos",
    "com.coloros.filemanager": "File Manager",
    "com.coloros.calculator": "Calculator",
    "com.coloros.alarmclock": "Clock",
    "com.coloros.weather2": "Weather",
    "com.coloros.compass2": "Compass",
    "com.coloros.soundrecorder": "Recorder",
    "com.coloros.note": "Notes",
    "com.oneplus.note": "Notes",
    "com.coloros.phonemanager": "Phone Manager",
    "com.coloros.backuprestore": "Backup & Restore",
    "com.coloros.gamespace": "Game Space",
    "com.oplus.games": "Game Space",
    "com.heytap.market": "App Market",
    "com.heytap.browser": "Browser",
    "com.heytap.music": "Music",
    "com.heytap.themestore": "Theme Store",
    "com.heytap.cloud": "Cloud",
    "com.realme.link": "realme Link",
    # Samsung
    "com.sec.android.app.camera": "Camera",
    "com.sec.android.gallery3d": "Gallery",
    "com.samsung.android.dialer": "Phone",
    "com.samsung.android.messaging": "Messages",
    "com.sec.android.app.myfiles": "My Files",
    "com.sec.android.app.popupcalculator": "Calculator",
    "com.sec.android.app.clockpackage": "Clock",
    "com.samsung.android.app.notes": "Samsung Notes",
    "com.sec.android.app.sbrowser": "Samsung Internet",
    # Xiaomi
    "com.miui.gallery": "Gallery",
    "com.miui.securitycenter": "Security",
    "com.miui.calculator": "Calculator",
    "com.mi.android.globalFileexplorer": "File Manager",
    # Popular third-party
    "com.whatsapp": "WhatsApp",
    "com.facebook.katana": "Facebook",
    "com.facebook.orca": "Messenger",
    "com.instagram.android": "Instagram",
    "com.netflix.mediaclient": "Netflix",
    "com.spotify.music": "Spotify",
    "in.amazon.mShop.android.shopping": "Amazon",
    "com.amazon.mShop.android.shopping": "Amazon Shopping",
    "com.linkedin.android": "LinkedIn",
    "com.twitter.android": "X",
    "org.telegram.messenger": "Telegram",
    "com.snapchat.android": "Snapchat",
    "com.zhiliaoapp.musically": "TikTok",
    "com.phonepe.app": "PhonePe",
    "net.one97.paytm": "Paytm",
    "com.microsoft.teams": "Teams",
    "com.microsoft.office.outlook": "Outlook",
    "us.zoom.videomeetings": "Zoom",
    "com.jio.myjio": "MyJio",
    # Test harness APKs (this project)
    "com.example.cameratest": "Camera Test Harness",
    "com.example.cameraunauthorized": "Camera Harness (Unauthorized Helper)",
    "com.example.camerasecondary": "Camera Harness (Secondary Helper)",
    "com.example.displaytest": "Display Test Harness",
}

_TLDS = {"com", "org", "net", "in", "io", "co", "us", "uk", "de", "cn", "jp", "me", "tv", "app", "dev"}
# Segments that name a platform, vendor or packaging detail rather than the app.
_GENERIC = {
    "android", "google", "apps", "app", "application", "mobile", "client", "main", "lite", "free",
    "pro", "release", "prod", "phone", "oplus", "coloros", "oppo", "heytap", "realme", "oneplus",
    "samsung", "sec", "miui", "xiaomi", "huawei", "vivo", "motorola", "mediaclient", "example",
}
_ACRONYMS = {"sim": "SIM", "fm": "FM", "pdf": "PDF", "vpn": "VPN", "nfc": "NFC", "tv": "TV", "ar": "AR", "ui": "UI"}


def _words(segment: str) -> list[str]:
    segment = re.sub(r"\d+$", "", segment)
    segment = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", segment)
    return [w for w in re.split(r"[\s_\-]+", segment) if w]


def derive_name(package: str) -> str:
    """Readable name from the package alone: last segment that is not a TLD / vendor / generic word."""
    parts = [p for p in package.split(".") if p]
    if len(parts) > 1 and parts[0].lower() in _TLDS:
        parts = parts[1:]
    meaningful = [p for p in parts if p.lower() not in _GENERIC and _words(p)]
    segment = meaningful[-1] if meaningful else (parts[0] if parts else package)
    words = _words(segment) or [segment]
    return " ".join(_ACRONYMS.get(w.lower(), w[:1].upper() + w[1:]) for w in words)


def app_name(package: str) -> tuple[str, str]:
    """(display name, source) where source is "known" (curated table) or "package" (derived)."""
    if package in KNOWN_APPS:
        return KNOWN_APPS[package], "known"
    return derive_name(package), "package"
