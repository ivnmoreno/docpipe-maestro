# Phase 0 Research: Streaming Generation Support (`013-streaming-generation`)

**Feature**: `013-streaming-generation` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## Research Decisions

### 1. Public API Surface & Root Export Stability (`36` Exports)

- **Decision**: Keep `docpipe_maestro.__all__` unchanged at `36` exports. Extend `answer()` in `src/docpipe_maestro/query/answer.py` with trailing keyword-only `stream: bool = False` using Python `@overload` (`Literal[False] = False -> str`, `Literal[True] -> Iterator[str]`, `bool -> str | Iterator[str]`). Add `"stream"` to `_RESERVED_MODEL_KWARGS` so callers cannot sneak conflicting `stream=...` into `model_kwargs`. Keep `answer_detailed()` returning buffered `GenerationResult` unchanged. Expose an internal/submodule stream helper (`_stream_answer_with_state` / `_GenerationStreamState`) inside `docpipe_maestro.query.answer` for CLI `ask --stream` to read completion truncation state without altering `answer()`'s `Iterator[str]` contract.
- **Rationale**: Preserves CI/release stability gates (`assert len(dp.__all__) == 36` in `.github/workflows/ci.yml`, `.github/workflows/release.yml`, and `tests/test_api_stability.py`), matches roadmap `6.2` (`answer()` yielding `Iterator[str]`), keeps all non-streaming callers 100% static-type compatible, and prevents `cli.py` from duplicating LiteLLM stream handling logic.
- **Alternatives Considered**:
  - Adding a new top-level `stream_answer()` root export: unnecessary root `__all__` bump (`36 -> 37`) when `answer()` is already documented in roadmap `6.2`.
  - Dropping the `stderr` truncation warning on `ask --stream`: diverges from non-streaming `ask` UX where operators expect warnings when tokens exhaust before completion.

### 2. Eager Preflight Validation & Pull-Started Transport Lifecycle

- **Decision**: Factor shared request preparation (`_prepare_generation_request`) executed eagerly inside both `answer_detailed()` and `answer(..., stream=True)` before any iterator is returned: validates `timeout`, `temperature`, `max_tokens`, reserved `model_kwargs`, `api_base`, normalizes ChatML messages, runs `guard_egress(..., local_only=local_only, pii_policy=pii_policy)` inside an active `correlation_id()` scope, and captures `cid`. Then `answer(..., stream=True)` returns a separate generator helper whose body executes lazily on the first `next()` pull:
  - When `has_context=False`: yields `EMPTY_CONTEXT_REFUSAL` once without calling `prepare_litellm()` or network providers.
  - When `has_context=True`: enters `with correlation_id(inherited_or_captured_cid):` and `with stage_event(logger, "answer", model=model, stream=True):`, calls `litellm.completion(..., stream=True, **kwargs)`, iterates delta frames, and releases resources deterministically in `finally:`.
- **Rationale**: In Python, placing a `yield` directly inside `answer()` would defer parameter validation and `guard_egress()` PII blocking until the first `next()` pull, violating fail-closed security expectations. Splitting eager preflight from the returned generator guarantees immediate pre-network exceptions (`DocpipeError`, `PiiBlockedError`, `ModelMismatchError`) at `answer(..., stream=True)` call time while keeping upstream provider I/O lazily pull-started (`0` network traffic if uniterated) and ensuring `stage_event("answer")` spans the complete request + stream consumption window.
- **Alternatives Considered**:
  - Putting `yield` directly inside `answer()`: delays validation/egress refusal until first iteration.
  - Opening `litellm.completion(..., stream=True)` eagerly before returning: performs network I/O and incurs latency/cost even if the caller drops or inspects the iterator before pulling chunks, and fragments `stage_event` timing.

### 3. LiteLLM Chunk Parsing, Error Scrubbing, Usage Preservation & Generator Cleanup

- **Decision**: Empirically verified against `litellm.types.utils` (`ModelResponseStream`, `StreamingChoices`, `Delta`):
  - Read `choices = _item_field(chunk, "choices", None)` and `usage = _item_field(chunk, "usage", None)` defensively (supporting both dict-shaped mocks and Pydantic/attribute objects).
  - Track across the stream: last non-empty `finish_reason`, latest `prompt_tokens`/`completion_tokens`/`reasoning_tokens`/`total_tokens`, `saw_content`, and `saw_reasoning` (`delta.reasoning_content` / `delta.reasoning` / `reasoning_tokens > 0`).
  - Raise `DocpipeError` cleanly if `delta.refusal` or `choice.refusal` is truthy.
  - Preserve whitespace verbatim in streamed chunks (`if isinstance(content, str) and content:` — unlike buffered `_extract_completion_details`, NEVER `.strip()` individual streamed deltas because token deltas carry significant leading/trailing spaces).
  - Wrap both `litellm.completion(..., stream=True)` and the `for chunk in raw_stream:` iteration with `raise_litellm_error(..., operation="generation", model=model)` so mid-stream failures scrub URL/API-key/env secrets before raising `MissingCredentialError` or `DocpipeError`.
  - When the upstream loop ends normally: if `not saw_content`, invoke `_raise_empty_response_error(...)`; update `answer_ev` telemetry fields (`finish_reason`, `truncated`, token counts); if `truncated and fail_on_truncation`, raise `DocpipeError`.
  - Close any closeable upstream stream object (`close_fn = getattr(raw_stream, "close", None)`) in `finally:`. Handle `GeneratorExit` cleanly inside `stage_event` (`closed_early = True`, `answer_ev["closed_early"] = True`, returning instead of letting `GeneratorExit` bypass `stage_event` emission or leak `_CORRELATION_ID`).
- **Rationale**: Directly verified against `src/docpipe_maestro/log.py` (`L195-215`): `stage_event` catches `Exception` (not `BaseException`/`GeneratorExit`) and emits `status="ok"` only on normal context exit. Returning after recording `closed_early=True` inside `GeneratorExit` guarantees every started stream emits its correlated `stage.end` record and cleans up upstream HTTP sockets cleanly on `for ...: break` or `.close()`.
- **Alternatives Considered**:
  - Stripping chunks before yielding: corrupts spacing (`"Annualleave"`).
  - Letting `GeneratorExit` bypass `stage_event`: drops telemetry on early consumer break.

### 4. CLI `docpipe-maestro ask --stream` & `--json` Mutual Exclusion

- **Decision**: In `src/docpipe_maestro/cli.py`, register `--stream` and `--json` inside `p_ask.add_mutually_exclusive_group()`, keeping `--stream` strictly a CLI flag (`default=False`, never read from `docpipe.toml`). Inside `_handle_ask`, when `args.stream` is `True`:
  - Run existing `local_only`, `retrieve()`, and optional `--show-context` (`stderr`) unchanged.
  - Call the submodule stream helper (`_stream_answer_with_state`) inside the active CLI `correlation_id()` scope, writing each chunk immediately via `sys.stdout.write(chunk)` + `sys.stdout.flush()`, tracking `wrote_any` so `finally:` emits a single trailing `"\n"` (`sys.stdout.flush()`) when any output was written.
  - Emit `Warning: Response for model {args.model!r} was truncated at token limit...` to `sys.stderr` after completion if `state.truncated` (when `fail_on_truncation=False`); if `fail_on_truncation=True`, `DocpipeError` exits `1` via `main()`'s existing clean error handler.
- **Rationale**: `argparse.add_mutually_exclusive_group()` enforces CLI conflict rejection with zero extra code (`exit 2` before `retrieve` or LLM calls). Keeping `--stream` CLI-only preserves predictable `docpipe.toml` + `--json` CI workflows.
- **Alternatives Considered**:
  - Reading `stream` from `docpipe.toml`: risks breaking existing `ask --json` scripts whenever `stream = true` is set in a workspace config.

### 5. Complete User-Facing Documentation Coverage (`FR-011`)

- **Decision**: Audit and update every user-facing doc file by feature completion (`README.md`, `PRODUCT.md`, `docs/README.md`, `docs/cli-reference.md`, `docs/api-reference.md`, `docs/architecture.md`, `docs/development.md` if applicable, `docs/future-features.md` §6.2 + summary matrix, and `CHANGELOG.md` `## Unreleased`).
- **Rationale**: Explicitly required by `FR-011` and user instruction so CLI, Python API, architecture/telemetry, roadmap, and changelog stay 100% accurate.
