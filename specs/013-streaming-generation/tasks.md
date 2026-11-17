---

description: "Task list for Streaming Generation Support (answer & ask --stream) under 013-streaming-generation"
---

# Tasks: Streaming Generation Support (`013-streaming-generation`)

**Input**: Design documents from `specs/013-streaming-generation/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/streaming-generation.md`, `quickstart.md`  
**Tests**: Explicit test tasks are included per Constitution `v1.4.0` Quality Gates (`answer(..., stream=True)`, eager `local_only` / `PiiBlockedError`, CLI `--stream` / `--json` conflict, Safety Gate #1 `reverse`, Safety Gate #2 `pii`, and telemetry/early-close cleanup).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (`US1`, `US2`, `US3`)
- Every task includes exact file paths and data-model / contract constraints.

---

## Phase 1: Setup (Shared Verification Baseline)

**Purpose**: Confirm clean branch state and tooling readiness on `feat/013-streaming-generation` under Constitution `v1.4.0`.

- [X] T001 Verify baseline lockfile and code quality checks (`uv lock --check`, `uv run --no-sync ruff check .`) from `pyproject.toml` on branch `feat/013-streaming-generation`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared preflight preparation helper and internal stream state/chunk extraction primitives required by all streaming user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Add `"stream"` to `_RESERVED_MODEL_KWARGS` and extract shared eager preflight helper `_prepare_generation_request(...)` (`_normalize_messages`, `_validate_generation_params`, `validate_api_base`, and `guard_egress(..., local_only=local_only, pii_policy=pii_policy)` inside `correlation_id()`) used by both `answer_detailed()` and streaming paths in `src/docpipe_maestro/query/answer.py`
- [X] T003 Define internal `_GenerationStreamState` dataclass (`model`, `finish_reason: str | None = None`, `truncated: bool = False`, `prompt_tokens: int | None = None`, `completion_tokens: int | None = None`, `reasoning_tokens: int | None = None`, `total_tokens: int | None = None`, `saw_content: bool = False`, `saw_reasoning: bool = False`, `closed_early: bool = False`), extend `_raise_empty_response_error(..., saw_reasoning: bool = False)`, and add chunk inspection helper `_process_stream_chunk(...)` (preserving delta whitespace verbatim without `.strip()`, skipping `None`/`""` deltas, detecting refusals, capturing reasoning deltas, preserving last non-empty `finish_reason` across trailing usage-only frames, and updating optional token counts) in `src/docpipe_maestro/query/answer.py`

**Checkpoint**: Foundation ready — shared eager preflight validation and defensive stream chunk parsing are verified in `query/answer.py`.

---

## Phase 3: User Story 1 - Synchronous Pull-Based Answer Streaming in Library Calls (Priority: P1) 🎯 MVP

**Goal**: Provide synchronous `answer(..., stream=True) -> Iterator[str]` yielding non-empty text chunks progressively while keeping default `answer(...) -> str` unchanged and root `docpipe_maestro.__all__` at `36` exports.

**Independent Test**: Invoke `answer(prompt, stream=True)` against mocked multi-delta streams, empty/role-only deltas, trailing usage-only frames, and `has_context=False`, verifying progressive non-empty `str` deltas and default `answer(prompt) -> str` parity.

### Tests for User Story 1

- [X] T004 [P] [US1] Add unit tests in `tests/test_prompts_answer.py` covering `answer(..., stream=True)` ordered `str` delta yields preserving whitespace, empty/`None`/role-only frame filtering, trailing usage-only frames preserving `finish_reason`, refusal chunks (`DocpipeError`), reasoning-only exhaustion diagnostics (`saw_reasoning=True`), `0` LiteLLM calls before first `next()` pull on `has_context=True`, `has_context=False` single `EMPTY_CONTEXT_REFUSAL` yield with `0` LiteLLM calls, default `answer(...) -> str` backward compatibility, and `model_kwargs={"stream": True}` rejection

### Implementation for User Story 1

- [X] T005 [US1] Implement pull-started stream generator `_iter_answer_stream(...)` and internal helper `_stream_answer_with_state(...)` in `src/docpipe_maestro/query/answer.py` (short-circuiting `has_context=False` to yield `EMPTY_CONTEXT_REFUSAL` without calling `prepare_litellm()`, opening `litellm.completion(..., stream=True, **kwargs)` lazily on first pull when `has_context=True`, yielding non-empty delta strings verbatim, calling `_raise_empty_response_error(..., saw_reasoning=state.saw_reasoning)` when no content is received, and closing `raw_stream.close()` in `finally:`)
- [X] T006 [US1] Add `@overload` signatures (`Literal[False] = False -> str`, `Literal[True] -> Iterator[str]`, `bool -> str | Iterator[str]`) and trailing keyword-only `stream: bool = False` to `answer()` in `src/docpipe_maestro/query/answer.py` while keeping root `docpipe_maestro.__all__` unchanged at `36` exports in `src/docpipe_maestro/__init__.py`

**Checkpoint**: User Story 1 (`answer(..., stream=True)`) is complete, typed with `@overload`, and independently verified as MVP.

---

## Phase 4: User Story 2 - Eager Preflight Validation, Safety Guarding, Error Normalization & Telemetry Hygiene (Priority: P1)

**Goal**: Enforce eager pre-iteration validation and `guard_egress` PII blocking/redaction, credential-scrubbed mid-stream exception handling, `fail_on_truncation` enforcement, and deterministic early-close/error cleanup with PII-safe correlated telemetry.

**Independent Test**: Verify eager `local_only` / `PiiBlockedError` / invalid parameter failures happen at call time before any `next()` pull, outbound PII redaction across streamed payloads, secret-scrubbed mid-stream `MissingCredentialError` / `DocpipeError`, `fail_on_truncation=True` refusal at `finish_reason="length"`, and single correlated `stage.end` events on complete/abort/error streams with zero raw tokens or PII.

### Tests for User Story 2

- [X] T007 [P] [US2] Add streaming egress safety and failure-mode tests in `tests/test_pii_safety.py` and `tests/test_prompts_answer.py` verifying eager call-time `PiiBlockedError` and `local_only` refusals (`0` pulls, `0` chunks, `0` LiteLLM calls — including ordering before `has_context=False`), outbound PII redaction on remote streaming prompts, credential-scrubbed mid-stream provider exceptions (`MissingCredentialError`/`DocpipeError`), and `fail_on_truncation=True` refusal on `finish_reason="length"`
- [X] T008 [P] [US2] Add streaming telemetry and lifecycle cleanup tests in `tests/test_logging.py` verifying correlated `"answer"` (`stream=True`) `stage.end` events across normal completion, `error_type` failure, early iterator close (`break`/`.close()`, recording `closed_early=True`, invoking `raw_stream.close()`, restoring `get_correlation_id() == None`, and leaking zero raw prompts/tokens/secrets), and zero `"answer"` `stage.end` events on `has_context=False`

### Implementation for User Story 2

- [X] T009 [US2] Wire eager `correlation_id()` capture across `_prepare_generation_request` into `_iter_answer_stream(...)`, `stage_event(logger, "answer", model=model, stream=True)` with `GeneratorExit` clean handling (`closed_early=True` before exiting `stage_event` cleanly), `raise_litellm_error(..., operation="generation", model=model)` around `litellm.completion` and chunk iteration, and `truncated and fail_on_truncation` `DocpipeError` enforcement in `src/docpipe_maestro/query/answer.py`

**Checkpoint**: User Stories 1 and 2 satisfy full pre-network safety, error hygiene, early-close resource cleanup, and telemetry contracts.

---

## Phase 5: User Story 3 - Real-Time Terminal Streaming via `docpipe-maestro ask --stream` (Priority: P2)

**Goal**: Add strictly CLI-only `--stream` on `docpipe-maestro ask` (mutually exclusive with `--json`), writing deltas progressively to `stdout` with immediate flush while keeping diagnostics, truncation warnings, and structured telemetry strictly on `stderr`.

**Independent Test**: Run `docpipe-maestro ask` with `--stream`, `--stream --show-context --log-json`, `--stream` under empty context, truncated stream with/without `--fail-on-truncation`, `--stream --json` mutual-exclusion failure (`exit 2`), and `stream = true` ignored in `docpipe.toml`.

### Tests for User Story 3

- [X] T010 [P] [US3] Add CLI integration tests in `tests/test_cli.py` covering `ask --stream` immediate flushed `stdout` writes and trailing newline, `--show-context` and `--log-json` strict `stderr` separation under one CLI `correlation_id`, empty-context refusal under `--stream`, truncation `stderr` warning vs `--fail-on-truncation` exit `1`, `--stream --json` exit `2` conflict before retrieval, and `docpipe.toml` ignoring `stream = true`

### Implementation for User Story 3

- [X] T011 [US3] Move `--json` (`dest="as_json"`) on `p_ask` into `p_ask.add_mutually_exclusive_group()` alongside `--stream` (`action="store_true"`, `default=False`, ignoring any `stream` key in `docpipe.toml`) and update `_handle_ask()` to invoke `_stream_answer_with_state(...)` with unbuffered `sys.stdout.write(chunk); sys.stdout.flush()`, `wrote_any`-guarded trailing newline inside `finally:`, and post-stream truncation warning on `stderr` in `src/docpipe_maestro/cli.py`

**Checkpoint**: All three user stories (`US1`, `US2`, `US3`) work independently and via CLI.

---

## Phase 6: Polish, User-Facing Documentation & Full Quality Gates

**Purpose**: Lock API stability invariants, update EVERY user-facing documentation file per `FR-011`, and pass all quality, safety, and coverage gates.

- [X] T012 [P] Update `root.answer` parameter assertions (`stream=False`) and validate `@overload` `answer(..., stream=True)` vs `answer(...)`, reserved `"stream"` kwarg rejection, and `len(root.__all__) == 36` in `tests/test_api_stability.py`
- [X] T013 [P] Update EVERY user-facing file per `FR-011` (`README.md`, `PRODUCT.md`, `docs/README.md`, `docs/cli-reference.md`, `docs/api-reference.md`, `docs/architecture.md`, `docs/development.md`, `docs/future-features.md` §6.2 & matrix row `*Implemented*`, and `CHANGELOG.md` `## Unreleased` noting `013-streaming-generation` and Constitution `v1.4.0`)
- [X] T014 Run quickstart validation scenarios from `specs/013-streaming-generation/quickstart.md` and full quality/safety/coverage gates (`uv lock --check`, `uv run --no-sync ruff format --check .`, `uv run --no-sync ruff check .`, `uv run --no-sync ruff check --select S src/`, `uv run --no-sync mypy src tests`, `uv run --no-sync pytest -m reverse -v`, `uv run --no-sync pytest -m pii -v`, `LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -v --cov`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — starts immediately.
- **Phase 2 (Foundational)**: Depends on `T001` — BLOCKS all user stories (`T002` -> `T003` sequentially in `src/docpipe_maestro/query/answer.py`).
- **Phase 3 (`US1`)**: Depends on Phase 2 (`T002`, `T003`). Write `T004` first (TDD), then implement `T005` -> `T006` sequentially in `query/answer.py`.
- **Phase 4 (`US2`)**: Depends on Phase 3 (`T006`) for `answer(..., stream=True)` signature and stream helper. Write parallel tests `T007` & `T008` first (disjoint test files), then implement `T009` in `query/answer.py`.
- **Phase 5 (`US3`)**: Depends on Phase 3 & Phase 4 (`T005` `_stream_answer_with_state` & `T009` error/truncation/telemetry handling). Write `T010` first, then implement `T011` in `src/docpipe_maestro/cli.py`.
- **Phase 6 (Polish & Docs)**: Depends on Phase 5 completion (`T012` & `T013` run in parallel before final gate `T014`).

### Parallel Opportunities

```bash
# Phase 4 parallel test tasks (disjoint files):
T007: Eager safety & error tests in tests/test_pii_safety.py & tests/test_prompts_answer.py
T008: Telemetry & early-close cleanup tests in tests/test_logging.py

# Phase 6 parallel polish & user-facing docs tasks:
T012: API stability signature & export checks in tests/test_api_stability.py
T013: User-facing doc updates across README.md, PRODUCT.md, docs/*, CHANGELOG.md
```

---

## Implementation Strategy

### MVP First (`US1` Only)

1. Complete Phase 1 (`T001`) and Phase 2 (`T002`–`T003`).
2. Complete Phase 3 (`T004`–`T006`) for pull-based synchronous `answer(..., stream=True)` and verify all US1 unit tests pass.

### Full Incremental Delivery (`US1` → `US2` → `US3`)

1. Complete Phase 4 (`T007`–`T009`) guaranteeing eager safety/egress parity, secret scrubbing, truncation enforcement, and clean stream close/telemetry.
2. Complete Phase 5 (`T010`–`T011`) exposing CLI `docpipe-maestro ask --stream` with `--json` mutual exclusion and flushed output.
3. Complete Phase 6 (`T012`–`T014`) updating every user-facing doc file and verifying 100% of test, safety gate, lint, strict type, and coverage gates pass.
