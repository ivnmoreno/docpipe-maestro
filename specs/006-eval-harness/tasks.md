---

description: "Task list for Retrieval Evaluation Harness (006-eval-harness)"
---

# Tasks: Retrieval Evaluation Harness

**Input**: Design documents from `/specs/006-eval-harness/`
**Prerequisites**: [plan.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/plan.md), [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/spec.md), [research.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/research.md), [data-model.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/data-model.md), [contracts/eval-harness.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/contracts/eval-harness.md), [quickstart.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/quickstart.md)

**Tests**: Explicit unit, integration, contract, CLI, API stability, AST purity, and full-suite regression tests are included per `FR-009` and `constitution.md` (`v1.2.2`). Top-level 33-symbol `docpipe_maestro.__all__`, `tests/fixtures/policy_corpus/`, and `tests/test_reverse_safety.py` MUST remain untouched.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps to `US1` (P1 Reproducible Offline Retrieval Measurement), `US2` (P2 Read-Only Command-Line Benchmark Workflow), `US3` (P3 Curated Policy Evaluation Suite & Recorded Baselines)
- Every task cites exact repository file paths

## Path Conventions

- **Library & CLI**: `src/docpipe_maestro/`
- **Tests & Packaged Fixtures**: `tests/`, `tests/fixtures/`
- **Docs & Baselines**: `docs/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify clean repository baseline tooling and scaffold the `docpipe_maestro.eval` subpackage without altering the frozen 33-symbol top-level `__all__`.

- [ ] T001 Verify baseline repository checks pass (`uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run pytest -m reverse -v`) and inspect `tests/fixtures/policy_corpus/` and `tests/test_reverse_safety.py` baseline status in repository root
- [ ] T002 Create package initializer scaffold in `src/docpipe_maestro/eval/__init__.py` while keeping top-level 33-symbol exports untouched in `src/docpipe_maestro/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define canonical evaluation `TypedDict` schemas once in `types.py` (Constitution Principle VII) and implement pure zero-I/O ranking metric primitives before any user story begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T003 Define canonical evaluation `TypedDict` shapes in `src/docpipe_maestro/types.py`: `_EvalQueryRequired(TypedDict)` (`question: str`, `relevant_ids: list[str]`) + `EvalQuery(_EvalQueryRequired, total=False)` (`notes: str`), `_EvalFixtureRequired(TypedDict)` (`queries: list[EvalQuery]`) + `EvalFixture(_EvalFixtureRequired, total=False)` (`collection: str`, `profile: str`), `EvalConfig(TypedDict)` (`collection`, `persist_dir`, `embed_model`, `k_values`, `expand_parent`, `follow_crossrefs`, `searcher`, `embedder`, `store`, `threshold`), `PerQueryResult(TypedDict)` (`question`, `notes`, `relevant_ids`, `retrieved_ids`, `retrieved_scores`, `precision_at_k: dict[str, float]`, `recall_at_k: dict[str, float]`, `reciprocal_rank: float`), `EvalMetricsSummary(TypedDict)` (`num_queries: int`, `mrr: float`, `precision_at_k: dict[str, float]`, `recall_at_k: dict[str, float]`), and `EvalReport(TypedDict)` (`config: EvalConfig`, `aggregate: EvalMetricsSummary`, `per_query: list[PerQueryResult]`)
- [ ] T004 [P] Implement pure zero-I/O ranking metrics and cutoff helper in `src/docpipe_maestro/eval/metrics.py`: implement `precision_at_k(retrieved_ids, relevant_ids, k) -> float`, `recall_at_k(retrieved_ids, relevant_ids, k) -> float`, `reciprocal_rank(retrieved_ids, relevant_ids) -> float`, and `normalize_k_values(k_values) -> tuple[int, ...]`; reject `bool` or non-positive `k <= 0` and empty `k_values` with `ValueError`, deduplicate and sort positive cutoffs ascending (`[10, 3, 3]` -> `(3, 10)`), deduplicate `relevant_ids` into `frozenset`, return `0.0` safely on empty `retrieved_ids` or empty `relevant_set`, clamp `Precision@K` and `Recall@K` cleanly in `[0.0, 1.0]` using `len(set(retrieved_ids[:k]) & relevant_set) / k` and standard IR `Recall@K` denominator `len(relevant_set)`, and avoid all third-party/config/I/O imports

**Checkpoint**: Canonical schemas (`src/docpipe_maestro/types.py`) and pure metric primitives (`src/docpipe_maestro/eval/metrics.py`) are ready for User Stories 1–3.

---

## Phase 3: User Story 1 - Reproducible Offline Retrieval Measurement (Priority: P1) 🎯 MVP

**Goal**: Provide a typed, deterministic, strictly read-only evaluation runner (`load_eval_fixture`, `evaluate`, `DEFAULT_EVAL_K_VALUES = (1, 3, 5, 10)`) and clean `docpipe_maestro.eval` API re-exports.

**Independent Test**: Run US1 unit and integration tests in `tests/test_eval.py` against a seeded offline collection (`tmp_persist_dir` + `mock_litellm_offline`) and confirm exact metric arithmetic, bit-for-bit identical repeated runs, zero persistence byte/file mutations across both `default` and `fts5_hybrid`, strict fixture validation errors, and zero store creation on missing/empty collections.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before runner implementation**

- [ ] T005 [P] [US1] Create US1 unit and offline integration tests in `tests/test_eval.py` covering `precision_at_k`, `recall_at_k` (`|relevant|` denominator), `reciprocal_rank`, `normalize_k_values` (empty inputs, `bool`/`k <= 0` `ValueError`, duplicate IDs, `[10, 3, 3]` -> `(3, 10)` normalization), `load_eval_fixture` errors (missing file, malformed JSON, non-object root, empty `queries`, blank `question`, empty/blank `relevant_ids`, invalid metadata types), missing/empty collection `DocpipeError` leaving `tmp_persist_dir` untouched, `ModelMismatchError`, `RegistryError` for unknown stage selectors, invalid `threshold`, collection precedence (`explicit > fixture > default`), `expand_parent` toggle, bit-for-bit consecutive run repeatability, and pre/post SHA-256 `0`-byte drift verification across `searcher="default"` and `searcher="fts5_hybrid"`

### Implementation for User Story 1

- [ ] T006 [US1] Implement `DEFAULT_EVAL_K_VALUES = (1, 3, 5, 10)`, `load_eval_fixture(fixture: str | Path | EvalFixture) -> EvalFixture`, and `evaluate(...) -> EvalReport` in `src/docpipe_maestro/eval/harness.py` (depends on `T003`, `T004`): re-export canonical `TypedDict`s from `docpipe_maestro.types`; normalize omitted `collection`/`profile`/`notes` to `""` while validating non-empty `queries`, non-blank `question`, and non-empty non-blank `relevant_ids`; validate `k_values` via `normalize_k_values` and finite `threshold` in `[0.0, 1.0]`; resolve `effective_collection` (`explicit collection > non-empty fixture collection > DEFAULT_COLLECTION`) via `validate_collection_name`; validate non-default `EMBEDDERS`/`STORES`/`SEARCHERS` keys upfront; verify pre-flight state strictly in order without touching `ChromaStore` (`manifest_path(...).exists()` -> `DocpipeError` if missing -> `load_manifest` -> `check_model_lock` -> `not manifest.sources` `DocpipeError`); invoke `retrieve(..., top_k=max(norm_k), ...)` once per query cleanly without eager heavy imports or any `tomli`/`dotenv`/`ingest.*` imports; compute exact `EvalReport` (`config`, `aggregate`, `per_query`) with string cutoff keys (`dict[str, float]`)
- [ ] T007 [US1] Populate clean public subpackage exports and `__all__` in `src/docpipe_maestro/eval/__init__.py` re-exporting `DEFAULT_EVAL_K_VALUES`, `evaluate`, `load_eval_fixture`, `precision_at_k`, `recall_at_k`, `reciprocal_rank`, `normalize_k_values`, `EvalQuery`, `EvalFixture`, `EvalConfig`, `PerQueryResult`, `EvalMetricsSummary`, and `EvalReport` without eager heavy backend imports (depends on `T004`, `T006`)
- [ ] T008 [US1] Run US1 test verification (`uv run pytest tests/test_eval.py tests/test_api_stability.py tests/test_library_purity.py -v`) and confirm independent pass for User Story 1, 33-symbol API stability, and AST library purity (depends on `T005`, `T006`, `T007`)

**Checkpoint**: User Story 1 (MVP) is complete and independently testable — `docpipe_maestro.eval` produces deterministic, strictly read-only evaluation reports.

---

## Phase 4: User Story 2 - Read-Only Command-Line Benchmark Workflow (Priority: P2)

**Goal**: Expose the read-only `docpipe-maestro eval` subcommand supporting global flags (`--config`, `--no-config`, `--collection`, `--persist-dir`), `Q3` collection precedence, `--k`, `--embed-model`, `--searcher`, `--expand-parent`/`--no-expand-parent`, `--json` / human summary output, lazy startup imports, and clean single-line `Error:` exit `1` behavior.

**Independent Test**: Execute CLI `eval` tests in `tests/test_cli.py` verifying `--help` / `build_parser()` avoids eager `chromadb`/`litellm`/`eval.harness` imports, test `--json` and human-readable outputs (`exit 0`), verify all 4 precedence tiers for `--collection` (both before and after `eval`), verify `--k` multi-value/repeated/duplicate/invalid handling, and verify single-line `stderr` + `exit 1` on missing/mismatched/invalid inputs.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before CLI handler implementation**

- [ ] T009 [P] [US2] Add CLI `eval` test suite to `tests/test_cli.py` covering `eval --json` (`EvalReport` schema, `exit 0`), default human-readable table summary (`Collection`, `Model`, `Searcher`, `Expand Parent`, `Queries`, `MRR`, `K | Precision@K | Recall@K`, per-query lines, `exit 0`), collection resolution precedence (`explicit --collection` before/after `eval` overrides fixture and `docpipe.toml`; omitted `--collection` resolves fixture `collection` over `docpipe.toml`; empty fixture `collection` falls back to `docpipe.toml` then `"default"`), `--k 5` / `--k 1 3 5` / `--k 1 --k 3` / `--k 10 3 --k 3` normalization, `--searcher fts5_hybrid`, `--no-expand-parent`, `--embed-model`, single-line `Error:` on `stderr` + `exit 1` (missing fixture, malformed fixture, `--k 0`, missing/empty collection, model mismatch, unknown `--searcher`), and `build_parser()` lazy startup keeping `chromadb`/`litellm` unloaded

### Implementation for User Story 2

- [ ] T010 [US2] Add `eval` subcommand to `src/docpipe_maestro/cli.py` (depends on `T006`, `T007`): implement `_StoreExplicitCollection(argparse.Action)` recording `namespace._collection_explicit = True` on both top-level and `common` `--collection` options (`parser.set_defaults(_collection_explicit=False)`); add `p_eval` (`--fixture` required, `--k` with `action="extend"`, `nargs="+"`, `type=int`, `default=None`, `dest="k_values"`, `--embed-model`, `--searcher`, `--expand-parent` `BooleanOptionalAction` default `True`, `--json` `store_true`); capture `cfg_collection = _cfg_opt_str(cfg, "collection")` cleanly in `main()` and pass to `_handle_eval`; lazy-import `DEFAULT_EVAL_K_VALUES`, `load_eval_fixture`, and `evaluate` inside `_handle_eval`, load fixture once, resolve collection strictly as `args.collection` (when `_collection_explicit`) `>` non-empty `loaded_fixture["collection"]` `>` `cfg_collection` `>` `DEFAULT_COLLECTION`, and pass `loaded_fixture` and resolved `collection` into `evaluate(...)`; add `_format_eval_text(report)` for readable terminal summary and emit `json.dumps(report, indent=2)` under `--json`, returning `0` on valid measurement runs with errors routed to existing `main()` `except (DocpipeError, ValueError, TypeError)` `stderr` + `exit 1` handler (no threshold exit-gate options)
- [ ] T011 [US2] Run CLI & startup verification (`uv run pytest tests/test_cli.py tests/test_library_purity.py -v`) and subprocess `uv run docpipe-maestro eval --help` sanity check (depends on `T009`, `T010`)

**Checkpoint**: User Stories 1 and 2 work independently — CLI `eval` integrates seamlessly with existing `cli.py` flags, TOML discovery, lazy startup, and error conventions.

---

## Phase 5: User Story 3 - Curated Policy Evaluation Suite & Recorded Baselines (Priority: P3)

**Goal**: Provide a self-contained curated 20+ query policy benchmark (`tests/fixtures/eval_corpus/` + untouched `tests/fixtures/policy_corpus/` + `tests/fixtures/eval_policy_corpus.json`) with `>= 3` verified rule-and-exception parent-section queries, commit offline side-by-side baseline snapshots (`docs/eval-baseline.json`, `docs/eval-baseline.md`), and verify exact automated replay in `tests/test_eval.py`.

**Independent Test**: Load `tests/fixtures/eval_policy_corpus.json`, verify `>= 20` queries across `direct_lookup`, `paraphrased`, `exact_identifier`, and `rule_and_exception` (`>= 3` matching complete enclosing parent sections in the seeded `"eval_policy"` collection), confirm `tests/fixtures/policy_corpus/` is untouched (`pytest -m reverse`), replay offline under `mock_litellm_offline`, and assert exact match against both `modes["default"]` and `modes["fts5_hybrid"]` in `docs/eval-baseline.json`.

### Implementation & Benchmark Curation for User Story 3

- [ ] T012 [P] [US3] Author complementary synthetic Markdown policy documents in `tests/fixtures/eval_corpus/` (`tests/fixtures/eval_corpus/information_security_policy.md`, `tests/fixtures/eval_corpus/incident_response_runbook.md`, and `tests/fixtures/eval_corpus/procurement_vendor_policy.md`) formatted cleanly for `POLICY` chunking with distinct numbered sections/clauses, exact control/code identifiers (`AES-256`, `KMS-401`, `SEV-1`, `SEV-2`, `IR-RB-012`, `DPO-24H`, `PROC-204`, `PO-5000`), cross-document section references, and explicit rule-plus-exception paragraphs (`except`, `unless`, `provided that`), keeping `tests/fixtures/policy_corpus/` completely untouched
- [ ] T013 [US3] Seed an isolated offline `"eval_policy"` collection (`ingest` of `tests/fixtures/policy_corpus/` followed by `tests/fixtures/eval_corpus/` under `profile="POLICY"` using offline `deterministic_embed` / `mock_litellm_offline`) and curate `tests/fixtures/eval_policy_corpus.json` (`EvalFixture` JSON: `collection: "eval_policy"`, `profile: "POLICY"`, `queries: [...]`) containing `>= 22` distinct human-verified queries labeled in `notes` across `direct_lookup`, `paraphrased`, `exact_identifier`, and `>= 5` `rule_and_exception` queries whose `relevant_ids` point strictly to verified enclosing parent section chunk IDs (depends on `T012`)
- [ ] T014 [US3] Generate and save committed offline baseline snapshot `docs/eval-baseline.json` conforming to `BaselineSnapshot` (`schema_version=1`, `fixture="tests/fixtures/eval_policy_corpus.json"`, `corpora=["tests/fixtures/policy_corpus", "tests/fixtures/eval_corpus"]`, `embed_mode="offline_deterministic"`, `collection="eval_policy"`, `profile="POLICY"`, `k_values=[1, 3, 5, 10]`, `modes={"default": EvalReport, "fts5_hybrid": EvalReport}`) via reproducible ephemeral offline `evaluate(...)` runs without committing helper generator scripts in `src/` or repository root, normalizing each mode's `config["persist_dir"]` to canonical `".docpipe"` (depends on `T006`, `T013`)
- [ ] T015 [P] [US3] Create human-readable baseline comparison summary `docs/eval-baseline.md` documenting side-by-side metrics (`MRR`, `Precision@1/3/5/10`, `Recall@1/3/5/10`, and dense-vs-hybrid deltas from `docs/eval-baseline.json`), corpus composition, query category breakdown (`direct_lookup`, `paraphrased`, `exact_identifier`, `rule_and_exception`), and exact offline/local reproduction steps (depends on `T014`)

### Replay & Fixture Tests for User Story 3

- [ ] T016 [P] [US3] Add curated benchmark & baseline replay tests to `tests/test_eval.py` asserting `tests/fixtures/eval_policy_corpus.json` contains `>= 20` unique queries spanning `direct_lookup`, `paraphrased`, `exact_identifier`, and `>= 3` `rule_and_exception` parent-section queries (verifying every `relevant_id` exists as a committed parent section in the seeded `"eval_policy"` collection), replaying `evaluate(..., searcher="default")` and `evaluate(..., searcher="fts5_hybrid")` offline with `mock_litellm_offline` and asserting exact equality with `docs/eval-baseline.json` (`modes["default"]` and `modes["fts5_hybrid"]`) across `aggregate`, `per_query`, and `config` excluding ephemeral runtime `persist_dir`, and running CLI `docpipe-maestro eval --fixture tests/fixtures/eval_policy_corpus.json` end-to-end with pre/post persistence SHA-256 `0`-byte drift verification (depends on `T005`, `T010`, `T014`)

**Checkpoint**: User Stories 1, 2, and 3 are all complete, offline reproducible, and independently verified.

---

## Phase 6: Polish & Cross-Cutting Verification

**Purpose**: Synchronize user-facing & architecture documentation, enforce untouched Release Gate #1 fixtures/tests, verify every `quickstart.md` flow, pass lint/security/strict typing, and run the complete test suite (`100%` passing).

- [ ] T017 [P] Update `docs/cli-reference.md` documenting `docpipe-maestro eval` options (`--fixture`, `--k`, `--searcher`, `--expand-parent` / `--no-expand-parent`, `--embed-model`, `--json`, global flags), `Q3` collection resolution precedence, human/JSON output examples, and error exit behavior
- [ ] T018 [P] Update `docs/api-reference.md` and `docs/architecture.md` documenting the `docpipe_maestro.eval` package API (`evaluate`, `load_eval_fixture`, `precision_at_k`, `recall_at_k`, `reciprocal_rank`, `normalize_k_values`, `DEFAULT_EVAL_K_VALUES`, and the 6 `TypedDict`s defined canonically in `src/docpipe_maestro/types.py`) and read-only Phase 2 boundary
- [ ] T019 Verify `tests/fixtures/policy_corpus/` and `tests/test_reverse_safety.py` have zero git modifications (`git diff --exit-code tests/fixtures/policy_corpus/ tests/test_reverse_safety.py`) and validate every offline scenario in `specs/006-eval-harness/quickstart.md` passes cleanly (depends on `T016`)
- [ ] T020 Run full formatting, lint, security static checks, and strict type checks (`uv run ruff format --check . && uv run ruff check . && uv run ruff check --select S src/ && uv run mypy src tests`) fixing any violations cleanly (depends on `T007`, `T010`, `T016`, `T017`, `T018`)
- [ ] T021 **REQUIRED**: Execute mandatory Release Gate #1 (`uv run pytest -m reverse -v`) and run all tests across the entire `tests/` suite with branch coverage on `src/docpipe_maestro/` (`uv run pytest -v --cov`) after all implementation and documentation tasks finish; 100% of tests MUST pass with zero failures and `>= 80%` branch coverage before reporting completion (depends on `T019`, `T020`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup, `T001`–`T002`)**: No dependencies — start immediately.
- **Phase 2 (Foundational, `T003`–`T004`)**: Depends on Phase 1 (`T002` creates `eval/` package). `T003` (`types.py`) and `T004` (`metrics.py`) run in parallel. BLOCKS US1–US3.
- **Phase 3 (US1 - MVP, `T005`–`T008`)**: Depends on Phase 2 (`T003`, `T004`). `T005` (tests) and `T006` (`harness.py`) can be written in parallel (test-first discipline), `T007` (`__init__.py`) depends on `T006`, `T008` verifies US1 + API stability + AST purity.
- **Phase 4 (US2 - CLI, `T009`–`T011`)**: Depends on `T006`/`T007` (harness API ready for CLI integration). `T009` (`tests/test_cli.py`) and `T010` (`src/docpipe_maestro/cli.py`) touch separate files and can be developed in parallel; `T011` verifies US2 + lazy startup.
- **Phase 5 (US3 - Suite & Baselines, `T012`–`T016`)**: Depends on US1 (`T006`) for baseline generation and US2 (`T010`) for CLI end-to-end replay in `T016`; `T012` corpus authoring (`tests/fixtures/eval_corpus/`) has no code dependencies and can even start anytime after Phase 1. After `T014` (`docs/eval-baseline.json`), `T015` (`docs/eval-baseline.md`) and `T016` (`tests/test_eval.py`) run in parallel.
- **Phase 6 (Polish & Verification, `T017`–`T021`)**: `T017` and `T018` docs updates run in parallel after API/CLI stabilize (`T007`, `T010`); `T019` -> `T020` -> `T021` run sequentially as final gates.

### User Story Dependencies

- **US1 (`P1`)**: Independent of US2 & US3 once Phase 2 completes (deliverable MVP!).
- **US2 (`P2`)**: Integrates `docpipe_maestro.eval.harness.evaluate` into `src/docpipe_maestro/cli.py`; independent of US3.
- **US3 (`P3`)**: Uses US1 runner + US2 CLI to ground & verify `eval_policy_corpus.json` and `docs/eval-baseline.{json,md}`.

### Within Each User Story

- Tests written first and verified failing before corresponding implementation (`T005` -> `T006`, `T009` -> `T010`, `T016` verifies baseline generation).
- Canonical schemas (`T003`) before runner (`T006`), runner before CLI integration (`T010`), curated corpus/fixture (`T012`–`T013`) before committed baseline (`T014`).
- Each story closes cleanly with an independent test verification checkpoint (`T008`, `T011`, `T016`).

---

## Parallel Opportunities

```bash
# Phase 2 parallel foundation:
Task: "T003 Define canonical evaluation TypedDict shapes in src/docpipe_maestro/types.py"
Task: "T004 [P] Implement pure zero-I/O metrics in src/docpipe_maestro/eval/metrics.py"

# Phase 3 test-first alongside Phase 5 static corpus authoring:
Task: "T005 [P] [US1] Write US1 unit & offline runner tests in tests/test_eval.py"
Task: "T012 [P] [US3] Author complementary Markdown policies in tests/fixtures/eval_corpus/"

# Phase 4 CLI tests alongside CLI implementation:
Task: "T009 [P] [US2] Add CLI eval tests in tests/test_cli.py"
# (paired cleanly with T010 editing src/docpipe_maestro/cli.py)

# Phase 5 & Phase 6 independent file updates:
Task: "T015 [P] [US3] Write baseline summary in docs/eval-baseline.md"
Task: "T016 [P] [US3] Add baseline replay tests in tests/test_eval.py"
Task: "T017 [P] Update CLI reference in docs/cli-reference.md"
Task: "T018 [P] Update API & architecture docs in docs/api-reference.md and docs/architecture.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (`T001`–`T002`) and Phase 2 (`T003`–`T004`).
2. Complete Phase 3 (`T005`–`T008`).
3. **STOP and VALIDATE**: Confirm `docpipe_maestro.eval` computes `Precision@K`, `Recall@K`, and `MRR` deterministically and strictly read-only with full US1 test coverage, 33-symbol API stability, and library purity passing.

### Incremental Delivery

1. Setup + Foundational (`T001`–`T004`) -> Canonical schemas & zero-I/O metrics ready.
2. Add US1 (`T005`–`T008`) -> Programmatic read-only `evaluate()` runner ready (MVP).
3. Add US2 (`T009`–`T011`) -> `docpipe-maestro eval` CLI ready with `Q3` collection precedence and lazy startup.
4. Add US3 (`T012`–`T016`) -> Curated `20+` query fixture and offline `default` + `fts5_hybrid` baselines committed & replay-verified.
5. Polish (`T017`–`T021`) -> Updated `docs/`, zero drift on `policy_corpus`, clean `ruff`/`mypy`, and mandatory `100%` passing full test suite (`uv run pytest -v --cov`).

---

## Notes

- `[P]` tasks operate on distinct files and have no unfulfilled same-file or sequential dependencies.
- Top-level `docpipe_maestro.__all__` (`33` symbols) and `tests/fixtures/policy_corpus/` + `tests/test_reverse_safety.py` MUST NOT be modified.
- All automated benchmark checks and committed baselines (`docs/eval-baseline.json`) execute strictly offline (`mock_litellm_offline`) with zero network calls or model downloads.
