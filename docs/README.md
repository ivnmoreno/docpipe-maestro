# docpipe-maestro Documentation

Welcome to the documentation for **`docpipe-maestro`** — a minimal, provider-agnostic, structure-aware RAG pipeline library and CLI built around strict two-phase separation and exception preservation.

> *"docpipe-maestro is a minimal RAG pipeline: it ingests any document, chunks it correctly, embeds it, stores it, retrieves the right sections, and optionally generates a grounded answer. It is the engine — not the app, not the framework."*

---

## Documentation Guides

| Guide | Audience | What It Covers |
|---|---|---|
| **[README](../README.md)** | Everyone | Quickstart, installation extras, provider setup, and high-level workflow examples |
| **[Architecture & Internals](architecture.md)** | Engineers & Architects | Two-phase pipeline data flow, format parsing heuristics, crossref resolution, structure-aware chunking, ChromaDB + SQLite FTS5 storage, and crash-safe staging |
| **[Python API Reference](api-reference.md)** | Application Developers | Exact signatures, defaults, stage registries, searcher strategies, data models, constants, and exception hierarchy |
| **[CLI Reference (`docpipe-maestro`)](cli-reference.md)** | CLI Users & Ops | Global flags, `docpipe.toml` schema, all 8 subcommands (including `eval`), `--searcher` modes, exact output formats, exit codes, and troubleshooting |
| **[Retrieval Evaluation Baselines](eval-baseline.md)** | Engineers & Maintainers | Side-by-side offline retrieval benchmark (`default` dense vs `fts5_hybrid`) on the curated policy corpus ([eval-baseline.json](eval-baseline.json)) |
| **[Development & Testing Guide](development.md)** | Contributors | Dev setup, `ruff`/`mypy --strict`/`pytest` quality gates, mandatory reverse safety gate, live Ollama testing, and extension guidelines |
| **[Future Features Backlog](future-features.md)** | Maintainers & Roadmap | Deferred post-v0.1 enhancements aligned with scope discipline (`LEGAL` profile, differential re-embedding, hybrid search, storage adapters) |

## Project & Design Context

- **[CHANGELOG](../CHANGELOG.md)**: Release notes and unreleased changes following Keep a Changelog and Conventional Commits.
- **[Product Description](../PRODUCT.md)**: Original product scope, personas, non-goals, and architectural rationale.
- **[Project Constitution](../.specify/memory/constitution.md)**: Non-negotiable design principles (Scope Discipline, Two-Phase Architecture, Library Purity, Search Small Return Big, Exception Preservation, Provider Agnosticism, Structured Correctness).
- **[v0.1 Feature Specification](../specs/001-core-rag-pipeline/spec.md)**: Requirements, implementation plan, and contracts generated during v0.1 design.
