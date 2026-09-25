"""Heuristics to distinguish real section/feature titles from values and page chrome.

Device-agnostic: rejects *shapes* of values (resolutions, bands, phone numbers),
not a fixed phone/laptop taxonomy. Uses a soft allow-list only for short
single-token module names that appear across many product categories.
"""

from __future__ import annotations

import re

# Webpage / brochure chrome — never treat as product feature modules
NAV_OR_CHROME = re.compile(
    r"^(reviews?|buy now|shop|compare|features|experience live demo|"
    r"accessories|specifications|contents|table of contents|toc|home|menu|"
    r"support|contact us|share|print|download|privacy|cookies?|"
    r"for all product related.*|manufactured by.*)$",
    re.I,
)

VALUE_LIKE = re.compile(
    r"""^(?:
        \d[\d\s,.x×*/+\-]*\s*(?:hz|mhz|ghz|mp|gb|tb|mb|kb|mah|mm|cm|inch|inches|w|v|fps|nit|nits)?
        | \d{2,5}\s*[x×]\s*\d{2,5}(?:\s*\([^)]+\))?
        | f\d+(?:\.\d+)?(?:\s*,\s*f\d+(?:\.\d+)?)*
        | @?\s*uhd\b.*
        | [bn]\d{1,3}\s*\([^)]+\)(?:\s*,\s*[bn]\d{1,3}\s*\([^)]+\))*
        | \d{3,5}(?:\s+\d{2,5}){1,4}(?:\s*\([^)]*\))?
        | https?://\S+
        | \d{1,2}/\d{1,2}/\d{2,4}.*
        | \d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|
            jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}
        | [\w.+-]+@[\w.-]+
        | (?:mp4|m4v|3gp|avi|mkv|webm|mp3|aac|flac|wav|ogg|pdf|amr|awb|mid|midi)
          (?:\s*,\s*[\w.+]+)*
        | (?:imy|rtttl|rtx|ota|dff|dsf|ape|xmf|mxmf)(?:\s*,\s*[\w.+]+)*
        | \d+\.\d+\s*mp(?:\s*\+\s*\d+\.\d+\s*mp)+
        | 4096-?qam
        | yes|no|true|false
        | \d+g\s+(?:gsm|umts|wcdma|lte|fdd|tdd).*
    )$""",
    re.I | re.VERBOSE,
)

MOSTLY_NUMERIC = re.compile(r"^[\d\s,.x×+\-/%()]+$", re.I)

# Soft allow-list for short module names (cross-device engineering labels).
GENERIC_MODULE_TOKENS = {
    "processor", "cpu", "display", "camera", "battery", "storage", "memory",
    "network", "connectivity", "sensors", "sensor", "audio", "video", "security",
    "power", "physical", "design", "wireless", "software", "hardware", "ports",
    "interfaces", "os", "chassis", "thermal", "environmental", "io",
    "nfc", "bluetooth", "wifi", "usb", "gps", "cellular", "radio",
    "mechanical", "electrical", "optics", "lens", "flash", "charging",
    "dimensions", "weight", "materials", "packaging", "warranty", "compliance",
    "performance", "multimedia", "location", "sim", "bearer",
}

COLORISH = re.compile(
    r"^(black|white|blue|red|green|yellow|pink|gold|silver|grey|gray|navy|"
    r"mint|coral|ivory|cream|orange|purple|violet|cyan|magenta|beige|bronze|"
    r"graphite|titanium|icyblue|blueblack|coralred|pinkgold|shadow)$",
    re.I,
)


def is_nav_or_chrome(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if NAV_OR_CHROME.match(t):
        return True
    if "\n" in t and any(NAV_OR_CHROME.match(ln.strip()) for ln in t.split("\n") if ln.strip()):
        return True
    low = t.lower()
    if low.startswith("for all product"):
        return True
    return False


def is_value_like_title(title: str) -> bool:
    t = (title or "").strip().rstrip(",")
    if not t:
        return True
    if len(t) > 80:
        return True
    if VALUE_LIKE.match(t):
        return True
    if MOSTLY_NUMERIC.match(t):
        return True
    if COLORISH.match(t):
        return True
    digits = sum(c.isdigit() for c in t)
    letters = sum(c.isalpha() for c in t)
    if digits >= 3 and digits >= letters:
        return True
    if t.count(",") >= 2:
        return True
    if (title or "").strip().endswith(","):
        return True
    return False


def is_valid_feature_section_title(title: str) -> bool:
    t = (title or "").strip()
    if not t or len(t) < 2:
        return False
    if is_nav_or_chrome(t):
        return False
    if is_value_like_title(t):
        return False
    if not re.search(r"[A-Za-z]", t):
        return False
    words = [w for w in re.split(r"[\s/]+", t) if w]
    if len(words) > 6:
        return False

    norms = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in words]

    # Single-token: reject junk; allow generic modules, acronyms, or plain alpha labels
    if len(words) == 1:
        tok = norms[0]
        if tok in GENERIC_MODULE_TOKENS:
            return True
        if words[0].isalpha() and words[0].isupper() and 2 <= len(words[0]) <= 5:
            return True
        # Plain alphabetic label (e.g. Design already covered; Alpha for tests)
        if words[0].isalpha() and len(words[0]) >= 3:
            return True
        return False

    # Multi-word with a known module token
    if any(n in GENERIC_MODULE_TOKENS for n in norms):
        return True

    # Multi-word alphabetic labels without digits (General Information, etc.)
    if digits_count(t) == 0 and all(w[0].isalpha() for w in words if w):
        # Reject product model lines like "Galaxy S25" (letter+digit model pattern in words)
        if any(re.search(r"[a-zA-Z]+\d|\d+[a-zA-Z]", w) for w in words):
            return False
        # Reject 4G Fdd Lte style if starts with digit+G
        if re.match(r"^\d+g\b", t, re.I):
            return False
        return True

    return False


def digits_count(s: str) -> int:
    return sum(c.isdigit() for c in s)


def looks_like_parameter_label(text: str) -> bool:
    t = (text or "").strip()
    if not t or "\n" in t:
        return False
    if is_value_like_title(t) or is_nav_or_chrome(t):
        return False
    if len(t) > 60:
        return False
    if MOSTLY_NUMERIC.match(t):
        return False
    return bool(re.search(r"[A-Za-z]", t))


def looks_like_parameter_value(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "\n" in t and len(t) > 120:
        return False
    return is_value_like_title(t) or bool(re.search(r"\d", t)) or t.lower() in {"yes", "no"}
