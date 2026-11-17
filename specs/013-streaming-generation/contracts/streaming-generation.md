# Contracts: Streaming Generation Support (`013-streaming-generation`)

**Feature**: `013-streaming-generation` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## 1. Python Library Contracts (`docpipe_maestro.query.answer` & Root `docpipe_maestro`)

### 1.1 `answer(..., *, stream: bool = False)` Overloads

```python
@overload
def answer(
    prompt: str | Sequence[Mapping[str, str]],
    *,
    model: str = DEFAULT_GENERATION_MODEL,
    api_base: str | None = None,
    has_context: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    model_kwargs: Mapping[str, Any] | None = None,
    fail_on_truncation: bool = False,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
    stream: Literal[False] = False,
) -> str: ...


@overload
def answer(
    prompt: str | Sequence[Mapping[str, str]],
    *,
    model: str = DEFAULT_GENERATION_MODEL,
    api_base: str | None = None,
    has_context: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    model_kwargs: Mapping[str, Any] | None = None,
    fail_on_truncation: bool = False,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
    stream: Literal[True],
) -> Iterator[str]: ...


@overload
def answer(
    prompt: str | Sequence[Mapping[str, str]],
    *,
    model: str = DEFAULT_GENERATION_MODEL,
    api_base: str | None = None,
    has_context: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    model_kwargs: Mapping[str, Any] | None = None,
    fail_on_truncation: bool = False,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
    stream: bool = False,
) -> str | Iterator[str]: ...
```

### 1.2 Behavioral Guarantees for `answer(..., stream=True)`

1. **Eager Preflight Execution (Call-Site, Pre-Network)**:
   - Immediately upon calling `answer(..., stream=True)`:
     - Validates `model_kwargs` (including rejecting `"stream"` in `_RESERVED_MODEL_KWARGS`), `timeout` (`> 0`), `temperature` (`>= 0`), `max_tokens` (`>= 1`), `api_base`, and ChatML messages (`_normalize_messages`).
     - Executes `guard_egress(messages, model=model, api_base=api_base, pii_policy=pii_policy, local_only=local_only)` inside `with correlation_id() as cid:` BEFORE returning the generator.
     - Raises `DocpipeError` / `PiiBlockedError` immediately if validation, `local_only`, or blocking PII rules trigger—producing zero network calls and zero yielded chunks.
2. **Pull-Started External Stream (`has_context=True` vs `has_context=False`)**:
   - External LLM transport (`prepare_litellm().completion(..., stream=True, **kwargs)`) is NOT called until the caller iterates the returned `Iterator[str]`.
   - If `has_context=False`, iterating the returned iterator yields `EMPTY_CONTEXT_REFUSAL` once and returns with zero `litellm.completion` / `prepare_litellm` calls and zero `"answer"` LLM network stage events.
3. **Chunk Processing & Edge Frames**:
   - Skips chunks with empty/missing `choices`, missing `delta`, or `delta.content` in `(None, "")`.
   - Yields non-empty string deltas (`content`) verbatim without `.strip()`.
   - Raises `DocpipeError` if `delta.refusal` or `choice.refusal` is non-empty.
   - Records `saw_reasoning` if `delta.reasoning_content` / `delta.reasoning` or `usage.reasoning_tokens` is present.
   - Updates `finish_reason` whenever a chunk reports a non-empty `finish_reason` string, and extracts optional usage counters (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `total_tokens`) even when delivered in trailing usage-only frames.
   - At normal exhaustion: if `not saw_content`, raises via `_raise_empty_response_error(..., saw_reasoning=state.saw_reasoning)` so reasoning-only streams without `usage.reasoning_tokens` preserve the same truncation/reasoning diagnostics. If `finish_reason == "length"` (`truncated=True`) and `fail_on_truncation=True`, raises `DocpipeError` cleanly.
4. **Error Scrubbing, Close Cleanup & Correlated Telemetry**:
   - Provider startup or mid-stream exceptions pass through `raise_litellm_error(..., operation="generation", model=model)`, emitting `ERROR` `stage.end` (`stage="answer", error_type=...`) without raw secrets and re-raising `MissingCredentialError` / `DocpipeError`.
   - When iteration finishes or is terminated early (`GeneratorExit` via `for ...: break` or `.close()`), the underlying provider stream's `.close()` (if callable) runs inside `finally:`, `stage_event(logger, "answer", model=model, stream=True)` emits one correlated `stage.end` record (`status="ok"`, `duration_ms`, plus `closed_early=True` if closed early or `finish_reason`/`truncated`/token counts on completion), and `correlation_id` resets deterministically. Raw prompts, streamed tokens, PII, and secrets are NEVER logged.
5. **Root Stability**:
   - Root `docpipe_maestro.__all__` stays strictly at `36` exports. Submodule `docpipe_maestro.query.answer` additionally provides internal helpers `_GenerationStreamState` + `_stream_answer_with_state(...)` (not in root `__all__`) for CLI truncation inspection.

---

## 2. CLI Contract (`src/docpipe_maestro/cli.py`)

### 2.1 `docpipe-maestro ask` Added Option

- Mutually exclusive group on `p_ask`:
  - `--json` (`action="store_true"`, `dest="as_json"`, `default=False`)
  - `--stream` (`action="store_true"`, `default=False`, help `"Stream generated answer chunks progressively to stdout (conflicts with --json)"`)
- `--stream` is strictly CLI-only (ignored if set in `docpipe.toml`).

### 2.2 Output & Exit-Code Behavior

- `--stream --json`: Rejected by `argparse` mutually exclusive group with exit code `2` on `stderr` before `retrieve()` or `answer()` executes.
- `--stream` with `sections` empty (`has_context=False`): writes `EMPTY_CONTEXT_REFUSAL`, flushes, prints trailing `"\n"`, exits `0`, zero LLM calls.
- `--stream` with context:
  1. Emits `--show-context` lines to `stderr` before streaming begins.
  2. Streams each delta immediately via `sys.stdout.write(chunk)` + `sys.stdout.flush()`, tracking `wrote_any = True`, and writes `"\n"` (`sys.stdout.flush()`) in `finally:` iff `wrote_any` is `True` (so pre-chunk/preflight errors keep `stdout` empty while partial mid-stream failures cleanly terminate the partial line before `Error:` on `stderr`).
  3. If truncated and `fail_on_truncation=False`, prints `Warning: Response for model ...` to `stderr` and returns `0`.
  4. If truncated and `fail_on_truncation=True` (or mid-stream error), exits `1` via normalized `DocpipeError` on `stderr` while `--log-json` telemetry stays strictly on `stderr` under one shared CLI `correlation_id`.
