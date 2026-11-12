# Future Features & Upgrades Backlog

> **Scope Guardrail & Alignment Principle:**  
> In accordance with the `docpipe-maestro` Constitution (Principle I: *"The engine — not the app, not the framework"*), any feature proposed for the core library must be accessible through the public library API and CLI without turning `docpipe-maestro` into an application server or framework. Features that require long-lived servers, authentication, or GUI layers belong in companion repositories or example wrappers.

This document aggregates all architectural suggestions, deferred backlog items, and future upgrade proposals identified across `Product.md`, the v0.1 specification (`specs/001-core-rag-pipeline/`), architectural research, and initial implementation.

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

### 2.1 `LEGAL` Chunking Profile (Deferred from v0.1)
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

### 2.3 User-Defined / Runtime Chunking Profiles
- **Problem**: Chunking profiles (`DEFAULT`, `POLICY`) are currently hardcoded Python constants to ensure determinism.
- **Proposed Upgrade**: Support user-defined profiles via code (`ChunkingProfile(...)`) and optionally via CLI configuration (`--profile-file custom_profile.toml`) while maintaining safe defaults.

---

## 3. Cross-Reference Resolution

### 3.1 Inter-Document Cross-Reference Resolution
- **Problem**: In v0.1, cross-reference resolution (`§2.1`, `Section 4`) operates intra-document only; references pointing to other documents in the corpus are logged as unresolved.
- **Proposed Upgrade**:
  - Maintain a corpus-wide section registry during batch ingestion.
  - Resolve cross-document citations (e.g., *"as defined in Employee Code of Conduct §3"*) across files indexed within the same collection.

### 3.2 Multi-Hop & Nested Cross-Reference Resolution
- **Problem**: References that chain across multiple clauses (e.g., Section 1.1 references Section 2.3, which in turn references Appendix B) may fail to include deep exceptions.
- **Proposed Upgrade**: Implement recursive reference expansion with cycle detection and a configurable maximum hop depth (e.g., depth 2).

---

## 4. Retrieval & Search Enhancements

### 4.1 Hybrid Search (BM25 Lexical + Dense Vector Similarity)
- **Problem**: Dense semantic embeddings excel at concepts but can miss exact clause identifiers (`§4.2.1`), acronyms, product numbers, or uncommon legal jargon.
- **Proposed Upgrade**:
  - Integrate a lightweight lexical index (e.g., BM25 / SQLite FTS5) alongside ChromaDB.
  - Fuse lexical and vector ranking using Reciprocal Rank Fusion (RRF) or weighted score normalization.

### 4.2 Pluggable Reranking Stage
- **Problem**: Vector similarity matches the closest candidates, but a dedicated cross-encoder reranker can dramatically increase top-1 precision.
- **Proposed Upgrade**:
  - Insert an optional reranker between child-chunk retrieval and parent expansion.
  - Support local rerankers (e.g., FlashRank, BGE-reranker) and cloud reranking APIs (e.g., Cohere Rerank) via a unified provider interface.

### 4.3 Query Rewriting & Expansion
- **Problem**: Ambiguous, brief, or poorly phrased user questions can lead to suboptimal semantic retrieval.
- **Proposed Upgrade**:
  - Provide optional pre-retrieval query expansion (e.g., Hypothetical Document Embeddings / HyDE, or multi-query generation).
  - Pure function transform over queries before embedding.

### 4.4 Structured Metadata Pre-Filtering
- **Problem**: Users may want to restrict retrieval to specific files, document versions, dates, or custom tags.
- **Proposed Upgrade**:
  - Expose structured metadata filters through `retrieve(where={...})` and the CLI (`docpipe query --filter 'source == "hr_policy.md"'`).
  - Pass filter predicates directly to ChromaDB's `where` query engine.

---

## 5. Storage Architecture & Scale

### 5.1 Two-Collection Storage Split
- **Problem**: In v0.1, child chunks and parent sections share a single ChromaDB collection (with parents storing zero vectors and filtered out during queries). For massive corpora (millions of chunks), zero-vector parent records add memory overhead.
- **Proposed Upgrade**:
  - Implement the planned two-collection migration: store child vectors in `<collection>_children` and parent sections in a key-value document store or separate unindexed collection `<collection>_parents`.

### 5.2 Additional Vector Database Backends
- **Problem**: Different deployment environments favor different storage engines (embedded vs. client-server vs. serverless).
- **Proposed Upgrade**:
  - Define an abstract `VectorStoreBase` protocol.
  - Implement additive adapters for:
    - **LanceDB** (zero-setup embedded storage on disk with columnar indexing).
    - **Qdrant** (high-performance vector engine for distributed deployments).
    - **SQLite-vec** (dependency-free pure SQLite vector extension).
    - **pgvector** (for enterprise PostgreSQL infrastructures).

---

## 6. Generation & Interaction Upgrades

### 6.1 Streaming Generation Support
- **Problem**: Generation waiting for completion blocks the caller until the full answer is generated.
- **Proposed Upgrade**:
  - Add streaming support to `answer()` yielding text chunks (`Iterator[str]`).
  - Add `--stream` flag to `docpipe ask` for real-time terminal output.

### 6.2 Citation Extraction & Verification
- **Problem**: LLMs can misattribute which retrieved section supported which claim in the generated text.
- **Proposed Upgrade**:
  - Add post-generation citation verification that programmatically checks whether asserted citations align with retrieved parent section content.
  - Return structured citation objects linking specific sentences to exact document sections.

---

## 7. Quality, Safety & Tooling

### 7.1 Automated Answer Evaluation Harness
- **Problem**: Ensuring ongoing answer quality across model upgrades requires continuous quantitative measurement.
- **Proposed Upgrade**:
  - Build an evaluation module measuring:
    - **Faithfulness** (does the answer contain claims not in the context?).
    - **Context Recall** (were all necessary sections retrieved?).
    - **Negative Rejection** (did the model refuse to answer when context was absent?).

### 7.2 Multi-Language & Stress-Testing Reverse Safety Corpus
- **Problem**: Current reverse safety tests focus on English exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`).
- **Proposed Upgrade**:
  - Expand fixture corpus with multi-language exception markers (e.g., Spanish, French, German).
  - Introduce synthetic fuzzing test cases that place contradictory clauses at document margins to test chunk boundary resilience.

---

## 8. CLI & Developer Experience

### 8.1 Dry-Run Mode for `sync` and `reindex`
- **Problem**: Users running `sync` or `reindex` on large corpora want to know what changes will occur before mutating the database or incurring embedding API costs.
- **Proposed Upgrade**:
  - Add `--dry-run` flag to `docpipe sync` and `docpipe reindex`.
  - Output summary report: number of new files, modified files, deleted files, estimated tokens, and estimated cost without making database or API changes.

### 8.2 Progress Hooks & OpenTelemetry Tracing
- **Problem**: Long ingestion runs provide limited progress visibility in programmatic environments.
- **Proposed Upgrade**:
  - Add optional progress callbacks to `ingest()` and `sync()`.
  - Add optional OpenTelemetry spans for tracing chunking, embedding latency, and retrieval times in production monitoring systems.

---

## Summary Matrix

| Upgrade / Feature | Domain | Proposed Phase | Impact | Complexity |
|---|---|---|---|---|
| **Table Preservation** | Ingestion | Post-v0.1 | High (Accuracy) | Medium |
| **`LEGAL` Profile** | Chunking | Post-v0.1 | High (Domain Safety) | Medium |
| **Chunk-Level Differential Re-Embedding** | Ingestion | Post-v0.1 | High (Cost / Speed) | Medium |
| **Hybrid Search (BM25 + Dense)** | Retrieval | Post-v0.1 | High (Recall) | Medium |
| **Streaming Output (`docpipe ask`)** | Generation | Post-v0.1 | High (UX) | Low |
| **`--dry-run` for `sync`/`reindex`** | CLI / Ops | Post-v0.1 | Medium (Safety) | Low |
| **Inter-Document Crossrefs** | Ingestion | Post-v0.1 | Medium (Completeness) | High |
| **Pluggable Reranker** | Retrieval | Post-v0.1 | High (Precision) | Low |
| **Additional Parsers (XLSX, PPTX)** | Intake | Post-v0.1 | Medium (Coverage) | Low |
| **Two-Collection Split** | Storage | Post-v0.1 | Medium (Scale) | High |
| **Storage Adapters (Qdrant, LanceDB)** | Storage | Post-v0.1 | Medium (Flexibility) | Medium |
| **Evaluation Harness** | QA / Safety | Post-v0.1 | High (Verification) | Medium |
