"""Regulatory certificate definitions shared by the API and the UI."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CertificateDef:
    id: str
    name: str
    desc: str
    issuers: tuple[str, ...]
    # Whole-word filename tokens (e.g. "fcc_grant.pdf").
    filename_tokens: tuple[str, ...]
    # Substrings matched against the filename with separators removed (e.g. "Wi-Fi" → "wifi").
    filename_compact: tuple[str, ...] = ()
    # (phrase, weight) pairs scored against document text; strong phrases weigh 3.
    content_keywords: tuple[tuple[str, int], ...] = ()
    id_label: str = "Certificate ID"
    id_pattern: re.Pattern[str] | None = None
    id_hint: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "issuers": list(self.issuers),
            "id_label": self.id_label,
            "id_hint": self.id_hint,
        }


GENERIC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/.]{3,}$")

CERTIFICATES: tuple[CertificateDef, ...] = (
    CertificateDef(
        id="fcc",
        name="FCC Certification",
        desc="US radio-frequency equipment authorization (FCC ID grant)",
        issuers=("Federal Communications Commission", "FCC", "Telecommunication Certification Body", "TCB"),
        filename_tokens=("fcc",),
        content_keywords=(
            ("federal communications commission", 3),
            ("grant of equipment authorization", 3),
            ("fcc id", 3),
            ("telecommunication certification body", 2),
            ("47 cfr", 2),
            ("fcc", 1),
        ),
        id_label="FCC ID",
        # Grantee code (3 or 5 chars) followed by a product code of up to 14 chars.
        id_pattern=re.compile(r"^[A-Z0-9]{3,5}[A-Z0-9\-]{1,14}$", re.IGNORECASE),
        id_hint="Grantee code + product code, e.g. 2AB12-XYZ100",
    ),
    CertificateDef(
        id="gcf",
        name="GCF Certification",
        desc="3GPP conformance for cellular radio and protocol",
        issuers=("Global Certification Forum", "GCF"),
        filename_tokens=("gcf",),
        content_keywords=(
            ("global certification forum", 3),
            ("gcf certified", 3),
            ("gcf", 2),
            ("3gpp", 1),
        ),
    ),
    CertificateDef(
        id="wifi",
        name="Wi-Fi Certification",
        desc="Wi-Fi CERTIFIED interoperability",
        issuers=("Wi-Fi Alliance",),
        filename_tokens=("wfa",),
        filename_compact=("wifi",),
        content_keywords=(
            ("wi-fi alliance", 3),
            ("wi-fi certified", 3),
            ("wifi certified", 3),
            ("certification id: wfa", 3),
            ("wi-fi", 1),
        ),
        id_label="Wi-Fi Certification ID",
        id_pattern=re.compile(r"^WFA\d{3,8}$", re.IGNORECASE),
        id_hint="WFA followed by digits, e.g. WFA123456",
    ),
    CertificateDef(
        id="bt",
        name="Bluetooth Certification",
        desc="Bluetooth qualification (Declaration ID / QDID)",
        issuers=("Bluetooth SIG", "Bluetooth Special Interest Group"),
        filename_tokens=("bt", "qdid", "bqb", "sig"),
        filename_compact=("bluetooth",),
        content_keywords=(
            ("bluetooth sig", 3),
            ("bluetooth special interest group", 3),
            ("qualified design id", 3),
            ("declaration id", 3),
            ("qdid", 3),
            ("bluetooth", 1),
        ),
        id_label="Declaration ID / QDID",
        id_pattern=re.compile(r"^(?:D\d{5,7}|\d{4,7})$", re.IGNORECASE),
        id_hint="D followed by digits (Declaration ID) or a numeric QDID",
    ),
    CertificateDef(
        id="nfc",
        name="NFC Certification",
        desc="NFC Forum device certification",
        issuers=("NFC Forum",),
        filename_tokens=("nfc",),
        content_keywords=(
            ("nfc forum", 3),
            ("nfc forum certified", 3),
            ("near field communication", 2),
            ("nfc", 1),
        ),
    ),
    CertificateDef(
        id="gms",
        name="GMS (CTS)",
        desc="Google Mobile Services licence and Compatibility Test Suite",
        issuers=("Google",),
        filename_tokens=("gms", "cts"),
        content_keywords=(
            ("google mobile services", 3),
            ("compatibility test suite", 3),
            ("android compatibility", 2),
            ("gms", 2),
            ("cts", 1),
        ),
    ),
    CertificateDef(
        id="csp",
        name="CSP Test Plan Compliance",
        desc="Operator test plan compliance statement",
        issuers=(),
        filename_tokens=("csp",),
        content_keywords=(
            ("test plan compliance", 3),
            ("compliance statement", 2),
            ("communication service provider", 3),
            ("operator test plan", 3),
            ("csp", 2),
        ),
    ),
)

BY_ID: dict[str, CertificateDef] = {c.id: c for c in CERTIFICATES}


def list_definitions() -> list[dict[str, object]]:
    return [c.to_dict() for c in CERTIFICATES]


def get_definition(cert_id: str) -> CertificateDef | None:
    return BY_ID.get(cert_id)
