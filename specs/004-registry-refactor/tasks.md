---

description: "Executable task list for refactoring docpipe-maestro pipeline stages into Strategy + Registry extensions"
---

# Tasks: Pluggable Pipeline Stage Registries

**Input**: Design documents from `/specs/004-registry-refactor/`
**Prerequisites**: [plan.md](plan.md) (required), [spec.md](spec.md) (required for user stories), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Automated test tasks are explicitly included per `FR-009` and `SC-001`–`SC-006` (registry contracts, public API signature stability, AST library purity, offline deterministic golden retrieval equivalence, and §1.3 invariant guards), while keeping all 12 baseline Stage 0 test files unmodified.

**Organization**: Tasks are grouped by user story (`US1`, `US2`, `US3`) to enable independent implementation and verification of each increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label (`[US1]`, `[US2]`, `[US3]`) used strictly inside user story phases
- Exact file paths and verbatim data-model/contract constraints are included in every task description

## Path Conventions

- Single library/CLI package rooted at `src/docpipe_maestro/` and `tests/`
- When converting a flat module (`embedder.py`, `store.py`, `ingest/intake.py`, `ingest/clean.py`, `ingest/chunker.py`) into a subpackage directory, always remove (`git rm`) the replaced `.py` file to avoid Python import shadowing

---

## Phase 1: Setup (Baseline Verification & Pre-Refactor Golden Capture)

**Purpose**: Verify a clean Stage 0 baseline and capture pre-refactor golden retrieval outputs before modifying core orchestrators or converting modules to packages.

- [X] T001 Verify clean Stage 0 test, lint, security, reverse-safety, and strict typing baseline via `uv run ruff format --check . && uv run ruff check . && uv run ruff check --select S src/ && uv run mypy src tests && uv run pytest -m reverse -v && uv run pytest -v` at repo root
- [X] T002 Capture pre-refactor deterministic retrieval baseline snapshot using `mock_litellm_offline` (`tests/conftest.py`) across `tests/fixtures/policy_corpus/` under `POLICY` profile (covering direct lookups, cross-references, and exception clauses) and write golden snapshot to `tests/fixtures/golden_query_stage1.json`
- [X] T003 [P] Create empty stage package scaffolding directories `src/docpipe_maestro/ingest/enricher/`, `src/docpipe_maestro/query/searcher/`, and `src/docpipe_maestro/query/reranker/` with placeholder awareness (no module shadowing)

---

## Phase 2: Foundational (Core Schema, Registry Engine & Stage Protocols)

**Purpose**: Establish shared data/exception schemas, the generic deferred-safe `Registry[T]`, and `@runtime_checkable` Phase 1/Phase 2 `Protocol` interfaces blocking all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 Update `src/docpipe_maestro/types.py` to define `RegistryError(DocpipeError)`, add Python 3.10-compatible two-step `TypedDict` `IngestContext` (`_IngestContextBase` with required `collection: str`, `source: str`, `content_hash: str`, `doc_version: str`, `embed_model: str`, `profile: str`; `IngestContext(_IngestContextBase, total=False)` with optional `extra: dict[str, Any]`), and relocate `@dataclass(slots=True)` models `ParsedClause` (`clause_label: str | None`, `text: str`, `page: int | None = None`), `ParsedSection` (`source: str`, `section_label: str`, `heading_level: int`, `raw_text: str`, `page: int | None = None`, `clauses: list[ParsedClause]`), and `ParsedDocument` (`source: str`, `format_name: str`, `sections: list[ParsedSection]`) from `src/docpipe_maestro/ingest/intake.py`
- [X] T005 Implement generic `Registry[T]` in `src/docpipe_maestro/_registry.py` (re-exporting `RegistryError` from `docpipe_maestro.types`) with private `_name: str`, `_entries: dict[str, type[T]]`, `_lazy_builtins: dict[str, tuple[str, str]]`, and `_materializing: set[str]`, enforcing immediate duplicate rejection (`RegistryError(f"registry '{self._name}' already has entry '{key}'")`) even against unmaterialized `_lazy_builtins` outside `_materializing`, deferred `register_lazy(key, module_path, attr)` rejection of duplicate `_entries`/`_lazy_builtins`, `resolve(key)` catching `KeyError` and calling `_materialize_all()` before raising `RegistryError(f"registry '{self._name}' has no entry '{key}' (available: {available})") from exc` (`available` sorted comma-joined or `"<empty>"`), `__contains__`, sorted `keys()`, and test-only `clear()` (depends on T004)
- [X] T006 [P] Define phase-neutral `@runtime_checkable` shared stage `Protocol` interfaces (`Embedder`, `Store`) in `src/docpipe_maestro/_stages.py` and Phase 1 `Protocol` interfaces (`Parser`, `Cleaner`, `Enricher`, `Chunker`, re-exporting `Embedder`, `Store`) in `src/docpipe_maestro/ingest/stages.py` preserving exact baseline signatures (`Parser.extensions: tuple[str, ...]`, `Parser.parse(self, path: Path, *, source_key: str) -> ParsedDocument`, `Embedder.embed_query(self, text: str, *, model: str, api_base: str | None = None) -> list[float]`, `Store.__init__(self, persist_dir: Path, collection_name: str) -> None`, `Store.query_children(..., where: dict[str, object] | None = None, include_embeddings: bool = False)`, `Store.delete_stale_versions(self, source: str, active_doc_version: str) -> None`, `Store.sweep_uncommitted(self, active_versions: dict[str, str]) -> int`, `Store.get_all_children(self) -> list[EmbeddedChunk]`) (depends on T004)
- [X] T007 [P] Define `@runtime_checkable` Phase 2 stage `Protocol` interfaces (`Searcher`, `Reranker`) in `src/docpipe_maestro/query/stages.py` (`Searcher.search(self, question: str, *, top_k: int, collection: str, persist_dir: str, embed_model: str, where: dict[str, object] | None = None) -> list[RetrievedChunk]` and `Reranker.rerank(self, query: str, chunks: list[RetrievedChunk], *, top_k: int) -> list[RetrievedChunk]`) (depends on T004)

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel across stage subpackages.

---

## Phase 3: User Story 1 — Extend Pipeline Stages Without Modifying Core Orchestration (Priority: P1) 🎯 MVP

**Goal**: Convert all active built-in parsers, cleaner, chunker, embedder, and Chroma vector store into lazy-declared registered stage adapters under dedicated subpackages with compatibility re-exports, route `pipeline.py` and `retriever.py` through the stage registries with optional keyword-only stage selectors (`"default"`), and prove custom stages execute end-to-end without editing core orchestrators.

**Independent Test**: Register custom `Parser`, `Cleaner`, `Chunker`, `Embedder`, or `Store` classes and execute `ingest` and `retrieve` end-to-end through custom identifiers (and extension routing) without modifying `pipeline.py` or `retriever.py`.

### Built-In Stage Subpackages & Parser Routing for User Story 1

- [X] T008 [P] [US1] Split `src/docpipe_maestro/ingest/intake.py` into package modules `src/docpipe_maestro/ingest/intake/_common.py` (`SUPPORTED_EXTENSIONS`, `_validate_docx_zip` 256 MiB guard, `detect_format` preserving `%PDF-`/`PK\x03\x04`/HTML/MD/UTF-8 extensionless fallback, `_sections_from_lines_stateful`, `_sections_from_lines`), `src/docpipe_maestro/ingest/intake/markdown.py` (`@PARSERS.register("md")` `MarkdownParser`, `extensions = (".md", ".markdown")`), `src/docpipe_maestro/ingest/intake/text.py` (`@PARSERS.register("txt")` `TextParser`, `extensions = (".txt",)`), `src/docpipe_maestro/ingest/intake/html.py` (`@PARSERS.register("html")` `HtmlParser`, `extensions = (".html", ".htm")` preserving iterative DOM walk & hidden prompt-injection guards with lazy `bs4` import), `src/docpipe_maestro/ingest/intake/pdf.py` (`@PARSERS.register("pdf")` `PdfParser`, `extensions = (".pdf",)` with lazy `pypdf` import), and `src/docpipe_maestro/ingest/intake/docx.py` (`@PARSERS.register("docx")` `DocxParser`, `extensions = (".docx",)` with lazy `python-docx` + zip-bomb guard), removing legacy `src/docpipe_maestro/ingest/intake.py`
- [X] T009 [US1] Create `src/docpipe_maestro/ingest/intake/__init__.py` declaring `PARSERS: Registry[Parser] = Registry("parser")`, `register_parser = PARSERS.register`, lazy declarations for `"docx"`, `"html"`, `"md"`, `"pdf"`, and `"txt"`, compatibility re-exports (`ParsedClause`, `ParsedSection`, `ParsedDocument`, `SUPPORTED_EXTENSIONS`, `detect_format`), and compatibility `parse_file(path: Path, *, source_key: str) -> ParsedDocument` delegating inside function body to `docpipe_maestro._resolve.resolve_parser` (depends on T005, T006, T008)
- [X] T010 [US1] Implement `resolve_parser(path: Path, preferred: str | None = None) -> Parser` in `src/docpipe_maestro/_resolve.py` checking `preferred` via `PARSERS.resolve`, raising `UnsupportedFormatError` if `not path.is_file()`, matching non-empty `path.suffix.lower()` across materialized `PARSERS.keys()` `extensions` (checking custom non-built-in sorted keys before built-in defaults `{"docx", "html", "md", "pdf", "txt"}` so custom overrides win deterministically), raising `UnsupportedFormatError` on unknown suffixes, and routing `path.suffix == ""` through `detect_format(path)` into `PARSERS.resolve(fmt)()` (depends on T009)
- [X] T011 [P] [US1] Convert `src/docpipe_maestro/ingest/clean.py` into `src/docpipe_maestro/ingest/clean/default.py` (`@CLEANERS.register("default")` `DefaultCleaner` with `name = "default"` preserving linear-time `_strip_html_tags`, `clean_text`, and `clean_document`) and `src/docpipe_maestro/ingest/clean/__init__.py` (`CLEANERS: Registry[Cleaner]`, `register_cleaner = CLEANERS.register`, lazy `"default"` built-in declaration, compatibility re-exports for `clean_text` and `clean_document`), removing legacy `src/docpipe_maestro/ingest/clean.py` (depends on T005, T006)
- [X] T012 [P] [US1] Convert `src/docpipe_maestro/ingest/chunker.py` into `src/docpipe_maestro/ingest/chunker/default.py` (`@CHUNKERS.register("default")` `DefaultChunker` with `name = "default"` preserving `estimate_tokens`, `chunk_document`, clause preservation, and section-scoped overlap reset) and `src/docpipe_maestro/ingest/chunker/__init__.py` (`CHUNKERS: Registry[Chunker]`, `register_chunker = CHUNKERS.register`, lazy `"default"` built-in declaration, lazy/compatibility re-exports for `chunk_document` and `estimate_tokens`), removing legacy `src/docpipe_maestro/ingest/chunker.py` (depends on T005, T006)
- [X] T013 [P] [US1] Update imports in `src/docpipe_maestro/ingest/crossrefs.py` to import `ParsedDocument` and `ParsedSection` from `docpipe_maestro.types` cleanly while keeping all crossref functions and exports intact (depends on T004)
- [X] T014 [P] [US1] Convert `src/docpipe_maestro/embedder.py` into `src/docpipe_maestro/embedder/default.py` (`@EMBEDDERS.register("default")` `LiteLLMEmbedder` with `name = "default"`, preserving Ollama direct fast-path, `prepare_litellm`, `validate_api_base`, `raise_litellm_error`, `_item_field`, `_is_loopback_host`, `embed_texts`, and `embed_query(text, *, model, api_base=None)`) and `src/docpipe_maestro/embedder/__init__.py` (`EMBEDDERS: Registry[Embedder]`, `register_embedder = EMBEDDERS.register` importing `Embedder` from phase-neutral `docpipe_maestro._stages`, lazy `"default"` declaration pointing to `docpipe_maestro.embedder.default.LiteLLMEmbedder`, eager-safe `DEFAULT_REQUEST_TIMEOUT = 120.0`, and lazy `__getattr__` re-exports keeping `litellm` unloaded on module import), removing legacy `src/docpipe_maestro/embedder.py` (depends on T005, T006)
- [X] T015 [P] [US1] Convert `src/docpipe_maestro/store.py` into `src/docpipe_maestro/store/chroma.py` (`@STORES.register("default")` `ChromaStore` with `name = "default"`, `VectorStore = ChromaStore` compatibility alias, `sweep_uncommitted(...) -> int` returning count of deleted `stale_ids` or `0`, `query_children(..., where: dict[str, object] | None = None, include_embeddings: bool = False)` keeping `where={"type": "child"}` behavior unchanged) and `src/docpipe_maestro/store/__init__.py` (`STORES: Registry[Store]`, `register_store = STORES.register` importing `Store` from phase-neutral `docpipe_maestro._stages`, lazy `"default"` declaration, and lazy `__getattr__` resolving `VectorStore` & `ChromaStore` so `chromadb` never imports eagerly), removing legacy `src/docpipe_maestro/store.py` (depends on T005, T006)

### Orchestrator Refactoring & Tests for User Story 1

- [X] T016 [US1] Refactor `src/docpipe_maestro/ingest/pipeline.py` to route per-file parsing through `resolve_parser(file_path).parse(...)` and resolve `CLEANERS`, `CHUNKERS`, `EMBEDDERS`, and `STORES` via strictly optional keyword-only stage selector parameters (`cleaner: str = "default"`, `chunker: str = "default"`, `embedder: str = "default"`, `store: str = "default"` on `ingest`/`sync`; `store: str = "default"` on `remove`/`status`, where `status` validates non-default `store` keys via `STORES.resolve` while computing metrics from the shared collection JSON manifest; `embedder: str = "default"`, `store: str = "default"` on `reindex`), preserving atomic pre-write staging (`store_cls(persist_path, collection)` after staging), early manifest-only paths (`status` and `remove` miss while validating non-default `store` keys), `resolve_crossrefs`, and all §1.3 invariants (depends on T010, T011, T012, T013, T014, T015)
- [X] T017 [US1] Refactor `src/docpipe_maestro/query/retriever.py` to add strictly optional keyword-only `embedder: str = "default"` and `store: str = "default"` on `retrieve()`, validate non-default stage keys prior to early empty/zero return, resolve `Embedder` and `Store` via `EMBEDDERS` and `STORES`, import `Store` from phase-neutral `src/docpipe_maestro/_stages.py` (preserving Phase 1/Phase 2 separation), type `_enrich_crossdoc_references(..., store: Store, ...)` against the shared `Store` protocol, and preserve `check_model_lock`, `expand_parent`, and scoring untouched (depends on T006, T014, T015)
- [X] T018 [US1] Create `tests/test_registry.py` (importing `register_*` from stage subpackages so US1 runs independently before `T022`) with unit tests for `Registry[T]` (`register`, `register_lazy`, `resolve`, duplicate rejection against live & deferred built-ins raising `RegistryError(DocpipeError)`, `KeyError` conversion listing sorted available keys and `<empty>`, membership `in`, sorted `keys()`, `clear()`), overlapping custom parser extension precedence in `resolve_parser` (`custom > built-in`), `status(..., store="missing")` error handling, and end-to-end custom `Parser`, `Cleaner`, `Chunker`, `Embedder`, and `Store` registration tests routed through `ingest` and `retrieve` without modifying orchestrators (depends on T016, T017)

**Checkpoint**: User Story 1 is complete — core orchestration routes cleanly through registries, all active built-ins use Stage 1 contracts, and custom extensions execute end-to-end.

---

## Phase 4: User Story 2 — Uniform Stage Contracts and Deferred Backend Loading (Priority: P1)

**Goal**: Provide the three empty contract-only registries (`ENRICHERS`, `SEARCHERS`, `RERANKERS`), export `RegistryError` and all eight lazy `register_*` extension entry points from `docpipe_maestro.__init__` (`__all__`), and ensure deferred built-in loading isolates heavy dependencies (`chromadb`, `litellm`) during startup and inspection.

**Independent Test**: Inspect all eight stage registries (`PARSERS`, `CLEANERS`, `ENRICHERS`, `CHUNKERS`, `EMBEDDERS`, `STORES`, `SEARCHERS`, `RERANKERS`), test `<empty>` diagnostics on reserved registries, verify protocol runtime checks, and confirm importing `docpipe_maestro` or accessing `register_*` keeps `chromadb`/`litellm` unloaded.

- [X] T019 [P] [US2] Create empty contract-only `Enricher` registry in `src/docpipe_maestro/ingest/enricher/__init__.py` exporting `ENRICHERS: Registry[Enricher] = Registry("enricher")`, `register_enricher = ENRICHERS.register`, and `__all__ = ["ENRICHERS", "register_enricher"]` (depends on T005, T006)
- [X] T020 [P] [US2] Create empty contract-only `Searcher` registry in `src/docpipe_maestro/query/searcher/__init__.py` exporting `SEARCHERS: Registry[Searcher] = Registry("searcher")`, `register_searcher = SEARCHERS.register`, and `__all__ = ["SEARCHERS", "register_searcher"]` (depends on T005, T007)
- [X] T021 [P] [US2] Create empty contract-only `Reranker` registry in `src/docpipe_maestro/query/reranker/__init__.py` exporting `RERANKERS: Registry[Reranker] = Registry("reranker")`, `register_reranker = RERANKERS.register`, and `__all__ = ["RERANKERS", "register_reranker"]` (depends on T005, T007)
- [X] T022 [US2] Update `src/docpipe_maestro/__init__.py` to export `RegistryError` (from `types.py`) and lazily expose all eight registration functions (`register_parser`, `register_cleaner`, `register_enricher`, `register_chunker`, `register_embedder`, `register_store`, `register_searcher`, `register_reranker`) in `__all__` (`33` exports total), `TYPE_CHECKING`, and `__getattr__` while preserving `_DocpipeModule` protection so subpackage imports never shadow `docpipe_maestro.ingest` (depends on T004, T009, T011, T012, T014, T015, T019, T020, T021)
- [X] T023 [P] [US2] Extend `tests/test_registry.py` to validate top-level public `from docpipe_maestro import register_*` exports for all eight stage registries (building on `T018`'s subpackage tests once `T022` lands), verify `ENRICHERS`, `SEARCHERS`, and `RERANKERS` return `[]` for `keys()` and raise `RegistryError` with `<empty>` on lookup, validate `@runtime_checkable` conformance across all built-in stage adapters, and assert lazy materialization does not trigger unrelated sibling built-ins (depends on T018, T022)

**Checkpoint**: User Stories 1 AND 2 both work cleanly — all 8 extension points are publicly exported with deferred loading and full typed contracts.

---

## Phase 5: User Story 3 — Zero-Behavior-Change Preservation & Automated Regression Guards (Priority: P1)

**Goal**: Lock public API signature stability, enforce CLI-exclusive config/`dotenv` AST library purity, verify bit-for-bit offline golden query equivalence against `tests/fixtures/golden_query_stage1.json`, and close any remaining unguarded §1.3 baseline invariants.

**Independent Test**: Run `tests/test_api_stability.py`, `tests/test_library_purity.py`, `tests/test_golden_refactor.py`, `tests/test_invariants_stage1.py`, `tests/test_cli.py`, and `pytest -m reverse -v` with zero failures.

- [X] T024 [P] [US3] Create `tests/test_api_stability.py` asserting all 24 baseline exports plus `RegistryError` (`issubclass(RegistryError, DocpipeError)`) and 8 `register_*` exports are present in `docpipe_maestro.__all__`, inspecting `inspect.signature` across `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, `answer`, and `answer_detailed` to confirm exact required positional/keyword parameters, strict `KEYWORD_ONLY` defaults (`"default"`) on new stage selector arguments, and preserved compatibility imports from `ingest.intake`, `ingest.clean`, `ingest.chunker`, `ingest.crossrefs`, `embedder`, and `store` (depends on T022)
- [X] T025 [P] [US3] Create `tests/test_library_purity.py` parsing AST nodes of every `.py` module under `src/docpipe_maestro/` excluding `cli.py` to reject `ast.Import`, `ast.ImportFrom`, and `importlib.import_module` referencing `tomllib`, `tomli`, `toml`, `configparser`, or `dotenv` (explicitly allowing document/manifest `open` and `Path.read_*` calls), plus subprocess checks verifying importing `docpipe_maestro`, accessing all 8 `register_*` attributes, and running `docpipe_maestro.cli.build_parser()` keep `chromadb` and `litellm` absent from `sys.modules` (depends on T022)
- [X] T026 [P] [US3] Create `tests/test_golden_refactor.py` ingesting `tests/fixtures/policy_corpus/` under `POLICY` profile with `mock_litellm_offline`, running every query defined in `tests/fixtures/golden_query_stage1.json` through refactored `retrieve()`, and asserting bit-for-bit equality of chunk `id`, `parent_id`, normalized `score`, `text`, and `metadata` (depends on T002, T016, T017)
- [X] T027 [P] [US3] Create `tests/test_invariants_stage1.py` guarding previously unguarded §1.3 invariants: direct `VectorStore.sweep_uncommitted(active_versions) -> int` orphan cleanup plus interrupted-write sweep on subsequent `ingest()`/`sync()`, empty-only file ingestion leaving `manifest.embed_dim is None` (`dim == 0` guard), extensionless magic-byte detection & zip-bomb rejection routed through `resolve_parser`, and `RegistryError` cleanly exiting with code `1` on stderr in `cli.main` (depends on T010, T015, T016, T022)

**Checkpoint**: All three P1 user stories and automated safety/stability/purity/golden gates are complete and independently verified.

---

## Phase 6: Polish & Cross-Cutting Verification

**Purpose**: Final cross-cutting audit confirming untouched baseline tests, clean formatting/linting/security/typing, Release Gate #1, and `>= 80%` branch coverage.

- [X] T028 Audit baseline test immutability via `git status --short tests/` and `git diff tests/conftest.py tests/test_*.py` (verifying zero edits to existing Stage 0 test files)
- [X] T029 Run full code quality and strict static analysis suite via `uv run ruff format --check . && uv run ruff check . && uv run ruff check --select S src/ && uv run mypy src tests`
- [X] T030 Execute mandatory Release Gate #1 (`uv run pytest -m reverse -v`) and full test + coverage suite (`uv run pytest -v --cov`, verifying `>= 80%` branch coverage), confirming every scenario in `specs/004-registry-refactor/quickstart.md` passes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Starts immediately — `T002` MUST execute before any refactor edits (`T008`–`T017`) so `golden_query_stage1.json` records unmodified baseline outputs
- **Foundational (Phase 2)**: Depends on Phase 1 (`T001`–`T003`) — `T004` (`types.py`) blocks `T005` (`_registry.py`), `T006` (`_stages.py` + `ingest/stages.py`), and `T007` (`query/stages.py`)
- **User Story 1 (Phase 3)**: Depends on Foundational (`T004`–`T006`) — builds all 5 active stage subpackages (`T008`–`T015`), wires `_resolve.py` (`T010`), orchestrators (`T016`–`T017`), and `test_registry.py` (`T018`)
- **User Story 2 (Phase 4)**: Depends on Foundational (`T004`–`T007`) for `T019`–`T021`; top-level exposure (`T022`) depends on stage subpackage `__init__.py` modules (`T009`, `T011`, `T012`, `T014`, `T015`, `T019`–`T021`)
- **User Story 3 (Phase 5)**: Depends on `T002`, `T016`, `T017`, `T022` — all four guard test suites (`T024`–`T027`) run in parallel once contracts & orchestration land
- **Polish (Phase 6)**: Depends on Phases 3–5 completion (`T028`–`T030`)

### Parallel Opportunities

- Within **Phase 2**: `T006` (`_stages.py` + `ingest/stages.py`) and `T007` (`query/stages.py`) run in parallel once `T004` (`types.py`) completes
- Within **Phase 3 (US1)**: `T008` (`intake/` parser implementations), `T011` (`clean/`), `T012` (`chunker/`), `T013` (`crossrefs.py`), `T014` (`embedder/`), and `T015` (`store/`) operate on disjoint paths and can be implemented in parallel
- Within **Phase 4 (US2)**: `T019` (`ingest/enricher/`), `T020` (`query/searcher/`), and `T021` (`query/reranker/`) run in parallel before `T022` (`__init__.py`)
- Within **Phase 5 (US3)**: `T024` (`test_api_stability.py`), `T025` (`test_library_purity.py`), `T026` (`test_golden_refactor.py`), and `T027` (`test_invariants_stage1.py`) are separate files and execute in parallel

---

## Parallel Example: User Story 1 Stage Subpackages

```bash
# Once Foundational (T004-T006) completes, launch stage subpackage conversions in parallel:
Task: "T008 [P] [US1] Convert ingest/intake.py into ingest/intake/{_common,markdown,text,html,pdf,docx}.py"
Task: "T011 [P] [US1] Convert ingest/clean.py into ingest/clean/default.py and __init__.py"
Task: "T012 [P] [US1] Convert ingest/chunker.py into ingest/chunker/default.py and __init__.py"
Task: "T013 [P] [US1] Update ingest/crossrefs.py imports to docpipe_maestro.types"
Task: "T014 [P] [US1] Convert embedder.py into embedder/default.py and lazy __init__.py"
Task: "T015 [P] [US1] Convert store.py into store/chroma.py and lazy __init__.py"
```

---

## Parallel Example: User Story 3 Guard Suites

```bash
# Once T022 and T016/T017 land, write all four verification suites concurrently:
Task: "T024 [P] [US3] Create tests/test_api_stability.py"
Task: "T025 [P] [US3] Create tests/test_library_purity.py"
Task: "T026 [P] [US3] Create tests/test_golden_refactor.py"
Task: "T027 [P] [US3] Create tests/test_invariants_stage1.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete **Phase 1: Setup** (`T001`–`T003`), locking `tests/fixtures/golden_query_stage1.json` BEFORE editing core source
2. Complete **Phase 2: Foundational** (`T004`–`T007`) — schema centralization, deferred-safe `Registry[T]`, Phase 1/Phase 2 `Protocol` contracts
3. Complete **Phase 3: User Story 1** (`T008`–`T018`) — stage subpackages, `_resolve.py`, orchestrator registry routing (`pipeline.py`, `retriever.py`), and `tests/test_registry.py`
4. **STOP & VALIDATE**: Run `uv run pytest -v` and verify existing tests + custom stage registration tests pass independently

### Incremental Delivery

1. Setup + Foundational (`T001`–`T007`) → shared core ready
2. User Story 1 (`T008`–`T018`) → core orchestrator decoupling & stage extensibility working (MVP!)
3. User Story 2 (`T019`–`T023`) → empty Stage 3/5/6 contracts + top-level lazy `register_*` / `RegistryError` public API
4. User Story 3 (`T024`–`T027`) → signature stability, AST library purity, golden query snapshot, and §1.3 invariant guards locked in CI
5. Polish (`T028`–`T030`) → full CI verification (`ruff`, `mypy --strict`, `@pytest.mark.reverse`, `>= 80%` branch coverage)

---

## Notes

- All `[P]` tasks touch distinct modules/files and have zero incomplete intra-phase dependencies.
- Never access `.__dict__` on `@dataclass(slots=True)` types (`ParsedClause`, `ParsedSection`, `ParsedDocument`, `Chunk`, `EmbeddedChunk`, `RetrievedChunk`, `ChunkingProfile`, `SourceRecord`, `Manifest`).
- Keep `typing` 100% Python `>=3.10` compatible (no `typing.Self`, no `typing.NotRequired`, no `datetime.UTC`).
- Reference commit groups from `REFACTOR_PROGRAM.md`: (1) Foundational `T004`–`T007` + `_resolve.py`, (2) Stage subpackages `T008`–`T015` + `T019`–`T022`, (3) Orchestrators `T016`–`T017`, (4) Guard suites `T018`, `T023`–`T027`.
