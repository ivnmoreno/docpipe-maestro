# Contract: Persistent Store Lifecycle Concurrency (`015-thread-safe-store-lifecycle`)

**Feature Branch**: `fix/015-store-lifecycle-thread-safety`  
**Date**: 2026-11-19

---

## 1. `ChromaStore` / `VectorStore` Lifecycle Contract (`src/docpipe_maestro/store/chroma.py`)

### 1.1 Concurrent Initialization (`__init__`)
- Calling `ChromaStore(persist_dir, collection_name)` (or `STORES.resolve("default")(persist_dir, collection_name)`) from `N >= 4` threads concurrently on a fresh cold process targeting the same `persist_dir` and `collection_name` **MUST** serialize backend client startup and collection acquisition so every caller receives an initialized, usable store handle with **0** initialization or missing-identifier errors.
- Concurrent initialization across distinct `persist_dir` paths or distinct `collection_name` values **MUST** complete without deadlock or cross-directory state corruption.

### 1.2 Error Surfacing & Partial-Init Rollback (`FR-003`)
- Input validation errors from `validate_collection_name(collection_name)` raise `DocpipeError("Invalid or unusable collection ...")` directly.
- Any failure during backend client creation (`chromadb.PersistentClient(...)`) or collection acquisition/validation (`get_or_create_collection(...)`) **MUST**:
  - Be wrapped in `DocpipeError(f"Invalid or unusable collection {collection_name!r}: {exc}") from exc` (or re-raised directly if already `DocpipeError`), preserving `__cause__`.
  - Skip calling backend client teardown when no client object was acquired (`_client is None`).
  - Release any acquired client handle under lifecycle synchronization when a client handle existed prior to failure, suppressing secondary teardown exceptions so the primary `DocpipeError` is never masked.
  - Leave shared backend client registry state uncorrupted (`SharedSystemClient` retains zero orphaned broken entries from the failed call).

### 1.3 Concurrent Teardown & Reset (`close`, `__exit__`, `reset_collection`)
- `close()` (and `__exit__`) **MUST** acquire the lifecycle lock, enforce idempotent `_closed` transition once across concurrent callers on the same instance, and preserve `SharedSystemClient` reference counting so a shared system stops only when the final holder closes.
- `reset_collection()` **MUST** execute `delete_collection` + `_get_or_create_collection` atomically under the lifecycle lock with respect to sibling initializers, resets, and closes.
- Post-close calls to non-`close` methods keep existing behavior untouched (out of scope per `FR-007`).

---

## 2. Preserved Pipeline, Plugin, Export & Latency Contracts

| Contract Surface | Requirement | Enforcement |
|---|---|---|
| **Steady-State Reads/Writes** (`FR-004`, `SC-003`) | `query_children`, `get_by_ids`, `get_parents_by_source`, `get_all_children`, `get_all_parents`, `add_chunks`, `delete_*`, `sweep_uncommitted` NEVER acquire the store lifecycle lock | Structural code contract + concurrent open-store query test |
| **Retrieval & Searchers** (`FR-005`) | `retrieve()`, `DenseSearcher`, and `HybridSearcher` keep existing store reuse lifetimes; zero per-query `store_obj.close()` calls injected | Caller paths untouched + `SC-003` verification |
| **`Store` Stage Plugins** (`FR-006`) | `docpipe_maestro._stages.Store` protocol does NOT require `.close()` | Verified by custom plugin compatibility & `mypy --strict` |
| **Public API Surface** (`FR-008`) | `docpipe_maestro.__all__` remains fixed at `36` exports with zero signature changes | Verified by `tests/test_api_stability.py` |
| **Lazy Startup Purity** (`FR-008`) | `import docpipe_maestro` and CLI parser build never eagerly import `chromadb` | Verified by `tests/test_library_purity.py` |
| **Minimal Core** (`FR-010`) | All cold-start concurrency, lifecycle, and rollback checks pass offline with zero optional extras installed | Verified by `minimal-core` CI pytest subset |
