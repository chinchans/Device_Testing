"""Strip webpage / brochure chrome from extracted PDF text lines."""

from __future__ import annotations

import re

# Full-line (or near full-line) chrome — cookies, nav, legal, site chrome
_CHROME_LINE_RE = re.compile(
    r"(?:"
    r"cookie\s*settings|accept\s*all|decline\s*all|learn\s*more|"
    r"first\s+and\s+third[- ]party\s+cookies|third[- ]party\s+cookies|"
    r"personalized\s+content|tailored\s+ads|"
    r"maintain\s+the\s+essential\s+functionality|"
    r"detect\s+website\s+performance|"
    r"select\s+an\s+option\s+or\s+go\s+to\s+cookie|"
    r"manage\s+your\s+preferences|"
    r"copyright\s*©|all\s+rights\s+reserved|"
    r"privacy\s+policy|user\s+agreement|cookie\s+policy|sitemap|"
    r"enter\s+(?:your\s+)?email|subscribe\s+to\s+our\s+newsletter|"
    r"follow\s+\w+|share\s+this|buy\s+now|add\s+to\s+cart|"
    r"global\s*/\s*global|recommended\s*$|"
    r"eu\s+declaration\s+of\s+conformity|"
    r"digital\s+services\s+act|investor\s+relations|"
    r"mobile\s+wearables|smart\s+home\s+lifestyle|"
    r"about\s+us\s+support\s+community|"
    r"support\s+community|"
    r"data\s+obtained\s+from|"
    r"available\s+storage\s+and\s+ram\s+are\s+less|"
    r"storages?\s+and\s+configuration\s+may\s+vary|"
    r"^\s*\d+\s*of\s*\d+\s*$|"
    r"^\s*\d+\s*/\s*\d+\s*$"
    r")",
    re.I,
)

# Short nav-only lines common on brand marketing PDFs
_NAV_ONLY_RE = re.compile(
    r"^(?:"
    r"home|menu|overview|specs?|support|community|about\s*us\.?|"
    r"contact\s*us|shop|store|compare|reviews?|newsroom|"
    r"mobile|wearables|smart\s*home|lifestyle|auto|"
    r"xiaomi\s+projects|poco\s+brand|leadership\s+team|"
    r"user\s+guide|warranty|international\s+warranty|"
    r"cookie\s+settings|accept\s+all|decline\s+all|"
    r"data\s+obtained\s+from\b.*"
    r")\.?$",
    re.I,
)

# Lines that are mostly a concatenation of nav tokens
_NAV_TOKEN_RE = re.compile(
    r"\b(?:home|menu|overview|specs?|support|community|about\s*us|"
    r"mobile|wearables|lifestyle|shop|store|compare|reviews?|"
    r"newsroom|contact)\b",
    re.I,
)

# Single-character / glyph OCR noise from image chrome
_NOISE_ONLY_RE = re.compile(r"^[\W_\d]{1,3}$")


def is_chrome_line(line: str) -> bool:
    """True if a line is website/nav/cookie chrome rather than product content."""
    t = (line or "").strip()
    if not t:
        return True
    if len(t) <= 2 and not t.isalnum():
        return True
    if _NOISE_ONLY_RE.match(t) and not any(c.isalnum() for c in t):
        return True
    if _NAV_ONLY_RE.match(t):
        return True
    if _CHROME_LINE_RE.search(t):
        return True
    # Multi-token nav bars glued into one OCR line
    nav_hits = len(_NAV_TOKEN_RE.findall(t))
    if nav_hits >= 2 and len(t) < 120 and not re.search(r"\d", t):
        return True
    return False


def chrome_line_ratio(text: str) -> float:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return 1.0
    chrome = sum(1 for ln in lines if is_chrome_line(ln))
    return chrome / len(lines)


def strip_chrome_text(text: str) -> str:
    """Remove chrome lines from a page or block of text."""
    if not text:
        return ""
    kept: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if is_chrome_line(s):
            continue
        kept.append(s)
    # Collapse runs of duplicate lines (banner leftovers)
    out: list[str] = []
    prev = None
    for ln in kept:
        if ln == prev:
            continue
        out.append(ln)
        prev = ln
    return "\n".join(out).strip()


def is_chrome_heavy(text: str, *, min_ratio: float = 0.35) -> bool:
    """True when a large share of lines look like site chrome."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 4:
        return chrome_line_ratio(text) >= 0.5
    return chrome_line_ratio(text) >= min_ratio
