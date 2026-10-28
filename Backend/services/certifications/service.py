"""Scan uploaded certificate files, validate them per certificate, and persist the latest results."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import get_settings
from observability.logging import logger

from .checkpoints import evaluate_checkpoints, fields_from_fixture, is_fixture, parse_fixture
from .classify import classify
from .definitions import BY_ID, CERTIFICATES, CertificateDef
from .fields import extract_fields, today
from .rules import run_checks, verdict
from .text import ExtractedText, extract_text, is_supported

MAX_FOLDER_FILES = 200
VALIDATION_WORKERS = 4

_text_cache: dict[tuple[str, int, int], ExtractedText] = {}
_cache_lock = threading.Lock()


class CertificationError(ValueError):
    """Bad request input (missing folder, nothing to scan)."""


def _results_file() -> Path:
    path = get_settings().resolve_path("data/certifications")
    path.mkdir(parents=True, exist_ok=True)
    return path / "latest.json"


def _cached_text(path: Path) -> ExtractedText:
    try:
        stat = path.stat()
    except OSError:
        return extract_text(path)
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        hit = _text_cache.get(key)
    if hit is not None:
        return hit
    result = extract_text(path)
    with _cache_lock:
        _text_cache[key] = result
    return result


def _folder_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise CertificationError(f"Folder not found: {folder}")
    found = [
        p
        for p in sorted(folder.rglob("*"))
        if p.is_file() and is_supported(p) and not any(part.startswith(".") for part in p.relative_to(folder).parts)
    ]
    return found[:MAX_FOLDER_FILES]


def scan(file_paths: list[str], folder_paths: list[str]) -> list[dict[str, Any]]:
    """Expand folders, read each file and detect which certificate it is."""
    paths: list[Path] = [Path(p).expanduser() for p in file_paths]
    for folder in folder_paths:
        paths.extend(_folder_files(Path(folder).expanduser()))
    if not paths:
        raise CertificationError(
            "No supported certificate files (PDF, DOCX, image, TXT) found in the selected folder"
            if folder_paths
            else "No files selected"
        )

    unique: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)

    def describe(path: Path) -> dict[str, Any]:
        supported = is_supported(path)
        extracted = _cached_text(path) if supported and path.is_file() else None
        text = extracted.text if extracted else ""
        found = classify(path.name, text)
        error = ""
        if not path.is_file():
            error = "File not found"
        elif not supported:
            error = f"Unsupported file type {path.suffix or '(none)'}"
        elif extracted and extracted.error:
            error = extracted.error
        return {
            "path": str(path),
            "name": path.name,
            "size": path.stat().st_size if path.is_file() else 0,
            "supported": supported,
            "cert_id": found.cert_id,
            "detected_by": found.detected_by,
            "error": error,
        }

    with ThreadPoolExecutor(max_workers=VALIDATION_WORKERS) as pool:
        return list(pool.map(describe, unique))


def _evaluate(cert: CertificateDef, path: Path, device: dict[str, str]) -> dict[str, Any]:
    extracted = _cached_text(path)
    if is_fixture(extracted.text):
        parsed = parse_fixture(extracted.text)
        fields = fields_from_fixture(parsed)
        checks = evaluate_checkpoints(cert, parsed)
        field_method = "checkpoints"
    else:
        fields, field_method = extract_fields(extracted.text, cert)
        checks = run_checks(
            cert,
            file_name=path.name,
            text=extracted.text,
            fields=fields,
            device=device,
            today=today(),
        )
    return {
        "file": {"path": str(path), "name": path.name},
        "fields": fields,
        "field_method": field_method,
        "text_method": extracted.method,
        "text_error": extracted.error,
        "checks": checks,
        "status": verdict(checks),
    }


def _pick_best(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    def rank(c: dict[str, Any]) -> tuple[int, int]:
        failures = sum(1 for chk in c["checks"] if chk["ok"] is False)
        return (0 if c["status"] == "passed" else 1, failures)

    return sorted(candidates, key=rank)[0]


def validate(files: list[dict[str, Any]], device: dict[str, str]) -> dict[str, Any]:
    """Validate every certificate: matched files are checked, the rest are reported as not available."""
    device = {
        "manufacturer": (device.get("manufacturer") or "").strip(),
        "model": (device.get("model") or "").strip(),
    }
    assigned: dict[str, list[Path]] = {c.id: [] for c in CERTIFICATES}
    for f in files:
        cert_id = f.get("cert_id")
        if cert_id in assigned and f.get("path"):
            assigned[cert_id].append(Path(f["path"]).expanduser())

    jobs = [(BY_ID[cid], path) for cid, paths in assigned.items() for path in paths]
    with ThreadPoolExecutor(max_workers=VALIDATION_WORKERS) as pool:
        evaluated = list(pool.map(lambda job: (job[0].id, _evaluate(job[0], job[1], device)), jobs))

    by_cert: dict[str, list[dict[str, Any]]] = {}
    for cert_id, outcome in evaluated:
        by_cert.setdefault(cert_id, []).append(outcome)

    results: dict[str, dict[str, Any]] = {}
    for cert in CERTIFICATES:
        candidates = by_cert.get(cert.id, [])
        base = {"cert_id": cert.id, "name": cert.name}
        if not candidates:
            results[cert.id] = {
                **base,
                "status": "not_available",
                "file": None,
                "other_files": [],
                "fields": {},
                "checks": [],
            }
            continue
        best = _pick_best(candidates)
        results[cert.id] = {
            **base,
            **best,
            "other_files": [c["file"] for c in candidates if c is not best],
        }

    statuses = [r["status"] for r in results.values()]
    record = {
        "validated_at": datetime.now().isoformat(timespec="seconds"),
        "device": device,
        "files": [
            {k: f.get(k) for k in ("path", "name", "size", "supported", "cert_id", "detected_by", "error")}
            for f in files
        ],
        "results": results,
        "summary": {
            "passed": statuses.count("passed"),
            "failed": statuses.count("failed"),
            "not_available": statuses.count("not_available"),
            "total": len(statuses),
        },
    }
    _save(record)
    return record


def _save(record: dict[str, Any]) -> None:
    try:
        _results_file().write_text(json.dumps(record, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save certification results: %s", exc)


def load_saved() -> dict[str, Any] | None:
    path = _results_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable certification results: %s", exc)
        return None


def clear_saved() -> None:
    path = _results_file()
    if path.is_file():
        path.unlink()
