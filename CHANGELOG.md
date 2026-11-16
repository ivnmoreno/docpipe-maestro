## Unreleased

### Feat

- **pii**: add configurable pre-chunking `PiiEnricher` (`redact`, `tokenize`, `block`) across headings, body text, and clauses, 7 built-in deterministic recognizers + extensible `@register_pii_recognizer` (`docpipe_maestro.register_pii_recognizer`, `PiiRecognizer`), lazy optional `[pii]` multi-language Presidio NER (`en`, `es`, etc. with zero runtime downloads), salted value-based HMAC tokenization, owner-only (`0o700`/`0o600`) zero-raw-PII `<collection>.audit.jsonl` logs with transactional `PiiBlockedError` rollback, shared `--local-only` / `local_only` preflight across embedding and generation workflows, Phase 2 `guard_egress` for prompt strings and ChatML messages, CLI `--pii-policy` JSON/TOML support, and Release Gate #2 (`@pytest.mark.pii`)
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
