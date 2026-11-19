---

description: "Task list for thread-safe persistent vector store lifecycle implementation"
---

# Tasks: Thread-Safe Persistent Vector Store Lifecycle

**Input**: Design documents from `/specs/015-thread-safe-store-lifecycle/`  
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/store-lifecycle.md](./contracts/store-lifecycle.md), [quickstart.md](./quickstart.md)

**Tests**: Explicit test tasks are included in TDD order because `spec.md` (`FR-009`, `FR-010`, `SC-001`–`SC-005`) mandates fresh-subprocess cold-start concurrency, in-process lifecycle/rollback, and steady-state non-serialization verification.

**Organization**: Tasks are grouped by user story (`US1` → `US2` → `US3`) to enable independent verification of each increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`US1`, `US2`, `US3`)
- Exact repository file paths are included in every task description.

---

## Phase 1: Setup (Baseline Verification)

**Purpose**: Confirm clean working branch environment and record baseline store/retriever test health before edits.

- [X] T001 Verify active branch `fix/015-store-lifecycle-thread-safety` and run baseline store and retriever tests via `uv run --no-sync pytest tests/test_store.py tests/test_retriever.py -v` in `tests/test_store.py` and `tests/test_retriever.py`
- [X] T002 [P] Audit caller sites `retrieve()`, `DenseSearcher`, `HybridSearcher`, and `ingest`/`sync`/`remove`/`reindex` in `src/docpipe_maestro/query/retriever.py`, `src/docpipe_maestro/query/searcher/dense.py`, `src/docpipe_maestro/query/searcher/hybrid.py`, and `src/docpipe_maestro/ingest/pipeline.py` to confirm zero pre-existing `.close()` auto-teardown calls and preserve caller invariance (`FR-005`)

---

## Phase 2: Foundational (Shared Lifecycle Guard Scaffold)

**Purpose**: Establish the shared reentrant module lock and initial handle attribute invariants required by all user stories.

**⚠️ CRITICAL**: Complete before User Story implementation edits begin.

- [X] T003 Add `import contextlib` and `import threading`, declare module-level `_CHROMA_CLIENT_LOCK = threading.RLock()` (`Lifecycle Transition Guard`), and initialize `self._closed = False` and `self._client: Any = None` ahead of client acquisition in `src/docpipe_maestro/store/chroma.py`

**Checkpoint**: Lifecycle guard symbol and safe default handle attributes exist in `src/docpipe_maestro/store/chroma.py`; story-level TDD tests and behavior changes can now proceed.

---

## Phase 3: User Story 1 - Cold-Start Concurrent Retrieval Without Initialization Races (Priority: P1) 🎯 MVP

**Goal**: Ensure concurrent callers (`N >= 4` threads) invoking `retrieve()` or opening `ChromaStore` in a freshly started cold process against the same or distinct `persist_dir` directories initialize cleanly with zero race failures (`FR-001`, `FR-009`, `SC-001`).

**Independent Test**: Run fresh-subprocess barrier-synchronized `retrieve()` concurrency test (`4` workers, offline mocked embeddings, `"chromadb" not in sys.modules` before barrier) across repeated runs and in-process barrier-synchronized concurrent `VectorStore(...)` initialization tests (`tests/test_retriever.py`, `tests/test_store.py`).

### Tests for User Story 1

> **NOTE: Write US1 tests FIRST and verify cold-start / race coverage before finishing implementation.**

- [X] T004 [P] [US1] Write fresh-subprocess barrier-synchronized (`threading.Barrier(4)`) cold-start concurrent `retrieve()` test (self-contained inline deterministic `litellm.embedding` stub matching `EMBED_DIM = 64` from the ingested fixture without relying on pytest `sys.path`, asserting `"chromadb" not in sys.modules` immediately before releasing the barrier, targeting shared `persist_dir` and collection across repeated cold subprocess runs) in `tests/test_retriever.py`
- [X] T005 [P] [US1] Write in-process barrier-synchronized concurrent `VectorStore(persist_dir, collection)` initialization tests covering concurrent threads against (a) identical `persist_dir` + `collection` and (b) distinct `persist_dir` directories in `tests/test_store.py`

### Implementation for User Story 1

- [X] T006 [US1] Guard `chromadb.PersistentClient(path=str(self._persist_dir))` and `self._get_or_create_collection()` inside `with _CHROMA_CLIENT_LOCK:` in `ChromaStore.__init__` in `src/docpipe_maestro/store/chroma.py`

**Checkpoint**: Run `uv run --no-sync pytest tests/test_retriever.py tests/test_store.py -v` — US1 cold-start concurrent retrieval and concurrent directory initialization pass independently (**MVP ready**).

---

## Phase 4: User Story 2 - Concurrent Store Lifecycle Coordination & Clean Failure Rollback (Priority: P1)

**Goal**: Serialize concurrent teardown (`close` / `__exit__`), collection resets (`reset_collection`), and reentrant failure rollback, wrapping both client startup and collection validation errors uniformly in `DocpipeError` while leaving `SharedSystemClient` uncorrupted (`FR-001`, `FR-002`, `FR-003`, `FR-007`, `FR-010`, `SC-002`).

**Independent Test**: Run concurrent shared-handle open/close/reopen/reset cycle tests and fault-injection tests simulating (a) `PersistentClient` startup failure (`_client is None`, teardown skipped), (b) collection validation failure overlapping concurrent opens/closes, and (c) secondary `_client.close()` failure during rollback in `tests/test_store.py`.

### Tests for User Story 2

> **NOTE: Write US2 tests FIRST before implementing US2 rollback and teardown guards.**

- [X] T007 [US2] Write concurrent store open, overlapping `close()` / context-manager exit, reopen immediately after final close, and overlapping `reset_collection()` lifecycle tests verifying idempotent close and `SharedSystemClient` refcount cleanup via `_active_systems_for` in `tests/test_store.py`
- [X] T008 [US2] Write fault-injection rollback tests covering (a) `chromadb.PersistentClient` raising during startup (assert `DocpipeError` match `"Invalid or unusable collection"` preserving `__cause__`, both `ChromaStore.close` and backend client teardown skipped when `_client is None`, `_active_systems_for == []`), (b) `get_or_create_collection` failing concurrently with sibling store opens/closes, and (c) secondary `_client.close()` exception suppressed during rollback so primary `DocpipeError` surfaces unmasked in `tests/test_store.py`

### Implementation for User Story 2

- [X] T009 [US2] Move `chromadb.PersistentClient(...)` inside the `try:` block under `with _CHROMA_CLIENT_LOCK:` in `ChromaStore.__init__` and add reentrant `_safe_rollback_close()` helper (setting `self._closed = True` directly without invoking `self.close()` when `self._client is None`, calling `with contextlib.suppress(Exception): self.close()` only when `self._client is not None`, re-raising `DocpipeError` directly, and wrapping non-`DocpipeError` exceptions in `DocpipeError(f"Invalid or unusable collection {self._collection_name!r}: {exc}") from exc`) in `src/docpipe_maestro/store/chroma.py`
- [X] T010 [US2] Guard `ChromaStore.close()` (checking `if self._closed: return` idempotently under `_CHROMA_CLIENT_LOCK`, setting `self._closed = True`, closing `self._client` if callable) and `ChromaStore.reset_collection()` (`delete_collection` + `_get_or_create_collection` under `_CHROMA_CLIENT_LOCK`, preserving untouched post-close behavior on other methods per `FR-007`) in `src/docpipe_maestro/store/chroma.py`

**Checkpoint**: Run `uv run --no-sync pytest tests/test_store.py -v` — US1 + US2 concurrent lifecycle, reference counting, and fault-injection rollback pass cleanly.

---

## Phase 5: User Story 3 - Non-Serialized Concurrent Reads, Preserved Plugin/Caller Contracts & Lazy Startup (Priority: P1)

**Goal**: Guarantee `_CHROMA_CLIENT_LOCK` is never acquired during steady-state reads, queries, or writes, confirm retrieval callers never auto-close stores per query, keep custom `Store` plugins without `.close()` compatible, and preserve locked `36` root exports and lazy `chromadb` imports (`FR-004`, `FR-005`, `FR-006`, `FR-008`, `SC-003`, `SC-004`).

**Independent Test**: Verify concurrent `query_children()` runs cleanly while another thread holds `_CHROMA_CLIENT_LOCK`, verify custom `Store` plugin without `.close()` succeeds through `retrieve()`, and pass `tests/test_api_stability.py` and `tests/test_library_purity.py`.

### Tests for User Story 3

- [X] T011 [P] [US3] Write concurrent steady-state read non-serialization test proving `query_children()` completes on an already-open `VectorStore` across threads while `_CHROMA_CLIENT_LOCK` is held on another thread in `tests/test_store.py`
- [X] T012 [P] [US3] Write `retrieve()` store-reuse and plugin compatibility test (a) registering a custom `Store` implementation lacking `.close()` and asserting successful child search + parent lookup, and (b) spying on `ChromaStore.close` during `retrieve()` against `"default"` store to assert `0` per-query teardown calls in `tests/test_retriever.py`

### Verification & Guard Audits for User Story 3

- [X] T013 [US3] Inspect `add_chunks`, `query_children`, `get_by_ids`, `get_parents_by_source`, `delete_by_source`, `delete_stale_versions`, `sweep_uncommitted`, `get_all_children`, `get_all_parents`, and `__enter__` in `src/docpipe_maestro/store/chroma.py` plus `src/docpipe_maestro/_stages.py` (`Store` Protocol) and `src/docpipe_maestro/store/__init__.py` to confirm zero lifecycle locking on steady-state reads/writes and unchanged plugin/lazy contracts
- [X] T014 [US3] Run public API export and lazy-import startup purity suites (`uv run --no-sync pytest tests/test_api_stability.py tests/test_library_purity.py -v`) verifying `len(docpipe_maestro.__all__) == 36` and `'chromadb' not in sys.modules` on root import and CLI `build_parser()`

**Checkpoint**: All 3 user stories (US1, US2, US3) are implemented and independently verified.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final formatting, security/static checks, Constitution Release Gates, `minimal-core` validation, and full offline test suite pass (`SC-005`).

- [X] T015 [P] Run formatting, linter, and security lint checks (`uv run --no-sync ruff format --check .`, `uv run --no-sync ruff check .`, `uv run --no-sync ruff check --select S src/`) cleanly across `src/docpipe_maestro/store/chroma.py`, `tests/test_store.py`, and `tests/test_retriever.py`
- [X] T016 [P] Run strict static type checking across source and tests (`uv run --no-sync mypy src tests`)
- [X] T017 Execute mandatory Constitution Release Gate #1 (`uv run --no-sync pytest -m reverse -v`) and Release Gate #2 (`uv run --no-sync pytest -m pii -v`)
- [X] T018 Execute `specs/015-thread-safe-store-lifecycle/quickstart.md` validation including `minimal-core` subset (`LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -q --ignore=tests/test_extended_complex.py --ignore=tests/test_intake_clean.py --ignore=tests/test_intake_formats_optional.py --ignore=tests/test_security_hardening.py --ignore=tests/test_pii_safety.py`) and full offline test suite (`LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -v --cov`) confirming 100% passing tests and >= 80% coverage

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — starts immediately (`T001`–`T002`)
- **Foundational (Phase 2)**: Depends on Setup (`T003`) — BLOCKS implementation across user stories
- **User Story 1 (Phase 3 - P1 🎯 MVP)**: Depends on Foundational (`T003`); `T004` and `T005` run in parallel before `T006`
- **User Story 2 (Phase 4 - P1)**: Depends on US1 (`ChromaStore.__init__` lock integration in `T006` precedes US2 rollback/close unification in `T009`–`T010`; `T007` then `T008` write failing/edge-case tests first inside `tests/test_store.py`)
- **User Story 3 (Phase 5 - P1)**: Tests `T011` and `T012` run in parallel once `T003` exists; `T013` and `T014` verify final state after `T010`
- **Polish (Phase 6)**: Depends on completion of US1, US2, and US3 (`T015` & `T016` run in parallel, followed by `T017` and final `T018`)

### Parallel Opportunities

- `T001` and `T002` (Setup baseline run + caller audit) can execute in parallel.
- `T004 [P] [US1]` (`tests/test_retriever.py`) and `T005 [P] [US1]` (`tests/test_store.py`) execute in parallel.
- `T011 [P] [US3]` (`tests/test_store.py`) and `T012 [P] [US3]` (`tests/test_retriever.py`) execute in parallel.
- `T015 [P]` (`ruff` format/check/security) and `T016 [P]` (`mypy --strict`) execute in parallel once code edits settle.

### Parallel Example: User Story 1 & User Story 3

```bash
# US1 tests in parallel (different test files):
Task: "T004 [P] [US1] Fresh-subprocess cold-start concurrent retrieve() test in tests/test_retriever.py"
Task: "T005 [P] [US1] In-process concurrent VectorStore initialization tests in tests/test_store.py"

# US3 verification tests in parallel (different test files):
Task: "T011 [P] [US3] Non-serialized open-store concurrent query_children() test in tests/test_store.py"
Task: "T012 [P] [US3] Custom Store plugin without .close() compatibility test in tests/test_retriever.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (`T001`–`T002`) and Phase 2 (`T003`).
2. Complete Phase 3 (`T004`–`T006`) to eliminate the cold-start `chromadb.PersistentClient` initialization crash.
3. **STOP and VALIDATE**: Confirm fresh-subprocess cold-start concurrent `retrieve()` passes across repeated runs.

### Full Incremental Delivery

1. Deliver **US1** (`T004`–`T006`): cold-start concurrent store & retrieval initialization safety (**MVP**).
2. Deliver **US2** (`T007`–`T010`): coordinated teardown/reset, refcounting preservation, uniform client-startup + collection `DocpipeError` wrapping, and clean secondary-error-suppressed rollback.
3. Deliver **US3** (`T011`–`T014`): verify steady-state read non-serialization, caller store-reuse preservation, custom `Store` plugin compatibility, locked `36` exports, and lazy startup.
4. Execute **Phase 6** (`T015`–`T018`): `ruff`, `mypy --strict`, `@pytest.mark.reverse`, `@pytest.mark.pii`, `minimal-core` subset, and full `pytest --cov`.

## Notes

- All tasks keep changes confined to `src/docpipe_maestro/store/chroma.py`, `tests/test_store.py`, and `tests/test_retriever.py`.
- Same-file tasks (`T007`/`T008` in `tests/test_store.py`, `T009`/`T010` in `src/docpipe_maestro/store/chroma.py`) intentionally omit `[P]` to avoid merge/edit conflicts.
- `T009` MUST keep `"Invalid or unusable collection"` in the wrapped `DocpipeError` message so all existing test matchers (`tests/test_store.py:251`, `tests/test_security_hardening.py:110,112`, `tests/test_cli.py:141`) stay green.
