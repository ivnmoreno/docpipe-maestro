# Data Model & State Transitions: Thread-Safe Persistent Vector Store Lifecycle

**Feature Branch**: `fix/015-store-lifecycle-thread-safety`  
**Spec**: [spec.md](./spec.md) | **Date**: 2026-11-19

---

## 1. Entities

### 1.1 `ChromaStore` (`Persistent Store Handle`)
- **Location**: `src/docpipe_maestro/store/chroma.py` (exported lazily as `ChromaStore` and `VectorStore`)
- **Fields**:
  - `name: str = "default"` (stage registry identifier)
  - `_persist_dir: Path` (local directory holding Chroma persistent storage and SQLite files)
  - `_collection_name: str` (validated collection name via `validate_collection_name`)
  - `_closed: bool` (idempotent handle-local closure flag; initialized `False`)
  - `_client: Any` (`chromadb.PersistentClient` instance once acquired; initialized `None` prior to client creation)
  - `_collection: chromadb.Collection` (active Chroma collection configured with `_COLLECTION_METADATA` HNSW settings)
- **Relationships**:
  - Multiple live `ChromaStore` handles pointing to the same `_persist_dir` share one process-wide `chromadb.api.shared_system_client.SharedSystemClient` `System` entry keyed by persistent path string.
  - Each `ChromaStore` owns one logical client handle (`_client`) contributing to Chroma's internal reference count (`_identifier_to_refcount`).

### 1.2 `_CHROMA_CLIENT_LOCK` (`Lifecycle Transition Guard`)
- **Location**: Module-level `threading.RLock()` in `src/docpipe_maestro/store/chroma.py`
- **Scope**:
  - Protects **only** lifecycle transitions:
    1. `ChromaStore.__init__` (backend client creation + collection acquisition/validation + error rollback)
    2. `ChromaStore.close` (idempotent `_closed` transition + `client.close()` release)
    3. `ChromaStore.reset_collection` (`delete_collection` + `_get_or_create_collection`)
  - **Excluded (lock-free at `ChromaStore` layer)**: `add_chunks`, `query_children`, `get_by_ids`, `get_parents_by_source`, `delete_by_source`, `delete_stale_versions`, `sweep_uncommitted`, `get_all_children`, `get_all_parents`, `__enter__`.
- **Reentrancy Rule (`FR-002`)**: `RLock` allows `__init__` rollback to call `self.close()` on the owning thread without deadlocking while blocking all other threads from mutating `SharedSystemClient` mid-initialization or mid-teardown.

### 1.3 `SharedSystemClient` Shared Process State (External Dependency Invariant)
- **State Managed by `chromadb`**:
  - `_identifier_to_system: dict[str, System]`
  - `_identifier_to_refcount: dict[str, int]`
- **Maintained Invariant**: Under `_CHROMA_CLIENT_LOCK`, no observer thread can ever witness `_identifier_to_system[id]` before `new_system.start()` has completed, nor observe a half-stopped/popped entry while acquiring or validating a collection.

---

## 2. Handle Lifecycle State Machine

```text
  [Uncreated]
       │  __init__() enters _CHROMA_CLIENT_LOCK
       ▼
  [Initializing] ──(validate_collection_name fails before lock)──▶ [Aborted: DocpipeError] (no client/lock acquired)
       │
       ├── PersistentClient() raises exc
       │      └─ _client is None → skip client.close(), set _closed = True → [Failed: DocpipeError(cause=exc)]
       │
       ├── PersistentClient() succeeds (_client bound), _get_or_create_collection() raises exc
       │      └─ _safe_rollback_close() calls self.close() (suppresses secondary close errors), _closed = True
       │         → [Failed: DocpipeError(cause=exc)] (refcount/system cleaned)
       │
       ▼ (collection bound; exits _CHROMA_CLIENT_LOCK)
  [Open / Active] ◀──────────────────────────────────────────┐
       │                                                     │
       ├── Steady-state reads/queries/writes (NO _CHROMA_CLIENT_LOCK)
       │
       ├── reset_collection() [acquires _CHROMA_CLIENT_LOCK] ┘
       │
       └── close() / __exit__() [acquires _CHROMA_CLIENT_LOCK]
              ├─ if _closed: no-op (idempotent)
              └─ set _closed = True → if _client is not None: _client.close()
                 (SharedSystemClient pops system only when last sibling handle closes)
                 ▼
              [Closed]
```

## 3. Validation & Scope Invariants

1. **No schema or manifest change**: Ingestion manifests, `ChunkMetadata`, `_COLLECTION_METADATA`, and SQLite FTS5 tables remain 100% unchanged.
2. **No `Store` protocol change**: `src/docpipe_maestro/_stages.py` (`Store`) remains unchanged; custom store plugins are not required to implement `.close()`.
3. **Post-close method boundary (`FR-007`)**: Post-close behavior of non-`close` methods (`reset_collection`, `query_children`, `add_chunks`, `__enter__`) is explicitly preserved unchanged; idempotency applies strictly to repeated `.close()` / `__exit__()` calls.
