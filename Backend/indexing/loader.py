"""Document loading, hashing, and content-addressed cache keys."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from core.config import get_settings


@dataclass
class LoadedDocument:
    document_id: str
    document_name: str
    document_hash: str
    path: Path
    size_bytes: int


def compute_file_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def persist_upload(upload_path: Path, original_name: str | None = None) -> LoadedDocument:
    """Copy an uploaded file into the managed uploads directory and assign IDs."""
    settings = get_settings()
    settings.uploads_path.mkdir(parents=True, exist_ok=True)

    name = original_name or upload_path.name
    doc_hash = compute_file_hash(upload_path)
    # Stable ID derived from content hash so unchanged docs reuse indexes.
    document_id = f"doc_{doc_hash[:16]}"
    dest = settings.uploads_path / f"{document_id}_{Path(name).name}"
    if not dest.exists():
        shutil.copy2(upload_path, dest)

    return LoadedDocument(
        document_id=document_id,
        document_name=Path(name).name,
        document_hash=doc_hash,
        path=dest,
        size_bytes=dest.stat().st_size,
    )


def save_upload_bytes(data: bytes, filename: str) -> LoadedDocument:
    settings = get_settings()
    settings.uploads_path.mkdir(parents=True, exist_ok=True)
    tmp = settings.uploads_path / f"_tmp_{uuid.uuid4().hex}_{Path(filename).name}"
    tmp.write_bytes(data)
    try:
        return persist_upload(tmp, original_name=filename)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
