# Data Model: Stage 8 Structured JSON Logging & Correlation Tracing

**Feature**: `011-structured-logging` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

## 1. Entities & Schemas

### 1.1 Structured Log Record (JSON Envelope)

Single-line JSON object serialized by `JsonFormatter.format(record)`:

| Envelope Key | Type | Always Present | Source / Rule |
|---|---|---|---|
| `ts` | `str` | Yes | UTC ISO-8601 timestamp (`datetime.fromtimestamp(record.created, timezone.utc).isoformat()`) |
| `level` | `str` | Yes | Standard severity string: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` (or `"CRITICAL"`) |
| `logger` | `str` | Yes | Originating Python logger name (e.g., `"docpipe_maestro.ingest.pipeline"`, `"docpipe_maestro._pii"`) |
| `msg` | `str` | Yes | Formatted log message (`"stage.end"` for timed stage events; existing diagnostic message for warnings) |
| `correlation_id` | `str \| None` | Yes | Active UUID trace ID from `record.correlation_id` or `get_correlation_id()`; `null` when outside any correlation scope |
| `fields` | `dict[str, Any]` | Yes | Nested structured attribute object (`{}` if none attached). Caller keys colliding with `ts`/`level`/`logger`/`msg`/`correlation_id` remain safely sandboxed inside `fields` |

Invariants:
- Serialized strictly on one line (`\n` escaped inside JSON strings; zero raw traceback blocks / `exc_info` appended — standalone `--log-level` `TextFormatter` enforces the same zero-traceback rule).
- Safe JSON fallback encoder (`_json_default`): `os.PathLike` -> `os.fspath()`, `set`/`tuple` -> `list()`, fallback -> `str()`.

---

### 1.2 Correlation Context

Thread-safe and async-task-safe trace identifier managed via `contextvars.ContextVar[str | None]`:

- Default value outside any scope: `None`
- Entering `with correlation_id(value=None) as cid:`:
  - If `value is not None`: validates `value.strip()` non-empty (`ValueError` otherwise) and binds explicit value.
  - Else if outer context is already active (`current is not None`): inherits/reuses `current` so multi-step operations (`CLI ask`, `sync`, `reindex`, `evaluate`) share one `correlation_id`.
  - Else: generates fresh UUID4 string `str(uuid.uuid4())`.
- Exiting scope (normal return or exception): unconditionally executes `_CORRELATION_ID.reset(token)` inside `finally`.

---

### 1.3 Canonical Stage Events (`msg = "stage.end"`)

Allowed stage names (strictly bounded canonical set):

| Phase | Stage Name | Default Severity (Outcome=`"ok"`) | Error Severity (Outcome=`"error"`) | Safe Metadata `fields` Allowed | Strictly Excluded (`INFO` & `DEBUG`) |
|---|---|---|---|---|---|
| Phase 1 | `intake` | `INFO` (batch summary) / `DEBUG` (per-doc) | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `docs`/`files`/`skipped`, `source`, `sections`, `error_type` | File text, extracted headings/content, filesystem paths outside `source` key if unnecessary, secrets |
| Phase 1 | `clean` | `INFO` (batch summary) / `DEBUG` (per-doc) | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `docs`, `source`, `sections`, `error_type` | Cleaned document strings, stripped HTML fragments |
| Phase 1 | `enrich` | `INFO` (batch summary) / `DEBUG` (per-doc) | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `profile`, `docs`, `source`, `pii_active`, `entities_detected`, `error_type` | Raw PII values, matched spans, document content, token salts, raw `PiiBlockedError` messages |
| Phase 1 | `chunk` | `INFO` (batch summary) / `DEBUG` (per-doc) | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `profile`, `docs`, `source`, `children`, `parents`, `error_type` | Chunk text, clause strings, metadata section titles if carrying text |
| Phase 1 | `embed` | `INFO` (batch summary) | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `embed_model`, `operation` (`"ingest"`/`"sync"`/`"reindex"`), `chunks`, `dim`, `error_type` | Embedded text batches, vectors, API keys, raw endpoint error bodies |
| Phase 1 | `store` | `INFO` | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `operation` (`"ingest"`/`"sync"`/`"remove"`/`"status"`/`"reindex"`), `source`, `added`/`updated`/`skipped`/`removed`, `children`, `parents`, `error_type` | Stored text payloads, vectors |
| Phase 2 | `embed` | `INFO` | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `embed_model`, `operation` (`"query"`), `error_type` | Raw query question string, query vector, API keys |
| Phase 2 | `search` | `INFO` | `ERROR` | `stage`, `status`, `duration_ms`, `collection`, `searcher`, `has_where`, `top_k`, `hits`, `parents`, `expand_parent`, `error_type` | Question text, raw `where` values if user text, returned chunk text |
| Phase 2 | `rerank` | `INFO` | `ERROR` | `stage`, `status`, `duration_ms`, `reranker`, `candidates`, `kept`, `error_type` | Question string, passage candidates, reranked text |
| Phase 2 | `egress` | `INFO` | `ERROR` | `stage`, `status`, `duration_ms`, `egress_mode`, `message_count`, `entities_detected`, `error_type` | Prompt text, ChatML contents, PII plaintext values |
| Phase 2 | `answer` | `INFO` | `ERROR` | `stage`, `status`, `duration_ms`, `model`, `finish_reason`, `truncated`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `total_tokens`, `error_type` | Prompt text, LLM completion answer text, API keys, raw HTTP error text |

Note on `fields` collision safety:
Inside `stage_event(...)`, core stage fields (`stage`, `status`, `duration_ms`, and `error_type` when failed) are written **after** merging caller `**fields` so computed timing and failure fields remain authoritative; inside `JsonFormatter`, the entire dictionary lives nested under `payload["fields"]`.

---

## 2. State Flows

### 2.1 CLI Telemetry Dispatch & Cleanup Flow

```text
cli.main(argv)
  ├─ argparse parse (--log-json, --log-level parsed before or after subcommand; TOML ignored)
  ├─ IF log_json or log_level set:
  │    ├─ save pkg_logger.level ("docpipe_maestro")
  │    ├─ compute effective_level = log_level or "INFO"
  │    ├─ attach temporary StreamHandler(sys.stderr) with JsonFormatter() or TextFormatter()
  │    └─ set pkg_logger.level = effective_level
  ├─ with correlation_id():
  │    └─ execute subcommand (ingest / sync / status / remove / reindex / query / ask / eval)
  │         └─ all nested library calls inherit same UUID correlation_id
  └─ finally:
       └─ remove & close temporary StreamHandler; restore previous pkg_logger.level
```

### 2.2 Host Library Usage Flow

```text
Host App:
  ├─ Default (no handler attached): pkg_logger ("docpipe_maestro") holds NullHandler only, level=NOTSET
  │    └─ ingest()/retrieve()/etc. emit to NullHandler -> 0 stdout, 0 stderr, root logger untouched
  └─ Host configures handler + level on get_logger():
       └─ ingest()/retrieve()/answer_detailed() bind ContextVar correlation_id
            └─ emitted LogRecords flow to host handler with nested fields & shared UUID correlation_id
```
