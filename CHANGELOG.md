## v0.2.1 (2026-11-17)

### Fix

- **store**: persist small HNSW segments eagerly (`hnsw:sync_threshold=2`) so small local collections (< 1,000 records) survive ChromaDB <= 1.5.9 Foyer cache eviction on low-file-handle platforms (Windows `512` / macOS `256`), and expose idempotent `ChromaStore.close()` and context-manager handle cleanup

### Docs

- **readme**: switch installation guide to PyPI and add PyPI badge
- **roadmap**: reconcile `docs/future-features.md` and `docs/README.md` with shipped `v0.2.0` milestones

## v0.2.0 (2026-11-17)

### Feat

- **log**: add opt-in structured JSON logging and `ContextVar`-backed `correlation_id()` tracing via submodule `docpipe_maestro.log` (`JsonFormatter`, `TextFormatter`, `get_logger()` with passive `NullHandler`-only defaults, `stage_event()` timing helper with `isEnabledFor()` short-circuiting), instrument Phase 1 (`ingest`, `sync`, `remove`, `status`, `reindex` with `INFO` batch summaries and `DEBUG` per-doc details across `intake`/`clean`/`enrich`/`chunk`/`embed`/`store`) and Phase 2 (`retrieve`, searchers, `rerank`, `guard_egress`, `answer_detailed`, `evaluate` across `embed`/`search`/`rerank`/`egress`/`answer`) with traceback-free `ERROR` `error_type` failure attribution and zero raw PII/content/secret emission, and add CLI-only global `--log-json` / `--log-level {DEBUG,INFO,WARNING,ERROR}` flags writing strictly to `stderr`
- **retrieve**: add structured metadata pre-filtering via `retrieve(..., where=...)`, `evaluate(..., where=...)`, and repeatable CLI `--where KEY=VALUE` across `query`, `ask`, and `eval`, supporting stored chunk fields (`source`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`), top-level manifest attributes (`profile` case-insensitive, UTC ISO-8601 `ingested_after` / `ingested_before` inclusive bounds) with zero re-ingestion migration and zero-embedder empty short-circuiting, full 10-operator Chroma + FTS5 SQLite parity (`$eq`, `$ne`, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$and`, `$or`), and upfront unknown-key / reserved `"type"` validation with store-level `{"$and": [{"type": "child"}, ...]}` defense-in-depth
- **pii**: add configurable pre-chunking `PiiEnricher` (`redact`, `tokenize`, `block`) across headings, body text, and clauses, 7 built-in deterministic recognizers + extensible `@register_pii_recognizer` (`docpipe_maestro.register_pii_recognizer`, `PiiRecognizer`), lazy optional `[pii]` multi-language Presidio NER (`en`, `es`, etc. with zero runtime downloads), salted value-based HMAC tokenization, owner-only (`0o700`/`0o600`) zero-raw-PII `<collection>.audit.jsonl` logs with transactional `PiiBlockedError` rollback, shared `--local-only` / `local_only` preflight across embedding and generation workflows, Phase 2 `guard_egress` for prompt strings and ChatML messages, CLI `--pii-policy` JSON/TOML support, and Release Gate #2 (`@pytest.mark.pii`)
- **enricher**: formalize Phase 1 post-clean, pre-chunk `Enricher` stage (`ChunkingProfile.enrichers`, ordered execution with duplicate support, upfront `ENRICHERS` resolution, atomic abort guarantees, `IngestContext`), migrate intra-document cross-reference resolution into lazy `CrossrefsEnricher` (`"crossrefs"`), extract pure shared cross-reference helpers into `docpipe_maestro._crossrefs`, and keep silent `docpipe_maestro.ingest.crossrefs` compatibility re-exports
- **rerank**: add opt-in child-first local cross-encoder reranking (`--rerank`, `retrieve(..., rerank=True)`, `evaluate(..., rerank=True)`), optional `[rerank]` extra (`sentence-transformers`), lazy `CrossEncoderReranker` (`BAAI/bge-reranker-base`) with process-local model caching, CLI/TOML configuration, and live `Q1` benchmark validation
- **eval**: add read-only retrieval evaluation harness (`docpipe_maestro.eval`, `docpipe-maestro eval`), curated policy benchmark corpus, and offline `default` vs `fts5_hybrid` baselines
- **searcher**: add hybrid SQLite FTS5 BM25 + dense vector RRF search (`--searcher fts5_hybrid`) and collocated `LexicalIndex` lifecycle sync
- **query**: add online LLM customization (`temperature`, `max_tokens`, `timeout`, `model_kwargs`), `build_chat_messages()` role separation, `answer_detailed()` + `GenerationResult`, CLI/TOML `ask` options (`--system-prompt`, `--system-prompt-file`, `--fail-on-truncation`, `--show-context`, `--json`), loopback-vs-HTTPS `api_base` transport validation, scoped CLI `.env` + `./docpipe.toml` auto-discovery (`--no-config`), direct Ollama `/api/embed` fast path, digit-normalized header/footer stripping, and cross-document `follow_crossrefs` retrieval
- **cli**: add `docpipe-maestro query --json` structured retrieval output envelope

### Refactor

- **pipeline**: introduce Strategy + Registry extension architecture (`register_*` entry points)

### Fix

- **query**: improve multi-section prompt synthesis and report explicit `finish_reason="length"` / `reasoning_tokens` diagnostics on empty model responses
- **eval**: use `math.fsum` in aggregate metrics for Python 3.12+ determinism
- **store**: skip unnecessary HNSW vector reads in `get_all()` and release test Chroma database handles cleanly on Windows
- **cross-os**: normalize LF line endings across fixtures via `.gitattributes`, handle `float32` / `os.PathLike` checks across macOS and Windows, and advance `mtime` explicitly in same-size manifest fast-path tests

### CI & Docs

- **workflow**: harden GitHub Actions CI matrix (`3.10`–`3.13`, `--no-extras` core smoke, `uv build` + `twine check --strict`, `pip-audit`, macOS/Windows smoke) and add OIDC Trusted Publishing release workflow (`.github/workflows/release.yml`)
- **docs**: enrich `README.md`, `docs/` guides, `CONTRIBUTING.md`, `SECURITY.md`, and `PRODUCT.md`, plus add Contributor Covenant Code of Conduct and `.env.example`

## v0.1.0 (2026-11-13)

### Feat

- **pipeline**: implement v0.1 core RAG pipeline, CLI, and quality gates

### Fix

- **security**: harden pipeline, add CI workflow, and update gitignore

### Refactor

- **cli**: rename CLI command to docpipe-maestro
