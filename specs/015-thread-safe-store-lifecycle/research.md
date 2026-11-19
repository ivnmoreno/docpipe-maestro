# Research: Thread-Safe Persistent Vector Store Lifecycle

**Feature Branch**: `fix/015-store-lifecycle-thread-safety`  
**Spec**: [spec.md](./spec.md) | **Date**: 2026-11-19

---

## 1. Root Cause Analysis in `chromadb==1.5.9` + `ChromaStore`

### Decision
Synchronize all `ChromaStore` lifecycle transitions (`__init__`, `close`, and `reset_collection`) in `src/docpipe_maestro/store/chroma.py` using a single module-level reentrant lock `_CHROMA_CLIENT_LOCK = threading.RLock()`. Do **not** acquire `_CHROMA_CLIENT_LOCK` in steady-state reads, queries, or writes, and do **not** add per-query `close()` teardown in retrieval or searcher modules.

### Observed Mechanism (Directly Verified in Repository & Core `chromadb==1.5.9`)
1. In `chromadb.api.shared_system_client.SharedSystemClient._create_system_if_not_exists(identifier, settings)`:
   - Inserts `cls._identifier_to_system[identifier] = new_system` **before** constructing `ServerAPI` components and **before** calling `new_system.start()`, with no mutual-exclusion guard around `_identifier_to_system`.
   - Meanwhile, `SharedSystemClient._release_system(identifier)` pops `_identifier_to_system.pop(identifier, None)` and stops `system` whenever `_decrement_refcount(identifier) <= 0`.
2. In `chromadb.api.client.Client.__init__`:
   - Calls `super().__init__()` (entering `_create_system_if_not_exists` + incrementing refcount), binds `self._server`, acquires `AdminClient.from_system(self._system)`, and calls `self._validate_tenant_database()`.
   - When Thread A and Thread B enter `chromadb.PersistentClient(path=str(self._persist_dir))` simultaneously on a fresh process:
     - Thread A inserts `_identifier_to_system[identifier]` before finishing `new_system.start()` (`RustBindingsAPI.bindings` does not yet exist).
     - Thread B sees `identifier` already in `_identifier_to_system`, skips creation, enters `_validate_tenant_database()`, and fails with `AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'` (wrapped into `ValueError` or propagating in `Client.__init__`).
     - If Thread B fails inside `Client.__init__` or `ChromaStore._get_or_create_collection()`, cleanup runs `_release_system`, decrementing refcount `<= 0` and popping `_identifier_to_system[identifier]` out from under Thread A, causing Thread A to crash with `KeyError` on the store identifier (`'.docpipe'`).
3. Inside `src/docpipe_maestro/store/chroma.py`:
   - `ChromaStore.__init__` calls `chromadb.PersistentClient(...)` at line 84 **outside** the `try:` rollback block (`lines 85–91`), leaving `self._client` unset on `PersistentClient` startup failure and letting raw backend exceptions escape without `DocpipeError`.
   - Neither `ChromaStore.__init__`, `ChromaStore.close()`, nor `ChromaStore.reset_collection()` currently holds any synchronization lock across concurrent instances targeting the process-wide `SharedSystemClient` registry.

### Alternatives Evaluated & Rejected
| Alternative | Why Rejected |
|---|---|
| Add per-query `store_obj.close()` in `retrieve()`, `dense.py`, and `hybrid.py` | Violates `FR-005`/`FR-006`/`SC-003`: tears down and restarts SQLite/HNSW/Foyer on every child search and parent lookup, creates handle/cache-eviction churn on low-file-handle platforms (Windows 512 stdio / macOS), breaks concurrent reuse while sibling threads hold clients, and breaks custom `Store` plugins without `.close()`. |
| Lock steady-state reads, queries, and writes (`query_children`, `get_by_ids`, `add_chunks`) | Violates `FR-004`/`SC-003`: serializes concurrent online retrieval queries behind client open/close/reset work with zero safety benefit once `PersistentClient` and `Collection` initialization are complete. |
| Instance-level `self._lock = threading.RLock()` | Fails to serialize two distinct threads constructing independent `ChromaStore(persist_dir, collection)` instances or calling `close()` concurrently on sibling instances sharing global `SharedSystemClient._identifier_to_system`. |
| Non-reentrant `threading.Lock()` | Self-deadlocks (`FR-002`) when `ChromaStore.__init__` holds `_CHROMA_CLIENT_LOCK`, catches a collection error, and calls `self.close()` on the same thread during rollback. |
| Per-`persist_dir` striped lock dictionary | Unnecessary complexity and stale-entry leak risk across normalized/symlinked paths; `SharedSystemClient._identifier_to_system` is a single class-global dict mutated across all store directories anyway, and lifecycle transitions occur infrequently enough that one module-level `RLock` cleanly protects all directories (`US1.3`). |
| Process-wide `asyncio` / `multiprocessing` file locks | Out of scope per `spec.md` Assumptions (`multi-threaded callers share a single worker process per host invocation`) and Constitution Principle I (`Scope Discipline`). |

---

## 2. Partial-Initialization Error Boundary & Safe Rollback (`FR-003`)

### Decision
1. Initialize `self._closed = False` and `self._client: Any = None` before acquiring `_CHROMA_CLIENT_LOCK`.
2. Wrap both `self._client = chromadb.PersistentClient(path=str(self._persist_dir))` and `self._collection = self._get_or_create_collection()` inside a single `try:` block inside `with _CHROMA_CLIENT_LOCK:`.
3. On failure inside `try:`:
   - Re-raise `DocpipeError` directly after defensive cleanup if a `DocpipeError` was raised directly.
   - Wrap any non-`DocpipeError` exception cleanly into `DocpipeError(f"Invalid or unusable collection {self._collection_name!r}: {exc}") from exc` (matching existing assertion regex `"Invalid or unusable collection"` in `tests/test_store.py:251`, `tests/test_security_hardening.py:110`, and `tests/test_cli.py:141`).
   - Run rollback cleanup safely: when `self._client is None`, set `self._closed = True` directly without invoking `self.close()`; when `self._client is not None`, call `self.close()` inside `contextlib.suppress(Exception)` so secondary close failures never mask the primary `DocpipeError`.

### Rationale
- Moving `chromadb.PersistentClient(...)` inside `with _CHROMA_CLIENT_LOCK:` prevents sibling threads from seeing an unstarted `System` or racing on `SharedSystemClient._identifier_to_system` while `Client.__init__` creates and starts `RustBindingsAPI`.
- Wrapping `PersistentClient(...)` in the same `try:` block satisfies Clarified `FR-003` (`Session 2026-11-19 Q1`): client startup failures and collection validation failures share one uniform `DocpipeError` contract without leaking raw backend/OS exceptions.
- Using `contextlib.suppress(Exception)` inside rollback ensures a secondary failure during `client.close()` never replaces or masks the primary initialization `DocpipeError` (`__cause__`), and keeps Ruff security rule `S110` (`try-except-pass`) clean.

### Edge Case Verified
- If `validate_collection_name(collection_name)` fails first, `DocpipeError` raises before acquiring `_CHROMA_CLIENT_LOCK` or creating any directory/client (`tests/test_security_hardening.py`).
- If `ensure_private_dir(self._persist_dir)` runs before lock acquisition and fails (`OSError`), keeping it outside Chroma client locking preserves exact baseline filesystem permission error behavior (`mkdir(parents=True, exist_ok=True)` is already concurrent-safe across threads).

---

## 3. Caller Reuse, Plugin Compatibility & Post-Close Scope (`FR-005`, `FR-006`, `FR-007`)

### Decision
1. Leave all retrieval, search, ingestion, maintenance, and reporting callers (`src/docpipe_maestro/query/retriever.py`, `src/docpipe_maestro/query/searcher/dense.py`, `src/docpipe_maestro/query/searcher/hybrid.py`, `src/docpipe_maestro/ingest/pipeline.py`, `src/docpipe_maestro/report.py`) completely **unmodified**: they already resolve `store_cls = STORES.resolve(store)` and instantiate `store_cls(persist_path, collection)` without invoking `.close()`.
2. Keep `Store` Protocol in `src/docpipe_maestro/_stages.py` untouched (no `.close()` requirement on custom `Store` plugins).
3. In `ChromaStore.close()`, keep idempotency (`if self._closed: return` -> `self._closed = True` -> close `self._client` if present) under `_CHROMA_CLIENT_LOCK`, preserving Chroma's `SharedSystemClient` reference counting so closing one handle never stops a shared system still held by another concurrent `ChromaStore` instance.
4. Keep `reset_collection()` protected under `_CHROMA_CLIENT_LOCK` so `delete_collection` + `_get_or_create_collection` cannot interleave with concurrent `close()` or `__init__()`.
5. Keep closed-handle guards on post-close `query_children`, `add_chunks`, `reset_collection`, `__enter__`, etc. **out of scope** per Clarified `FR-007` (`Session 2026-11-19 Q2`).

---

## 4. Lazy Import Startup & Test Strategy (`FR-008`, `FR-009`, `FR-010`)

### Decision
1. `import threading` and `import contextlib` in `src/docpipe_maestro/store/chroma.py` run **only** when `docpipe_maestro.store.chroma` is lazily imported via `STORES.resolve("default")` or `docpipe_maestro.store.__getattr__`. Top-level `import docpipe_maestro` and CLI `build_parser()` still import zero `chromadb` modules (`tests/test_library_purity.py:181` stays green).
2. Add comprehensive offline deterministic tests in `tests/test_store.py` and `tests/test_retriever.py` (both run in both full `quality` matrix `3.10–3.13` AND `minimal-core` CI):
   - **Fresh-subprocess cold-start concurrency test** (`tests/test_retriever.py`): pre-populate a collection offline, then spawn isolated `subprocess.run([sys.executable, "-c", ...])` workers across repeated cold runs; inside each child process, patch `litellm.embedding` offline cleanly, assert `"chromadb" not in sys.modules` right before releasing `threading.Barrier(4)`, run `retrieve()` concurrently on 4 threads (`top_k=1`, `local_only=True`), and assert 100% pass rate (`0` errors, deterministic parent results).
   - **In-process concurrent store lifecycle test** (`tests/test_store.py`): barrier-synchronized concurrent `VectorStore(tmp_persist_dir, col)` initialization (same collection + multiple collections + multiple persist dirs), interleaved `close()` / context manager + reopen, and concurrent `reset_collection()` + open/close cycles checking `_active_systems_for(tmp_persist_dir)`.
   - **Fault-injection rollback tests** (`tests/test_store.py`):
     - Patch `chromadb.PersistentClient` to raise `RuntimeError`: assert `DocpipeError("Invalid or unusable collection ...")` is raised with `__cause__`, `self.close` client teardown is skipped (`_client is None`), and `_active_systems_for` stays empty.
     - Patch `chromadb.api.client.Client.get_or_create_collection` to raise `RuntimeError` while sibling open/close runs concurrently (and test secondary close error inside `_client.close()`): assert primary `DocpipeError` surfaces unmasked and shared system state stays uncorrupted.
   - **Steady-state non-serialization check** (`tests/test_store.py`): prove that a slow in-progress `ChromaStore.__init__` / `_CHROMA_CLIENT_LOCK` acquisition on one store or holding a collection query open across two barrier-synchronized threads does **not** serialize concurrent `query_children()` reads on an already-open store instance (zero `_CHROMA_CLIENT_LOCK` entry during reads/writes).
