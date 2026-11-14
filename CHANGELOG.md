## Unreleased

### Feat

- **enricher**: formalize Phase 1 post-clean, pre-chunk `Enricher` stage (`ChunkingProfile.enrichers`, ordered execution with duplicate support, upfront `ENRICHERS` resolution, atomic abort guarantees, `IngestContext`), migrate intra-document cross-reference resolution into lazy `CrossrefsEnricher` (`"crossrefs"`), extract pure shared cross-reference helpers into `docpipe_maestro._crossrefs`, and keep silent `docpipe_maestro.ingest.crossrefs` compatibility re-exports
- **rerank**: add opt-in child-first local cross-encoder reranking (`--rerank`, `retrieve(..., rerank=True)`, `evaluate(..., rerank=True)`), optional `[rerank]` extra (`sentence-transformers`), lazy `CrossEncoderReranker` (`BAAI/bge-reranker-base`) with process-local model caching, CLI/TOML configuration, and live `Q1` benchmark validation
- **eval**: add read-only retrieval evaluation harness (`docpipe_maestro.eval`, `docpipe-maestro eval`), curated policy benchmark corpus, and offline `default` vs `fts5_hybrid` baselines
- **searcher**: add hybrid SQLite FTS5 BM25 + dense vector RRF search (`--searcher fts5_hybrid`) and collocated `LexicalIndex` lifecycle sync
- **pipeline**: implement v0.1 core RAG pipeline, CLI, and quality gates

### Fix

- **security**: harden pipeline, add CI workflow, and update gitignore

### Refactor

- **pipeline**: introduce Strategy + Registry extension architecture (`register_*` entry points)
- **cli**: rename CLI command to docpipe-maestro
