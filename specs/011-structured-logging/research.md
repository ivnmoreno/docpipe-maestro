# Research: Stage 8 Structured JSON Logging & Correlation Tracing

**Feature**: `011-structured-logging` (`feat/011-structured-logging`) | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

## 1. Existing Logging Surface Audit

Repository search across `src/` and `tests/` identified three existing logger consumers using standard library `logging.getLogger(__name__)`:

1. `src/docpipe_maestro/_pii.py` (`logger = logging.getLogger("docpipe_maestro._pii")`) — emits `WARNING` logs on optional Presidio fallback/unload diagnostics, verified in `tests/test_pii_safety.py` via `caplog.at_level(logging.WARNING, logger="docpipe_maestro._pii")`.
2. `src/docpipe_maestro/ingest/pipeline.py` (`logger = logging.getLogger("docpipe_maestro.ingest.pipeline")`) — emits `WARNING` logs when skipping symlinks or directory-escaping paths.
3. `src/docpipe_maestro/ingest/enricher/crossrefs.py` (`logger = logging.getLogger("docpipe_maestro.ingest.enricher.crossrefs")`) — emits `WARNING` logs for unresolved intra-document crossrefs, verified in `tests/test_crossrefs.py` via `caplog.at_level(logging.WARNING)`.

Because every module logger sits beneath `"docpipe_maestro"` with default `propagate=True`, managing passive defaults (`NullHandler`) and CLI-time handler attachment at `"docpipe_maestro"` covers all Stage 8 telemetry plus existing library warnings uniformly.

---

## 2. Design Decisions

### Decision 1: Submodule-Only Telemetry API (`docpipe_maestro.log`)
- **Decision**: Place all telemetry helpers (`LOGGER_NAME`, `RESERVED_ENVELOPE_KEYS`, `JsonFormatter`, `TextFormatter`, `get_logger`, `get_correlation_id`, `correlation_id`, `stage_event`) strictly inside `src/docpipe_maestro/log.py` and keep root `docpipe_maestro.__all__` unchanged at 36 exports.
- **Rationale**: Clarified in Session `2026-11-16` (`Q1`) and verified against `tests/test_api_stability.py` (`EXPECTED_ALL` strict equality + Constitution `v1.3.1` root export inventory). Matches how `docpipe_maestro.eval` exposes auxiliary capability outside the 36-symbol root contract. Keeping `log.py` phase-neutral with stdlib-only imports also satisfies `tests/test_library_purity.py` lazy-import and Phase 1/2 separation guards.
- **Alternatives Considered**: Re-exporting logging helpers at root `__init__.py` (rejected: would require amending Constitution `v1.3.1` Quality Gates and expanding the minimal root API surface).

### Decision 2: Passive `NullHandler`-Only Library Default Without Level Mutation
- **Decision**: `get_logger(name: str = LOGGER_NAME)` ensures the root package logger (`logging.getLogger("docpipe_maestro")`) has a `logging.NullHandler` whenever no `NullHandler` is already attached, never invokes `logging.basicConfig()`, never touches the Python root logger `logging.getLogger()`, and never forces `pkg_logger.setLevel(...)` during library execution.
- **Rationale**: Forces zero stdout/stderr emissions unless the consuming host application explicitly configures logging handlers/levels or CLI flags activate stderr logging. Preserves existing `pytest` `caplog` capture tests and host logger level inheritance (`NOTSET`).
- **Alternatives Considered**: Defaulting `pkg_logger.setLevel(logging.INFO)` on import (rejected: breaks hosts that set root logger to `WARNING` expecting child modules to obey root threshold, or causes unexpected `INFO` noise if a host attaches an unfiltered root handler).

### Decision 3: Single-Line JSON Envelope with Protected Nested `fields`
- **Decision**: `JsonFormatter.format(record)` constructs a dictionary with fixed top-level envelope keys in deterministic order: `ts` (UTC ISO-8601), `level`, `logger`, `msg`, `correlation_id`, and `fields`. Stage attributes are passed via `extra={"docpipe_fields": ...}` and emitted strictly nested under `payload["fields"]`, preventing collisions even if callers supply fields named `"ts"`, `"level"`, `"logger"`, `"msg"`, or `"correlation_id"`. Raw `exc_info` / `exc_text` tracebacks are excluded from JSON records.
- **Rationale**: Prevents untrusted stage attributes from corrupting envelope keys and prevents accidental credential/PII dumps from Python traceback locals or exception strings (`Q4`, `SC-005`). Safe `_json_default` converts non-JSON helper types (e.g., `Path`, `tuple`, `set`) via `os.fspath` / `list` / `str` so telemetry never breaks pipeline execution.
- **Alternatives Considered**: Flat `payload.update(extra)` with key filtering (rejected: fragile if new core keys are added and forces dropping user fields silently rather than isolating them cleanly under `"fields"`).

### Decision 4: Async-Safe & Thread-Safe `ContextVar` Correlation Scoping
- **Decision**: Store active trace ID in `_CORRELATION_ID: ContextVar[str | None] = ContextVar("docpipe_correlation_id", default=None)`. `correlation_id(value: str | None = None)` reuses the current active ID when `value is None` and an outer scope is active, otherwise generates `str(uuid.uuid4())` (or validates non-empty stripped `value`), and resets via `ContextVar.reset(token)` in `finally`.
- **Rationale**: `ContextVar` isolates concurrent `asyncio` tasks (each Task snapshots context) and separate threads automatically without shared locks or dict races. Outer scope reuse means multi-step flows (`CLI ask` -> `retrieve` + `answer_detailed`, `sync` -> changed doc extraction, `reindex`, `evaluate` -> loop of `retrieve`) naturally share one `correlation_id`.
- **Alternatives Considered**: `threading.local()` (rejected: shares IDs across `asyncio` tasks running on one thread).

### Decision 5: `stage_event` Context Manager with Summed Phase 1 Batch Summaries (`INFO`) & Per-Document Details (`DEBUG`)
- **Decision**:
  ```python
  @contextmanager
  def stage_event(
      logger: logging.Logger,
      stage: str,
      *,
      log_level: int = logging.INFO,
      **fields: Any,
  ) -> Iterator[dict[str, Any]]:
  ```
  `stage_event` yields a mutable `dict[str, Any]` seeded with `fields` so callers can populate runtime output counters (e.g., `hits`, `chunks`, `kept`) prior to exit, then logs `"stage.end"` at `log_level` on normal exit (`status="ok"`, `duration_ms`) or at `logging.ERROR` on exception (`status="error"`, `duration_ms`, `error_type=type(exc).__name__`) before re-raising.
  Inside Phase 1 (`ingest`, `sync`), a shared `_StageMetrics` helper tracks cumulative wall-clock `duration_ms` and counts across documents so `intake`, `clean`, `enrich`, `chunk`, `embed`, and `store` emit per-document `DEBUG` detail events (`intake`, `clean`, `enrich`, `chunk`) plus batch-scoped `INFO` `stage.end` summary events (`Q2`).
- **Rationale**: Avoids emitting `4 * N` `INFO` lines on large document batches while keeping per-file timing breakdowns one `--log-level DEBUG` flag away and partitioning total batch wall time cleanly across stages. Yielding `dict[str, Any]` rather than returning `None` avoids emitting duplicate `"stage.start"`/`"stage.end"` lines just to record runtime counts, while requiring no mandatory `as` binding.
- **Alternatives Considered**: Emitting per-doc events at `INFO` (rejected per `Q2`: noisy on multi-hundred-document directories); separate `start` + `end` events per stage (rejected: doubles log volume).

### Decision 6: Query `embed` vs `search` Boundaries & `guard_egress` / `answer` Boundaries
- **Decision**:
  - `DenseSearcher.search()` and `Fts5HybridSearcher.search()` wrap `embedder_inst.embed_query(...)` with `stage_event(..., "embed", operation="query", collection=collection, embed_model=embed_model)` (skipped naturally on empty-manifest / impossible-`where` short-circuits!).
  - `retrieve()` wraps `searcher_inst.search(...)` in `stage_event(..., "search", ...)` (covering custom registered searchers uniformly) and `reranker_cls().rerank(...)` in `stage_event(..., "rerank", ...)` when `rerank=True`.
  - `guard_egress()` emits `stage_event(..., "egress", ...)` only when remote PII egress scanning actually runs (remote target with `pii_policy` active and `egress != "allow"`), recording `egress_mode`, `message_count`, and redacted/blocked counts (zero plaintext!).
  - `answer_detailed()` wraps `litellm.completion(...)` + usage extraction inside `stage_event(..., "answer", model=model)` when `has_context=True` (recording `finish_reason`, `truncated`, and usage token counts; skipped when deterministic empty-context refusal avoids completion).
  - Outer `correlation_id()` scopes wrap `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `answer_detailed`, `evaluate`, and top-level CLI dispatch (`cli.main`).
- **Rationale**: Every Phase 1 & Phase 2 entry point and CLI command establishes correlation consistently (`Q5`), while optional/conditional stages (`rerank`, `egress`, `answer`, empty short-circuit `embed`) only emit when those stages genuinely execute (`FR-004`).

### Decision 7: CLI-Only `--log-json` and `--log-level` Setup & Deterministic Handler Cleanup
- **Decision**: Add `--log-json` (`store_true`) and `--log-level` (`choices=("DEBUG", "INFO", "WARNING", "ERROR")`, `type=str.upper`) to root `parser` and shared `common` parent parser in `src/docpipe_maestro/cli.py`, omitting `docpipe.toml` keys (`Q3`). In `main()`, attach `StreamHandler(sys.stderr)` dynamically onto `"docpipe_maestro"` inside a `contextlib.ExitStack` / `try...finally` helper (restoring previous logger level and removing/closing the handler on exit) and enter `with correlation_id():` around command execution. When `--log-level` is passed without `--log-json`, use `TextFormatter` emitting human-readable lines containing timestamp, level, `[correlation_id]`, logger name, message, and key=value fields to `stderr`.
- **Rationale**: Deferring `StreamHandler(sys.stderr)` creation until `main()` runs ensures `contextlib.redirect_stderr` and pytest `capsys` capture CLI output reliably; `finally:` cleanup guarantees repeated in-process `cli.main(...)` calls never stack duplicate handlers or alter direct library calls afterward.
