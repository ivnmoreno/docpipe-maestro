# Future Features & Additions (Post-v0.1 Backlog)

> **Scope Guardrail:** Every proposed addition must pass the `docpipe-maestro` Constitution's one-sentence positioning test: *"It is the engine — not the app, not the framework"* and be reachable through the public library API.

## 1. Chunking Profiles & Domain Intelligence

- **`LEGAL` Profile (Deferred from v0.1)**
  - Dedicated parameters for contracts, terms of service, and regulatory filings (to be calibrated after `POLICY` reverse-test benchmarks).
  - Mandatory cross-reference resolution (including defined-term lookback, e.g., `"Affiliate" as defined in Section 1.2`) and mandatory reverse-test coverage for legal exception markers (`notwithstanding`, `save as otherwise`, `subject to`).
- **Table & Structured List Preservation**
  - Markdown/HTML/PDF table-aware chunking that keeps table headers attached to split row groups so numeric/eligibility matrices remain interpretable.

## 2. Retrieval & Search Enhancements (Phase 2)

- **Hybrid Search (Keyword + Vector)**
  - Combine BM25/lexical matching with dense vector similarity (e.g., Reciprocal Rank Fusion) to improve exact-match recall on clause numbers (`§4.2.1`), form codes, and acronyms.
- **Optional Reranking Stage**
  - Pluggable cross-encoder or lightweight local reranker between child-chunk retrieval and parent expansion.
- **Query Rewriting / Expansion**
  - Optional pre-retrieval query normalization or multi-query expansion for ambiguous user questions.
- **Metadata Pre-Filtering**
  - Expose structured `where` filters (e.g., filter by `source` document, `section`, or date range) via `retrieve()` and `docpipe query`.

## 3. Storage & Ingestion Scaling (Phase 1 & 2)

- **Two-Collection Storage Split**
  - Migration path from the single-collection `type="child"|"parent"` design to separate `children` (vector-indexed) and `parents` (KV/document store) collections if corpus size grows large.
- **Additional Vector Database Adapters**
  - Additive backend adapters (e.g., Qdrant, LanceDB, pgvector) behind the `store.py` interface without modifying upstream chunking/retrieval logic.
- **Additional Document Parsers**
  - Additive intake extras for `.xlsx`, `.pptx`, `.epub`, and `.rst`.
- **Differential / Chunk-Level Re-Embedding**
  - Compare content-addressed chunk IDs before calling the embedding provider during updates so unchanged clauses within an edited document are not re-embedded.

## 4. Quality, Safety & Tooling

- **Answer Evaluation Harness**
  - Separate evaluation tooling measuring faithfulness, context recall, and citation accuracy on top of the reverse safety test.
- **Expanded Reverse Test Corpus Fixtures**
  - Multi-language exception-marker fixtures and nested cross-reference stress tests.
- **Dry-Run Mode for `sync` / `reindex`**
  - `--dry-run` flag on `docpipe sync` and `docpipe reindex` to preview `NEW`, `CHANGED`, `DELETED`, and `SKIPPED` counts before mutating the store.
