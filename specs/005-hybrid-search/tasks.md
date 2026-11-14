---

description: "Task list for Hybrid Lexical Search with Reciprocal Rank Fusion (005-hybrid-search)"
---

# Tasks: Hybrid Lexical Search with Reciprocal Rank Fusion

**Input**: Design documents from `/specs/005-hybrid-search/`
**Prerequisites**: [plan.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/plan.md), [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/spec.md), [research.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/research.md), [data-model.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/data-model.md), [contracts/hybrid-search.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/contracts/hybrid-search.md)

**Tests**: Explicit offline tests covering FTS5 query sanitization, RRF fusion, lifecycle synchronization, CLI integration, API stability, library purity, latency bounds, and Release Gate #1 are included across Phases 3–6. Existing Stage 0 baseline tests (`tests/conftest.py` and the 12 original Stage 0 `tests/test_*.py` suites) MUST remain untouched.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps to `US1` (P1 Hybrid Retrieval), `US2` (P2 Lexical Index Lifecycle), `US3` (P3 Score Normalization, Thresholding & CLI/TOML Config)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify baseline tooling health and SQLite FTS5 capability before implementation begins.

- [X] T001 Verify stdlib SQLite FTS5 runtime support (`unicode61` tokenizer + `bm25()`) and clean baseline checks (`uv run ruff format --check . && uv run pytest -m reverse -v`) in repository root

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core collocated FTS5 index storage and encapsulated default dense searcher required before user story integration.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Create collocated SQLite FTS5 `LexicalIndex` and `sanitize_fts_query` in `src/docpipe_maestro/store/lexical.py`: persist at `<persist_dir>/lexical/<safe_collection>.db`, validate collection name via `validate_collection_name()` and `resolve().is_relative_to(lexical_dir.resolve())`, enforce `0o700` dir / `0o600` file permissions, create FTS5 virtual table `chunks_fts` (`tokenize='unicode61'`) with `UNINDEXED` columns `(chunk_id, parent_id, source, doc_version, page, chunk_index, embed_model)` and indexed columns `(section, clause, content)` weighted `(1.5, 2.0, 1.0)` in `bm25()`, sanitize raw queries via `[^\W]+(?:[.\-:/][^\W]+)*` (max 64 deduplicated terms, double-quote escaped, `OR`-joined), open Phase 2 reads via strict SQLite URI `mode=ro`, filter hits against `active_versions`, and implement idempotent child `add_chunks`, `exists`, `has_indexed_rows`, `delete_by_source`, `delete_stale_versions`, `sweep_uncommitted`, and `reset` with parameterized `?` SQL
- [X] T003 Export lazy `LexicalIndex` in `src/docpipe_maestro/store/__init__.py` via `_LAZY_STORE_EXPORTS` and `TYPE_CHECKING` without eager `sqlite3` or `chromadb` import at package initialization (depends on T002)
- [X] T004 [P] Create `DenseSearcher` (`name = "default"`, zero-arg `__init__(self, *, embedder: str = "default", store: str = "default")`) implementing `Searcher` protocol using existing dense vector child search in `src/docpipe_maestro/query/searcher/dense.py`

**Checkpoint**: Foundation ready — `LexicalIndex` and `DenseSearcher` are ready for Phase 3+ stories.

---

## Phase 3: User Story 1 - Exact-Match and Semantic Hybrid Retrieval (Priority: P1) 🎯 MVP

**Goal**: Provide a pluggable `Fts5HybridSearcher` combining dense semantic similarity and SQLite FTS5 BM25 lexical search via Reciprocal Rank Fusion while preserving bit-for-bit identical Stage 1 behavior when `searcher="default"`.

**Independent Test**: Index documents containing exact codes/clause IDs (`SEV-1`, `AES-256`, `Clause 1.2`) offline, run `retrieve(query, searcher="fts5_hybrid")`, and confirm exact matches elevate to Top-1 with parent expansion and exception preservation while `searcher="default"` remains bit-for-bit unchanged.

- [X] T005 [P] [US1] Create US1 unit & integration tests in `tests/test_hybrid_search.py` covering `sanitize_fts_query` (hyphens, dots, slashes, unbalanced quotes, wildcards, `AND`/`OR`/`NOT`, whitespace/punctuation-only), `Fts5HybridSearcher` RRF rank fusion and Top-1 exact-identifier recall lift over dense-only, `"default"` golden parity, empty/no-lexical-match graceful degradation, and `Searcher` protocol conformance
- [X] T006 [US1] Implement `Fts5HybridSearcher` (`name = "fts5_hybrid"`, zero-arg `__init__(self, *, embedder: str = "default", store: str = "default")`, fixed v1 constants `RRF_K = 60`, `DENSE_WEIGHT = 0.5`, `LEXICAL_WEIGHT = 0.5`, `MAX_RRF_SCORE = 1.0 / 61.0`, `candidate_k = max(top_k * 2, 20)`) in `src/docpipe_maestro/query/searcher/hybrid.py`: validate committed non-empty collection has populated lexical index or raise actionable `DocpipeError` suggesting `reindex` / `--force`, short-circuit whitespace queries to `[]`, query both dense `Store` and read-only `LexicalIndex`, compute normalized theoretical-max RRF scores in `[0.0, 1.0]`, and sort deterministically by `(-score, id)` (depends on T002, T004)
- [X] T007 [US1] Register lazy built-in searchers `"default"` (`DenseSearcher`) and `"fts5_hybrid"` (`Fts5HybridSearcher`) via `SEARCHERS.register_lazy` in `src/docpipe_maestro/query/searcher/__init__.py` (depends on T004, T006)
- [X] T008 [US1] Update `retrieve(...)` in `src/docpipe_maestro/query/retriever.py` to accept keyword-only `searcher: str = "default"`, validate unknown keys via `SEARCHERS.resolve(searcher)`, instantiate built-in searchers with forwarding for `embedder`/`store` selectors (while instantiating custom `Searcher` plugins with zero args), preserve bit-for-bit dense results on `"default"`, and run downstream `threshold`, `expand_parent` (`max(child.score)`), and `follow_crossrefs` uniformly (depends on T007)
- [X] T009 [US1] Update Stage 1 searcher registry checks in `tests/test_registry.py` moving `SEARCHERS` from empty-registry assertions to built-in (`"default"`, `"fts5_hybrid"`) lazy-loading and `Searcher` protocol checks (depends on T007)

**Checkpoint**: User Story 1 is functional and independently testable — hybrid search elevates exact lexical hits cleanly without disturbing default dense retrieval.

---

## Phase 4: User Story 2 - Consistent Read-Only Queries and Synchronized Index Lifecycle (Priority: P2)

**Goal**: Synchronize `LexicalIndex` across all Phase 1 storage mutations (`ingest`, `sync`, `remove`, `reindex`) including 2-phase crash safety and legacy collection re-indexing, while keeping Phase 2 strictly read-only.

**Independent Test**: Run `ingest()` -> modify/delete files -> `sync()` -> `remove()` -> verify deleted/superseded keywords yield zero lexical matches; inject uncommitted FTS5 rows to verify sweep cleanup; query an unindexed legacy collection with `fts5_hybrid` to confirm actionable `reindex` error, then run `reindex()` and verify hybrid search succeeds.

- [X] T010 [P] [US2] Add US2 lifecycle tests in `tests/test_hybrid_search.py` covering collocated `<persist_dir>/lexical/<collection>.db` creation on `ingest` (including 0-chunk empty-file initialization), incremental `sync()` updates and deletions purging old terms, `remove()` purging source rows, `sweep_uncommitted()` orphan recovery after interrupted writes, strict Phase 2 `mode=ro` enforcement (erroring with `reindex` hint on unindexed legacy collections), and `reindex()` populating FTS5 cleanly
- [X] T011 [US2] Integrate `LexicalIndex` lifecycle into `src/docpipe_maestro/ingest/pipeline.py`: call `lexical.sweep_uncommitted(active_versions)` prior to writes in `ingest()` and `sync()`, initialize schema + stage child chunks in `lexical.add_chunks(...)` before `save_manifest`, call `lexical.delete_stale_versions(...)` and `lexical.delete_by_source(...)` after manifest commit, clean `lexical.delete_by_source(...)` in `remove()`, and call `lexical.reset()` + `lexical.add_chunks(rebuilt_children)` in `reindex()` (depends on T002, T003)

**Checkpoint**: User Stories 1 and 2 work independently and maintain strict Phase 1 write / Phase 2 read-only crash safety.

---

## Phase 5: User Story 3 - Score Normalization, Thresholding, CLI & Configuration Integration (Priority: P3)

**Goal**: Integrate `--searcher` into CLI `query`/`ask` and optional TOML defaults, lock normalized theoretical-max RRF score bounds with `threshold` filtering, and update API contract & purity guards.

**Independent Test**: Invoke `docpipe-maestro query` and `docpipe-maestro ask` with `--searcher fts5_hybrid`, TOML `searcher = "fts5_hybrid"`, `--threshold`, and invalid `--searcher ghost` (verifying exit code `1`), verify API stability + AST library purity + lazy imports, and benchmark `< 20 ms` added search latency on 5,000 child chunks.

- [X] T012 [P] [US3] Add US3 integration & non-functional tests in `tests/test_hybrid_search.py` covering theoretical-max RRF score normalization (`dual rank-1 == 1.0`, `single-signal rank-1 == 0.5`), `threshold` filtering on normalized hybrid scores, CLI `query`/`ask --searcher` flag + `docpipe.toml` `searcher` default, unknown `--searcher` exit code `1`, Release Gate #1 reverse-safety corpus equivalence under `searcher="fts5_hybrid"`, lazy-import subprocess test (`chromadb`/`litellm`/`sqlite3` absent on `build_parser()` & package import), and `< 20 ms` cold hybrid lookup benchmark at 5,000 chunks
- [X] T013 [US3] Update `tests/test_api_stability.py` adding `("searcher", kw_only, "default")` to expected `root.retrieve` signature assertions (depends on T008)
- [X] T014 [US3] Update `src/docpipe_maestro/cli.py` to read `_cfg_str(cfg, "searcher", "default")`, add `--searcher` flag to `query` and `ask` subparsers, and forward `searcher=args.searcher` to `retrieve(...)` cleanly (depends on T008)
- [X] T015 [US3] Verify AST library purity (`tests/test_library_purity.py`) confirms zero config/dotenv reads outside `cli.py` and zero Phase 1 stage leaks inside Phase 2 modules across all modified/added source files (depends on T002, T006, T008, T011, T014)

**Checkpoint**: All 3 user stories, API stability, CLI/TOML integration, and latency/purity constraints are complete and verified.

---

## Phase 6: Polish & Cross-Cutting Verification

**Purpose**: Confirm Stage 0 test immutability, strict formatting/linting/security/typing, mandatory Release Gate #1, `>= 80%` branch coverage, and `quickstart.md` scenarios.

- [X] T016 Audit Stage 0 baseline test immutability via `git diff tests/conftest.py tests/test_chunker.py tests/test_cli.py tests/test_crossrefs.py tests/test_extended_complex.py tests/test_intake_clean.py tests/test_manifest.py tests/test_prompts_answer.py tests/test_retriever.py tests/test_reverse_safety.py tests/test_security_hardening.py tests/test_store.py tests/test_sync_lifecycle.py` and confirm every scenario in `specs/005-hybrid-search/quickstart.md` passes
- [X] T017 Run full code quality, security audit, and strict type checks (`uv run ruff format --check . && uv run ruff check . && uv run ruff check --select S src/ && uv run mypy src tests`)
- [X] T018 Execute mandatory Release Gate #1 (`uv run pytest -m reverse -v`) and full test + branch coverage suite (`uv run pytest -v --cov`, confirming `>= 80%` branch coverage and zero regressions)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately.
- **Phase 2 (Foundational)**: Depends on Phase 1 (`T001`). `T002` + `T004` can start in parallel; `T003` depends on `T002`. BLOCKS US1–US3.
- **Phase 3 (US1 - MVP)**: Depends on Phase 2 (`T002`, `T004`). `T005` and `T006` can run after Phase 2 (`T005` `[P]` test-first); `T007` -> `T008` & `T009`.
- **Phase 4 (US2 - Lifecycle)**: Can start in parallel with `T006` once `T002`/`T003` are complete (`T010` `[P]` + `T011` modifying `pipeline.py`).
- **Phase 5 (US3 - CLI & Normalization)**: `T012` `[P]`; `T013` + `T014` depend on `T008`; `T015` runs after implementation files settle.
- **Phase 6 (Polish)**: Runs after all desired stories complete (`T016` -> `T017` -> `T018`).

### Parallel Opportunities

```bash
# Phase 2 parallel start:
Task: "T002 Implement LexicalIndex in src/docpipe_maestro/store/lexical.py"
Task: "T004 [P] Implement DenseSearcher in src/docpipe_maestro/query/searcher/dense.py"

# Phase 3–5 test authoring while implementation stabilizes (separate files / independent test helpers):
Task: "T005 [P] [US1] Sanitization & RRF fusion tests in tests/test_hybrid_search.py"
Task: "T013 [US3] Update expected retrieve() signature in tests/test_api_stability.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (`T001`) + Phase 2 (`T002`–`T004`).
2. Complete Phase 3 (`T005`–`T009`) + `pipeline.py` staging (`T011` minimum `ingest` write hook if testing end-to-end).
3. Validate `tests/test_hybrid_search.py` and `tests/test_golden_refactor.py` before moving to lifecycle/CLI polish.

### Incremental Delivery

1. Setup + Foundational -> `LexicalIndex` & `DenseSearcher` ready.
2. US1 -> Registered `"default"` + `"fts5_hybrid"` searchers + `retrieve(..., searcher=...)`.
3. US2 -> Full Phase 1 lifecycle (`ingest`, `sync`, `remove`, `reindex`, `sweep_uncommitted`) + unindexed collection error guard.
4. US3 -> CLI `--searcher` flags, TOML defaults, theoretical-max RRF threshold verification, API stability & `<20ms` latency verification.
5. Phase 6 -> Final clean gates (`ruff`, `S`, `mypy`, `reverse`, `--cov`).
