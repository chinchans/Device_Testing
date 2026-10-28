"""Rule checks for one certificate document. Each check: ok True (pass), False (fail), None (not checkable)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .classify import content_scores
from .definitions import GENERIC_ID_RE, CertificateDef
from .text import SUPPORTED_EXTENSIONS

MIN_READABLE_CHARS = 30


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def loosely_matches(a: str, b: str) -> bool:
    x, y = _norm(a), _norm(b)
    return bool(x and y and (x in y or y in x))


def _parse(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _check(label: str, ok: bool | None, detail: str = "") -> dict[str, Any]:
    return {"label": label, "ok": ok, "detail": detail}


def run_checks(
    cert: CertificateDef,
    *,
    file_name: str,
    text: str,
    fields: dict[str, str],
    device: dict[str, str],
    today: date,
) -> list[dict[str, Any]]:
    suffix = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    readable = len(text.strip()) >= MIN_READABLE_CHARS
    scores = content_scores(text)
    own = scores.get(cert.id, 0)
    best_other = max((s for cid, s in scores.items() if cid != cert.id), default=0)

    issuer = fields.get("issuer", "")
    cert_id = re.sub(r"\s+", "", fields.get("certificate_id", ""))
    manufacturer = fields.get("manufacturer", "")
    model = fields.get("model", "")
    issued = _parse(fields.get("issue_date", ""))
    expires = _parse(fields.get("expiry_date", ""))
    want_mfr = (device.get("manufacturer") or "").strip()
    want_model = (device.get("model") or "").strip()
    id_re = cert.id_pattern or GENERIC_ID_RE
    if own == 0:
        type_detail = "No wording typical of this certificate was found"
    elif own < best_other:
        type_detail = "The document reads more like a different certificate"
    else:
        type_detail = ""

    return [
        _check("Certificate document attached", True, file_name),
        _check(
            "Document is a PDF, Word file, image or text file",
            suffix in SUPPORTED_EXTENSIONS,
            suffix or "no extension",
        ),
        _check(
            "Document text could be read",
            readable,
            "" if readable else "No readable text (empty, encrypted or unreadable scan)",
        ),
        _check(
            f"Document content matches {cert.name}",
            (own > 0 and own >= best_other) if readable else None,
            type_detail,
        ),
        _check(
            f"Issued by {cert.issuers[0]}" if cert.issuers else "Issuing organisation is named",
            (any(loosely_matches(issuer, i) for i in cert.issuers) if cert.issuers else True) if issuer else None,
            issuer,
        ),
        _check(
            f"{cert.id_label} is present and well formed",
            bool(id_re.match(cert_id)) if cert_id else None,
            cert_id or (cert.id_hint and f"Expected: {cert.id_hint}"),
        ),
        _check(
            f"Manufacturer matches the device ({want_mfr})" if want_mfr else "Manufacturer is stated",
            (loosely_matches(manufacturer, want_mfr) if want_mfr else True) if manufacturer else None,
            manufacturer,
        ),
        _check(
            f"Model matches the device ({want_model})" if want_model else "Model is stated",
            (loosely_matches(model, want_model) if want_model else True) if model else None,
            model,
        ),
        _check("Issue date is not in the future", issued <= today if issued else None, fields.get("issue_date", "")),
        _check("Certificate has not expired", expires >= today if expires else None, fields.get("expiry_date", "")),
        _check(
            "Expiry date is after the issue date",
            expires > issued if issued and expires else None,
        ),
    ]


def verdict(checks: list[dict[str, Any]]) -> str:
    return "failed" if any(c["ok"] is False for c in checks) else "passed"
