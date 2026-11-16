# Contracts: Stage 8 Structured JSON Logging & Correlation Tracing

**Feature**: `011-structured-logging` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

## 1. Public Submodule Contract (`docpipe_maestro.log`)

*Root package `docpipe_maestro.__all__` remains strictly unchanged at 36 exports (`Q1`). Structured logging utilities are imported explicitly from `docpipe_maestro.log`.*

### 1.1 Module Constants & Exports

```python
__all__ = [
    "LOGGER_NAME",
    "RESERVED_ENVELOPE_KEYS",
    "JsonFormatter",
    "TextFormatter",
    "correlation_id",
    "get_correlation_id",
    "get_logger",
    "stage_event",
]

LOGGER_NAME = "docpipe_maestro"
RESERVED_ENVELOPE_KEYS = frozenset({"ts", "level", "logger", "msg", "correlation_id"})
```

### 1.2 Signatures & Behavioral Guarantees

```python
class JsonFormatter(logging.Formatter):
    """Render LogRecords as single-line JSON without leaking tracebacks."""

    def format(self, record: logging.LogRecord) -> str: ...


class TextFormatter(logging.Formatter):
    """Render LogRecords concisely to stderr when --log-level is used without --log-json,
    suppressing raw exc_info/exc_text tracebacks identically to JsonFormatter."""

    def format(self, record: logging.LogRecord) -> str: ...


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """Return logger under ``docpipe_maestro`` with NullHandler guaranteed on package root."""


def get_correlation_id() -> str | None:
    """Return active ContextVar correlation ID or None when no scope is active."""


@contextmanager
def correlation_id(value: str | None = None) -> Iterator[str]:
    """Bind or inherit an async/thread-safe UUID correlation ID for the current scope."""


@contextmanager
def stage_event(
    logger: logging.Logger,
    stage: str,
    *,
    log_level: int = logging.INFO,
    **fields: Any,
) -> Iterator[dict[str, Any]]:
    """Measure stage elapsed duration_ms and emit a correlated ``stage.end`` record."""
```

Behavioral requirements:
1. Calling `get_logger()` or any pipeline entry point MUST NOT add non-null handlers, modify root logger (`logging.getLogger()`), or call `logging.basicConfig()`.
2. `correlation_id()` raises `ValueError` if given an explicit blank/whitespace string; when `value is None` and an outer correlation ID is active, yields and preserves the active ID. Resets `ContextVar` token unconditionally in `finally`.
3. `stage_event(...)` records wall time via `time.perf_counter()`, yields a mutable `dict[str, Any]` (`event_fields`) for post-stage counts, checks `logger.isEnabledFor(...)` before allocating/emitting `"stage.end"` at `log_level` (`status="ok"`, `duration_ms` float >= 0) on success or at `logging.ERROR` (`status="error"`, `duration_ms`, `error_type=type(exc).__name__`) on exception, and re-raises without masking.
4. `JsonFormatter` builds:
   ```json
   {
     "ts": "2026-11-16T15:00:00.000000+00:00",
     "level": "INFO",
     "logger": "docpipe_maestro.query.retriever",
     "msg": "stage.end",
     "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
     "fields": {
       "stage": "search",
       "status": "ok",
       "duration_ms": 12.345,
       "searcher": "fts5_hybrid",
       "hits": 4
     }
   }
   ```
   and ignores `record.exc_info` / `record.exc_text` so exception messages and traceback frames are never emitted into JSON logs.

---

## 2. Pipeline & CLI Instrumentation Contracts

| Call Site | Outer Correlation Scope | Timed Stages Emitted |
|---|---|---|
| `cli.main()` | Opens `with correlation_id():` + `_cli_logging_scope(...)` when `--log-json` or `--log-level` active | All stages triggered by subcommand share single CLI `correlation_id`; cleans up handler in `finally` |
| `ingest()` / `sync()` | `with correlation_id():` | Batch `INFO` `stage.end` for `intake`, `clean`, `enrich`, `chunk`, `embed`, `store` (including `docs=0` all-skipped runs); per-doc `DEBUG` `stage.end` for `intake`, `clean`, `enrich`, `chunk`; mid-batch exceptions emit failed stage's `ERROR` `stage.end` immediately without post-abort `"ok"` batch summaries |
| `remove()` / `status()` | `with correlation_id():` | `INFO` `stage.end` for `store` (`operation="remove"` or `"status"`) |
| `reindex()` | `with correlation_id():` | `INFO` `stage.end` for `embed` (when `children` non-empty) and `store` (`operation="reindex"`) |
| `retrieve()` | `with correlation_id():` | `INFO` `stage.end` for `search` and (if `rerank=True` and matches > 0) `rerank` |
| `DenseSearcher.search()` / `Fts5HybridSearcher.search()` | Inherits outer scope | `INFO` `stage.end` for `embed` (`operation="query"`) around `embed_query()` (omitted cleanly when empty short-circuit triggers) |
| `guard_egress()` | Inherits outer scope | `INFO` `stage.end` for `egress` only when remote PII scrubbing/blocking actually runs (emits `ERROR` `stage.end` on `PiiBlockedError`) |
| `answer_detailed()` | `with correlation_id():` | `INFO` `stage.end` for `answer` around completion execution when `has_context=True` |
| `evaluate()` | `with correlation_id():` | Outer `correlation_id` inherited by all `retrieve()` calls in the eval run |

---

## 3. CLI Contract Extensions (`src/docpipe_maestro/cli.py`)

Shared global options registered on root parser and `common` parent parser (`default=argparse.SUPPRESS` on `common`), **not** read from `docpipe.toml`:

| Flag | Values / Type | Default | Stream Behavior |
|---|---|---|---|
| `--log-json` | Flag (`store_true`) | `False` | Emits single-line JSON log records to `sys.stderr` (default threshold `INFO` unless `--log-level` specified); leaves `stdout` completely clean |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` (case-insensitive) | `None` | Sets severity threshold on `docpipe_maestro`; when passed without `--log-json`, attaches `TextFormatter` writing to `sys.stderr`; invalid choices exit non-zero via `argparse` |

Both flags work either before or after the subcommand name:
- `docpipe-maestro --log-json --log-level INFO ingest ./docs`
- `docpipe-maestro query "leave days" --json --log-json --log-level DEBUG`
