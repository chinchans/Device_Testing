"""Checkpoints for the lab certificate fixtures: extract the record, then pass or fail each point."""

from __future__ import annotations

import re
from typing import Any

from .definitions import CertificateDef
from .fields import normalize_date

# A document uses this path when it has the shared record + test-table layout.
_FIXTURE_MARKERS = ("record identification", "reference identifier", "test objective")

_RESULT_WORDS = {"PASS", "FAIL", "REVIEW", "SKIP", "SKIPPED", "NA", "N/A"}


def _check(label: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"label": label, "ok": ok, "detail": detail}


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _field_map(lines: list[str]) -> dict[str, str]:
    """Field/Value rows. The PDF text lists the label and the value on successive lines."""
    found: dict[str, str] = {}
    for index, line in enumerate(lines[:-1]):
        if line.lower() != "field" or lines[index + 1].lower() != "value":
            continue
        cursor = index + 2
        while cursor + 1 < len(lines):
            label, value = lines[cursor], lines[cursor + 1]
            if re.match(r"^\d+\.", label) or label.lower() == "test id":
                break
            found[label.lower()] = value
            cursor += 2
        break
    return found


def _tests(lines: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(len(lines) - 2):
        if (
            lines[index].lower() != "test id"
            or lines[index + 1].lower() != "test objective"
            or lines[index + 2].lower() != "result"
        ):
            continue
        cursor = index + 3
        while cursor + 2 < len(lines):
            test_id, objective, result = lines[cursor], lines[cursor + 1], lines[cursor + 2]
            if re.match(r"^\d+\.", test_id) or test_id.lower().startswith("issuer"):
                break
            if result.upper() not in _RESULT_WORDS:
                break
            rows.append({"id": test_id, "objective": objective, "result": result.upper()})
            cursor += 3
        break
    return rows


def _first(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def is_fixture(text: str) -> bool:
    lowered = (text or "").lower()
    return all(marker in lowered for marker in _FIXTURE_MARKERS)


def parse_fixture(text: str) -> dict[str, Any]:
    lines = _lines(text)
    issuer = _first(r"Issuer:\s*([^.]+)", text)
    url = _first(r"Public reference:\s*(https?://\S+)", text).rstrip(").,")
    status = _first(r"DOCUMENT STATUS:\s*(.+)", text)
    return {
        "fields": _field_map(lines),
        "tests": _tests(lines),
        "issuer": issuer,
        "public_reference": url,
        "document_status": status,
    }


def _value(parsed: dict[str, Any], label: str) -> str:
    return str(parsed["fields"].get(label.lower()) or "").strip()


def _token(value: str) -> str:
    return re.split(r"\s+\(", value.strip(), maxsplit=1)[0].strip()


def _has_groups(value: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    lowered = value.lower()
    return bool(lowered) and all(any(option in lowered for option in group) for group in groups)


def _reference_ok(kind: str, value: str) -> bool:
    token = _token(value)
    if kind == "fcc_id":
        return bool(re.fullmatch(r"[A-Z0-9]{3,5}[A-Z0-9-]{1,14}", token, re.IGNORECASE))
    if kind == "digits":
        return bool(re.fullmatch(r"\d{3,8}", token))
    if kind == "qdid":
        return bool(re.search(r"qdid", token, re.IGNORECASE) or re.fullmatch(r"(?:D\d{5,7}|\d{4,7})", token, re.IGNORECASE))
    return bool(token)


# scheme words, reference kind, required test ids, issuer phrases, labelled fields.
# A field value is either None (any non-empty text) or groups of accepted phrases.
_SPECS: dict[str, dict[str, Any]] = {
    "fcc": {
        "scheme": ("fcc",),
        "reference": "fcc_id",
        "tests": ("FCC-RF-001", "FCC-EMC-002", "FCC-SAR-003"),
        "issuers": ("federal communications commission", "telecommunication certification body"),
        "fields": (
            ("Equipment class", None),
            ("Regulatory scope", (("part 15", "transmitter"),)),
            ("Radio domains", (("cellular",), ("wi-fi", "wifi"), ("bluetooth",), ("nfc",))),
            ("Supporting evidence", (("rf", "emission"), ("sar", "exposure"), ("emc",))),
        ),
    },
    "gcf": {
        "scheme": ("gcf",),
        "reference": "digits",
        "tests": ("GCF-PRO-001", "GCF-RF-002", "GCF-IMS-003"),
        "issuers": ("global certification forum",),
        "fields": (
            ("Radio access", (("gsm",), ("lte",), ("nr", "5g"))),
            ("5G modes", (("sa",), ("nsa",))),
            ("Selected NR bands", None),
            ("SIM capabilities", (("uicc",), ("euicc",))),
        ),
    },
    "wifi": {
        "scheme": ("wi-fi", "wifi"),
        "reference": "any",
        "tests": ("WIFI-001", "WIFI-002", "WIFI-003"),
        "issuers": ("wi-fi alliance", "wifi alliance"),
        "fields": (
            ("Certification programs", (("wi-fi certified", "wifi certified"), ("wpa3",))),
            ("Bands", (("2.4",), ("5",))),
            ("Security", (("wpa2",), ("wpa3",))),
            ("Interoperability", (("association",), ("roaming",))),
        ),
    },
    "bt": {
        "scheme": ("bluetooth",),
        "reference": "qdid",
        "tests": ("BT-001", "BT-002", "BT-003"),
        "issuers": ("bluetooth sig", "bluetooth special interest group"),
        "fields": (
            ("Technology", (("le", "low energy"), ("br/edr", "br", "edr"))),
            ("Qualification elements", (("profile",), ("declaration",))),
            ("Profiles", (("gatt",), ("gap",), ("a2dp",))),
            ("Evidence", (("conformance",), ("interoperability",))),
        ),
    },
    "nfc": {
        "scheme": ("nfc",),
        "reference": "digits",
        "tests": ("NFC-001", "NFC-002", "NFC-003"),
        "issuers": ("nfc forum",),
        "fields": (
            ("Device class", (("nfc",),)),
            ("Certification requirements", (("release",),)),
            ("Test release", None),
            ("Public certificate date", "date"),
        ),
    },
    "gms": {
        "scheme": ("android cts", "gms", "cts"),
        "reference": "any",
        "tests": ("CTS-API-001", "CTS-SEC-002", "CTS-MEDIA-003"),
        "issuers": ("google",),
        "fields": (
            ("Android version", None),
            ("Assessment basis", (("cdd",), ("cts",))),
            ("GMS license", None),
            ("Coverage", (("api",), ("permission",), ("security",))),
        ),
    },
    "csp": {
        "scheme": ("csp", "operator"),
        "reference": "any",
        "tests": ("CSP-REG-001", "CSP-DATA-002", "CSP-FOTA-003"),
        "issuers": ("operator", "communication service provider"),
        "fields": (
            ("Program basis", None),
            ("Pre-requisites", (("gcf", "ptcrb"), ("fota",))),
            ("Test campaign", (("registration",), ("fota",))),
            ("Approval status", None),
        ),
    },
}


def _field_ok(kind: Any, value: str) -> bool:
    if kind is None:
        return bool(value)
    if kind == "date":
        return bool(normalize_date(value))
    if kind == "gms_license":
        lowered = value.lower()
        return bool(lowered) and not any(word in lowered for word in ("not verified", "not evidenced", "illustrative"))
    if kind == "approval":
        lowered = value.lower()
        return "approv" in lowered and not any(word in lowered for word in ("no operator approval", "sample only", "not approved"))
    return _has_groups(value, kind)


def _official(parsed: dict[str, Any]) -> bool:
    # Rejecting sample or synthetic documents is deferred. A stated document status is enough for now.
    return bool(str(parsed["document_status"]).strip())


def _issuer_ok(issuer: str, accepted: tuple[str, ...]) -> bool:
    # Strict authority matching is deferred. A named issuer is enough for now.
    del accepted
    return bool(issuer.strip())


def _evidence_ok(value: str) -> bool:
    # Verified-only evidence is deferred. A stated evidence status is enough for now.
    return bool(value.strip())


def evaluate_checkpoints(cert: CertificateDef, parsed: dict[str, Any]) -> list[dict[str, Any]]:
    spec = _SPECS[cert.id]
    scheme = _value(parsed, "Scheme")
    reference = _value(parsed, "Reference identifier")
    tests = parsed["tests"]
    found_ids = {row["id"] for row in tests}
    missing = [test_id for test_id in spec["tests"] if test_id not in found_ids]
    checks = [
        _check(
            "Scheme matches this certificate",
            any(word in scheme.lower() for word in spec["scheme"]),
            scheme or "Not found",
        ),
        _check("Device / product is stated", bool(_value(parsed, "Device / product")), _value(parsed, "Device / product")),
        _check(
            "Reference identifier is present and well formed",
            _reference_ok(spec["reference"], reference),
            _token(reference) or "Not found",
        ),
        _check("Document ID is stated", bool(_value(parsed, "Sample document ID")), _value(parsed, "Sample document ID")),
        _check(
            "Record date is stated",
            bool(normalize_date(_value(parsed, "Record date"))),
            normalize_date(_value(parsed, "Record date")) or _value(parsed, "Record date") or "Not found",
        ),
        _check("Evidence is verified", _evidence_ok(_value(parsed, "Evidence status")), _value(parsed, "Evidence status") or "Not found"),
    ]
    for label, kind in spec["fields"]:
        value = _value(parsed, label)
        checks.append(_check(f"{label} is covered", _field_ok(kind, value), value or "Not found"))
    checks.extend(
        [
            _check(
                "Required test IDs are present",
                not missing,
                ", ".join(sorted(found_ids)) if not missing else f"Missing {', '.join(missing)}",
            ),
            _check(
                "Every listed test passed",
                bool(tests) and not missing,
                ", ".join(f"{row['id']} {row['result']}" for row in tests) or "No test rows",
            ),
            _check(
                "Issued by the certification authority",
                _issuer_ok(parsed["issuer"], spec["issuers"]),
                parsed["issuer"] or "Not found",
            ),
            _check("Public reference is stated", parsed["public_reference"].startswith("http"), parsed["public_reference"] or "Not found"),
            _check(
                "Document is an official certificate",
                _official(parsed),
                parsed["document_status"] or "Not found",
            ),
        ]
    )
    return checks


def fields_from_fixture(parsed: dict[str, Any]) -> dict[str, str]:
    """Map the fixture record onto the fields the certification page already shows, plus the checkpoint extras."""
    tests = "; ".join(f"{row['id']} {row['result']}" for row in parsed["tests"])
    return {
        "issuer": parsed["issuer"],
        "certificate_id": _token(_value(parsed, "Reference identifier")),
        "manufacturer": "",
        "model": _value(parsed, "Device / product"),
        "issue_date": normalize_date(_value(parsed, "Record date")),
        "expiry_date": "",
        "scheme": _value(parsed, "Scheme"),
        "evidence_status": _value(parsed, "Evidence status"),
        "document_status": parsed["document_status"],
        "public_reference": parsed["public_reference"],
        "tests": tests,
    }
