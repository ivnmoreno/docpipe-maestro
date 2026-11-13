# Implementation Plan: Pluggable Pipeline Stage Registries

**Branch**: `refactor/004-registry-refactor` (spec `004-registry-refactor`) | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from [spec.md](spec.md) (clarifications Q1 and Q2 resolved).

## Summary

Refactor `docpipe-maestro`'s Phase 1 ingestion and Phase 2 retrieval pipelines into a uniform Strategy + Registry extension architecture with zero behavioral changes. Introduce a generic deferred-safe `Registry[T]` (`src/docpipe_maestro/_registry.py`), public `RegistryError(DocpipeError)` (`types.py`), parser format/content-sniffing router (`src/docpipe_maestro/_resolve.py`), phase-neutral shared `Protocol` contracts (`_stages.py` for `Embedder` and `Store`), Phase 1 (`ingest/stages.py`) and Phase 2 (`query/stages.py`) `Protocol` contracts, lightweight lazy-initialized stage subpackages wrapping built-in parser/cleaner/chunker/embedder/store implementations, empty contract-only registries for `Enricher`, `Searcher`, and `Reranker`, and strictly backward-compatible optional keyword-only stage selector parameters (`cleaner`, `chunker`, `embedder`, `store` defaulting to `"default"`), backed by registry, API-stability, library-purity AST, §1.3 invariant, and offline golden-query regression gates.

## Technical Context

**Language/Version**: Python `>=3.10` (CI matrix `3.10`, `3.11`, `3.12`, `3.13`; typing checked against `python_version = "3.10"`)
**Primary Dependencies**: `chromadb>=1.5.9`, `litellm>=1.108.0`, `langchain-text-splitters>=0.3.0`, `python-dotenv>=1.0.0` (CLI only), `tomli>=2.0.0; python_version < '3.11'` (CLI only); optional extras `pypdf>=6.21.3` (`[pdf]`), `python-docx>=1.1.0` (`[docx]`), `beautifulsoup4>=4.12.0` (`[html]`). Zero new runtime or dev dependencies added.
**Storage**: Persistent local ChromaDB (`PersistentClient`, cosine HNSW index) + atomic JSON collection manifests under `<persist_dir>/manifests/<collection>.json` (`0o700` owner-restricted directory permissions)
**Testing**: `pytest>=8.0.0`, `pytest-cov>=5.0.0` (`--strict-markers`, `filterwarnings = ["error"]`, branch coverage `fail_under = 80`), `ruff>=0.8.0` (`E, W, F, I, UP, B, SIM, RUF` + `--select S src/`), `mypy>=1.11.0` (`strict = true` across `src` and `tests`)
**Target Platform**: Cross-platform OS independent local workstation / air-gapped CPU server (POSIX `0o700` permission guards where supported)
**Project Type**: Library + CLI (`src/docpipe_maestro`, entry point `docpipe-maestro`)
**Performance Goals**: Instantaneous top-level import & CLI `--help` parser initialization with zero eager `chromadb` / `litellm` imports; zero per-query latency increase (`include_embeddings=False`, read-only Phase 2)
**Constraints**: Zero behavioral drift from Stage 0 baseline across all 14 load-bearing §1.3 invariants; `RegistryError` must inherit `DocpipeError`; new public callable stage selectors must be strictly keyword-only defaulting to `"default"`; `@dataclass(slots=True)` preserved without `.__dict__` access; Python 3.10 stdlib typing compatibility (no `NotRequired`/`Self`)
**Scale/Scope**: Single-package refactor (`~20` source modules converted cleanly into stage subpackages + compatibility shims; `~12` existing baseline test modules untouched + `4` new verification test suites + golden fixture snapshot)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Gate Evaluation

| Principle / Gate | Compliance Status | Assessment |
|---|---|---|
| **I. Scope Discipline** | PASS | Refactor strictly serves the core engine ("ingest, chunk, embed, store, retrieve, answer") and exposes all extension entry points directly on the public surface (`register_*`, `RegistryError`). Concrete future stages remain out of scope. |
| **II. Two-Phase Architecture** | PASS | Phase 1 (`ingest/stages.py`, `ingest/{intake,clean,enricher,chunker}/`) and Phase 2 (`query/stages.py`, `query/{searcher,reranker}/`) contracts remain strictly separated; shared infrastructure and shared `Embedder`/`Store` contracts live cleanly in `_registry.py`, `_stages.py`, `types.py`, `embedder/`, `store/` so Phase 2 never imports Phase 1 stage definitions. (`query/retriever.py` crossref helper import decoupling from `ingest/crossrefs.py` is tracked cleanly for Stage 3 per roadmap without altering Stage 1 scope.) |
| **III. Library Purity** | PASS | Zero non-CLI modules read config files or `.env`; verified via new AST guard (`tests/test_library_purity.py`). No provider registry added (`provider/model` still routes through `LiteLLMEmbedder`). |
| **IV. Search Small, Return Big** | PASS | `ChromaStore.query_children` still enforces `where={"type": "child"}`, child `parent_id` linkage, and deduplicated parent expansion in `retrieve()`. |
| **V. Exception Preservation (Release Gate #1)** | PASS | Chunking rules, overlap, crossrefs, parent expansion, and `tests/test_reverse_safety.py` (`@pytest.mark.reverse`) remain unmodified. |
| **VI. Provider Agnosticism & Local Default** | PASS | `LiteLLMEmbedder` wraps existing direct-Ollama fast path + `prepare_litellm()` local cost map and `validate_api_base()` / secret redaction logic unchanged. |
| **VII. Structured Correctness Over Speed** | PASS | `ParsedClause`, `ParsedSection`, `ParsedDocument`, and `IngestContext` centralize into `types.py` as the single schema source of truth with compatibility re-exports. |
| **Data, Quality Gates & Footprint** | PASS | All 14 §1.3 invariants preserved verbatim (plus explicit guards added for `sweep_uncommitted` & empty `dim == 0`). `pyproject.toml` dependencies unchanged (16 GB RAM CPU footprint untouched). |

### Post-Design Re-Evaluation (After Phase 1 Contracts & Data Model)

- **Public API Contract Reconciliation (`Quality Gates`)**: Constitution `v1.2.1` syncs the public API contract enumeration with the Stage 1 extension surface (`RegistryError` and the eight lazy `register_*` decorators) while preserving Release Gate #2 reservation (`v1.3.0`), and `Footprint` mandates additive format/store extensibility without modifying core modules. Stage 1 preserves all 24 shipped top-level exports with exact baseline parameters, and cleanly adds `RegistryError` (as a `DocpipeError` subclass per Q2) + the 8 lazy `register_*` entry points (`__all__` expands `24 -> 33`), plus optional keyword-only stage selector parameters defaulting to `"default"` (per Q1). **Status: PASS — zero breaking changes or unjustified complexity.**
- **Python 3.10 + Strict Mypy Design Verification**: Resolved structural subtyping mismatches found between draft notes and shipped `store.py` / `embedder.py` (`Store.get_all_children -> list[EmbeddedChunk]`, `Store.delete_stale_versions(source, active_doc_version)`, `Store.sweep_uncommitted(...) -> int`, `Embedder.embed_query(text, ...)`, Python 3.10 two-step `IngestContext` `TypedDict`) in [contracts/stage-protocols.md](contracts/stage-protocols.md) and [data-model.md](data-model.md). **Status: PASS.**

## Project Structure

### Documentation (this feature)

```text
specs/004-registry-refactor/
├── spec.md                       # Feature specification (with Q1 & Q2 clarifications)
├── checklists/
│   └── requirements.md           # Specification quality checklist (16/16 passing)
├── plan.md                       # This implementation plan
├── research.md                   # Phase 0 design decisions & trade-offs
├── data-model.md                 # Registry, stage states, Intake dataclasses, IngestContext
├── quickstart.md                 # End-to-end validation & release gate guide
└── contracts/
    ├── registry-api.md           # Generic Registry[T], RegistryError, 8 stage instances
    ├── stage-protocols.md        # Phase 1 & Phase 2 @runtime_checkable Protocols + _resolve
    └── public-api.md             # 33 top-level exports, callable signatures, re-exports
```

### Source Code (repository root)

> **Module-to-Package Replacement Rule**: When converting flat modules (`store.py`, `embedder.py`, `ingest/intake.py`, `ingest/clean.py`, `ingest/chunker.py`) into stage subpackages (`store/`, `embedder/`, `ingest/intake/`, `ingest/clean/`, `ingest/chunker/`), each replaced `.py` file MUST be removed (`git rm`) so Python never experiences module-vs-package import shadowing.

```text
src/docpipe_maestro/
├── __init__.py                   # Preserves 24 baseline exports + lazy RegistryError & 8 register_* + _DocpipeModule
├── __main__.py                   # Unchanged CLI entry point
├── _registry.py                  # NEW: generic Registry[T] with lazy built-ins & duplicate-deferred guard
├── _resolve.py                   # NEW: resolve_parser(path, preferred=None) using custom-before-builtin extension match + detect_format
├── _stages.py                    # NEW: phase-neutral shared @runtime_checkable Protocols (Embedder, Store)
├── cli.py                        # Unchanged CLI parser & config/dotenv exclusivity (zero chromadb/litellm on init)
├── config.py                     # Unchanged static constants & ChunkingProfile defaults
├── manifest.py                   # Unchanged atomic manifest persistence, hashing & model locking
├── types.py                      # +RegistryError(DocpipeError), +IngestContext, +relocated ParsedClause/Section/Document
├── embedder/                     # REPLACES embedder.py (lazy __getattr__ re-exports for compatibility & zero eager litellm)
│   ├── __init__.py               # EMBEDDERS registry, lazy "default" declaration, DEFAULT_REQUEST_TIMEOUT, lazy helpers
│   └── default.py                # LiteLLMEmbedder (@EMBEDDERS.register("default")), embed_texts/embed_query & security utils
├── store/                        # REPLACES store.py (lazy __getattr__ for VectorStore/ChromaStore so chromadb stays lazy)
│   ├── __init__.py               # STORES registry, lazy "default" declaration, lazy VectorStore/ChromaStore aliases
│   └── chroma.py                 # ChromaStore (@STORES.register("default")) + VectorStore alias, sweep_uncommitted -> int
├── ingest/
│   ├── __init__.py
│   ├── stages.py                 # NEW: Phase 1 @runtime_checkable Protocols (Parser, Cleaner, Enricher, Chunker; re-exports Embedder, Store from _stages)
│   ├── intake/                   # REPLACES ingest/intake.py
│   │   ├── __init__.py           # PARSERS registry, 5 lazy built-ins, re-exports Parsed* types, detect_format, parse_file
│   │   ├── _common.py            # detect_format(), _validate_docx_zip(), SUPPORTED_EXTENSIONS, _sections_from_lines*
│   │   ├── markdown.py           # MarkdownParser (@PARSERS.register("md"))
│   │   ├── text.py               # TextParser (@PARSERS.register("txt"))
│   │   ├── html.py               # HtmlParser (@PARSERS.register("html")) with hidden-content/deep-nesting guards
│   │   ├── pdf.py                # PdfParser (@PARSERS.register("pdf"))
│   │   └── docx.py               # DocxParser (@PARSERS.register("docx")) with ZIP-bomb guard
│   ├── clean/                    # REPLACES ingest/clean.py
│   │   ├── __init__.py           # CLEANERS registry, lazy "default", re-exports clean_text & clean_document
│   │   └── default.py            # DefaultCleaner (@CLEANERS.register("default")), O(n) _TAG_START_RE cleaner & boilerplate
│   ├── enricher/                 # NEW: contract-only empty registry for Stage 3/4
│   │   └── __init__.py           # ENRICHERS registry + register_enricher (empty in Stage 1)
│   ├── chunker/                  # REPLACES ingest/chunker.py
│   │   ├── __init__.py           # CHUNKERS registry, lazy "default", re-exports chunk_document & estimate_tokens
│   │   └── default.py            # DefaultChunker (@CHUNKERS.register("default")), chunk_document, estimate_tokens
│   ├── crossrefs.py              # Compatibility preserved untouched until Stage 3 (imports Parsed* via types/intake)
│   └── pipeline.py               # Updated orchestrator resolving stages via registries + optional keyword-only selectors
└── query/
    ├── __init__.py
    ├── stages.py                 # NEW: Phase 2 @runtime_checkable Protocols (Searcher, Reranker)
    ├── searcher/                 # NEW: contract-only empty registry for Stage 6
    │   └── __init__.py           # SEARCHERS registry + register_searcher (empty in Stage 1)
    ├── reranker/                 # NEW: contract-only empty registry for Stage 5
    │   └── __init__.py           # RERANKERS registry + register_reranker (empty in Stage 1)
    ├── retriever.py              # Updated Phase 2 orchestrator resolving EMBEDDERS/STORES cleanly via shared _stages.Store protocol
    ├── prompts.py                # Unchanged
    └── answer.py                 # Updated internal import only if needed via embedder compatibility re-exports

tests/
├── conftest.py                   # Unchanged deterministic offline doubles
├── fixtures/
│   ├── docs/                     # Unchanged intake fixtures
│   ├── policy_corpus/            # Unchanged policy fixtures
│   └── golden_query_stage1.json  # NEW: pre-refactor captured deterministic retrieval snapshot
├── test_*.py                     # All 12 existing Stage 0 test files preserved unmodified (imports & assertions intact)
├── test_registry.py              # NEW: registry contracts, deferred duplicate guard, 8 stage registries, E2E custom stage
├── test_api_stability.py         # NEW: 33 exports & exact inspect.signature parameter stability verification
├── test_library_purity.py        # NEW: AST config/dotenv import & call scanner (non-CLI modules) + register_* laziness
├── test_golden_refactor.py       # NEW: bit-for-bit offline retrieval equivalence against golden_query_stage1.json
└── test_invariants_stage1.py     # NEW: explicit §1.3 regression guards (sweep_uncommitted crash recovery, empty embed_dim)
```

**Structure Decision**: Single library/CLI package rooted under `src/docpipe_maestro` with subpackage-per-stage isolation cleanly reflecting Phase 1 (`ingest/`), shared (`_registry.py`, `_resolve.py`, `types.py`, `embedder/`, `store/`), and Phase 2 (`query/`). All existing module import paths remain intact via package `__init__.py` re-exports so zero Stage 0 tests or downstream callers break.

## Complexity Tracking

No Constitution violations or exceptions required. The `Registry[T]` + `Protocol` structure introduces strictly minimal core infrastructure directly mandated by Constitution `v1.2.1` (`Footprint`: *"A new file format or storage backend must be additive — no existing module should need modification beyond registration"*).
