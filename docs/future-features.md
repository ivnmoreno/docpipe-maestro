# Future Features & Upgrades Backlog

> **Scope Guardrail & Alignment Principle:**  
> In accordance with the `docpipe-maestro` Constitution (Principle I: *"The engine — not the app, not the framework"*), any feature proposed for the core library must be accessible through the public library API and CLI without turning `docpipe-maestro` into an application server or framework. Features that require long-lived servers, authentication, or GUI layers belong in companion repositories or example wrappers.

This document tracks all architectural suggestions, completed `v0.2.0` upgrades, and remaining post-`v0.2` backlog proposals identified across `PRODUCT.md`, feature specifications (`specs/001-core-rag-pipeline/` through `specs/011-structured-logging/`), and implementation.

---

## 1. Document Intake & Parsing

### 1.1 Table & Structured List Preservation
- **Problem**: Tabular data and nested bulleted lists in Markdown, HTML, and PDFs can be split mid-table during chunking, causing rows to lose header context.
- **Proposed Upgrade**: Implement table-aware parsing that detects table boundaries and ensures header rows are replicated across split row groups so numeric and eligibility matrices remain interpretable by LLMs.
- **Formats Affected**: PDF, DOCX, HTML, Markdown.

### 1.2 Additional Document Formats (Intake Extras)
- **Problem**: Enterprise and research corpora frequently include spreadsheets, slide decks, and specialized documentation formats.
- **Proposed Upgrade**: Add additive optional dependencies and parsers under `[project.optional-dependencies]`:
  - `xlsx = ["openpyxl>=3.1.0"]` for Microsoft Excel spreadsheets (`.xlsx`).
  - `pptx = ["python-pptx>=1.0.0"]` for PowerPoint presentations (`.pptx`).
  - `epub = ["ebooklib>=0.18"]` for digital books (`.epub`).
  - `rst = ["docutils>=0.20"]` for reStructuredText (`.rst`).
  - `csv` / `tsv` built-in delimiter parsing.

### 1.3 Optical Character Recognition (OCR) for Scanned Documents
- **Problem**: Scanned PDFs and image-heavy documents currently yield empty or incomplete text.
- **Proposed Upgrade**: Add an optional OCR extraction extra (e.g., via `pytesseract` or lightweight ONNX models) triggered when a PDF page contains images but no extractable text stream.

---

## 2. Structure-Aware Chunking & Domain Profiles

### 2.1 `LEGAL` Chunking Profile (Deferred to Post-v0.2)
- **Problem**: Legal contracts, terms of service, and regulatory filings require stricter clause-boundary preservation and specialized exception handling than standard policy handbooks.
- **Proposed Upgrade**:
  - Introduce `LEGAL` chunking profile with calibrated chunk and overlap sizes.
  - Implement defined-term lookback (e.g., resolving `"Affiliate" as defined in Section 1.2`).
  - Expand legal exception markers (`notwithstanding`, `save as otherwise`, `subject to`, `provided always that`).
  - Add contract-specific reverse safety benchmarks.

### 2.2 Differential / Chunk-Level Re-Embedding
- **Problem**: Currently, when an updated file has a changed hash, all chunks for that document are re-embedded, even if only one paragraph was modified in a 50-page document.
- **Proposed Upgrade**:
  - Compare content-addressed chunk IDs against existing records before making provider embedding API calls.
  - Re-use vectors for unchanged chunks and only call the embedding provider for newly created or modified clauses.
  - Substantially reduces embedding latency, API token usage, and cloud provider costs during incremental sync.

### 2.3 User-Defined / Runtime Chunking Profiles — *Programmatic API Implemented; CLI Profile Overrides Post-v0.2*
- **Implemented (`v0.1` / `008-enricher-stage`)**: Programmatic `ChunkingProfile(...)` construction in Python (including custom `enrichers=(...)` pipelines, chunk sizes, and overlap) passed directly to `ingest()`, `sync()`, and `reindex()`.
- **Remaining Proposed Upgrade (Post-v0.2)**: Support CLI-only custom profile overrides (e.g., in `docpipe.toml` or CLI flags parsed strictly inside `cli.py`) while preserving Constitution Principle III (*"Chunking profiles are Python constants, not files"* in library modules).

---

## 3. Enrichment & Cross-Reference Resolution

### 3.1 Inter-Document Cross-Reference Resolution — *Phase 2 Query-Time Implemented (`002` / `008`); Phase 1 Corpus-Wide Ingest Post-v0.2*
- **Implemented (`002-online-llm-customization` / `008-enricher-stage`)**: Phase 1 `CrossrefsEnricher` (`"crossrefs"`) resolves intra-document references per file pre-chunking, and Phase 2 `retrieve(..., follow_crossrefs=True)` resolves 1-hop cross-document section/clause citations across the collection at retrieval time (via shared helpers in `docpipe_maestro._crossrefs`).
- **Remaining Proposed Upgrade (Post-v0.2)**: Maintain a corpus-wide section registry during Phase 1 batch ingestion so inter-document `[Crossref ...]` annotations can also be materialized directly at ingest time.

### 3.2 Multi-Hop & Nested Cross-Reference Resolution
- **Problem**: References that chain across multiple clauses (e.g., Section 1.1 references Section 2.3, which in turn references Appendix B) may fail to include deep exceptions beyond 1 hop.
- **Proposed Upgrade**: Implement recursive reference expansion with cycle detection and a configurable maximum hop depth (e.g., depth 2).

### 3.3 Pre-Chunking Enrichment Stage & PII Protection — *Implemented*
- **Status**: Implemented in `008-enricher-stage` and `009-pii-protection`.
- **Details**: Formalizes the post-clean, pre-chunk `Enricher` protocol (`@register_enricher` / `ENRICHERS`, `ChunkingProfile.enrichers`, `IngestContext`) with `CrossrefsEnricher` (`"crossrefs"`) and `PiiEnricher` (`"pii"`, supporting `redact`, `tokenize` with salted HMAC-SHA256 value digests, and `block` raising `PiiBlockedError` before store/manifest writes), 7 offline deterministic recognizers + `@register_pii_recognizer` + optional `[pii]` Presidio NER, owner-only zero-raw-PII `<collection>.audit.jsonl` logs, `--local-only` preflight, Phase 2 `guard_egress()`, and mandatory Release Gate #2 (`@pytest.mark.pii`).

---

## 4. Retrieval & Search Enhancements

### 4.1 Hybrid Search (BM25 Lexical + Dense Vector Similarity) — *Implemented*
- **Status**: Implemented in `005-hybrid-search` (`Fts5HybridSearcher` registered as `"fts5_hybrid"` alongside collocated `LexicalIndex` in `store/lexical.py`).
- **Details**: Uses SQLite FTS5 (`unicode61`) BM25 fused with dense ChromaDB cosine rankings via theoretical-max normalized Reciprocal Rank Fusion (`k=60`, weights `0.5`/`0.5`), exposed via `retrieve(..., searcher="fts5_hybrid")`, `--searcher fts5_hybrid`, and TOML `searcher`.

### 4.2 Pluggable Reranking Stage — *Local Reranker Implemented (`007-cross-encoder-rerank`); Cloud Adapters Post-v0.2*
- **Implemented (`007-cross-encoder-rerank`)**: Child-first `Reranker` protocol (`@register_reranker` / `RERANKERS` registry), `validate_rerank_options()`, and lazy optional `[rerank]` `CrossEncoderReranker` (`BAAI/bge-reranker-base`, sigmoid `[0.0, 1.0]` scores, `--rerank`, `--reranker`, `--rerank-top-n`) executing prior to parent expansion.
- **Remaining Proposed Upgrade (Post-v0.2)**: Add optional cloud reranking adapters (e.g., Cohere Rerank) implementing the same `Reranker` protocol.

### 4.3 Query Rewriting & Expansion
- **Problem**: Ambiguous, brief, or poorly phrased user questions can lead to suboptimal semantic retrieval.
- **Proposed Upgrade**:
  - Provide optional pre-retrieval query expansion (e.g., Hypothetical Document Embeddings / HyDE, or multi-query generation).
  - Pure function transform over queries before embedding.

### 4.4 Structured Metadata Pre-Filtering — *Implemented*
- **Status**: Implemented in `010-metadata-filtering` (`src/docpipe_maestro/_filters.py`, `retrieve(..., where=...)`, `evaluate(..., where=...)`, and repeatable CLI `--where KEY=VALUE` across `query`, `ask`, and `eval`).
- **Details**: Supports stored chunk attributes (`source`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`), top-level manifest attributes (`profile` case-insensitively and ISO-8601 UTC `ingested_after` / `ingested_before` inclusive bounds) with zero re-ingestion migration and empty-allowlist short-circuiting prior to embeddings, full 10-operator parity across ChromaDB and SQLite FTS5 (`$eq`, `$ne`, `$in`, `$nin`, `$gt`–`$lte` for integer fields, `$and`/`$or`), upfront unknown-key and reserved `"type"` rejection, and mandatory `{"$and": [{"type": "child"}, ...]}` defense-in-depth. (Arbitrary custom user metadata tags at ingest time remain out of scope.)

---

## 5. Storage Architecture & Scale

### 5.1 Two-Collection Storage Split
- **Problem**: Child chunks and parent sections currently share a single ChromaDB collection (with parents storing zero vectors and filtered out during similarity queries; `ChromaStore.get_all()` already skips HNSW vector loading via `include=["documents", "metadatas"]` as of `v0.2.0`). For massive corpora (millions of chunks), zero-vector parent records in the HNSW index still add storage overhead.
- **Proposed Upgrade**:
  - Implement the planned two-collection migration: store child vectors in `<collection>_children` and parent sections in a key-value document store or separate unindexed collection `<collection>_parents`.

### 5.2 Additional Vector Database Backends — *`Store` Protocol & Registry Implemented (`004`); Additional Adapters Post-v0.2*
- **Implemented (`004-registry-refactor`)**: Runtime-checkable `Store` protocol (`docpipe_maestro.store.Store`) and `@register_store` / `STORES` registry (alongside `PARSERS`, `CLEANERS`, `ENRICHERS`, `CHUNKERS`, `EMBEDDERS`, `SEARCHERS`, and `RERANKERS`).
- **Remaining Proposed Upgrade (Post-v0.2)**: Implement additive storage adapters for:
  - **LanceDB** (zero-setup embedded storage on disk with columnar indexing).
  - **Qdrant** (high-performance vector engine for distributed deployments).
  - **SQLite-vec** (dependency-free pure SQLite vector extension).
  - **pgvector** (for enterprise PostgreSQL infrastructures).

---

## 6. Generation & Interaction Upgrades

### 6.1 Online LLM Customization & Role-Separated Chat — *Implemented*
- **Status**: Implemented in `002-online-llm-customization`.
- **Details**: Adds `build_chat_messages()`, `answer_detailed()` returning `GenerationResult`, generation tuning (`temperature`, `max_tokens`, `timeout`, `model_kwargs`), explicit `finish_reason="length"` / `reasoning_tokens` diagnostics, HTTPS gateway validation, scoped `.env` + `./docpipe.toml` discovery, and CLI `ask` flags (`--system-prompt`, `--system-prompt-file`, `--fail-on-truncation`, `--show-context`, `--json`).

### 6.2 Streaming Generation Support
- **Problem**: Generation waiting for completion blocks the caller until the full answer is generated.
- **Proposed Upgrade**:
  - Add streaming support to `answer()` yielding text chunks (`Iterator[str]`).
  - Add `--stream` flag to `docpipe-maestro ask` for real-time terminal output.

### 6.3 Citation Extraction & Verification
- **Problem**: LLMs can misattribute which retrieved section supported which claim in the generated text.
- **Proposed Upgrade**:
  - Add post-generation citation verification that programmatically checks whether asserted citations align with retrieved parent section content.
  - Return structured citation objects linking specific sentences to exact document sections.

---

## 7. Quality, Safety & Tooling

### 7.1 Automated Retrieval & Answer Evaluation Harness — *Retrieval Implemented; Answer Judge Post-v0.2*
- **Implemented (`006-eval-harness`)**: Deterministic, read-only retrieval evaluation (`docpipe_maestro.eval`, `docpipe-maestro eval`, `Precision@K`, standard IR `Recall@K`, `MRR`) with a 24-query curated policy suite (`tests/fixtures/eval_policy_corpus.json`) and offline `default` vs `fts5_hybrid` baselines (`docs/eval-baseline.{json,md}`).
- **Remaining Proposed Upgrade (Post-v0.2)**:
  - Build optional answer-synthesis checks measuring:
    - **Faithfulness** (does the generated answer contain claims absent from retrieved context?).
    - **Negative Rejection** (does `answer()` refuse cleanly when context is insufficient?).

### 7.2 Multi-Language & Stress-Testing Reverse Safety Corpus
- **Problem**: Current reverse safety tests focus on English exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`).
- **Proposed Upgrade**:
  - Expand fixture corpus with multi-language exception markers (e.g., Spanish, French, German).
  - Introduce synthetic fuzzing test cases that place contradictory clauses at document margins to test chunk boundary resilience.

---

## 8. CLI & Developer Experience

### 8.1 Dry-Run Mode for `sync` and `reindex` — *Implemented (`012-dry-run`)*
- **Status**: Implemented in `012-dry-run`.
- **Details**: Adds non-mutating `--dry-run` and machine-readable `--json` support across `sync()` / `docpipe-maestro sync` and `reindex()` / `docpipe-maestro reindex`, exposing offline chunk counts (`estimated_children`, `estimated_parents`), offline token totals (`estimate_tokens`), and offline LiteLLM cost estimates (`estimate_embedding_cost()`), with zero embedder calls, zero `.audit.jsonl` appends on `PiiBlockedError`, and lazy read-only `?mode=ro` SQLite inspection for `0`-byte immutable `chroma.sqlite3` previews.

### 8.2 Progress Hooks & OpenTelemetry Tracing — *Built-In JSON Stage Logging Implemented (`011-structured-logging`); OTel Export Post-v0.2*
- **Implemented (`011-structured-logging`)**: Stdlib-only `docpipe_maestro.log` (`JsonFormatter`, `correlation_id()`, `stage_event()`, passive `NullHandler` default) plus CLI `--log-json` / `--log-level` on `stderr`.
- **Remaining Proposed Upgrade (Post-v0.2)**:
  - Add optional progress callbacks to `ingest()` and `sync()`.
  - Add optional OpenTelemetry exporter spans bridging built-in `stage_event()` timings in production monitoring systems.

---

## Summary Matrix

| Upgrade / Feature | Domain | Status / Target Phase | Impact | Complexity |
|---|---|---|---|---|
| **Strategy + Registry Architecture (`register_*`)** | Architecture | *Implemented* (`004-registry-refactor`) | High (Extensibility) | Medium |
| **Online LLM Customization & `answer_detailed()`** | Generation / CLI | *Implemented* (`002-online-llm-customization`) | High (Flexibility) | Medium |
| **Hybrid Search (BM25 + Dense)** | Retrieval | *Implemented* (`005-hybrid-search`) | High (Recall) | Medium |
| **Evaluation Harness (Retrieval)** | Retrieval / QA | *Implemented* (`006-eval-harness`; Answer Eval Post-v0.2) | High (Verification) | Medium |
| **Pluggable Reranker** | Retrieval | *Local Implemented* (`007-cross-encoder-rerank`; Cloud Post-v0.2) | High (Precision) | Low |
| **Pre-Chunking `Enricher` Stage & PII Protection** | Ingestion / Safety | *Implemented* (`008-enricher-stage`, `009-pii-protection`) | High (Privacy / Safety) | Medium |
| **Metadata Pre-Filtering (`where`)** | Retrieval / Eval | *Implemented* (`010-metadata-filtering`) | High (Precision / Scoping) | Medium |
| **Structured JSON Telemetry (`docpipe_maestro.log`)** | Telemetry / CLI | *Implemented* (`011-structured-logging`; OTel Post-v0.2) | Medium (Observability) | Low |
| **Inter-Document Crossrefs** | Ingestion / Query | *Phase 2 Implemented* (`002`/`008`; Phase 1 Ingest Post-v0.2) | Medium (Completeness) | High |
| **Runtime Chunking Profiles** | Chunking | *Python API Implemented*; CLI Overrides Post-v0.2 | Medium (Flexibility) | Low |
| **Storage Adapters (Qdrant, LanceDB)** | Storage | *`Store` Protocol Implemented* (`004`); Adapters Post-v0.2 | Medium (Flexibility) | Medium |
| **Table Preservation** | Ingestion | Post-v0.2 | High (Accuracy) | Medium |
| **`LEGAL` Profile** | Chunking | Post-v0.2 | High (Domain Safety) | Medium |
| **Chunk-Level Differential Re-Embedding** | Ingestion | Post-v0.2 | High (Cost / Speed) | Medium |
| **Streaming Output (`docpipe-maestro ask`)** | Generation | Post-v0.2 | High (UX) | Low |
| **`--dry-run` for `sync`/`reindex`** | CLI / Ops | *Implemented* (`012-dry-run`) | Medium (Safety) | Low |
| **Additional Parsers (XLSX, PPTX)** | Intake | Post-v0.2 | Medium (Coverage) | Low |
| **Two-Collection Split** | Storage | Post-v0.2 | Medium (Scale) | High |
