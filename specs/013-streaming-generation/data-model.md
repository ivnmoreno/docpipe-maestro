# Data Model: Streaming Generation Support (`013-streaming-generation`)

**Feature**: `013-streaming-generation` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## Public & Internal Interfaces (`src/docpipe_maestro/query/answer.py` & `cli.py`)

### 1. `answer(...)` Overloads (Public Root Export, Unchanged `__all__` Count `36`)

- **Default (`stream: Literal[False] = False`)**: Returns stripped `str` via `answer_detailed(...).text` (100% backward compatible).
- **Streaming (`stream: Literal[True]`)**: Returns synchronous `Iterator[str]` yielding raw non-empty delta text segments (`""` / `None` skipped; whitespace within/around deltas preserved verbatim).
- **Dynamic (`stream: bool = False`)**: Returns `str | Iterator[str]`.
- `_RESERVED_MODEL_KWARGS`: Includes `"stream"` alongside `"model"`, `"messages"`, `"prompt"`, `"api_base"`, `"base_url"`, `"api_key"`, `"temperature"`, `"max_tokens"`, `"timeout"`, and `"num_retries"`.

---

### 2. `_GenerationStreamState` (Submodule Internal State in `query/answer.py`)

Internal dataclass passed into `_stream_answer_with_state(...)` so `cli.py` can inspect completion telemetry (`truncated`, `finish_reason`) without altering `answer(..., stream=True)`'s `Iterator[str]` return type:

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | `str` | required | Target `provider/model` string |
| `finish_reason` | `str \| None` | `None` | Last non-empty `finish_reason` observed on the stream |
| `truncated` | `bool` | `False` | `True` when final `finish_reason == "length"` |
| `prompt_tokens` | `int \| None` | `None` | Latest provider-reported input token count (if emitted) |
| `completion_tokens` | `int \| None` | `None` | Latest provider-reported output token count (if emitted) |
| `reasoning_tokens` | `int \| None` | `None` | Latest provider-reported reasoning token count (if emitted) |
| `total_tokens` | `int \| None` | `None` | Latest provider-reported total token count (if emitted) |
| `saw_content` | `bool` | `False` | Whether at least one non-empty delta string was yielded |
| `saw_reasoning` | `bool` | `False` | Whether reasoning deltas/tokens were observed before end |
| `closed_early` | `bool` | `False` | `True` if consumer aborted iteration before stream completion |

Invariants:
- Usage and `finish_reason` counters update defensively across chunks: a trailing usage-only frame (`choices=[]` or `finish_reason=None`) never overwrites a non-empty `finish_reason` recorded on an earlier delta chunk.
- Root `docpipe_maestro.__all__` remains strictly unchanged at `36` exports.

---

### 3. CLI `ask` Output Modes (`src/docpipe_maestro/cli.py`)

| Flag Combination | `stdout` Behavior | `stderr` Behavior | `docpipe.toml` Key |
|---|---|---|---|
| Default (`--json` & `--stream` off) | Complete stripped answer text + `\n` | `--show-context`, truncation warning, telemetry (`--log-json`/`--log-level`) | Existing TOML defaults |
| `--json` | Pretty JSON payload (`answer`, `model`, `truncated`, `finish_reason`, `usage`, `elapsed_seconds`, `retrieval_elapsed_seconds`, `sources`) | Same diagnostics & JSON telemetry (`--log-json`) | CLI-only (`as_json=False` default) |
| `--stream` | Sequential unbuffered `sys.stdout.write(chunk)` + `flush()`, ending with `\n` | `--show-context`, truncation warning post-stream (when `!fail_on_truncation`), telemetry (`--log-json`) | CLI-only (`stream=False` default) |
| `--stream --json` | Rejected by mutually exclusive parser group before execution | `argparse` usage/conflict error | Exit `2` |
