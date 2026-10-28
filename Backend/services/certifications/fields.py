"""Extract certificate fields (issuer, ID, manufacturer, model, dates) from document text."""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger

from .definitions import CertificateDef

FIELD_KEYS = ("issuer", "certificate_id", "manufacturer", "model", "issue_date", "expiry_date")
LLM_TEXT_CHARS = 12_000

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}

_DATE_PATTERNS = (
    re.compile(r"(?P<y>\d{4})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})"),
    re.compile(r"(?P<d>\d{1,2})[-/.](?P<m>\d{1,2})[-/.](?P<y>\d{4})"),
    re.compile(r"(?P<d>\d{1,2})(?:st|nd|rd|th)?[ \-](?P<mon>[A-Za-z]{3,9})\.?,?[ \-](?P<y>\d{4})"),
    re.compile(r"(?P<mon>[A-Za-z]{3,9})\.?[ \-](?P<d>\d{1,2})(?:st|nd|rd|th)?,?[ \-](?P<y>\d{4})"),
)


def normalize_date(value: str | None) -> str:
    """Return an ISO date (YYYY-MM-DD) or "" when the value is not a recognisable date."""
    if not value:
        return ""
    value = str(value).strip()
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        pass
    for pattern in _DATE_PATTERNS:
        m = pattern.search(value)
        if not m:
            continue
        parts = m.groupdict()
        try:
            month = _MONTHS.get(parts["mon"].lower()) if parts.get("mon") else int(parts["m"])
            if not month:
                continue
            return date(int(parts["y"]), month, int(parts["d"])).isoformat()
        except (ValueError, TypeError):
            continue
    return ""


def _labelled_value(text: str, labels: str, value_re: str) -> str:
    m = re.search(rf"(?:{labels})\s*[:\-]?\s*({value_re})", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


_ANY_DATE = (
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)?[ \-][A-Za-z]{3,9}\.?,?[ \-]\d{4}|[A-Za-z]{3,9}\.?[ \-]\d{1,2}(?:st|nd|rd|th)?,?[ \-]\d{4}"
)


def regex_fields(text: str, cert: CertificateDef) -> dict[str, str]:
    """Deterministic fallback used when the LLM is unavailable or leaves gaps."""
    id_labels = re.escape(cert.id_label) + r"|certificate (?:id|no\.?|number)|certification id|declaration id|qdid|grant (?:id|no\.?)"
    fields = {
        "issuer": "",
        "certificate_id": _labelled_value(text, id_labels, r"[A-Za-z0-9][A-Za-z0-9\-_/.]{3,30}"),
        "manufacturer": _labelled_value(text, r"manufacturer|grantee|applicant|company", r"[^\n]{2,80}"),
        "model": _labelled_value(text, r"model(?: name| number| no\.?)?|product name|device name", r"[^\n]{1,80}"),
        "issue_date": normalize_date(
            _labelled_value(text, r"date of issue|issue date|issued on|issued|grant date|date of grant|certification date", _ANY_DATE)
        ),
        "expiry_date": normalize_date(
            _labelled_value(text, r"expiry date|expiration date|expires on|expires|valid until|valid through|validity", _ANY_DATE)
        ),
    }
    lowered = text.lower()
    for issuer in cert.issuers:
        if issuer.lower() in lowered:
            fields["issuer"] = issuer
            break
    return fields


def _llm_fields(text: str, cert: CertificateDef) -> dict[str, str] | None:
    system = (
        "You read regulatory certificate documents and return JSON only. "
        "Use only values literally present in the document; use an empty string when a value is absent. "
        "Never invent or infer values."
    )
    user = (
        f"Certificate type: {cert.name} ({cert.desc}). The identifier is called '{cert.id_label}'.\n"
        "Return a JSON object with exactly these keys:\n"
        '{"issuer": "organisation that issued or granted the certificate", '
        f'"certificate_id": "the {cert.id_label}", '
        '"manufacturer": "manufacturer / grantee / applicant company", '
        '"model": "device model name or number", '
        '"issue_date": "YYYY-MM-DD", "expiry_date": "YYYY-MM-DD"}\n\n'
        f"Document text:\n{text[:LLM_TEXT_CHARS]}"
    )
    try:
        content, _ = chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("Certificate field extraction via LLM failed: %s", exc)
        return None
    data = parse_json_content(content)
    if not isinstance(data, dict):
        logger.warning("Certificate field extraction returned non-JSON: %s", json.dumps(content)[:200])
        return None
    return {k: str(data.get(k) or "").strip() for k in FIELD_KEYS}


def extract_fields(text: str, cert: CertificateDef, *, use_llm: bool = True) -> tuple[dict[str, str], str]:
    """Return (fields, method). LLM values win; regex fills any gaps."""
    fallback = regex_fields(text, cert)
    if not text.strip():
        return fallback, "none"
    llm = _llm_fields(text, cert) if use_llm and is_azure_configured() else None
    if llm is None:
        return fallback, "regex"
    merged = {k: llm.get(k) or fallback.get(k, "") for k in FIELD_KEYS}
    merged["issue_date"] = normalize_date(merged["issue_date"])
    merged["expiry_date"] = normalize_date(merged["expiry_date"])
    return merged, "llm"


def today() -> date:
    return datetime.now().date()
