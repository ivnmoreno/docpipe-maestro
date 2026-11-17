---

description: "Task list for Dry-Run Preview Mode (sync & reindex) under 012-dry-run"
---

# Tasks: Dry-Run Preview Mode (`012-dry-run`)

**Input**: Design documents from `specs/012-dry-run/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/dry-run.md`, `quickstart.md`  
**Tests**: Explicit test tasks are included per Constitution Quality Gates and spec User Scenarios / Measurable Outcomes (`0` embedder calls, `0` byte drift, CLI `--json`, Gate #1 `reverse`, Gate #2 `pii`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (`US1`, `US2`, `US3`)
- Every task includes exact file paths and data-model / contract constraints.

---

## Phase 1: Setup (Shared Verification Baseline)

**Purpose**: Confirm clean branch state and tooling readiness on `feat/012-dry-run` before foundational edits.

- [X] T001 Verify baseline lockfile and code quality checks (`uv lock --check`, `uv run --no-sync ruff check .`) from `pyproject.toml` on branch `feat/012-dry-run`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core result models and offline embedding cost estimator shared by all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] Extend `SyncResult` with defaulted fields (`dry_run: bool = False`, `estimated_children: int = 0`, `estimated_parents: int = 0`, `estimated_tokens: int = 0`, `estimated_cost_usd: float | None = None`, and JSON-serializable `to_dict()`) and add frozen dataclass `ReindexPreview` (`collection: str`, `embed_model: str`, `previous_embed_model: str | None`, `total_sources: int`, `total_children: int`, `total_parents: int`, `estimated_tokens: int`, `estimated_cost_usd: float | None`, `dry_run: bool = True`, and `to_dict()`) in `src/docpipe_maestro/types.py`
- [X] T003 [P] Implement offline `estimate_embedding_cost(embed_model: str, estimated_tokens: int) -> float | None` (`0.0` when `estimated_tokens <= 0` or `is_local_target(embed_model)` without importing `litellm`, else lookup `litellm.model_cost` via `prepare_litellm()` with exact/lowercase/suffix fallback returning `round(estimated_tokens * rate, 10)` if finite numeric `>= 0.0` else `None`) in `src/docpipe_maestro/embedder/default.py` and re-export in `src/docpipe_maestro/embedder/__init__.py`
- [X] T004 Export `ReindexPreview` in `src/docpipe_maestro/ingest/__init__.py` while keeping root `docpipe_maestro.__all__` unchanged at `36` exports in `src/docpipe_maestro/__init__.py`

**Checkpoint**: Foundation ready — `SyncResult`, `ReindexPreview`, and `estimate_embedding_cost()` are available and strictly typed.

---

## Phase 3: User Story 1 - Preview Directory Synchronization Without Mutations or Embedding Calls (Priority: P1) 🎯 MVP

**Goal**: Provide non-mutating `sync(..., dry_run=True)` returning exact file classifications (`added`, `updated`, `skipped`, `removed`), staged chunk counts, offline `estimated_tokens`, and offline `estimated_cost_usd` with `0` disk/store writes and `0` embedding calls (and populate identical chunk/token/cost metrics across live `sync()` calls).

**Independent Test**: Run `sync(..., dry_run=True)` over both an uninitialized persistence directory and a seeded collection with new, modified, mtime-drifted unchanged, and deleted files plus blocked PII / mismatched models, verifying `0` embedder calls and identical filesystem hashes.

### Tests for User Story 1

- [X] T005 [P] [US1] Add unit/integration tests for `sync(..., dry_run=True)`, live vs. dry-run metric parity (`estimated_children`, `estimated_parents`, `estimated_tokens`, `estimated_cost_usd`), zero directory creation on missing `persist_dir`, `0`-byte drift across mtime-drifted collections, `ModelMismatchError`, `local_only`, `PiiBlockedError` without `.audit.jsonl` writes, and offline `estimate_embedding_cost()` pricing cases (`ollama/*`, `openai/text-embedding-3-small`, unknown model) in `tests/test_sync_lifecycle.py`
- [X] T006 [P] [US1] Add telemetry test verifying `sync(..., dry_run=True)` emits `intake`/`clean`/`enrich`/`chunk` prep summaries and a `store` preview event (`dry_run=True`) with zero `embed` stage event and zero raw PII leaks in `tests/test_logging.py`

### Implementation for User Story 1

- [X] T007 [US1] Add trailing keyword-only `dry_run: bool = False` to `sync()` and `_sync_impl()` in `src/docpipe_maestro/ingest/pipeline.py` (passing `persist_path=None, audit_mode=None` to `_extract_document_chunks()` when `dry_run=True` to block `.audit.jsonl` writes on `PiiBlockedError`, validating `STORES.resolve` / `EMBEDDERS.resolve` without instantiating `store_cls` or `LexicalIndex`, skipping `save_manifest` on `mtime`/`size` drift, computing `estimated_children`, `estimated_parents`, `estimated_tokens`, and `estimated_cost_usd` consistently for both live and dry runs, and emitting read-only `store` preview telemetry)

**Checkpoint**: User Story 1 (`sync(..., dry_run=True)`) is complete, independently verified, and MVP-ready.

---

## Phase 4: User Story 2 - Preview Full Collection Re-Embedding Volume and Cost (Priority: P2)

**Goal**: Provide non-mutating `reindex(..., dry_run=True)` returning `ReindexPreview` with active committed source/child/parent totals, offline `estimated_tokens`, and offline `estimated_cost_usd`, guaranteeing `0` embedder calls and `0`-byte immutability across standalone processes and read-only directories for default local storage.

**Independent Test**: Run `reindex(..., dry_run=True)` against an uninitialized collection (zero-work preview with no directory creation) and against a seeded collection inside a fresh subprocess / `chmod 0555` read-only persistence directory plus a custom registered `Store`, asserting `0` byte drift, `0` embedder calls, and exact chunk/token counts.

### Tests for User Story 2

- [X] T008 [P] [US2] Add unit/subprocess tests for `reindex(..., dry_run=True)` covering missing/empty manifests (zero-work `ReindexPreview` without creating `.docpipe/`), active multi-doc collections excluding uncommitted staging, cold-subprocess and read-only-directory (`chmod 0555`) `0`-byte immutability on `chroma.sqlite3`, custom `STORES` delegation, cloud/local cost estimation, `local_only=True` remote-model refusal, invalid `embedder`/`store` `RegistryError` parity, and `0` embedder calls in `tests/test_sync_lifecycle.py`
- [X] T009 [P] [US2] Add lazy-import verification confirming `sqlite3`, `chromadb`, and `litellm` remain unimported on `docpipe_maestro` and `reindex(..., dry_run=True)` local/missing-manifest paths in `tests/test_hybrid_search.py`

### Implementation for User Story 2

- [X] T010 [P] [US2] Implement stdlib-only lazy SQLite reader `read_chroma_active_preview_rows(persist_dir: Path, collection_name: str, active_versions: Mapping[str, str]) -> tuple[list[str], int]` (returning `([], 0)` when `chroma.sqlite3` or the collection row is absent) using `db_path.resolve().as_uri() + "?mode=ro"` (with `?mode=ro&immutable=1` fallback only on read-only directory open error) in `src/docpipe_maestro/store/_readonly.py`
- [X] T011 [US2] Add `@overload` signatures (`Literal[False] = False -> int`, `Literal[True] -> ReindexPreview`, `bool -> int | ReindexPreview`) and `dry_run: bool = False` handling to `reindex()` and `_reindex_impl()` in `src/docpipe_maestro/ingest/pipeline.py` (early zero-work `ReindexPreview` when manifest absent/empty, lazy `store._readonly` path for `store == "default"` without ever instantiating `ChromaStore` and delegating to `store_cls` only when `store != "default"`, token/cost summation, and `store` preview `stage_event` without `embed` stage)

**Checkpoint**: User Stories 1 and 2 are independently functional and verified.

---

## Phase 5: User Story 3 - Machine-Readable JSON & Human Dry-Run Reports via CLI (Priority: P2)

**Goal**: Expose `--dry-run` and `--json` flags on `docpipe-maestro sync` and `docpipe-maestro reindex` with clean human summaries and parseable JSON on `stdout` (`--log-json` strictly on `stderr`).

**Independent Test**: Invoke `docpipe-maestro sync <dir> --dry-run [--json]` and `docpipe-maestro reindex --model ... --dry-run [--json]` (including cold CLI subprocesses) and assert JSON schemas, exit codes, `stdout`/`stderr` separation, and `0`-byte filesystem immutability.

### Tests for User Story 3

- [X] T012 [P] [US3] Add CLI integration and cold-subprocess tests for `sync --dry-run`, `sync --dry-run --json`, live `sync --json`, `reindex --dry-run`, `reindex --dry-run --json`, live `reindex --json`, and `--log-json` stderr separation in `tests/test_cli.py`

### Implementation for User Story 3

- [X] T013 [US3] Register `--dry-run` (`store_true`) and `--json` (`store_true`, `dest="as_json"`) on `p_sync` and `p_reindex`, extract small helper `_format_cost_usd(cost: float | None) -> str`, and update `sync`/`reindex` command dispatch in `src/docpipe_maestro/cli.py`

**Checkpoint**: All three user stories (`US1`, `US2`, `US3`) work independently and via CLI.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Public API contract stability, documentation sync, quickstart validation, and full release-gate verification.

- [X] T014 [P] Update `root.sync` and `root.reindex` parameter assertions (`dry_run=False`) and add `SyncResult` / `ReindexPreview` / `estimate_embedding_cost` checks while verifying `len(root.__all__) == 36` in `tests/test_api_stability.py`
- [X] T015 [P] Update CLI, API, architecture, roadmap, and release notes across `docs/cli-reference.md`, `docs/api-reference.md`, `docs/architecture.md`, `docs/README.md`, `docs/future-features.md`, `PRODUCT.md`, `README.md`, and add/update an `## Unreleased` section in `CHANGELOG.md`
- [X] T016 Run quickstart scenarios from `specs/012-dry-run/quickstart.md` and full quality/safety/coverage gates (`uv lock --check`, `uv run --no-sync ruff format --check .`, `uv run --no-sync ruff check .`, `uv run --no-sync ruff check --select S src/`, `uv run --no-sync mypy src tests`, `uv run --no-sync pytest -m reverse -v`, `uv run --no-sync pytest -m pii -v`, `LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -v --cov`, core subset checks)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — starts immediately.
- **Phase 2 (Foundational)**: Depends on `T001` — BLOCKS `US1`, `US2`, and `US3`. (`T002` and `T003` run in parallel; `T004` follows `T002`).
- **Phase 3 (`US1`)**: Depends on Phase 2 (`T002`, `T003`, `T004`). `T005` & `T006` run in parallel before `T007`.
- **Phase 4 (`US2`)**: Depends on Phase 2 (`T002`, `T003`, `T004`) and shares `src/docpipe_maestro/ingest/pipeline.py` with `T007` (run `T010` parallel with `T007`, then `T011` after `T007` & `T010`).
- **Phase 5 (`US3`)**: Depends on `T007` (`sync`) and `T011` (`reindex`) library support.
- **Phase 6 (Polish)**: Depends on completion of `US1`, `US2`, and `US3`.

### Parallel Opportunities

```bash
# Phase 2 parallel foundation tasks:
T002: Extend SyncResult and add ReindexPreview in src/docpipe_maestro/types.py
T003: Add estimate_embedding_cost() in src/docpipe_maestro/embedder/default.py & __init__.py

# Phase 3 + Phase 4 parallel test & helper tasks:
T005: Add sync dry-run & cost tests in tests/test_sync_lifecycle.py
T006: Add sync dry-run logging test in tests/test_logging.py
T009: Add lazy-import checks in tests/test_hybrid_search.py
T010: Implement lazy ?mode=ro reader in src/docpipe_maestro/store/_readonly.py
```

---

## Implementation Strategy

### MVP First (`US1` Only)
1. Complete Phase 1 (`T001`) and Phase 2 (`T002`–`T004`).
2. Complete Phase 3 (`T005`–`T007`) for `sync(..., dry_run=True)` and verify offline parity and `0`-byte immutability.

### Full Incremental Delivery (`US1` → `US2` → `US3`)
1. Complete Phase 4 (`T008`–`T011`) for `reindex(..., dry_run=True)` with lazy read-only SQLite inspection.
2. Complete Phase 5 (`T012`–`T013`) exposing CLI `--dry-run` and `--json` for both commands.
3. Complete Phase 6 (`T014`–`T016`) locking API stability, docs, and passing 100% of test, lint, type, and coverage gates.
