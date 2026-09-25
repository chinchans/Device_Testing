# Device Testing — Agentic RAG (Generic Feature/Spec Extraction)

Production-oriented, **device-agnostic** Agentic RAG that extracts features and specifications from arbitrary product-specification PDFs. Feature categories are **discovered from each document** — nothing is hard-coded for phones, laptops, etc.

## Architecture

```
PDF upload
   │
   ▼
A. DOCUMENT INDEXING PIPELINE
   load → layout parse → clean → structure discovery
   → hierarchical chunking → embed (batched, cached)
   → dual index (dense vectors + BM25)
   │
   ▼
B. AGENTIC RETRIEVAL + EXTRACTION (LangGraph-compatible)
   QueryUnderstanding → ExtractionPlanner (per discovered section)
   → Hybrid retrieve (vector ∥ BM25) → RRF → Rerank
   → Parent/neighbor expansion → Structured extract
   → Grounding validation → Coverage validation
   → Retry loop (query rewrite) → Dedup/reconcile → JSON result
```

## Directory structure

```
Backend/
  main.py                 # FastAPI entry
  config/default.yaml     # Top-N, RRF k, chunk sizes, retries
  core/                   # schemas, config, LangGraph state
  indexing/               # loader, parser, cleaner, structure, chunker, embedder, pipeline
  retrieval/              # vector store, BM25, hybrid, RRF, reranker, context expansion
  agents/                 # intent, planner, rewrite, extract, grounding, coverage, reconcile
  graph/workflow.py       # orchestration
  app/api/                # routes + UI adapters
  llm/                    # Azure OpenAI client
  storage/                # document registry / caches
  observability/          # logs + per-query traces
  tests/
  samples/run_example.py
```

## Quick start

```bash
cd /home/tcs/Documents/Device_Testing
source dt_venv/bin/activate
pip install -r Backend/requirements.txt

# Terminal 1 — API
cd Backend && python main.py

# Terminal 2 — sample extraction
cd Backend && python samples/run_example.py

# Tests
cd Backend && pytest -q
```

## Configuration

See `Backend/config/default.yaml` and `.env`:

| Variable | Purpose |
|----------|---------|
| `AZURE_OPENAI_*` | Chat LLM for extraction / cheap agents |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Azure embedding deployment (recommended) |
| `EMBEDDING_PROVIDER` | `azure` or `hashing` (local fallback) |
| `RERANKER_PROVIDER` | `llm` (default) or `lexical` |

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + Azure status |
| POST | `/api/documents/upload` | Index a PDF (content-hash dedupe) |
| GET | `/api/documents` | List indexed docs |
| GET | `/api/documents/{id}/structure` | Discovered section hierarchy |
| POST | `/api/extract` | Agentic extraction → grounded schema |
| POST | `/api/extract-features` | Upload + extract → UI feature cards |
| POST | `/api/extract-from-path` | Index local path + extract (Electron) |

### Example extraction output

```json
{
  "document": {
    "document_id": "doc_...",
    "document_name": "spec.pdf",
    "product_name": "...",
    "product_type": "..."
  },
  "features": [
    {
      "feature_name": "Connectivity",
      "specifications": [
        {
          "parameter": "USB",
          "value": "USB 3.2 Gen 1",
          "unit": null,
          "qualifiers": [],
          "source": { "page": 1, "section": "Connectivity", "chunk_id": "chk_..." }
        }
      ]
    }
  ],
  "coverage": {
    "sections_discovered": 6,
    "sections_processed": 6,
    "sections_with_features": 6,
    "coverage_complete": true
  }
}
```

## Anti-hallucination

- Extraction uses **only** retrieved evidence.
- Grounding validator drops unsupported parameter/value pairs.
- Coverage validator flags missed specification-bearing sections (`INCOMPLETE` — never silent).
- Source terminology and exact values/units are preserved.
- Absence of evidence is never converted to `"No"`.

## Observability

Per-query JSON traces are written under `Backend/data/traces/`. Set `DEBUG_MODE=true` to include debug payloads in API responses.

## Swappable providers

| Concern | Interface | Default |
|---------|-----------|---------|
| Embeddings | `Embedder` | Azure / HashingEmbedder |
| Vector index | `VectorStore` | NumPy cosine |
| Sparse index | `BM25Store` | rank_bm25 |
| Reranker | `Reranker` | LLM / lexical |
| LLM | `azure_client.chat_completion` | Azure OpenAI |
| Parser | `parse_pdf` | PyMuPDF (+ OCR when needed) |
