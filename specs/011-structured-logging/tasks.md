---

description: "Task list for Stage 8 Structured JSON Logging & Correlation Tracing"
---

# Tasks: Structured JSON Logging & Correlation Tracing

**Input**: Design documents from `/specs/011-structured-logging/`  
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/structured-logging.md](contracts/structured-logging.md), [quickstart.md](quickstart.md)

**Tests**: Explicit unit, concurrency, CLI stderr/stdout separation, AST purity, and `@pytest.mark.pii` privacy-hygiene tests are included as requested in [spec.md](spec.md) and [plan.md](plan.md).

**Organization**: Tasks are grouped by user story (`US1`, `US2`, `US3`) so each story can be implemented, tested, and verified cleanly on top of the foundational `docpipe_maestro.log` module.

## Format: `[ID] [P?] [Story?] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`[US1]`, `[US2]`, `[US3]`)
- Include exact repository-relative file paths in every task

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm baseline safety/API-stability constraints prior to edits

- [X] T001 Verify clean `feat/011-structured-logging` baseline (`ruff`, `mypy`, `tests/test_api_stability.py` 36-export `__all__`, and `tests/test_library_purity.py`) via `uv run pytest tests/test_api_stability.py tests/test_library_purity.py -q`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build phase-neutral, stdlib-only `src/docpipe_maestro/log.py` and lock library purity guards before instrumenting Phase 1, Phase 2, or CLI modules.

**⚠️ CRITICAL**: No user story work (`US1`, `US2`, `US3`) can begin until `docpipe_maestro.log` exists cleanly.

- [X] T002 Create `src/docpipe_maestro/log.py` core constants and correlation context helpers (`LOGGER_NAME = "docpipe_maestro"`, `RESERVED_ENVELOPE_KEYS = frozenset({"ts", "level", "logger", "msg", "correlation_id"})`, stdlib-only imports, `_CORRELATION_ID: ContextVar[str | None]`, `get_correlation_id()`, and `@contextmanager correlation_id(value: str | None = None) -> Iterator[str]` validating non-empty stripped values, inheriting active outer IDs when `value is None`, generating UUID4 strings when absent, and resetting via `ContextVar.reset(token)` in `finally`)
- [X] T003 Implement `JsonFormatter`, `TextFormatter`, `_json_default`, and passive `get_logger(name: str = LOGGER_NAME) -> logging.Logger` in `src/docpipe_maestro/log.py` (single-line JSON envelope `{ts, level, logger, msg, correlation_id, fields}` with UTC ISO-8601 `ts`, active/`null` `correlation_id`, caller keys sandboxed inside nested `fields`, `exc_info`/`exc_text` stripped from BOTH `JsonFormatter` and `TextFormatter` output, `os.PathLike`/`set`/`tuple`/`str` serialization fallback, and `logging.NullHandler()` attached strictly to `"docpipe_maestro"` without mutating root logger or forcing `setLevel`)
- [X] T004 Implement typed `stage_event(logger: logging.Logger, stage: str, *, log_level: int = logging.INFO, **fields: Any) -> Iterator[dict[str, Any]]` timing context manager and explicit `__all__` exports in `src/docpipe_maestro/log.py` (recording `perf_counter` `duration_ms >= 0`, yielding mutable fields dict for safe post-stage counts, short-circuiting `LogRecord` emission via `logger.isEnabledFor(...)` when inactive, emitting `"stage.end"` at `log_level` with `status="ok"` on clean exit or at `logging.ERROR` with `status="error"` and `error_type=type(exc).__name__` on exception before re-raising, without adding anything to `src/docpipe_maestro/__init__.py`)
- [X] T005 [P] Update `tests/test_library_purity.py` to enforce AST import isolation on `src/docpipe_maestro/log.py` (forbidding imports from `docpipe_maestro.ingest`, `docpipe_maestro.query`, `docpipe_maestro.store`, `docpipe_maestro.embedder`, and config/dotenv modules)

**Checkpoint**: Foundation ready — `docpipe_maestro.log` contract and AST purity guards are in place; US1, US2, and US3 implementation can begin cleanly.

---

## Phase 3: User Story 1 — Host Applications Collect Correlated Pipeline Telemetry (Priority: P1) 🎯 MVP

**Goal**: Instrument all Phase 1 and Phase 2 entry points and pipeline stages with `correlation_id()` and timed `stage.end` events (`INFO` batch summaries + `DEBUG` per-doc details in Phase 1; `INFO` stage events in Phase 2) while leaving unconfigured host loggers, root logger, `stdout`, and `stderr` untouched.

**Independent Test**: Run `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `answer_detailed`, and `evaluate` in an unconfigured process verifying unchanged root logger and zero unsolicited output; attach a `JsonFormatter` handler to `get_logger()` (at `INFO` and `DEBUG`, including concurrent `asyncio` tasks and threads) verifying correlated UUID `correlation_id`, canonical stage names, `INFO` vs `DEBUG` Phase 1 granularity, and zero raw content fields.

- [X] T006 [P] [US1] Add shared internal `_StageMetrics` batch timer/counter helper, `with correlation_id():` scoping across `ingest()`, `sync()`, `remove()`, `status()`, and `reindex()`, per-document `DEBUG` `stage_event` blocks (`intake`, `clean`, `enrich`, `chunk`), batch-scoped `INFO` `stage.end` summary events (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store` — including `docs=0` all-skipped runs, while mid-batch exceptions propagate cleanly via the failed stage's `ERROR` `stage.end` without emitting post-abort `"ok"` batch summaries), `reindex()` (`embed`, `store`), and `remove()`/`status()` (`store`) in `src/docpipe_maestro/ingest/pipeline.py` (recording safe counts/profile/collection/source keys/doc digests only — never document or PII text)
- [X] T007 [P] [US1] Wrap `embedder_inst.embed_query(...)` with `stage_event(..., "embed", operation="query", collection=collection, embed_model=embed_model)` strictly after empty/short-circuit guards in `src/docpipe_maestro/query/searcher/dense.py`
- [X] T008 [P] [US1] Wrap `embedder_inst.embed_query(...)` with `stage_event(..., "embed", operation="query", collection=collection, embed_model=embed_model)` strictly after empty/short-circuit guards in `src/docpipe_maestro/query/searcher/hybrid.py`
- [X] T009 [P] [US1] Wrap `retrieve()` with `with correlation_id():`, wrap `searcher_inst.search(...)` with `stage_event(..., "search", collection=collection, searcher=searcher, has_where=where is not None, top_k=child_top_k)` (recording `hits` / `parents`), and wrap conditional `reranker_cls().rerank(...)` with `stage_event(..., "rerank", reranker=reranker, candidates=len(child_matches))` (recording `kept`) in `src/docpipe_maestro/query/retriever.py`
- [X] T010 [P] [US1] Wrap `answer_detailed()` with `with correlation_id():` and wrap `litellm.completion` + response extraction (when `has_context=True`) with `stage_event(..., "answer", model=model)` recording `finish_reason`, `truncated`, and usage token counts in `src/docpipe_maestro/query/answer.py`
- [X] T011 [P] [US1] Wrap `evaluate()` with `with correlation_id():` in `src/docpipe_maestro/eval/harness.py` so every retrieval query in an evaluation run inherits a single trace ID
- [X] T012 [US1] Create `tests/test_logging.py` with tests covering `NullHandler`-only silence, untouched root logger and `stdout`/`stderr`, `JsonFormatter` envelope keys (`ts`, `level`, `logger`, `msg`, `correlation_id`, nested `fields`), reserved envelope key collision sandboxing, `os.PathLike` fallback serialization, `correlation_id()` invalid blank rejection, nested inheritance, concurrent `asyncio` task + thread isolation, Phase 1 `INFO` batch vs `DEBUG` per-doc granularity across `ingest`/`sync`/`remove`/`status`/`reindex`, and Phase 2 `embed`/`search`/`rerank`/`answer`/`evaluate` events

**Checkpoint**: User Story 1 is complete and independently verifiable as the core library observability MVP.

---

## Phase 4: User Story 2 — CLI Operators Stream Structured Diagnostics Without Polluting Output (Priority: P1)

**Goal**: Provide CLI-only global `--log-json` and `--log-level {DEBUG,INFO,WARNING,ERROR}` flags usable before or after any subcommand, emitting correlated diagnostics exclusively to `stderr` while keeping CLI `stdout` (including `--json` output) clean and restoring logger state after execution.

**Independent Test**: Run `cli.main()` with Phase 1 and Phase 2 subcommands (`ingest`, `query --json`, `ask --json`, `eval --json`) using flags before and after subcommands, verifying pure parseable `stdout` JSON, correlated NDJSON on `stderr`, text mode when `--log-level` runs alone, non-zero exit on invalid levels, ignored `docpipe.toml` log keys, and zero duplicate handlers across repeated in-process CLI calls.

- [X] T013 [US2] Register global `--log-json` (`action="store_true"`) and `--log-level` (`choices=("DEBUG", "INFO", "WARNING", "ERROR")`, `type=str.upper`) on root `parser` and shared `common` parent parser (`default=argparse.SUPPRESS`), omit log keys from `_load_toml_config()`, implement `_cli_logging_scope(log_json=..., log_level=...)` attaching transient `StreamHandler(sys.stderr)` (with `JsonFormatter` defaulting threshold to `INFO` when `--log-json` is set, or `TextFormatter` when `--log-level` is used alone) and unconditionally removing/closing the handler + restoring package logger level in `finally`, and wrap subcommand dispatch in `with _cli_logging_scope(...), correlation_id():` in `src/docpipe_maestro/cli.py`
- [X] T014 [US2] Add CLI structured logging tests in `tests/test_cli.py` covering global `--log-json` and `--log-level` placement before and after subcommands, `--log-json` default `INFO` threshold, `--log-level` standalone text mode on `stderr`, invalid `--log-level` rejection, clean `--json` `stdout` parsing (`query`, `ask`, `eval`, `status`) with NDJSON `stderr` sharing one `correlation_id`, non-interpretation of `docpipe.toml` `log_json`/`log_level`, and repeated in-process `cli.main()` cleanup with zero handler leaks

**Checkpoint**: User Stories 1 and 2 work independently with clean `stdout`/`stderr` CLI telemetry separation.

---

## Phase 5: User Story 3 — Sensitive Data & Credentials Never Leak Into Telemetry Logs (Priority: P1)

**Goal**: Coordinate remote outbound PII egress logging and ensure failed stages record `ERROR` `stage.end` (`status="error"`, `error_type` only) with zero exposure of raw PII, raw exception messages, stack tracebacks, document text, questions, prompts, completions, or provider API keys across `INFO` and `DEBUG`.

**Independent Test**: Enable `DEBUG` JSON logging across workflows with synthetic PII (`redact`/`tokenize`/`block`), remote `guard_egress()`, and failing stages throwing secret-bearing exceptions, verifying `error_type` logging and zero raw PII/credential/content strings anywhere in emitted JSON logs.

- [X] T015 [P] [US3] Wrap active remote PII egress scrubbing/blocking (`not is_local_target and validated.egress != "allow"`) with `stage_event(..., "egress", egress_mode=validated.egress)` recording safe `message_count` and `entities_detected` counts (emitting `ERROR` `stage.end` on `PiiBlockedError` with zero raw PII strings) in `src/docpipe_maestro/query/egress.py`
- [X] T016 [US3] Add stage-failure and `DEBUG` secret-hygiene tests in `tests/test_logging.py` verifying `ERROR` `stage.end` (`status="error"`, `duration_ms`, `error_type` class name only), exclusion of raw exception messages and stack traces (`exc_info`), and absence of raw document text, questions, prompts, answers, and simulated API keys across `INFO` and `DEBUG` JSON logs (depends on `T012`, `T015`)
- [X] T017 [US3] Extend `@pytest.mark.pii` verification in `tests/test_pii_safety.py` to assert `DEBUG`-level JSON telemetry captured during PII ingest (`tokenize`/`redact`/`block` rollback) and remote `guard_egress` scrub/block runs records `enrich`/`egress` stage events with zero raw synthetic PII values, token salts, or credentials (depends on `T006`, `T015`)

**Checkpoint**: All 3 User Stories (`US1`, `US2`, `US3`) and PII/failure telemetry invariants are implemented and verified.

---

## Phase 6: Polish, Documentation & Full Quality Verification

**Purpose**: Update user-facing reference docs and `CHANGELOG.md`, then run end-to-end verification and all mandatory CI quality gates across the entire project.

- [X] T018 [P] Document `src/docpipe_maestro/log.py` module, silent `NullHandler` default, `{ts, level, logger, msg, correlation_id, fields}` JSON envelope, 10 canonical stage names, `INFO` vs `DEBUG` batch granularity, failure `error_type` behavior, and privacy exclusions in `docs/architecture.md`
- [X] T019 [P] Document global CLI options `--log-json` and `--log-level {DEBUG,INFO,WARNING,ERROR}`, before/after subcommand placement, `stderr`-only isolation, non-TOML behavior, and JSON/text invocation examples in `docs/cli-reference.md`
- [X] T020 [P] Document `docpipe_maestro.log` public submodule exports (while root `__all__` stays at 36) in `docs/api-reference.md` and add the Stage 8 entry under `## Unreleased` in `CHANGELOG.md`
- [X] T021 Validate end-to-end workflows in `specs/011-structured-logging/quickstart.md` and run all mandatory quality & safety gates (`uv run ruff format --check .`, `uv run ruff check .`, `uv run ruff check --select S src/`, `uv run mypy src tests`, `uv run pytest -m reverse -v`, `uv run pytest -m pii -v`, and `LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov` confirming >= 80% branch coverage and 100% tests passing)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: Starts immediately (`T001`).
- **Phase 2 (Foundational `log.py`)**: Depends on `T001` (`T002` -> `T003` -> `T004`; `T005` parallel once `log.py` path is active) — **BLOCKS** Phases 3, 4, and 5.
- **Phase 3 (`US1` — Host Telemetry)**: Depends on Phase 2 (`T006`–`T011` can run in parallel across distinct files; `T012` runs after instrumentation).
- **Phase 4 (`US2` — CLI Flags)**: Depends on Phase 2 (and uses Phase 3 instrumentation for end-to-end subcommand stages; `T013` -> `T014`).
- **Phase 5 (`US3` — PII & Failure Hygiene)**: Depends on Phase 2 and Phase 3 (`T015` `[P]`, then `T016` and `T017` after `T015` / `T006` / `T012`).
- **Phase 6 (Polish & Verification)**: Depends on Phases 3–5 (`T018` `[P]`, `T019` `[P]`, and `T020` `[P]`, then `T021` final full-suite gate).

### Parallel Opportunities

- Inside **Phase 3 (`US1`)**: `T006` (`pipeline.py`), `T007` (`dense.py`), `T008` (`hybrid.py`), `T009` (`retriever.py`), `T010` (`answer.py`), and `T011` (`harness.py`) touch strictly disjoint files and can all be implemented in parallel once Phase 2 completes.
- Inside **Phase 5 (`US3`)**: `T015` (`query/egress.py`) completes before `T016` (`tests/test_logging.py`) and `T017` (`tests/test_pii_safety.py`), after which `T016` and `T017` can verify in parallel across distinct test files.
- Inside **Phase 6 (Polish)**: `T018` (`docs/architecture.md`), `T019` (`docs/cli-reference.md`), and `T020` (`docs/api-reference.md` + `CHANGELOG.md`) are parallel before final verification `T021`.

---

## Parallel Example: User Story 1 Instrumentation

```bash
# After Phase 2 (T002-T005) finishes, all Phase 1/Phase 2 instrumentation edits run in parallel:
Task: "T006 [P] [US1] Batch/doc stage metrics + correlation in src/docpipe_maestro/ingest/pipeline.py"
Task: "T007 [P] [US1] Query embed stage telemetry in src/docpipe_maestro/query/searcher/dense.py"
Task: "T008 [P] [US1] Query embed stage telemetry in src/docpipe_maestro/query/searcher/hybrid.py"
Task: "T009 [P] [US1] Search & rerank telemetry in src/docpipe_maestro/query/retriever.py"
Task: "T010 [P] [US1] Answer generation telemetry in src/docpipe_maestro/query/answer.py"
Task: "T011 [P] [US1] Evaluation correlation scoping in src/docpipe_maestro/eval/harness.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete **Phase 1 + Phase 2** (`T001`–`T005`): standalone `docpipe_maestro.log` + purity guard.
2. Complete **Phase 3 (`US1`, `T006`–`T012`)**: full host-app telemetry across all Phase 1 & Phase 2 entry points and stages.
3. **STOP and VALIDATE**: Run `pytest tests/test_logging.py tests/test_library_purity.py tests/test_api_stability.py`.

### Incremental Delivery

4. Add **Phase 4 (`US2`, `T013`–`T014`)**: CLI `--log-json` & `--log-level` global flags on `stderr`.
5. Add **Phase 5 (`US3`, `T015`–`T017`)**: remote egress stage logging & Stage 4 PII / failure leak-hygiene proofs.
6. Complete **Phase 6 (`T018`–`T021`)**: architecture/CLI/API docs, `CHANGELOG.md`, and full CI quality, reverse-safety, PII-safety, and coverage gates.
