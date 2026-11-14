# Phase 0 Research: Hybrid Lexical Search with Reciprocal Rank Fusion

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/spec.md) | **Date**: 2026-11-14

## Research Decisions

### 1. Placement & Lifecycle of Collocated Lexical Index

- **Decision**: Implement `LexicalIndex` in `src/docpipe_maestro/store/lexical.py` inside the shared `store/` package using Python stdlib `sqlite3`, persisted at `<persist_dir>/lexical/<safe_collection>.db`. Maintain lexical index state exclusively during Phase 1 lifecycle operations (`ingest`, `sync`, `remove`, `reindex`) and read strictly in read-only mode during Phase 2 (`retrieve` / `Fts5HybridSearcher`).
- **Rationale**: Obeys Constitution Principle II (*Two-Phase Architecture*): shared `store/` serves Phase 1 writes and Phase 2 reads without cross-phase leakage, Phase 2 performs zero disk writes or latency-degrading backfills, and all crash-safety invariants (staging under uncommitted `doc_version`, post-manifest stale deletion, `sweep_uncommitted`) mirror `ChromaStore` identically.
- **Alternatives Considered**:
  - *Query-time index sync in Phase 2*: Rejected because it violates Principle II ("Phase 2 must treat the store and manifest as read-only") and adds unbounded query latency.
  - *External pure-Python BM25 library (`rank-bm25`, `bm25s`)*: Rejected because rebuilding/loading full inverted indexes in RAM violates `<15-20ms` cold-query latency and adds external dependencies.

### 2. Built-In Searcher Registry Layout (`"default"` vs `"fts5_hybrid"`)

- **Decision**: Register two lazy built-ins in `src/docpipe_maestro/query/searcher/__init__.py`:
  1. `"default"` -> `DenseSearcher` (`src/docpipe_maestro/query/searcher/dense.py`) encapsulating current dense child retrieval cleanly.
  2. `"fts5_hybrid"` -> `Fts5HybridSearcher` (`src/docpipe_maestro/query/searcher/hybrid.py`) combining dense child retrieval + `LexicalIndex` BM25 search via RRF.
  Both constructors accept zero required arguments (satisfying `Searcher` protocol) and optional keyword-only `embedder: str = "default"`, `store: str = "default"` so `retrieve(..., embedder=..., store=...)` forwards custom backends cleanly while preserving custom third-party `Searcher` plugin compatibility.
- **Rationale**: Makes `"default"` a first-class inspectable `Searcher` entry while preserving bit-for-bit identical Stage 1 dense output, deferring `chromadb`/`litellm`/`sqlite3` imports until runtime resolution (`register_lazy`), and allowing `retrieve()` to handle `threshold`, `expand_parent`, and `follow_crossrefs` uniformly across any registered `Searcher`.
- **Alternatives Considered**:
  - *Special-casing `"default"` without registering it in `SEARCHERS`*: Rejected because it creates an asymmetric registry where `SEARCHERS.keys()` omits the default implementation.

### 3. SQLite FTS5 Schema, Sanitization, and Performance

- **Decision**: Create FTS5 virtual table `chunks_fts` with `tokenize='unicode61'`, indexing `(section, clause, content)` with `bm25(chunks_fts, 1.5, 2.0, 1.0)` weighting and storing `UNINDEXED` provenance columns (`chunk_id`, `parent_id`, `source`, `doc_version`, `page`, `chunk_index`, `embed_model`) directly in the row so lexical hits reconstruct `RetrievedChunk` in a single query without ChromaDB round-trips. Sanitize queries via regex extraction (`[^\W]+(?:[.\-:/][^\W]+)*`), capping at 64 deduplicated terms, double-quote escaping (`"` -> `""`), and `OR`-joining tokens.
- **Rationale**: Tested directly against runtime `sqlite3`: quoted phrase tokens prevent syntax crashes on hyphens (`SEV-1`), dots (`1.2`), unbalanced quotes, wildcards, and SQL operators (`AND`, `OR`, `NOT`), while `OR`-joining + `bm25()` lets high-overlap technical terms dominate ranking without returning zero hits when stopwords appear in the question. Unindexed provenance columns eliminate secondary N+1 store reads, keeping FTS5 queries well under 5ms on 5,000 chunks.
- **Alternatives Considered**:
  - *Joining tokens with `AND`*: Rejected because a single stopword or synonymous word in a natural-language question causes false-negative zero lexical results.
  - *Using `porter unicode61` stemmer*: Rejected in favor of plain `unicode61` so exact technical codes, acronyms, and model identifiers aren't distorted by stemming.

### 4. Unindexed Collection Detection & Legacy Behavior (Clarified Q1 = A)

- **Decision**: Before running FTS5 lookup inside `Fts5HybridSearcher.search(...)`, verify lexical index readiness whenever `manifest` contains committed child chunks (`sum(len(s.chunk_ids) for s in manifest.sources.values()) > 0`). If the collocated DB is absent, uninitialized, or empty despite committed children existing, raise `DocpipeError` instructing the user to run `docpipe-maestro reindex --model <model> --collection <collection>` or re-ingest with `--force`. Meanwhile, `ingest_empty` (`0` children) initializes an empty schema cleanly so empty-file collections return `[]` rather than erroring.
- **Rationale**: Matches resolved Q1 (`Option A`), strictly respects Principle II (no Phase 2 disk mutations), avoids silent accuracy degradation, and upgrades cleanly via `pipeline.reindex()` rebuilding both ChromaDB and `LexicalIndex`.
- **Alternatives Considered**:
  - *Read-only in-memory BM25 fallback*: Rejected per Q1 clarification.

### 5. Reciprocal Rank Fusion Formula & Normalization (Clarified Q2 = A, Q3 = A)

- **Decision**: Fetch candidate pool `candidate_k = max(top_k * 2, 20)` from dense `Store.query_children` and `LexicalIndex.search`. Fuse by 1-based rank:
  $$\text{raw}(c) = \frac{0.5}{60 + r_{\text{dense}}(c)} + \frac{0.5}{60 + r_{\text{lexical}}(c)}$$
  $$\text{score}(c) = \min\left(1.0,\ \max\left(0.0,\ \frac{\text{raw}(c)}{1.0 / 61}\right)\right)$$
  Sort deterministically by `(-score, id)` and return top `top_k` `RetrievedChunk` items (before `retrieve()` applies optional `threshold`, `expand_parent`, and `follow_crossrefs`).
- **Rationale**: Matches resolved Q2 (`Option A`) and Q3 (`Option A`). Dual #1 matches normalize to `1.0`, single-signal #1 matches normalize to `0.5`, preserving discrimination for `threshold` filtering while keeping `k=60` and equal `0.5/0.5` weights fixed per Principle I.
- **Alternatives Considered**:
  - *Query-relative min-max scaling*: Rejected because it inflates every query's top hit to `1.0`, blinding threshold filters.

### 6. Safety & Security Controls

- **Decision**: Reuse `manifest.validate_collection_name()` and path-containment verification (`resolve().is_relative_to(...)`), call `manifest.ensure_private_dir()` (`0o700`) and enforce `0o600` file permissions on the SQLite DB, open SQLite read-only (`file:<uri>?mode=ro` with `uri=True`) during Phase 2 so SQLite cannot accidentally create or modify DB files on disk during queries, and keep all SQL queries parameterized (`?`) cleanly passing `ruff check --select S`.
- **Rationale**: Eliminates SQL injection vectors, prevents Phase 2 accidental file creation on nonexistent DB paths, and maintains parity with Chroma/manifest security hardening.
