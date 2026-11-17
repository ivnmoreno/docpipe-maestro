# docpipe-maestro Documentation

Welcome to the documentation for **`docpipe-maestro`** — a minimal, provider-agnostic, structure-aware RAG pipeline library and CLI built around strict two-phase separation and exception preservation.

> *"docpipe-maestro is a minimal RAG pipeline: it ingests any document, chunks it correctly, embeds it, stores it, retrieves the right sections, and optionally generates a grounded answer. It is the engine — not the app, not the framework."*

---

## Documentation Guides

| Guide | Audience | What It Covers |
|---|---|---|
| **[README](../README.md)** | Everyone | Quickstart, installation extras, provider setup, and high-level workflow examples |
| **[Architecture & Internals](architecture.md)** | Engineers & Architects | Two-phase pipeline data flow, format parsing heuristics, pre-chunking `PiiEnricher` & crossref resolution, ChromaDB + SQLite FTS5 storage & `where` filtering, `.audit.jsonl`, and Phase 2 egress guard |
| **[Python API Reference](api-reference.md)** | Application Developers | Exact signatures (`sync`/`reindex` `dry_run=True`, `ReindexPreview`, `estimate_embedding_cost`, `answer(..., stream=True)`, `retrieve(..., where=...)`, `evaluate(..., where=...)`), `docpipe_maestro.log` telemetry exports, defaults, stage registries, searcher strategies, data models, constants, and exception hierarchy |
| **[CLI Reference (`docpipe-maestro`)](cli-reference.md)** | CLI Users & Ops | Global flags (`--log-json`, `--log-level`, `--local-only`, `--pii-policy`), `docpipe.toml` schema, all 8 subcommands (including `sync`/`reindex` `--dry-run` & `--json`, `ask --stream`, and `eval`), repeatable `--where` pre-filtering, `--searcher` modes, exact output formats, exit codes, and troubleshooting |
| **[Retrieval Evaluation Baselines](eval-baseline.md)** | Engineers & Maintainers | Side-by-side offline retrieval benchmark (`default` dense vs `fts5_hybrid`) on the curated policy corpus ([eval-baseline.json](eval-baseline.json)) |
| **[Development & Testing Guide](development.md)** | Contributors | Dev setup, `ruff`/`mypy --strict`/`pytest` quality gates, Release Gates #1 (`reverse`) & #2 (`pii`), live Ollama testing, and extension guidelines |
| **[Future Features Backlog](future-features.md)** | Maintainers & Roadmap | Implementation status and remaining deferred enhancements (`LEGAL` profile, differential re-embedding, citation verification, storage adapters) |

## Project & Design Context

- **[CHANGELOG](../CHANGELOG.md)**: Release history following Keep a Changelog and Conventional Commits.
- **[Product Description](../PRODUCT.md)**: Original product scope, personas, non-goals, and architectural rationale.
- **[Project Constitution](../.specify/memory/constitution.md)**: Non-negotiable design principles (Scope Discipline, Two-Phase Architecture, Library Purity, Search Small Return Big, Exception Preservation & PII Safety, Provider Agnosticism, Structured Correctness).
- **[Feature Specifications (`specs/`)](../specs/001-core-rag-pipeline/spec.md)**: Requirements, implementation plans, and contracts across `001-core-rag-pipeline` through `013-streaming-generation`.
