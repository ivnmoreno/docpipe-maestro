# Implementation Plan: Thread-Safe Persistent Vector Store Lifecycle

**Branch**: `fix/015-store-lifecycle-thread-safety` | **Date**: 2026-11-19 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `specs/015-thread-safe-store-lifecycle/spec.md`

## Summary

Synchronize `ChromaStore` lifecycle transitions (`__init__`, `close`, and `reset_collection`) in `src/docpipe_maestro/store/chroma.py` using a single module-level reentrant lock `_CHROMA_CLIENT_LOCK = threading.RLock()` to eliminate the cold-start `chromadb.PersistentClient` / `SharedSystemClient` multithreaded initialization and teardown race. Move `chromadb.PersistentClient(...)` inside the `__init__` `try:` rollback envelope so both client creation and collection validation failures surface uniformly as `DocpipeError` with safe, reentrant rollback (`_client` guarded against `None` and secondary close errors suppressed). Keep steady-state queries, reads, and writes unserialized, leave retrieval/searcher store reuse untouched (no per-query `.close()`), preserve `Store` plugin compatibility and lazy startup, and verify with fresh-subprocess cold-start concurrency, lifecycle, and fault-injection tests.

## Technical Context

**Language/Version**: Python `>=3.10` (`3.10`–`3.13` in CI; `mypy --strict`)  
**Primary Dependencies**: Core standard library (`threading`, `contextlib`) coordinating existing `chromadb>=1.5.9` (`PersistentClient`, `SharedSystemClient`)  
**Storage**: Embedded local `chromadb.PersistentClient` SQLite + HNSW store (`src/docpipe_maestro/store/chroma.py`); zero schema, manifest, or HNSW config changes  
**Testing**: `pytest` + `pytest-cov` (`fail_under = 80`), `ruff` (format/check/`S`), `mypy --strict`, `@pytest.mark.reverse`, `@pytest.mark.pii`, `minimal-core` CI subset  
**Target Platform**: Cross-platform (`linux`, `macos`, `windows`) offline local execution within `< 16 GiB` RAM  
**Project Type**: Minimal two-phase Python library (`docpipe_maestro`) + CLI (`docpipe-maestro`)  
**Performance Goals**: Zero serialization wait across concurrent steady-state reads, queries, lookups, or writes once open; zero per-query store teardown/restart latency in `retrieve()`, `DenseSearcher`, or `HybridSearcher`  
**Constraints**: Root `docpipe_maestro.__all__` fixed at `36` exports; lazy `chromadb` import at root/CLI startup preserved; custom `Store` plugins never required to implement `.close()`; post-close method error guards excluded out of scope (`FR-007`); zero new dependencies  
**Scale/Scope**: 1 source module modified (`src/docpipe_maestro/store/chroma.py`) and 2 existing test suites extended (`tests/test_store.py`, `tests/test_retriever.py`)

## Constitution Check

*GATE: Evaluated both pre-research and post-design (`research.md`, `data-model.md`, `contracts/store-lifecycle.md`).*

| Principle | Pre-Design Status | Post-Design Status | Verification |
|---|---|---|---|
| **I. Scope Discipline (`v1.4.0`)** | Pass | Pass | Minimal surgical fix scoped strictly to `ChromaStore` lifecycle methods; no server/UI/async changes; post-close method guards explicitly out of scope per `FR-007`. |
| **II. Two-Phase Architecture** | Pass | Pass | Shared store module serves Phase 1 (ingest/reindex) and Phase 2 (read-only retrieve/search) cleanly without altering phase boundaries or injecting Phase 2 teardown. |
| **III. Library Purity** | Pass | Pass | Zero config/dotenv file reads; zero hardcoded provider registries; lazy import of `docpipe_maestro.store.chroma` untouched (`test_library_purity.py` passes). |
| **IV. Search Small, Return Big** | Pass | Pass | Child similarity search, `parent_id` linkage, and parent expansion/deduplication unchanged; non-serialized concurrent reads preserve Phase 2 behavior. |
| **V. Exception Preservation & Safety Gates** | Pass | Pass | Uniform `DocpipeError` wrapping across client startup and collection validation with suppressed secondary teardown noise; `@pytest.mark.reverse` and `@pytest.mark.pii` preserved and run as final gates. |
| **VI. Provider Agnosticism & Local-First Default** | Pass | Pass | All cold-start concurrency, lifecycle, and fault-injection tests run 100% offline with local deterministic embeddings/doubles. |
| **VII. Structured Correctness Over Speed** | Pass | Pass | Cold-start shared client races eliminated safely via reentrant mutex instead of unsafe retries or silent fallback; no `types.py` schema changes. |
| **Quality Gates & Footprint** | Pass | Pass | Compatible with `minimal-core` (`chromadb` is core); root `36` exports unchanged; `Store` protocol without `.close()` preserved; CI `ruff`, `mypy --strict`, and `--cov >= 80` satisfied. |

## Project Structure

### Documentation (this feature)

```text
specs/015-thread-safe-store-lifecycle/
├── spec.md                              # Feature specification + Session 2026-11-19 clarifications
├── checklists/
│   └── requirements.md                  # Spec quality validation checklist (16/16 pass)
├── plan.md                              # This file (/speckit-plan output)
├── research.md                          # Phase 0 root-cause analysis & alternatives evaluated
├── data-model.md                        # Phase 1 handle/registry entities & lifecycle state machine
├── contracts/
│   └── store-lifecycle.md               # Phase 1 lifecycle, error, non-serialization & plugin contracts
├── quickstart.md                        # Phase 1 offline validation scenarios & release gate commands
└── tasks.md                             # Phase 2 output (/speckit-tasks command - not created here)
```

### Source Code (repository root)

```text
src/docpipe_maestro/store/
└── chroma.py                            # Add _CHROMA_CLIENT_LOCK = threading.RLock(); guard __init__,
                                         # close(), reset_collection(); wrap PersistentClient() in try
                                         # with safe _safe_rollback_close() helper; leave reads/writes unlocked

tests/
├── test_store.py                        # Add concurrent open/close/reset, fault-injected client & collection
│                                        # rollback (incl. secondary close error), and unblocked read tests
├── test_retriever.py                    # Add fresh-subprocess barrier-synchronized cold-start retrieve() test
├── test_api_stability.py                # Existing 36-export & signature contract verification (unchanged)
└── test_library_purity.py               # Existing lazy-import startup purity verification (unchanged)
```

**Structure Decision**: Confine production edits strictly to `src/docpipe_maestro/store/chroma.py` so every caller (`retrieve`, `DenseSearcher`, `HybridSearcher`, `ingest`, `sync`, `remove`, `reindex`, `report`, and direct `VectorStore`/`ChromaStore` users) inherits thread-safe store lifecycle coordination automatically without modifying callers, plugins, or `_stages.py`. Place automated regression checks directly inside existing core test suites (`tests/test_store.py` and `tests/test_retriever.py`), which run in both full Python `3.10`–`3.13` CI and the `minimal-core` CI job.

## Complexity Tracking

> Zero Constitution violations; no extra abstractions or justifications required.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| *None* | — | — |
