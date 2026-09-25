"""Persistent document registry and parsed artifact cache."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.schemas import Chunk, DocumentStructure, IndexedDocument
from indexing.parser import ParsedDocument
from observability.logging import logger


class DocumentStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.root = self.settings.documents_path
        self.root.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, document_id: str) -> Path:
        path = self.root / document_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def has_index(self, document_hash: str) -> IndexedDocument | None:
        """Return IndexedDocument if an unchanged hash is already indexed."""
        for path in self.root.glob("*/manifest.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("document_hash") == document_hash:
                    return IndexedDocument.model_validate(data)
            except Exception:
                continue
        return None

    def get(self, document_id: str) -> IndexedDocument | None:
        path = self._doc_dir(document_id) / "manifest.json"
        if not path.exists():
            return None
        return IndexedDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_manifest(self, indexed: IndexedDocument) -> None:
        path = self._doc_dir(indexed.document_id) / "manifest.json"
        path.write_text(indexed.model_dump_json(indent=2), encoding="utf-8")

    def save_structure(self, document_id: str, structure: DocumentStructure) -> None:
        path = self._doc_dir(document_id) / "structure.json"
        path.write_text(structure.model_dump_json(indent=2), encoding="utf-8")

    def load_structure(self, document_id: str) -> DocumentStructure | None:
        path = self._doc_dir(document_id) / "structure.json"
        if not path.exists():
            return None
        return DocumentStructure.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        # Persist without embeddings (embeddings live in vector store / embedding cache)
        slim = []
        for ch in chunks:
            d = ch.model_dump()
            d["embedding"] = None
            slim.append(d)
        path = self._doc_dir(document_id) / "chunks.json"
        path.write_text(json.dumps(slim, indent=2), encoding="utf-8")

    def load_chunks(self, document_id: str) -> list[Chunk]:
        path = self._doc_dir(document_id) / "chunks.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Chunk.model_validate(c) for c in data]

    def save_parsed(self, document_id: str, parsed: ParsedDocument) -> None:
        path = self._doc_dir(document_id) / "parsed.json"
        payload = {
            "document_id": parsed.document_id,
            "document_name": parsed.document_name,
            "page_count": parsed.page_count,
            "blocks": [b.model_dump() for b in parsed.blocks],
            "raw_pages": parsed.raw_pages,
            "used_ocr_pages": parsed.used_ocr_pages,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save_normalized(self, document_id: str, payload: dict[str, Any]) -> None:
        path = self._doc_dir(document_id) / "normalized.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_normalized(self, document_id: str) -> dict[str, Any] | None:
        path = self._doc_dir(document_id) / "normalized.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def list_documents(self) -> list[IndexedDocument]:
        docs = []
        for path in sorted(self.root.glob("*/manifest.json")):
            try:
                docs.append(IndexedDocument.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except Exception as exc:
                logger.warning("Skip bad manifest %s: %s", path, exc)
        return docs
