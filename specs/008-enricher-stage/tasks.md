---

description: "Executable task list for Feature 008: First-Class Enricher Stage & Cross-Reference Migration"
---

# Tasks: First-Class Enricher Stage & Cross-Reference Migration

**Input**: Design documents from `/specs/008-enricher-stage/`  
**Prerequisites**: [plan.md](plan.md) (required), [spec.md](spec.md) (required for user stories), [research.md](research.md), [data-model.md](data-model.md), [contracts/enricher.md](contracts/enricher.md), [quickstart.md](quickstart.md)

**Tests**: Included per `.specify/memory/constitution.md` (`v1.2.2` Quality Gates: every behavioral change ships with tests and full suite must pass with 100% pass rate).

**Organization**: Tasks are grouped by user story (`US1`, `US2`, `US3`) to enable independent implementation and testing of each increment.

## Format: `[ID] [P?] [Story?] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`[US1]`, `[US2]`, `[US3]`)
- Setup, Foundational, and Polish phases intentionally omit `[Story]` labels

## Path Conventions

- **Single project**: `src/docpipe_maestro/`, `tests/` at repository root

## Constitution Check

All tasks comply with `.specify/memory/constitution.md` (`v1.2.2`, Principles I–VII and Quality Gates): Principle I (locked `33`-symbol `__all__` and signatures preserved), Principle II (`_crossrefs.py` phase-neutral core + zero direct or transitive `query/` → `ingest/` AST imports verified in `T012`, `T015`, `T018`), Principle III (lazy built-in registration `T010`, zero config I/O), Principles IV–V (Release Gate #1 `@pytest.mark.reverse` verified in `T016`), Principle VI (`100%` offline/local execution), and Principle VII (`ChunkingProfile`/`IngestContext` schemas in `types.py` `T003` + mandatory `100%` passing full test suite `T019`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Align package documentation metadata prior to refactoring cross-reference and enricher modules

- [X] T001 Update ingestion package overview docstring in `src/docpipe_maestro/ingest/__init__.py` to reflect the `enricher` stage cleanly alongside intake, cleaning, chunking, and pipeline

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the phase-neutral cross-reference core and extend `ChunkingProfile` before user story implementation begins

**⚠️ CRITICAL**: No user story work (`Phase 3+`) can begin until this phase is complete

- [X] T002 Extract pure cross-reference regexes (`CROSSREF_RE`, `_DOC_SCOPED_CROSSREF_RE`, `_TOKEN_RE`, `_DOC_PHRASE_STOPWORDS`, `_SECTION_NUM_RE`, `_CLAUSE_START_LINE_RE`) and pure functions (`extract_section_num`, `truncate_excerpt` defaulting to `max_chars: int = 400`, `parse_crossref_match`, `iter_clause_blocks`, `index_section_targets`, `extract_doc_crossrefs`, `match_source_key`) into `src/docpipe_maestro/_crossrefs.py` using stdlib-only imports (`re`, `collections.abc.Sequence`) and zero `docpipe_maestro.ingest.*` or `docpipe_maestro.query.*` dependencies
- [X] T003 [P] Add `enrichers: tuple[str, ...] = ()` and `__post_init__` normalization (`tuple(self.enrichers)`; set `("crossrefs",)` via `object.__setattr__` when `self.resolve_crossrefs` is `True` and `not normalized`, while keeping explicit non-empty `enrichers` unmodified regardless of `resolve_crossrefs`) on frozen slotted `ChunkingProfile` in `src/docpipe_maestro/types.py`

**Checkpoint**: Foundation ready — phase-neutral `_crossrefs.py` and normalized `ChunkingProfile.enrichers` available for user story implementation

---

## Phase 3: User Story 1 - Extensible Ordered Enricher Pipeline Stage (Priority: P1) 🎯 MVP

**Goal**: Enable developers to register custom `Enricher` transformations on `ENRICHERS` and run them deterministically in declared `ChunkingProfile.enrichers` order between Clean and Chunk across both `ingest()` and `sync()`, with upfront registry validation and clean pre-persistence failure abort.

**Independent Test**: Register custom test enrichers in `ENRICHERS`, run `ingest()` and `sync()` with profiles declaring multi-step sequences, duplicate enricher names, `DEFAULT` (`enrichers=()`), unregistered names, and raising enrichers; verify exact execution order, full `IngestContext` delivery (`doc_version`), upfront `RegistryError` on unchanged collections, and zero ChromaDB/SQLite/manifest writes on failure.

### Tests for User Story 1

> **NOTE: Write these tests FIRST and ensure they FAIL before implementing T006**

- [X] T004 [P] [US1] Add integration tests in `tests/test_registry.py` verifying custom enrichers execute in profile-declared order `("first", "second")` and duplicate order `("first", "first")` between Clean and Chunk, receive full `IngestContext` (`collection`, `source`, `content_hash`, `doc_version = content_hash.split(":", 1)[1][:12]`, `embed_model`, `profile = prof.name`) across both `ingest()` and `sync()`, fail up front with `RegistryError` even when zero files changed, and skip all `ENRICHERS.resolve(...)` calls on `DEFAULT`
- [X] T005 [P] [US1] Add atomic transactional abort and profile normalization tests in `tests/test_invariants_stage1.py` verifying mid-sequence or mid-batch enricher exceptions abort both `ingest()` and `sync()` prior to any ChromaDB `Store`, FTS5 `LexicalIndex`, or `save_manifest()` writes (preserving existing committed versions intact), confirming legacy `ChunkingProfile(..., resolve_crossrefs=True).enrichers == ("crossrefs",)` dataclass normalization, and verifying explicit `ChunkingProfile(..., resolve_crossrefs=True, enrichers=("custom",))` override precedence end-to-end in `ingest()` (without requiring built-in `"crossrefs"` registration yet)

### Implementation for User Story 1

- [X] T006 [US1] Refactor `ingest()` and `sync()` in `src/docpipe_maestro/ingest/pipeline.py` to remove the inline `resolve_crossrefs` import and `if prof.resolve_crossrefs:` branches, adding shared helpers `_resolve_enrichers(enricher_names)` (returning `[]` on empty sequence or resolving/instantiating every entry up front alongside `CLEANERS`/`CHUNKERS`/`EMBEDDERS`/`STORES`) and `_apply_enrichers(doc, enrichers, ctx)` invoked per changed document in memory before chunking with complete `IngestContext` (depends on `T003`, `T004`, `T005`)

**Checkpoint**: User Story 1 is independently testable — custom enricher registration, ordering, `DEFAULT` skipping, `IngestContext` propagation, upfront lookup, and transactional abort work independently without requiring Phase 4 `"crossrefs"` migration yet (run `-k enricher` tests)

---

## Phase 4: User Story 2 - Built-In Cross-Reference Enricher on Policy Profile (Priority: P1)

**Goal**: Migrate intra-document cross-reference resolution into a lazily registered built-in `"crossrefs"` `Enricher` strategy configured via `POLICY.enrichers == ("crossrefs",)`, preserving exact `[Crossref ...]` output, cycle prevention, unresolved warning logs, golden retrieval output, and Release Gate #1 compliance.

**Independent Test**: Run `CrossrefsEnricher().enrich(doc, ctx)` vs `resolve_crossrefs(doc)`, inspect `ENRICHERS.keys()`, ingest policy documents under `DEFAULT` (`enrichers=()`) and `POLICY` (`enrichers=("crossrefs",)`), and run golden retrieval + `@pytest.mark.reverse` checks with zero regressions.

### Tests for User Story 2

> **NOTE: Write these tests FIRST and ensure they FAIL before T009–T011**

- [X] T007 [P] [US2] Add unit and end-to-end profile-parity tests in `tests/test_crossrefs.py` verifying `CrossrefsEnricher` implements `Enricher` (`name == "crossrefs"`), matches `resolve_crossrefs(doc)` output and `WARNING` logs identically across cycle/dotted/wrapped-clause cases, confirms `DEFAULT.enrichers == ()` and `POLICY.enrichers == ("crossrefs",)`, and verifies both `ingest(..., profile="POLICY")` / `sync(..., profile="POLICY")` and legacy `ChunkingProfile(..., resolve_crossrefs=True)` invoke `"crossrefs"` via `ENRICHERS` to produce baseline-identical `[Crossref ...]` chunks
- [X] T008 [P] [US2] Update `test_top_level_eight_registries_empty_defaults_and_protocol_conformance` in `tests/test_registry.py` (after `T004`) to assert `ENRICHERS.keys() == ["crossrefs"]` and `RegistryError` message `registry 'enricher' has no entry 'missing' (available: crossrefs)` while preserving custom `TagEnricher` registration checks

### Implementation for User Story 2

- [X] T009 [P] [US2] Implement `resolve_crossrefs(doc: ParsedDocument) -> ParsedDocument` (backed by pure helpers from `docpipe_maestro._crossrefs`) and `@ENRICHERS.register("crossrefs")` class `CrossrefsEnricher` (`name: str = "crossrefs"`, `enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument`) in `src/docpipe_maestro/ingest/enricher/crossrefs.py` preserving exact `[Crossref ...]` format, `max_chars=400`, cycle exclusion, and `WARNING` logging (depends on `T002`)
- [X] T010 [US2] Register lazy built-in `ENRICHERS.register_lazy("crossrefs", "docpipe_maestro.ingest.enricher.crossrefs", "CrossrefsEnricher")` and lazy `__getattr__` exports (`CrossrefsEnricher`, `resolve_crossrefs`) in `src/docpipe_maestro/ingest/enricher/__init__.py` keeping `__all__ = ["ENRICHERS", "CrossrefsEnricher", "register_enricher", "resolve_crossrefs"]` (depends on `T009`)
- [X] T011 [P] [US2] Configure explicit `enrichers=("crossrefs",)` on `POLICY` while keeping `DEFAULT` with `resolve_crossrefs=False` (`enrichers == ()`) in `src/docpipe_maestro/config.py` (depends on `T003`)

**Checkpoint**: User Stories 1 and 2 work together end-to-end — `POLICY` uses `CrossrefsEnricher` via `ENRICHERS`, `DEFAULT` skips enrichment, and Release Gate #1 (`@pytest.mark.reverse`) passes

---

## Phase 5: User Story 3 - Phase-Neutral Cross-Reference Core & Phase Isolation (Priority: P2)

**Goal**: Eliminate the final Phase 2 → Phase 1 import coupling by pointing `query/retriever.py` at `_crossrefs.py`, locking the full `docpipe_maestro.ingest` namespace out of `query/` via AST checks, and preserving `ingest/crossrefs.py` as a silent five-symbol compatibility shim.

**Independent Test**: Run `tests/test_library_purity.py` confirming zero static or dynamic `docpipe_maestro.ingest*` imports across all `query/**/*.py` files and zero eager `ingest.enricher.crossrefs` startup imports, plus run `tests/test_crossrefs.py`, `tests/test_api_stability.py`, and `tests/test_retriever.py` under `-Werror`.

### Tests for User Story 3

- [X] T012 [P] [US3] Tighten `test_phase2_query_does_not_import_phase1_stage_contracts` in `tests/test_library_purity.py` to reject any static import or dynamic `importlib.import_module` targeting `docpipe_maestro.ingest` or `docpipe_maestro.ingest.*` anywhere under `src/docpipe_maestro/query/` AND verify `src/docpipe_maestro/_crossrefs.py` imports zero `docpipe_maestro.ingest*` or `docpipe_maestro.query*` modules (proving zero direct or transitive Phase 2 → Phase 1 dependencies), and assert `"docpipe_maestro.ingest.enricher.crossrefs" not in sys.modules` in `test_top_level_register_exports_and_cli_avoid_heavy_deps`
- [X] T013 [P] [US3] Add silent compatibility re-export checks in `tests/test_crossrefs.py` (after `T007`) verifying importing and invoking `extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, `resolve_crossrefs`, and `truncate_excerpt` from `docpipe_maestro.ingest.crossrefs` emits zero warnings under strict warning capture and preserves object identity with `docpipe_maestro._crossrefs` / `docpipe_maestro.ingest.enricher.crossrefs`

### Implementation for User Story 3

- [X] T014 [P] [US3] Convert `src/docpipe_maestro/ingest/crossrefs.py` into a silent five-symbol compatibility re-export module (`extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, `truncate_excerpt` from `docpipe_maestro._crossrefs`, plus `resolve_crossrefs` from `docpipe_maestro.ingest.enricher.crossrefs`) with `__all__` and zero deprecation warnings (depends on `T002`, `T009`)
- [X] T015 [P] [US3] Update `src/docpipe_maestro/query/retriever.py` to import `extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, and `truncate_excerpt` from `docpipe_maestro._crossrefs` instead of `docpipe_maestro.ingest.crossrefs`, keeping `_enrich_crossdoc_references()` and `follow_crossrefs` semantics unchanged (depends on `T002`)

**Checkpoint**: All three user stories pass independently — zero Phase 2 → Phase 1 imports, shared canonical `_crossrefs` engine, and 100% legacy API stability

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation of architectural boundaries, style/typing gates, quickstart scenarios, and 100% test pass gate

- [X] T016 Run targeted quickstart verification scenarios from `specs/008-enricher-stage/quickstart.md` (`uv run pytest tests/test_library_purity.py tests/test_crossrefs.py tests/test_extended_complex.py tests/test_api_stability.py tests/test_golden_refactor.py tests/test_retriever.py tests/test_registry.py tests/test_invariants_stage1.py tests/test_sync_lifecycle.py -Werror -v` and `uv run pytest -m reverse -v`)
- [X] T017 [P] Run formatting, linting, security rules, and strict type checking across source and tests (`uv run ruff format --check . && uv run ruff check . && uv run ruff check --select S src/ && uv run mypy src tests`)
- [X] T018 Inspect `git diff src/docpipe_maestro/` to verify zero `docpipe_maestro.ingest` imports inside `src/docpipe_maestro/query/`, zero `if prof.resolve_crossrefs:` branches inside `src/docpipe_maestro/ingest/pipeline.py`, and unchanged 33-symbol `docpipe_maestro.__all__`
- [X] T019 **REQUIRED**: Run all tests across `tests/` against `src/docpipe_maestro/` with branch coverage (`uv run pytest --cov=docpipe_maestro`) after all implementation and cleanup finish; `100%` of tests must pass with zero failures and `>= 80%` branch coverage before reporting completion

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (`Phase 1`)**: No dependencies — starts immediately (`T001`)
- **Foundational (`Phase 2`)**: Starts immediately or after `T001` — **BLOCKS** all user stories (`T002` + `T003` in parallel)
- **User Story 1 (`Phase 3`, P1)**: Depends on Foundational (`T003` specifically unlocks `T006`; `T004`/`T005` test tasks can start right after `Phase 2`)
- **User Story 2 (`Phase 4`, P1)**: Depends on Foundational (`T002` unlocks `T009`; `T003` unlocks `T011`); builds cleanly after `US1` (`T006` pipeline dispatch + `T008` after `T004` in `tests/test_registry.py`) so full end-to-end `POLICY` runs pass cleanly
- **User Story 3 (`Phase 5`, P2)**: Depends on Foundational (`T002` unlocks `T014` & `T015`) and `T009` (`T014` re-exports `resolve_crossrefs`); `T015` (Phase 2 decoupling) can run immediately after `T002` in parallel with US1/US2 source edits (`T006`/`T009`/`T011`)
- **Polish (`Phase 6`)**: Depends on completion of `Phase 3`, `Phase 4`, and `Phase 5`

### User Story Dependencies

- **US1 (P1 — MVP)**: Depends on Foundational `T003`; independently verifiable with custom registered enrichers + `DEFAULT` profile without requiring `"crossrefs"` built-in migration
- **US2 (P1)**: Depends on Foundational `T002`/`T003` (and runtime `POLICY` pipeline dispatch from `T006` for full pipeline execution); independently testable at unit/registry level (`CrossrefsEnricher`, `ENRICHERS`, `POLICY.enrichers`)
- **US3 (P2)**: `T015` (`query/retriever.py`) depends only on Foundational `T002`; `T014` (`ingest/crossrefs.py` shim) depends on `T002` + `T009`; `T012` (`test_library_purity.py`) passes once `T010` + `T015` land

### Within Each User Story

- Tests (`T004`–`T005`, `T007`–`T008`, `T012`–`T013`) written BEFORE their corresponding implementation tasks and observed failing (TDD red → green)
- Implementation tasks ordered from shared/strategy modules (`crossrefs.py`, `config.py`) to package registration (`__init__.py`) and orchestration/consumers (`pipeline.py`, `retriever.py`)

### Parallel Opportunities

- **Foundational**: `T002` (`_crossrefs.py`) and `T003` (`types.py`) modify separate files → run in parallel
- **US1 Tests**: `T004` (`tests/test_registry.py`) and `T005` (`tests/test_invariants_stage1.py`) → run in parallel
- **US2 Tests & Impl**: `T007` (`tests/test_crossrefs.py`) and `T008` (`tests/test_registry.py`) run in parallel; `T009` (`ingest/enricher/crossrefs.py`) and `T011` (`config.py`) run in parallel
- **US3 Tests & Impl**: `T012` (`tests/test_library_purity.py`) and `T013` (`tests/test_crossrefs.py`) run in parallel; `T014` (`ingest/crossrefs.py`) and `T015` (`query/retriever.py`) run in parallel
- **Cross-Story**: `T015` (`query/retriever.py`) touches only Phase 2 and can execute alongside US1/US2 Phase 1 edits once `T002` completes

---

## Parallel Example: User Story 2

```bash
# Launch US2 tests in parallel:
Task: "T007 [P] [US2] Add CrossrefsEnricher parity & profile tests in tests/test_crossrefs.py"
Task: "T008 [P] [US2] Update ENRICHERS built-in key assertion in tests/test_registry.py"

# Launch US2 independent implementation modules in parallel:
Task: "T009 [P] [US2] Implement CrossrefsEnricher and resolve_crossrefs in src/docpipe_maestro/ingest/enricher/crossrefs.py"
Task: "T011 [P] [US2] Configure POLICY.enrichers in src/docpipe_maestro/config.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete **Phase 1** (`T001`) + **Phase 2** (`T002`, `T003`)
2. Complete **Phase 3: US1** (`T004`, `T005`, `T006`)
3. **STOP and VALIDATE**: Run `uv run pytest tests/test_registry.py tests/test_invariants_stage1.py -k enricher -Werror -v` to prove registry-driven ordered execution, `IngestContext` delivery, upfront fail-fast lookup, `DEFAULT` bypass, and atomic pre-persistence rollback independently

### Incremental Delivery

1. Complete **Setup + Foundational** (`T001`–`T003`) → Shared `_crossrefs.py` + `ChunkingProfile.enrichers` ready
2. Deliver **US1** (`T004`–`T006`) → Ordered Enricher pipeline stage active in `ingest()` and `sync()`
3. Deliver **US2** (`T007`–`T011`) → `"crossrefs"` registered lazily, `POLICY` profile migrated with full Release Gate #1 & golden parity
4. Deliver **US3** (`T012`–`T015`) → Phase 2 → Phase 1 import eliminated (`_crossrefs.py`), silent legacy shims preserved, AST guard hardened
5. Execute **Polish** (`T016`–`T019`) → All linters, `mypy --strict`, AST purity, Reverse Safety Gate, and 100% test suite pass confirmed

---

## Notes

- `[P]` tasks operate on distinct files with no unmet dependencies
- `[US1]`/`[US2]`/`[US3]` map every task directly to `specs/008-enricher-stage/spec.md`
- Never commit or conclude before `T019` passes `100%` of tests (`Constitution v1.2.2`)
- Respect locked 33-symbol `docpipe_maestro.__all__` and locked `ingest()` / `sync()` parameter signatures (`tests/test_api_stability.py`)
