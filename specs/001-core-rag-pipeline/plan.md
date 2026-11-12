# Implementation Plan: Core RAG Pipeline

**Branch**: `001-core-rag-pipeline` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-core-rag-pipeline/spec.md`

## Summary

Implement `docpipe-maestro` v0.1, a minimal, provider-agnostic two-phase RAG pipeline Python library and `docpipe` CLI. Phase 1 (`ingest`, `sync`, `remove`, `status`, `reindex`) performs atomic multi-format document intake, structure-aware hierarchical parent-child chunking (preserving clauses and resolving intra-document cross-references), batched embeddings via `litellm`, and crash-safe delete-then-reinsert persistence into embedded ChromaDB paired with a database-collocated `sha256` manifest. Phase 2 (`retrieve`, `build_prompt`, optional `answer`) treats the store and manifest as read-only, queries child chunks via `where={"type": "child"}` on normalized cosine similarity, expands deduplicated parent sections ordered by `max(score)`, constructs citation-grounded prompts purely offline, and optionally invokes local (Ollama default) or cloud LLMs via `provider/model` strings.

## Technical Context

**Language/Version**: Python `>=3.10` (validated on Python 3.12.3)
**Primary Dependencies**: `chromadb>=0.5.0` (local embedded vector store), `litellm>=1.55.0` (base SDK without `[proxy]` for unified `provider/model` embeddings and optional generation), `langchain-text-splitters>=0.3.0` (fallback structural splitting), plus optional per-format extras (`pypdf>=4.0.0`, `python-docx>=1.1.0`, `beautifulsoup4>=4.12.0`) and `generation` extra
**Storage**: Embedded `chromadb.PersistentClient` (`hnsw:space: cosine`) + database-collocated JSON manifest (`<persist_dir>/manifests/<collection>.json`)
**Testing**: `pytest>=8.0.0`, `pytest-cov`, deterministic offline fixture reverse safety suite (`tests/test_reverse_safety.py`), `ruff` (lint/format), `mypy --strict`
**Target Platform**: Cross-platform local workstations/servers (Linux/macOS/Windows), 16 GB RAM without GPU requirement for default local models
**Project Type**: Python library + `docpipe` CLI (`src/` layout via `hatchling` + `hatch-vcs`)
**Performance Goals**: Pure sub-millisecond `build_prompt`; `mtime`/`size` fast-path skip for unchanged files during `ingest`/`sync`; batched Phase 1 embeddings
**Constraints**: Zero outbound network calls under local Ollama configuration (offline-safe token estimator without runtime BPE downloads); no user config file reads inside library modules (`cli.py` only); credentials via env vars only; MIT-compatible dependency licensing
**Scale/Scope**: Single ChromaDB collection per corpus (`v0.1`); personal to mid-size document collections (hundreds to low tens of thousands of sections)

## Constitution Check

*GATE: Evaluated before Phase 0 research and re-verified after Phase 1 design.*

| Principle / Constraint | Compliance Status | How Satisfied in Design |
|---|---|---|
| **I. Scope Discipline (NON-NEGOTIABLE)** | PASS | Public API exports solely `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, optional `answer`, shared types (`Chunk`, `EmbeddedChunk`, `RetrievedChunk`, result/status types), and exceptions. Zero UI, HTTP, auth, session, or streaming code. |
| **II. Two-Phase Architecture** | PASS | Phase 1 modules live under `ingest/`, Phase 2 modules under `query/`, and shared primitives (`types.py`, `config.py`, `store.py`, `manifest.py`, `embedder.py`) at package root. Phase 2 treats ChromaDB and manifest strictly read-only. |
| **III. Library Purity** | PASS | Only `cli.py` parses optional `--config` TOML files. Chunking profiles (`DEFAULT`, `POLICY`) are Python constants in `config.py`. Zero provider registry in code; `litellm` resolves `provider/model` strings using env vars only. |
| **IV. Search Small, Return Big (NON-NEGOTIABLE)** | PASS | Child chunks carry `parent_id` and `metadata["type"] = "child"`; parents store `[0.0] * dim` with `metadata["type"] = "parent"` and are excluded from search by `where={"type": "child"}`. Parents are expanded by ID and deduplicated (`max(score)`). |
| **V. Exception Preservation** | PASS | `POLICY` profile forbids mid-clause splitting, keeps section context intact via parent expansion, resolves intra-document crossrefs, and uses staged delete-then-reinsert to prevent orphaned deleted clauses. Mandatory `tests/test_reverse_safety.py` gate verifies all 5 exception markers. |
| **VI. Provider Agnosticism & Local-First** | PASS | Default embedding (`ollama/nomic-embed-text`) and generation (`ollama/llama3.2`) are local; offline token estimator avoids `tiktoken` network fetches; switching providers requires only changing `provider/model` and setting env vars. |
| **VII. Structured Correctness Over Speed** | PASS | Splitting hierarchy: headings → sections → clauses → sentences → chars; overlap resets at section boundaries; crossrefs resolved or logged; single source of data shapes in `types.py`; content-hash manifest prevents stale index drift. |
| **Data, Quality Gates & Footprint** | PASS | Transactional staging (`doc_version`) + atomic manifest swap (`os.replace`); MIT/BSD permissive extras (`pypdf`, `python-docx`, `beautifulsoup4`) keep core install lean; CI enforces `ruff`, `mypy`, `pytest`, and reverse test gate. |

**Post-Design Re-Check**: All Phase 1 artifacts (`data-model.md`, `contracts/python-api.md`, `contracts/cli.md`, `quickstart.md`) adhere strictly to Principles I–VII with zero constitutional exceptions or waivers required.

## Project Structure

### Documentation (this feature)

```text
specs/001-core-rag-pipeline/
├── plan.md              # This implementation plan
├── research.md          # Phase 0 technical decisions & dependency rationale
├── data-model.md        # Entity schemas, storage record mapping & staging flow
├── quickstart.md        # End-to-end validation & safety gate guide
├── contracts/
│   ├── python-api.md    # Public library functions, types & exceptions
│   └── cli.md           # docpipe CLI commands & flags
└── tasks.md             # Phase 2 breakdown (/speckit-tasks)
```

### Source Code (repository root)

```text
pyproject.toml
README.md
LICENSE
src/
└── docpipe_maestro/
    ├── __init__.py          # Public API surface + lazy optional answer export
    ├── py.typed             # PEP 561 type information marker
    ├── types.py             # Single source of truth for Chunk, EmbeddedChunk, RetrievedChunk, Manifest, Results, Errors
    ├── config.py            # Static constants: DEFAULT & POLICY ChunkingProfiles, default models
    ├── embedder.py          # Shared unified embedding client (litellm.embedding batching)
    ├── store.py             # Shared ChromaDB PersistentClient adapter (cosine space, where={"type": "child"}, staging cleanup)
    ├── manifest.py          # Shared DB-collocated manifest (sha256, mtime fast-path, atomic swap, embed_model lock)
    ├── cli.py               # Entry point (`docpipe`); sole module permitted to read optional user config file
    ├── ingest/              # Phase 1 (Offline batch ingestion & corpus lifecycle)
    │   ├── __init__.py
    │   ├── intake.py        # Multi-format parser (.md, .txt built-in; .pdf, .docx, .html extras) + magic-byte fallback
    │   ├── clean.py         # Artifact removal, whitespace normalization, boilerplate stripping
    │   ├── crossrefs.py     # Intra-document cross-reference detection, cycle-safe resolution & warning logs
    │   ├── chunker.py       # Structure-aware hierarchical splitter (parent + child, context header, scoped overlap)
    │   └── pipeline.py      # Orchestrates ingest, sync, remove, status, reindex & transactional staging
    └── query/               # Phase 2 (Online read-only retrieval, prompting & optional answer)
        ├── __init__.py
        ├── retriever.py     # Child search, doc_version check, threshold filter, parent expansion & max-score dedup
        ├── prompts.py       # Pure sub-ms prompt builder with grounding rules and source citations
        └── answer.py        # Optional grounded generation (empty-context short-circuit + litellm.completion)

tests/
├── conftest.py              # Offline embedding/LLM test doubles & temp ChromaDB fixtures
├── fixtures/
│   ├── docs/                # Sample .pdf, .docx, .html, .md, .txt test documents
│   └── policy_corpus/       # Curated policy fixtures covering all 5 exception markers
├── test_intake_clean.py     # Multi-format parsing, magic fallback, atomic fail-fast on bad files
├── test_crossrefs.py        # Intra-document resolution, cycle guard, logging unresolved refs
├── test_chunker.py          # Structure hierarchy, clause preservation, parent-child IDs, scoped overlap
├── test_store.py            # Metadata None-stripping, where={"type": "child"}, parent fetch, doc_version delete
├── test_manifest.py         # mtime fast-path, sha256 check, 3-way sync, shrinking-file zero-orphan, rollback, model lock
├── test_retriever.py        # Parent expansion, max(score) dedup, threshold cutoff, expand_parent=False
├── test_prompts_answer.py   # Pure build_prompt, short-circuit refusal, credential leak prevention, env var routing
├── test_cli.py              # All 7 CLI subcommands & --config handling isolated to cli.py
└── test_reverse_safety.py   # Mandatory Release Gate: 100% exception preservation across policy corpus
```

**Structure Decision**: Phase-grouped single-package `src/` layout placing shared contracts/state (`types.py`, `config.py`, `embedder.py`, `store.py`, `manifest.py`) at root and isolating Phase 1 (`ingest/`) from Phase 2 (`query/`). This satisfies `Product.md` §16 #2 and Constitution Principle II so every module's execution phase is immediately legible from the directory tree.

## Complexity Tracking

No Constitution violations or complexity waivers are required. All principles I–VII and footprint/safety constraints are satisfied directly by the planned architecture.
