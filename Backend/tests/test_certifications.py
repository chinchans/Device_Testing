"""Tests for regulatory certificate detection, field extraction, rule checks and the API."""

from __future__ import annotations

import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pymupdf as fitz
from fastapi.testclient import TestClient

from services.certifications import fields as fields_mod
from services.certifications import service
from services.certifications.classify import classify, classify_by_filename
from services.certifications.definitions import BY_ID, CERTIFICATES
from services.certifications.fields import normalize_date, regex_fields
from services.certifications.rules import run_checks, verdict

FCC_TEXT = (
    "Federal Communications Commission\nGrant of Equipment Authorization\n"
    "Grantee: Acme Mobile Ltd\nFCC ID: 2AB12-XYZ100\nModel: Acme X1\n"
    "Date of Grant: 2025-03-01\n"
)
WIFI_TEXT = (
    "Wi-Fi Alliance\nWi-Fi CERTIFIED Interoperability Certificate\n"
    "Certification ID: WFA123456\nCompany: Acme Mobile Ltd\nModel Number: Acme X1\n"
    "Date of Issue: 01 March 2025\n"
)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(fields_mod, "is_azure_configured", lambda: False)
    monkeypatch.setattr(service, "_results_file", lambda: tmp_path / "results" / "latest.json")
    (tmp_path / "results").mkdir()
    service._text_cache.clear()


def _pdf(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def _docx(path: Path, lines: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return path


def _png(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=14)
    page.get_pixmap(dpi=150).save(str(path))
    doc.close()
    return path


def test_fcc_is_defined_first_and_seven_certificates_exist():
    assert [c.id for c in CERTIFICATES] == ["fcc", "gcf", "wifi", "bt", "nfc", "gms", "csp"]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("FCC_grant.pdf", "fcc"),
        ("acme-wi-fi-certificate.pdf", "wifi"),
        ("Bluetooth QDID.pdf", "bt"),
        ("gms_cts_report.pdf", "gms"),
        ("scan_0001.pdf", None),
        ("fcc_and_nfc.pdf", None),
    ],
)
def test_classify_by_filename(name, expected):
    assert classify_by_filename(name) == expected


def test_classify_falls_back_to_content():
    found = classify("scan_0001.pdf", FCC_TEXT)
    assert (found.cert_id, found.detected_by) == ("fcc", "content")
    assert classify("scan_0002.pdf", "Quarterly sales report").cert_id is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2025-03-01", "2025-03-01"),
        ("01/03/2025", "2025-03-01"),
        ("1 March 2025", "2025-03-01"),
        ("March 1, 2025", "2025-03-01"),
        ("not a date", ""),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_regex_fields_read_labelled_values():
    f = regex_fields(FCC_TEXT, BY_ID["fcc"])
    assert f["certificate_id"] == "2AB12-XYZ100"
    assert f["issuer"] == "Federal Communications Commission"
    assert f["issue_date"] == "2025-03-01"
    assert "Acme Mobile" in f["manufacturer"]


def _checks(cert_id: str, text: str, fields: dict[str, str], device: dict[str, str] | None = None):
    return run_checks(
        BY_ID[cert_id],
        file_name="doc.pdf",
        text=text,
        fields=fields,
        device=device or {},
        today=date(2026, 1, 1),
    )


def test_valid_certificate_passes():
    fields = regex_fields(FCC_TEXT, BY_ID["fcc"])
    assert verdict(_checks("fcc", FCC_TEXT, fields, {"manufacturer": "Acme", "model": "Acme X1"})) == "passed"


def test_expired_wrong_id_and_wrong_model_fail():
    fields = {**regex_fields(FCC_TEXT, BY_ID["fcc"]), "certificate_id": "??", "expiry_date": "2025-06-01"}
    checks = _checks("fcc", FCC_TEXT, fields, {"model": "Other Phone 9"})
    failed = {c["label"] for c in checks if c["ok"] is False}
    assert verdict(checks) == "failed"
    assert "FCC ID is present and well formed" in failed
    assert "Certificate has not expired" in failed
    assert "Model matches the device (Other Phone 9)" in failed


def test_document_of_another_type_fails_type_check():
    checks = _checks("fcc", WIFI_TEXT, regex_fields(WIFI_TEXT, BY_ID["fcc"]))
    type_check = next(c for c in checks if c["label"].startswith("Document content matches"))
    assert type_check["ok"] is False


def test_scan_folder_reads_pdf_docx_and_image(tmp_path):
    folder = tmp_path / "certs"
    folder.mkdir()
    _pdf(folder / "fcc_grant.pdf", FCC_TEXT)
    _docx(folder / "scan_17.docx", WIFI_TEXT.splitlines())
    _png(folder / "bt_declaration.png", "Bluetooth SIG Declaration ID: D123456")
    (folder / "notes.xyz").write_text("ignored")

    files = {f["name"]: f for f in service.scan([], [str(folder)])}
    assert set(files) == {"fcc_grant.pdf", "scan_17.docx", "bt_declaration.png"}
    assert (files["fcc_grant.pdf"]["cert_id"], files["fcc_grant.pdf"]["detected_by"]) == ("fcc", "filename")
    assert (files["scan_17.docx"]["cert_id"], files["scan_17.docx"]["detected_by"]) == ("wifi", "content")
    assert files["bt_declaration.png"]["cert_id"] == "bt"


def test_validate_reports_missing_certificates_as_not_available(tmp_path):
    fcc = _pdf(tmp_path / "fcc.pdf", FCC_TEXT)
    wifi = _pdf(tmp_path / "wifi.pdf", WIFI_TEXT)
    record = service.validate(
        [{"path": str(fcc), "cert_id": "fcc"}, {"path": str(wifi), "cert_id": "wifi"}],
        {"manufacturer": "Acme Mobile", "model": "Acme X1"},
    )
    results = record["results"]
    assert results["fcc"]["status"] == "passed"
    assert results["wifi"]["status"] == "passed"
    assert {cid for cid, r in results.items() if r["status"] == "not_available"} == {"gcf", "bt", "nfc", "gms", "csp"}
    assert record["summary"] == {"passed": 2, "failed": 0, "not_available": 5, "total": 7}
    assert service.load_saved()["summary"]["passed"] == 2


def test_sample_fixtures_pass_until_strict_checkpoints_return():
    from services.certifications.checkpoints import evaluate_checkpoints, is_fixture, parse_fixture

    folder = Path("/home/tcs/Downloads/regulatory_certifications")
    if not folder.is_dir():
        pytest.skip("sample certification folder is not on this machine")
    expected = {
        "FCC_RF_Equipment_Authorization_SAMPLE.pdf": "fcc",
        "GCF_Conformance_Declaration_SAMPLE.pdf": "gcf",
        "WiFi_CERTIFIED_Product_Record_SAMPLE.pdf": "wifi",
        "Bluetooth_Qualification_Record_SAMPLE.pdf": "bt",
        "NFC_Forum_Certificate_SAMPLE.pdf": "nfc",
        "Android_CTS_Compatibility_Report_SAMPLE.pdf": "gms",
        "CSP_Operator_Acceptance_SAMPLE.pdf": "csp",
    }
    files = [{"path": str(folder / name), "name": name, "cert_id": cert_id} for name, cert_id in expected.items()]
    record = service.validate(files, {})
    for name, cert_id in expected.items():
        result = record["results"][cert_id]
        assert result["status"] == "passed", name
        failed = [c["label"] for c in result["checks"] if c["ok"] is False]
        assert failed == [], name
        assert is_fixture(service._cached_text(folder / name).text)
        parsed = parse_fixture(service._cached_text(folder / name).text)
        assert evaluate_checkpoints(BY_ID[cert_id], parsed)


def test_official_fixture_with_all_pass_results_passes():
    from services.certifications.checkpoints import evaluate_checkpoints, parse_fixture

    text = """
DOCUMENT STATUS: APPROVED GRANT
1. Record identification
Field
Value
Scheme
FCC
Device / product
Acme X1
Reference identifier
A3LSMS931U
Sample document ID
LAB-FCC-2026-009
Record date
2026-01-15
Evidence status
VERIFIED
Equipment class
Mobile phone
Regulatory scope
FCC Part 15
Radio domains
Cellular, Wi-Fi, Bluetooth, NFC
Supporting evidence
RF emissions, SAR exposure, EMC
2. Test execution summary
Test ID
Test objective
Result
FCC-RF-001
Transmitter frequency configuration
PASS
FCC-EMC-002
Radiated emission limits
PASS
FCC-SAR-003
RF exposure evidence
PASS
3. Validation and traceability
Issuer: Federal Communications Commission. Approval signature: granted.
Public reference: https://fccid.io/A3LSMS931U
"""
    checks = evaluate_checkpoints(BY_ID["fcc"], parse_fixture(text))
    assert [c["label"] for c in checks if not c["ok"]] == []
    assert verdict(checks) == "passed"


def test_api_definitions_scan_validate_and_results(tmp_path):
    from main import app

    client = TestClient(app)
    defs = client.get("/api/certifications").json()["certificates"]
    assert defs[0]["id"] == "fcc"

    fcc = _pdf(tmp_path / "fcc_grant.pdf", FCC_TEXT)
    scanned = client.post("/api/certifications/scan", json={"file_paths": [str(fcc)]}).json()["files"]
    assert scanned[0]["cert_id"] == "fcc"

    res = client.post("/api/certifications/validate", json={"files": scanned, "device": {"model": "Acme X1"}})
    assert res.status_code == 200
    assert res.json()["results"]["fcc"]["status"] == "passed"
    assert client.get("/api/certifications/results").json()["saved"]["summary"]["passed"] == 1

    assert client.post("/api/certifications/scan", json={"folder_paths": [str(tmp_path / "nope")]}).status_code == 400
    bad = client.post("/api/certifications/validate", json={"files": [{"path": str(fcc), "cert_id": "xyz"}]})
    assert bad.status_code == 400
    assert client.delete("/api/certifications/results").json() == {"cleared": True}
