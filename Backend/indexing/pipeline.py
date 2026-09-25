"""Document indexing pipeline: load → parse → clean → [RAG normalize] → structure → chunk → embed → dual index."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.config import get_settings
from core.schemas import IndexedDocument
from indexing.chunker import build_chunks, retrievable_chunks
from indexing.cleaner import clean_parsed_document
from indexing.embedder import embed_chunks, get_embedder
from indexing.loader import LoadedDocument, persist_upload, save_upload_bytes
from indexing.parser import parse_pdf
from indexing.rag_normalize import apply_rag_normalize
from indexing.structure import discover_structure
from observability.logging import TraceRecorder, logger
from retrieval.bm25_store import BM25Store
from retrieval.vector_store import VectorStore
from storage.document_store import DocumentStore


class IndexingPipeline:
    def __init__(self) -> None:
        self.store = DocumentStore()
        self.embedder = get_embedder()

    def index_file(
        self,
        path: Path,
        original_name: str | None = None,
        *,
        force_reindex: bool = False,
        force_ocr: bool = False,
        trace: TraceRecorder | None = None,
    ) -> IndexedDocument:
        loaded = persist_upload(Path(path), original_name=original_name)
        return self._index_loaded(
            loaded,
            force_reindex=force_reindex or force_ocr,
            force_ocr=force_ocr,
            trace=trace,
        )

    def index_bytes(
        self,
        data: bytes,
        filename: str,
        *,
        force_reindex: bool = False,
        force_ocr: bool = False,
        trace: TraceRecorder | None = None,
    ) -> IndexedDocument:
        loaded = save_upload_bytes(data, filename)
        return self._index_loaded(
            loaded,
            force_reindex=force_reindex or force_ocr,
            force_ocr=force_ocr,
            trace=trace,
        )

    def _index_loaded(
        self,
        loaded: LoadedDocument,
        *,
        force_reindex: bool,
        force_ocr: bool = False,
        trace: TraceRecorder | None,
    ) -> IndexedDocument:
        settings = get_settings()
        pipeline_version = settings.indexing.index_pipeline_version
        trace = trace or TraceRecorder(document_id=loaded.document_id)
        existing = self.store.has_index(loaded.document_hash)
        if (
            existing
            and not force_reindex
            and getattr(existing, "pipeline_version", 1) >= pipeline_version
        ):
            # Ensure stores load
            vs = VectorStore(existing.document_id)
            bm = BM25Store(existing.document_id)
            if vs.load() and bm.load():
                logger.info(
                    "Reusing existing index for %s (hash=%s)",
                    existing.document_name,
                    loaded.document_hash[:12],
                )
                trace.log("index_cache_hit", {"document_id": existing.document_id})
                return existing

        with trace.timed("parse"):
            parsed = parse_pdf(
                loaded.path,
                loaded.document_id,
                loaded.document_name,
                force_ocr=force_ocr,
            )
        with trace.timed("clean"):
            parsed = clean_parsed_document(parsed)

        rag_normalized = False
        normalize_payload = None
        with trace.timed("rag_normalize"):
            parsed, normalize_payload = apply_rag_normalize(
                parsed,
                source_path=loaded.path,
                force_full_ocr=force_ocr,
            )
            rag_normalized = bool(
                normalize_payload and (normalize_payload.get("modules") or [])
            )
            if normalize_payload is not None:
                self.store.save_normalized(loaded.document_id, normalize_payload)

        with trace.timed("structure"):
            structure = discover_structure(parsed)
            if (
                rag_normalized
                and normalize_payload
                and normalize_payload.get("product_name")
                and not structure.product_name
            ):
                structure.product_name = str(normalize_payload["product_name"]).strip()
        with trace.timed("chunk"):
            chunks = build_chunks(parsed, structure, loaded.document_name)
            retrievable = retrievable_chunks(chunks)
        with trace.timed("embed"):
            retrievable = embed_chunks(retrievable, embedder=self.embedder)
        with trace.timed("dual_index"):
            vs = VectorStore(loaded.document_id)
            bm = BM25Store(loaded.document_id)
            vs.add_chunks(retrievable)
            bm.add_chunks(retrievable)

        indexed = IndexedDocument(
            document_id=loaded.document_id,
            document_name=loaded.document_name,
            document_hash=loaded.document_hash,
            product_name=structure.product_name,
            product_type=structure.product_type,
            page_count=parsed.page_count,
            structure=structure,
            chunk_ids=[c.chunk_id for c in chunks],
            indexed_at=datetime.now(timezone.utc).isoformat(),
            pipeline_version=pipeline_version,
            rag_normalized=rag_normalized,
        )
        self.store.save_parsed(loaded.document_id, parsed)
        self.store.save_structure(loaded.document_id, structure)
        self.store.save_chunks(loaded.document_id, chunks)
        self.store.save_manifest(indexed)
        trace.log(
            "index_complete",
            {
                "document_id": loaded.document_id,
                "pages": parsed.page_count,
                "chunks": len(chunks),
                "retrievable": len(retrievable),
                "sections": len(structure.sections),
                "force_ocr": force_ocr,
                "used_ocr_pages": parsed.used_ocr_pages,
                "rag_normalized": rag_normalized,
                "pipeline_version": pipeline_version,
            },
        )
        logger.info(
            "Indexed %s: pages=%d chunks=%d retrievable=%d rag_normalized=%s",
            loaded.document_name,
            parsed.page_count,
            len(chunks),
            len(retrievable),
            rag_normalized,
        )
        return indexed

    def get_retrievers(self, document_id: str) -> tuple[VectorStore, BM25Store]:
        vs = VectorStore(document_id)
        bm = BM25Store(document_id)
        if not vs.load() or not bm.load():
            raise FileNotFoundError(f"Indexes not found for document_id={document_id}")
        return vs, bm
