# Tasks: Cross-Encoder Reranking

**Input**: Design documents from `/specs/007-reranking/`
**Prerequisites**: [plan.md](plan.md) (required), [spec.md](spec.md) (required for user stories), [research.md](research.md), [data-model.md](data-model.md), [contracts/reranker.md](contracts/reranker.md), [quickstart.md](quickstart.md)

**Tests**: Explicit unit, integration, contract, lazy-import/purity, API stability, CLI/evaluation, and Release Gate #1 (`@pytest.mark.reverse`) test tasks ARE included as required by `FR-010`, `FR-007`, and repository constitution `v1.2.2`. All automated tests run offline with zero network requests.

## Constitution Check

All planned work satisfies `.specify/memory/constitution.md` (`v1.2.2`, Principles I–VII and Quality Gates) as verified in [plan.md](plan.md#constitution-check): opt-in `rerank=False` scope isolation, `33`-symbol top-level `__all__`, strict CLI-only TOML configuration, child-first parent expansion, Release Gate #1 (`@pytest.mark.reverse`), local-first CPU execution, canonical `types.py` schemas, and mandatory `100%` test pass rate.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., `US1`, `US2`, `US3`)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/docpipe_maestro/`, `tests/`, `docs/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish baseline green state, isolated `[rerank]` packaging metadata, mypy stub overrides, and reproducible lockfile synchronization

- [X] T001 Verify pre-change baseline passes cleanly across `tests/` by running `LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v`
- [X] T002 Add optional extra `rerank = ["sentence-transformers>=3.0.0"]` under `[project.optional-dependencies]` (keeping `[project.dependencies]` and parser-only `[project.optional-dependencies].all` unchanged) and add `"sentence_transformers.*"` (`ignore_missing_imports = true`) under `[[tool.mypy.overrides]]` in `pyproject.toml`
- [X] T003 Regenerate lockfile and sync optional `[rerank]` environment (`uv sync --all-extras --group dev`) updating `uv.lock`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core constants, conditional evaluation config schema, lazy `RERANKERS` strategy registration, `CrossEncoderReranker`, and shared preflight validation required before any user story can execute

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Add static constants `DEFAULT_RERANK_TOP_N = 20` (`int`, default pre-rerank candidate child pool limit `>= 1`) and `DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"` (`str`) in `src/docpipe_maestro/config.py`
- [X] T005 [P] Refactor `EvalConfig` into `_EvalConfigRequired(TypedDict)` preserving all 10 required baseline keys (`collection`, `persist_dir`, `embed_model`, `k_values`, `expand_parent`, `follow_crossrefs`, `searcher`, `embedder`, `store`, `threshold`) plus `class EvalConfig(_EvalConfigRequired, total=False)` adding optional `"rerank": bool`, `"reranker": str`, and `"rerank_top_n": int` in `src/docpipe_maestro/types.py`
- [X] T006 Implement `CrossEncoderReranker` (`name: str = "cross_encoder"`) registered via `@RERANKERS.register("cross_encoder")` in `src/docpipe_maestro/query/reranker/cross_encoder.py` (depends on T004): implement `validate_available(cls)` checking `sys.modules` and `importlib.util.find_spec("sentence_transformers")` without importing `sentence_transformers` or `torch` and raising `MissingExtraError("Cross-encoder reranking requires the 'rerank' extra: pip install 'docpipe-maestro[rerank]'")` when absent; implement `_instantiate_cross_encoder(model_name)` invoking `CrossEncoderReranker.validate_available()`, lazily importing `from sentence_transformers import CrossEncoder`, and returning `CrossEncoder(model_name)`; implement `_load_cross_encoder(model_name)` caching instances per `model_name` in `_MODEL_CACHE: dict[str, Any]` guarded by `threading.Lock()` and delegating cold creation to `_instantiate_cross_encoder(model_name)`; implement `rerank(query, chunks, *, top_k)` short-circuiting empty/`top_k <= 0` inputs to `[]` cleanly, calling `_load_cross_encoder(self._model_name)` when non-empty (so direct `.rerank()` callers without `[rerank]` also raise `MissingExtraError`), evaluating `[(query, c.text) for c in chunks]` in one batch, rejecting non-finite logits (`math.isnan` / `math.isinf`) or prediction length mismatch with `DocpipeError`, normalizing finite logits monotonically onto `[0.0, 1.0]` via overflow-safe sigmoid clamped to `[0.0, 1.0]`, returning non-mutating copies via `dataclasses.replace(chunk, score=norm_score)` compatible with `@dataclass(slots=True)`, and sorting descending `[:top_k]` with relative tie order preserved
- [X] T007 Implement lazy registry wiring and shared validation in `src/docpipe_maestro/query/reranker/__init__.py` (depends on T004, T006): register `RERANKERS.register_lazy("cross_encoder", "docpipe_maestro.query.reranker.cross_encoder", "CrossEncoderReranker")`, expose `"CrossEncoderReranker"` lazily via module `__getattr__`, set `__all__ = ["RERANKERS", "CrossEncoderReranker", "register_reranker", "validate_rerank_options"]`, and implement `validate_rerank_options(*, rerank: bool, reranker: str, rerank_top_n: int) -> type[Reranker] | None` rejecting `isinstance(rerank_top_n, bool)` or `not isinstance(rerank_top_n, int)` or `rerank_top_n <= 0` with `ValueError("rerank_top_n must be a positive integer >= 1")`, returning `None` when `rerank` is `False`, and resolving `RERANKERS.resolve(reranker)` plus optional availability hook (`validate_fn = getattr(reranker_cls, "validate_available", None); if callable(validate_fn): validate_fn()`) when `rerank` is `True` (preserving custom `@register_reranker` strategies without that hook)

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Opt-In Local Child-First Reranking in Retrieval (Priority: P1) 🎯 MVP

**Goal**: Enable opt-in child-first local reranking in `retrieve()` across `default` and `fts5_hybrid` search with expansion-aware candidate fetching, pre-rerank score thresholds, `[0.0, 1.0]` score normalization, parent deduplication ranked by `max(child.score)`, `expand_parent=False` child ranking, cached model reuse, and exception preservation (`@pytest.mark.reverse`)

**Independent Test**: Run `uv run pytest tests/test_reranker.py tests/test_reverse_safety.py tests/test_api_stability.py tests/test_retriever.py tests/test_hybrid_search.py -v` offline with mocked `_instantiate_cross_encoder` and deterministic test rerankers

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST and verify retrieval/API/reverse tests FAIL before `T012` implements `retrieve()` reranking**

- [X] T008 [P] [US1] Write offline `CrossEncoderReranker` unit and caching tests in `tests/test_reranker.py` verifying `isinstance(CrossEncoderReranker(), Reranker)`, `RERANKERS.resolve("cross_encoder")`, `(query, chunk.text)` batch pair formatting, overflow-safe sigmoid clamping onto `[0.0, 1.0]` across extreme positive/negative logits, `DocpipeError` on `math.isnan`/`math.isinf`/length mismatch, `@dataclass(slots=True)` immutability via `dataclasses.replace`, stable tie ordering, empty/`top_k <= 0` short-circuit, and thread-safe `_MODEL_CACHE` reuse plus per-`model_name` isolation (`"model-a"` vs `"model-b"`) via mocked `_instantiate_cross_encoder`
- [X] T009 [US1] Add child-first retrieval integration tests in `tests/test_reranker.py` (depends on T008) covering `default` and `fts5_hybrid` search with active `doc_version` filtering, expansion-aware pool depth `max(rerank_top_n, top_k * 3)` when `expand_parent=True` and `max(rerank_top_n, top_k)` when `expand_parent=False`, pre-rerank `threshold` filtering (including zero-survivor `[]` return without calling `rerank()`, and no post-rerank bi-encoder threshold re-filtering), valid-env `retrieve(..., rerank=True, top_k=0)` returning `[]` without invoking `_load_cross_encoder`, custom `@register_reranker` strategy conforming solely to `Reranker` Protocol without `validate_available()`, parent deduplication ordered by `max(child.score)` passing `top_k=len(child_matches)` before expansion, `expand_parent=False` top-`k` child output, `_enrich_crossdoc_references` preservation, and `rerank=False` identity
- [X] T010 [P] [US1] Add rerank-enabled Release Gate #1 (`@pytest.mark.reverse`) exception-preservation tests across all `EXCEPTION_CASES` on `tests/fixtures/policy_corpus` using a deterministic registered test reranker in `tests/test_reverse_safety.py`
- [X] T011 [P] [US1] Update expected `root.retrieve` parameter contract (`_params_info`) with appended keyword-only defaults `rerank: bool = False`, `reranker: str = "cross_encoder"`, `rerank_top_n: int = 20` and assert exact `33`-symbol `docpipe_maestro.__all__` invariance in `tests/test_api_stability.py`

### Implementation for User Story 1

- [X] T012 [US1] Extend `retrieve()` in `src/docpipe_maestro/query/retriever.py` (depends on T008–T011): append keyword-only `rerank: bool = False`, `reranker: str = "cross_encoder"`, and `rerank_top_n: int = DEFAULT_RERANK_TOP_N` after `searcher`; run `validate_rerank_options(rerank=rerank, reranker=reranker, rerank_top_n=rerank_top_n)` upfront alongside `EMBEDDERS`/`STORES`/`SEARCHERS` resolution before manifest/empty-source/`top_k <= 0` early returns; when `rerank=True`, compute `child_top_k = max(rerank_top_n, top_k * 3) if expand_parent else max(rerank_top_n, top_k)`, filter pre-rerank `threshold`, return `[]` if zero children survive, instantiate `reranker_cls()`, execute `child_matches = reranker_inst.rerank(question, child_matches, top_k=len(child_matches) if expand_parent else top_k)`, and proceed into existing parent `max(child.score)` aggregation and `_enrich_crossdoc_references`
- [X] T013 [US1] Validate User Story 1 independently against `tests/test_reranker.py`, `tests/test_reverse_safety.py`, `tests/test_api_stability.py`, `tests/test_retriever.py`, and `tests/test_hybrid_search.py` by running `uv run pytest tests/test_reranker.py tests/test_reverse_safety.py tests/test_api_stability.py tests/test_retriever.py tests/test_hybrid_search.py -v`

**Checkpoint**: At this point, User Story 1 (opt-in local child-first reranking in `retrieve()`) is fully functional, exception-safe, and API-compatible

---

## Phase 4: User Story 2 - Lean Default Install & Fail-Fast Missing Dependency Diagnostics (Priority: P2)

**Goal**: Keep package import, CLI startup, and non-reranked workflows free of `sentence_transformers`/`torch` imports while exposing `--rerank`/`--no-rerank`, `--reranker`, and `--rerank-top-n` (plus TOML defaults) on `query` and `ask` with fail-fast single-line diagnostics

**Independent Test**: Run `uv run pytest tests/test_library_purity.py tests/test_reranker.py tests/test_cli.py -v` verifying zero `sentence_transformers`/`torch` startup imports and exit-`1` single-line diagnostics for missing `[rerank]`, unknown `reranker`, and invalid `rerank_top_n <= 0`

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST and verify CLI/purity/diagnostic tests FAIL before `T017` implements CLI & config wiring**

- [X] T014 [P] [US2] Extend `test_top_level_register_exports_and_cli_avoid_heavy_deps` and AST checks in `tests/test_library_purity.py` verifying `'sentence_transformers'` and `'torch'` are absent from `sys.modules` on `docpipe_maestro` import, `register_reranker` access, `docpipe_maestro.query.reranker` import, and `cli.build_parser()`, and ensuring `query/` has zero `tomli`/`dotenv`/`ingest` imports
- [X] T015 [P] [US2] Add mocked preflight failure tests in `tests/test_reranker.py` using `monkeypatch` on `sys.modules`/`importlib.util.find_spec` to verify `MissingExtraError` guidance (`pip install 'docpipe-maestro[rerank]'`) without importing `torch` (both via `retrieve(..., rerank=True)` and direct non-empty `CrossEncoderReranker().rerank(...)`), `RegistryError` on unregistered `reranker`, and `ValueError("rerank_top_n must be a positive integer >= 1")` on `rerank_top_n <= 0`, `bool`, or non-`int` trigger upfront before collection/store access (including empty collections and `top_k <= 0`)
- [X] T016 [P] [US2] Add CLI and TOML config tests for `query` and `ask` in `tests/test_cli.py` verifying `--rerank`/`--no-rerank` (`BooleanOptionalAction`), `--reranker`, `--rerank-top-n`, precedence `CLI > TOML > built-in defaults` (`False`, `"cross_encoder"`, `20`), TOML type check (`DocpipeError` on bad type/bool) in `build_parser()` vs runtime `rerank_top_n <= 0` rejection on `query`/`ask` without breaking unrelated commands (`status`/`ingest`/`--help`), single-line `Error: ...` on `stderr` with exit status `1` on `MissingExtraError`/`RegistryError`/`ValueError`, and unchanged execution when `rerank=False`

### Implementation for User Story 2

- [X] T017 [US2] Add TOML defaults (`rerank` via `_cfg_bool(..., False)`, `reranker` via `_cfg_str(..., "cross_encoder")`, `rerank_top_n` via `_cfg_int(..., DEFAULT_RERANK_TOP_N)` keeping integer-type checks only in `build_parser()` so `status`/`ingest`/`--help` remain unaffected), attach shared `--rerank`/`--no-rerank` (`argparse.BooleanOptionalAction`), `--reranker`, and `--rerank-top-n` flags to `p_query` and `p_ask`, and forward `rerank`, `reranker`, and `rerank_top_n` cleanly into `query` execution (`retrieve`) and `_handle_ask` (where `validate_rerank_options` enforces `rerank_top_n >= 1`) in `src/docpipe_maestro/cli.py` (depends on T014–T016)
- [X] T018 [US2] Validate User Story 2 independently against `tests/test_library_purity.py`, `tests/test_reranker.py`, and `tests/test_cli.py` by running `LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest tests/test_library_purity.py tests/test_reranker.py tests/test_cli.py -v`

**Checkpoint**: User Stories 1 AND 2 both work independently with lean startup and actionable diagnostics

---

## Phase 5: User Story 3 - Evaluation Integration & Baseline-Gated Acceptance (Priority: P3)

**Goal**: Integrate opt-in reranking parameters cleanly into `evaluate()` and `docpipe-maestro eval`, keeping persisted storage strictly read-only (`0`-byte mutation) and emitting `"rerank"`, `"reranker"`, and `"rerank_top_n"` inside `EvalReport["config"]` ONLY when `rerank=True` so committed `docs/eval-baseline.json` stays byte-unchanged

**Independent Test**: Run `LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest tests/test_eval.py tests/test_cli.py -v` and verify conditional `EvalConfig` keys, `docs/eval-baseline.json` replay equality, preflight validation, and zero storage drift

### Tests for User Story 3 ⚠️

> **NOTE: Write these tests FIRST and verify eval/CLI tests FAIL before `T021`–`T022` implement harness & CLI forwarding**

- [X] T019 [P] [US3] Add read-only evaluation reranking tests in `tests/test_eval.py` covering `evaluate(..., rerank=True, reranker=..., rerank_top_n=...)` across `default` and `fts5_hybrid`, conditional `EvalConfig` schema (`"rerank": True`, `"reranker"`, `"rerank_top_n"` present ONLY when `rerank=True` and omitted completely when `rerank=False`), existing `test_curated_policy_suite_and_baseline_replay` invariance against `docs/eval-baseline.json`, preflight `MissingExtraError`/`RegistryError`/`ValueError` rejection before manifest/store access, and `0`-byte persistence drift across manifests, ChromaDB, and SQLite FTS5 files
- [X] T020 [P] [US3] Add CLI `eval` rerank tests in `tests/test_cli.py` covering `--rerank`/`--no-rerank`, `--reranker`, `--rerank-top-n`, TOML override precedence on `eval`, conditional `--json` output `"config"` keys, conditional `_format_eval_text` header `| Reranker: <name> (top_n=<n>)` presence only when `rerank=True`, and exit code `1` single-line `stderr` diagnostics

### Implementation for User Story 3

- [X] T021 [US3] Extend `_preflight_check` and `evaluate()` in `src/docpipe_maestro/eval/harness.py` (depends on T019) to accept keyword-only `rerank: bool = False`, `reranker: str = "cross_encoder"`, and `rerank_top_n: int = DEFAULT_RERANK_TOP_N` before `**retrieve_kwargs`, invoke `validate_rerank_options` upfront before manifest/store access, forward options into read-only `retrieve(...)`, and populate `"rerank": True`, `"reranker": reranker`, and `"rerank_top_n": rerank_top_n` in `report["config"]` strictly when `rerank=True`
- [X] T022 [US3] Attach shared rerank CLI options to `p_eval`, forward `rerank`, `reranker`, and `rerank_top_n` cleanly inside `_handle_eval`, and append `| Reranker: {cfg['reranker']} (top_n={cfg['rerank_top_n']})` in `_format_eval_text` strictly when `cfg.get("rerank")` is `True` in `src/docpipe_maestro/cli.py` (depends on T020, T021)
- [X] T023 [US3] Validate User Story 3 independently against `tests/test_eval.py`, `tests/test_cli.py`, and `docs/eval-baseline.json` by running `LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest tests/test_eval.py tests/test_cli.py -v`

**Checkpoint**: All user stories (`US1`, `US2`, `US3`) are independently implemented and verified offline

---

## Phase 6: Polish, Live Benchmark Gate & Cross-Cutting Verification

**Purpose**: Execute the empirical Q1 benchmark/revert gate first, then conditionally publish user/API/architecture docs, validate quickstart checks, and pass all CI quality gates

- [X] T024 Execute live local Ollama (`nomic-embed-text`) + `BAAI/bge-reranker-base` benchmark across `tests/fixtures/eval_policy_corpus.json` (`default --no-rerank`, `default --rerank`, `fts5_hybrid --no-rerank`, `fts5_hybrid --rerank`) with SHA-256 storage-drift check per `specs/007-reranking/quickstart.md`, enforce strict per-mode Clarification Q1 gate (retain only if **both** `default` and `fts5_hybrid` individually achieve `Precision@5 > baseline` **or** (`MRR > baseline` and `Precision@1 > baseline` and `Precision@5 >= baseline`); cleanly revert rerank implementation and rerank-specific test changes if either mode fails), and record full live metric table and retention/revert outcome in `docs/eval-baseline.md`
- [X] T025 [P] (Conditional: run only if `T024` retains reranking) Document `docpipe-maestro[rerank]` optional extra (distinct from parser-only `[all]`) and CLI/library examples in `README.md` (depends on T024)
- [X] T026 [P] (Conditional: run only if `T024` retains reranking) Document `--rerank`, `--no-rerank`, `--reranker`, `--rerank-top-n`, and TOML defaults (`rerank`, `reranker`, `rerank_top_n`) across `query`, `ask`, and `eval` in `docs/cli-reference.md` (depends on T024)
- [X] T027 [P] (Conditional: run only if `T024` retains reranking) Document `retrieve(..., rerank=..., reranker=..., rerank_top_n=...)`, `evaluate(..., rerank=...)`, `CrossEncoderReranker`, and `@register_reranker` contract in `docs/api-reference.md` (depends on T024)
- [X] T028 [P] (Conditional: run only if `T024` retains reranking) Update Phase 2 query pipeline diagram and child-first reranker stage dataflow (`007-reranking`) in `docs/architecture.md` (depends on T024)
- [X] T029 Record `feat(rerank)` delivery summary (when retained by `T024`) or empirical Q1 revert summary in `CHANGELOG.md` (depends on T024)
- [X] T030 Run offline CI checks from `specs/007-reranking/quickstart.md` (plus `--rerank` & live drift checks when retained by `T024`) confirming zero unintended diffs in `docs/eval-baseline.json` and `0` byte storage mutations (depends on T024–T029)
- [X] T031 **REQUIRED**: Run full CI quality suite across `src/` and `tests/` after final edits (`uv run ruff format --check . && uv run ruff check . && uv run ruff check --select S src/ && uv run mypy src tests && LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -m reverse -v && LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov`), confirming `0` failures, `0` warnings, and `>= 80%` branch coverage

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — starts immediately (`T001` -> `T002` -> `T003`)
- **Foundational (Phase 2)**: Depends on Setup completion (`T004` and `T005` parallel -> `T006` -> `T007`) — **BLOCKS** all user stories (`US1`, `US2`, `US3`)
- **User Story 1 (Phase 3 - P1 🎯 MVP)**: Depends on Foundational (`T007`); delivers core child-first `retrieve()` reranking
- **User Story 2 (Phase 4 - P2)**: Depends on Foundational (`T007`); touches `tests/test_library_purity.py`, `tests/test_cli.py`, `src/docpipe_maestro/cli.py`, and extends `tests/test_reranker.py` (can run in parallel with US1 except `tests/test_reranker.py` coordination, or immediately after US1 MVP)
- **User Story 3 (Phase 5 - P3)**: Depends on Foundational (`T007`) and User Story 1 (`T012` for `retrieve()` rerank forwarding in `evaluate()`); coordinates with US2 on `src/docpipe_maestro/cli.py` and `tests/test_cli.py`
- **Polish & Governance Gate (Phase 6)**: Depends on completion of `US1`, `US2`, and `US3`; `T024` (live Q1 benchmark/revert gate) runs FIRST, then `T025`–`T029` run (`T025`–`T028` conditionally if retained), followed by `T030` and `T031`

### User Story Dependencies

- **User Story 1 (P1)**: Independent once Foundational (`Phase 2`) completes — no dependency on `US2` or `US3`
- **User Story 2 (P2)**: Independent once Foundational (`Phase 2`) completes — CLI/startup diagnostics work standalone before `eval` integration
- **User Story 3 (P3)**: Uses `retrieve(..., rerank=..., reranker=..., rerank_top_n=...)` (`US1`) and shared CLI flag builder (`US2`) to wire `evaluate()` and `docpipe-maestro eval` cleanly

### Within Each User Story

- Tests MUST be written FIRST and verified failing prior to implementing production changes
- Foundational shared config/types/reranker registry -> `retrieve()` / `evaluate()` service logic -> CLI flag/output formatting -> story verification checkpoint

### Parallel Opportunities

- **Foundational**: `T004` (`src/docpipe_maestro/config.py`) and `T005` (`src/docpipe_maestro/types.py`) modify disjoint files and run in parallel
- **User Story 1**: Initial test authoring `T008` (`tests/test_reranker.py`), `T010` (`tests/test_reverse_safety.py`), and `T011` (`tests/test_api_stability.py`) modify separate files and run in parallel before `T009` (`tests/test_reranker.py`) and `T012` (`src/docpipe_maestro/query/retriever.py`)
- **User Story 2**: `T014` (`tests/test_library_purity.py`), `T015` (`tests/test_reranker.py`), and `T016` (`tests/test_cli.py`) touch distinct test files and run in parallel before `T017` (`src/docpipe_maestro/cli.py`)
- **User Story 3**: `T019` (`tests/test_eval.py`) and `T020` (`tests/test_cli.py`) touch distinct files and run in parallel before `T021` (`src/docpipe_maestro/eval/harness.py`) and `T022` (`src/docpipe_maestro/cli.py`)
- **Polish**: Once `T024` retains reranking, `T025` (`README.md`), `T026` (`docs/cli-reference.md`), `T027` (`docs/api-reference.md`), and `T028` (`docs/architecture.md`) modify independent documentation files and run in parallel alongside `T029` (`CHANGELOG.md`)

---

## Parallel Example: User Story 1

```bash
# Launch disjoint User Story 1 test files in parallel:
Task: "T008 [P] [US1] Write offline CrossEncoderReranker unit and caching tests in tests/test_reranker.py"
Task: "T010 [P] [US1] Add rerank-enabled Release Gate #1 tests in tests/test_reverse_safety.py"
Task: "T011 [P] [US1] Update retrieve() signature expectations in tests/test_api_stability.py"
```

## Parallel Example: User Story 2

```bash
# Launch disjoint User Story 2 test files in parallel:
Task: "T014 [P] [US2] Extend lazy-import assertions in tests/test_library_purity.py"
Task: "T015 [P] [US2] Add mocked MissingExtraError/RegistryError/ValueError preflight tests in tests/test_reranker.py"
Task: "T016 [P] [US2] Add query/ask CLI & TOML precedence tests in tests/test_cli.py"
```

## Parallel Example: User Story 3

```bash
# Launch disjoint User Story 3 test files in parallel:
Task: "T019 [P] [US3] Add read-only evaluation & conditional EvalConfig tests in tests/test_eval.py"
Task: "T020 [P] [US3] Add eval CLI flag & text header formatting tests in tests/test_cli.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (`T001`–`T003`)
2. Complete Phase 2: Foundational (`T004`–`T007`) — CRITICAL blocking foundation
3. Complete Phase 3: User Story 1 (`T008`–`T013`)
4. **STOP and VALIDATE**: Confirm offline reranked retrieval passes unit, parent-aggregation, API stability, and `@pytest.mark.reverse` checks before advancing

### Incremental Delivery

1. Setup + Foundational (`T001`–`T007`) -> Foundation & registry contract ready
2. Add User Story 1 (`T008`–`T013`) -> Child-first programmatic retrieval reranking working & verified (MVP!)
3. Add User Story 2 (`T014`–`T018`) -> Lean install isolation, TOML/CLI `query`+`ask` flags & fail-fast errors verified
4. Add User Story 3 (`T019`–`T023`) -> Read-only `eval` harness & `docpipe-maestro eval` forwarding verified
5. Execute Phase 6 (`T024`–`T031`) -> Live Ollama + `BAAI/bge-reranker-base` benchmark enforces Q1 retain-vs-revert gate (`T024`), documentation matches final outcome (`T025`–`T029`), and full CI suite passes cleanly (`T030`–`T031`)

### Parallel Team Strategy

1. Single maintainer or paired team completes Setup + Foundational (`T001`–`T007`) together
2. Once `T007` passes:
   - Track A: `US1` retrieval & reverse safety (`T008`–`T013`)
   - Track B: `US2` startup purity & `query`/`ask` CLI/diagnostics (`T014`–`T018`, writing different files until converging cleanly on `cli.py`)
3. Merge Track A + Track B -> complete `US3` `eval` integration (`T019`–`T023`) and Phase 6 live Q1 gate (`T024`–`T031`)

---

## Notes

- `[P]` tasks operate on independent files with zero shared incomplete dependencies
- Never download Hugging Face model weights during automated pytest runs (`tests/test_reranker.py`, `tests/test_eval.py`, `tests/test_cli.py`); reserve real `BAAI/bge-reranker-base` weights exclusively for Phase 6 live benchmark (`T024`)
- Preserve exact baseline schemas: `docs/eval-baseline.json` must remain untouched (`0`-byte diff) across `US1`–`US3` and non-reranked evaluation runs
- Commit logically after each phase or verified user story increment before executing `T024` so any Q1 revert remains clean and atomic
