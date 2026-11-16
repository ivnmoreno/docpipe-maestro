# Feature Specification: Structured JSON Logging & Correlation Tracing

**Feature Branch**: `feat/011-structured-logging`  
**Created**: 2026-11-16  
**Status**: Draft  
**Input**: User description: "Add opt-in structured JSON logging and per-operation correlation IDs across Phase 1 and Phase 2 pipeline stages without configuring root loggers, leaking stdout noise, or logging raw secrets/PII."

## Clarifications

### Session 2026-11-16

- Q: Should host-facing structured logging helpers be exposed exclusively from a dedicated logging submodule, or also re-exported at the top-level package root? → A: Expose structured logging helpers exclusively from a dedicated logging submodule (`docpipe_maestro.log`), keeping top-level root package exports unchanged.
- Q: How should per-document preparation steps (intake, clean, enrich, chunk) emit stage timing events during multi-file ingestion or synchronization? → A: Emit batch-scoped `stage.end` summary events for `intake`, `clean`, `enrich`, `chunk`, `embed`, and `store` at `INFO`, plus per-document detail events at `DEBUG`.
- Q: How should `--log-json` and `--log-level` activate CLI stderr logging, and should TOML config files also configure those telemetry settings? → A: Treat telemetry strictly as CLI flags (no `docpipe.toml` keys); `--log-json` alone emits `INFO` JSON on `stderr`, `--log-level` alone emits formatted text on `stderr` at that level, and omitting both leaves CLI diagnostic logging disabled.
- Q: When a pipeline stage raises an error, what severity level and failure details should the stage failure event log? → A: Emit failed `stage.end` at `ERROR` with `duration_ms`, `status="error"`, and `error_type` (exception class name only), excluding raw exception messages and stack traces even at `DEBUG`.
- Q: Should top-level CLI commands (such as `ask`, `eval`, `reindex`) and remaining lifecycle entry points (`reindex`, `remove`, `status`, `evaluate`) also open an outer correlation scope? → A: Yes — open an outer correlation scope at top-level CLI subcommand dispatch and across `reindex`, `remove`, `status`, and `evaluate` alongside `ingest`, `sync`, `retrieve`, and `answer_detailed`, so all nested steps share one `correlation_id`.

## Constitution Check

All requirements comply with [constitution.md](../../.specify/memory/constitution.md) (`v1.3.1`, ratified `2026-11-12`, last amended `2026-11-15`):

- **Scope Discipline (I)**: Exposes opt-in structured operational telemetry strictly through existing ingestion, retrieval, and question-answering workflows and the CLI — keeping the core library focused on the RAG engine with zero external telemetry servers, log rotation daemons, or application UI/framework layers.
- **Two-Phase Architecture (II)**: Uses a shared, phase-neutral telemetry utility to observe both Phase 1 offline ingestion workflows (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`) and Phase 2 online query workflows (`search`, `rerank`, `egress`, `answer`) without introducing writes or state mutations into Phase 2.
- **Library Purity (III)**: Core library logging remains strictly passive and unconfigured at import or execution time (attaching only a silent no-op handler on the library logger namespace, never mutating the host application's root logger, and never writing telemetry to stdout). Only the CLI boundary parses `--log-json` / `--log-level` and attaches an active error-stream handler.
- **Search Small, Return Big & Exception Preservation (IV, V)**: Telemetry instrumentation wraps existing stage execution passively without altering child-to-parent retrieval semantics or exception preservation (**Release Gate #1**).
- **Privacy, Data Protection & Egress Coordination (V, Data & Privacy)**: Coordinates strictly with existing Stage 4 PII protections (**Release Gate #2**) by omitting raw document content, user questions, prompt messages, chunk text, raw PII values, and provider credentials from all structured log payloads.
- **Provider Agnosticism, Local-First & Footprint (VI, VII, Footprint)**: Operates offline with zero added runtime dependencies and negligible overhead when logging is disabled by default.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Host Applications Collect Correlated Pipeline Telemetry (Priority: P1)

An engineering team embeds `docpipe-maestro` inside a host service or batch worker that already owns logging configuration. When the host application attaches its own structured handler to the `docpipe_maestro` logger namespace, every Phase 1 ingestion or synchronization run and every Phase 2 retrieval or question-answering run automatically assigns and propagates a shared `correlation_id` across all stages executed during that invocation, emitting timed `stage.end` events (`duration_ms` plus safe counts and statuses) without `docpipe-maestro` altering root logger handlers, changing global log levels, or writing unexpected noise to standard output.

**Why this priority**: Silent default behavior and leak-free host observability are foundational library contracts; host applications fail cleanly or break JSON pipelines immediately if embedded libraries touch root loggers or stdout.

**Independent Test**: Can be fully tested in an isolated process by verifying root logger handlers, package logger handler behavior, and captured standard output remain completely untouched during default library ingestion and retrieval runs, and by attaching a capturing handler to `docpipe_maestro` to verify every emitted record parses as valid JSON sharing a single non-empty UUID `correlation_id` across stages.

**Acceptance Scenarios**:

1. **Given** a host application has not configured any handler on `docpipe_maestro`, **When** it runs document ingestion, synchronization, retrieval, or question answering, **Then** the root logger remains unconfigured/unchanged, no unsolicited log lines appear on `stdout` or `stderr`, and only a silent no-op handler is present on the library logger.
2. **Given** a host application attaches a custom JSON-formatted handler to the `docpipe_maestro` logger, **When** it invokes ingestion or retrieval, **Then** every stage event emitted during that operation parses cleanly as single-line JSON with envelope keys (`ts`, `level`, `logger`, `msg`, `correlation_id`), nests safe operational attributes under `fields` without overwriting envelope keys, and shares the same UUID `correlation_id` across all stages of that run.
3. **Given** multiple concurrent or interleaved executions run in the same host process, **When** two retrieval or ingestion requests execute concurrently, **Then** each execution retains its own isolated `correlation_id` without cross-request identifier bleed.

---

### User Story 2 - CLI Operators Stream Structured Diagnostics Without Polluting Output (Priority: P1)

An operator or DevOps engineer running batch ingestion or debugging query latency from the command line passes global `--log-json` and/or `--log-level INFO` flags (either before or after the subcommand name) alongside standard commands such as `ingest`, `sync`, `query`, `ask`, or `eval`. Structured JSON timing and outcome events stream strictly to `stderr` while normal human responses and `--json` command payloads remain clean and parseable on `stdout`.

**Why this priority**: Operators frequently pipe CLI `--json` output directly into downstream tools or log shippers; mixing diagnostic logs into `stdout` would corrupt structured CLI responses.

**Independent Test**: Can be fully tested across representative CLI invocations (`ingest`, `query --json`, `ask --json`) with `--log-json` and `--log-level` placed both before and after subcommands, verifying `stdout` remains valid machine-parseable output while every line on `stderr` parses as a correlated single-line JSON log record.

**Acceptance Scenarios**:

1. **Given** a corpus directory ready for indexing, **When** a user runs `docpipe-maestro --log-json --log-level INFO ingest ./docs` (or places those flags after `ingest`), **Then** single-line JSON stage events (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`) appear on `stderr` sharing one `correlation_id` while `stdout` reports only the command result.
2. **Given** an operator pipelines CLI JSON output into another parser, **When** they run `docpipe-maestro --log-json --log-level INFO query "..." --json`, **Then** `stdout` parses cleanly as the pure query JSON object with zero interleaved log lines while `stderr` carries single-line JSON stage events (`embed`, `search`, `rerank`, if enabled, and retrieval completion).
3. **Given** `--log-level WARNING` or `--log-level ERROR` is configured without verbose telemetry, **When** a normal non-failing command runs, **Then** informational stage timing events are suppressed according to the chosen threshold while warnings and failures still appear at the configured severity.

---

### User Story 3 - Sensitive Data & Credentials Never Leak Into Telemetry Logs (Priority: P1)

A security-conscious organization runs ingestion and question answering on sensitive internal policies containing personal identifiers, credentials, prompts, and proprietary text with structured telemetry enabled. Telemetry logs record only safe operational metadata — such as stage names, durations in milliseconds, chunk/document counts, status indicators, profile names, redaction action summaries, and source identifiers — and never log API keys, raw document text, user questions, prompt text, raw chunk content, or unredacted PII at any telemetry level (`INFO` or `DEBUG`).

**Why this priority**: Constitution §Data and Privacy mandates zero credentials and zero raw PII in logs and error telemetry, aligning Stage 8 directly with Release Gate #2 (`009-pii-protection`).

**Independent Test**: Can be fully tested by enabling `DEBUG`-level JSON telemetry across workflows containing known synthetic PII entities, prompts, secret-looking environment credentials, and raw document passages (including PII-blocked ingest failures and remote outbound egress guards) and asserting zero forbidden raw values appear anywhere in emitted log records.

**Acceptance Scenarios**:

1. **Given** an ingested document containing protected PII (such as an identifier that triggers redaction or blocking under an active PII policy), **When** ingestion completes or halts with a blocked-PII error while `DEBUG` JSON logging is enabled, **Then** emitted stage events record only safe diagnostics (stage name, `duration_ms`, failure/outcome flag, safe entity/chunk counts) and contain zero raw PII text, zero raw document body text, and zero sensitive matched substrings.
2. **Given** a retrieval or question-answering workflow using remote provider credentials and user questions, **When** `DEBUG` structured logging runs across `search`, `egress`, and `answer` stages, **Then** no raw user question string, outbound prompt payload, retrieved passage body, or API key appears anywhere in the captured JSON log stream.

---

### Edge Cases

- **Stage failures & interrupted pipelines**: If a pipeline stage raises an error mid-operation (such as a blocked-PII error, missing extra error, or model/provider failure), the stage boundary must emit an `ERROR`-level `stage.end` failure event carrying `duration_ms`, `status="error"`, `error_type` (exception class name only), and the active `correlation_id` before re-raising, excluding raw exception messages and stack traces at all severity levels (including `DEBUG`) so untrusted text or credentials never leak.
- **Repeated CLI invocations in one process**: Executing the CLI entry point multiple times within the same process (such as automated test suites or scripting harnesses) must not accumulate duplicate stderr handlers, leak active handlers to direct library callers afterward, or mutate the root logger.
- **Reserved envelope field collisions**: If a stage caller or extension logs custom metadata attempting to pass keys named `ts`, `level`, `logger`, `msg`, or `correlation_id`, placing custom attributes inside the nested `fields` dictionary prevents callers from corrupting or overwriting core JSON envelope attributes.
- **Nested multi-step workflows**: When a higher-level workflow calls nested pipeline functions (for example, CLI `ask` calling retrieval followed by egress and answer generation, or `sync` calling ingestion for multiple updated documents), a single outer `correlation_id` spans the entire invocation rather than fragmenting stages across disconnected trace IDs.
- **Caller-supplied correlation context**: When a host application establishes an outer correlation identifier before calling a library function, nested pipeline operations respect and reuse that active identifier rather than silently discarding it, and restore prior correlation context upon exit even when exceptions occur.
- **Non-JSON serializable custom field values**: Passing safe helper objects (such as filesystem paths, numeric summaries, or boolean flags) in event fields serializes deterministically into valid JSON without raising serialization crashes that break the pipeline.
- **Logging disabled performance / minimal overhead**: When neither a host handler nor CLI logging flags are enabled (or the logger threshold suppresses a stage's severity), telemetry helpers must short-circuit record allocation and JSON formatting based on logger level enablement so disabled logging incurs negligible runtime overhead and leaves all existing outputs, timings, and safety gates untouched.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The library MUST expose its passive structured telemetry interface exclusively from the dedicated `docpipe_maestro.log` submodule under the `docpipe_maestro` logger namespace — leaving top-level package root exports unchanged, attaching only a silent no-op handler by default, NOT attaching output stream handlers on import or during library execution, NOT configuring or mutating the host process root logger, and NOT altering host stdout output.
- **FR-002**: Every structured JSON log record MUST emit a single-line JSON object containing the core envelope keys:
  - `ts`: UTC ISO-8601 timestamp string
  - `level`: Log severity name (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
  - `logger`: Originating logger name
  - `msg`: Event message identifier (including `stage.end` for timed pipeline stage events)
  - `correlation_id`: Active trace identifier string (or `null` when no operation correlation context is active)
  - `fields`: Dedicated nested object holding stage/event attributes (including numeric `duration_ms` for timed stage events) so event-specific keys cannot overwrite top-level envelope keys (`ts`, `level`, `logger`, `msg`, `correlation_id`).
- **FR-003**: The telemetry interface MUST manage execution-context-isolated correlation IDs (async-safe and thread-safe) such that:
  - Entering an explicit correlation context sets an identifier for the active execution flow (generating a unique UUID when none is supplied or active, or reusing an explicit/active outer identifier when present unless overridden intentionally).
  - Exiting or failing within that context reliably restores the previous correlation context state without leaking across concurrent tasks or subsequent unrelated calls.
- **FR-004**: Pipeline stage instrumentation MUST establish outer correlation scoping at Phase 1 entry points (`ingest`, `sync`, `reindex`, `remove`, `status`), Phase 2 entry points (`retrieve`, `answer_detailed`, `evaluate`), and top-level CLI subcommand dispatch (ensuring multi-step flows such as CLI `ask`, `reindex`, and `evaluate` share a single outer `correlation_id`), and MUST emit timed `stage.end` telemetry events (`duration_ms` plus safe operational outcome status and numeric counts) across active pipeline stages:
  - Phase 1 stages: emit batch-scoped `INFO`-level `stage.end` summary events for `intake`, `clean`, `enrich`, `chunk`, `embed`, and `store` sharing the operation's `correlation_id`, plus per-document `DEBUG`-level events for `intake`, `clean`, `enrich`, and `chunk`.
  - Phase 2 stages: emit `INFO`-level `stage.end` events for `embed` (query embedding when executed), `search`, `rerank` (when reranking runs), `egress` (when remote egress protection runs), and `answer` (when generation runs).
- **FR-005**: Stage failure telemetry MUST emit an `ERROR`-level `stage.end` event recording `duration_ms`, `status="error"`, and `error_type` (the exception class name only) — excluding raw exception messages and stack traces across all severity levels including `DEBUG` — before propagating the original exception without masking it.
- **FR-006**: Privacy and secret hygiene MUST enforce strict redaction boundaries on default `INFO` and `DEBUG` telemetry logs: structured events MUST NOT log raw document contents, raw chunk text, raw user question strings, outbound prompt messages, LLM completion text, raw PII values, or provider API keys/credentials; telemetry MAY include safe operational counters, collection/profile identifiers, stage identifiers, boolean flags, elapsed durations, and safe document source keys/version digests consistent with Constitution §Data and Privacy.
- **FR-007**: The CLI boundary MUST accept global CLI-only telemetry options `--log-json` and `--log-level {DEBUG,INFO,WARNING,ERROR}` (without supporting telemetry keys in `docpipe.toml`), accessible before or after subcommand names across CLI subcommands:
  - Passing `--log-json` alone emits single-line JSON on `stderr` defaulting to `INFO` severity; passing `--log-level` alone emits human-readable formatted text on `stderr` at the requested threshold; passing both emits single-line JSON at the requested severity; omitting both keeps CLI diagnostic telemetry disabled.
  - CLI stream logging MUST be configured exclusively inside the CLI dispatch lifecycle without altering library-level defaults, MUST clean up CLI-attached handlers after CLI dispatch completes, and MUST keep `stdout` strictly free of log lines across both text and `--json` outputs.
- **FR-008**: User-facing reference documentation (`docs/architecture.md`, `docs/cli-reference.md`, and `docs/api-reference.md`) and `CHANGELOG.md` (`## Unreleased`) MUST be updated to describe structured logging behavior, the silent-by-default library logger policy, `docpipe_maestro.log` exports, core JSON envelope fields, covered pipeline stages, privacy exclusions, and CLI `--log-json` / `--log-level` usage.
- **FR-009**: All changes MUST preserve existing public API stability contracts, strict static type checking, lint/security compliance, **Release Gate #1** (Exception Preservation), and **Release Gate #2** (PII Safety).

### Key Entities

- **Structured Log Record**: A single-line JSON diagnostic payload consisting of core envelope metadata (`ts`, `level`, `logger`, `msg`, `correlation_id`) plus a nested `fields` dictionary containing stage metrics and safe operational attributes.
- **Correlation Context**: An execution-context-isolated trace scope binding a UUID `correlation_id` to an entire logical operation (ingestion batch, sync run, retrieval query, or question-answering flow) and restoring previous state upon completion or error.
- **Stage Event**: A timed boundary measurement emitted upon completion or failure of a discrete pipeline stage (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`, `search`, `rerank`, `egress`, `answer`), capturing elapsed milliseconds (`duration_ms`), outcome status, and sanitized summary counts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of direct library calls (`ingest`, `sync`, `reindex`, `remove`, `status`, `retrieve`, `answer_detailed`, `evaluate`) executed without host logging configuration leave root logger handlers unchanged and emit 0 unexpected lines to `stdout` and `stderr`.
- **SC-002**: 100% of log records captured via host handler attachment or CLI `--log-json` parse cleanly as valid single-line JSON conforming to the envelope schema (`ts`, `level`, `logger`, `msg`, `correlation_id`, `fields`), with 0 overwrites of reserved envelope keys and accurate numeric `duration_ms` timing on every executed stage (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`, `search`, `rerank`, `egress`, `answer`).
- **SC-003**: 100% of stages executed within a single logical library operation or CLI subcommand invocation (including multi-step `ask`, `reindex`, and `evaluate` flows) share one non-empty UUID `correlation_id`, and concurrent overlapping executions exhibit 0 cross-operation identifier contamination.
- **SC-004**: 100% of CLI commands invoked with `--log-json` / `--log-level` emit logs exclusively to `stderr`, leaving `stdout` 100% valid JSON under `--json` flags across all subcommands.
- **SC-005**: 0 raw user questions, document passages, prompts, completion responses, synthetic PII entities, or provider credentials appear across all captured `INFO` and `DEBUG` JSON telemetry logs (verified automatically alongside **Release Gate #1**, **Release Gate #2**, formatting, security lint, and full automated tests).

## Assumptions

- **CLI-only telemetry scope**: `docpipe.toml` excludes `log_json`/`log_level` configuration keys so runtime diagnostic verbosity stays an explicit per-invocation CLI choice like `--json`. Passing `--log-json` alone defaults to `INFO` JSON on `stderr`, passing `--log-level` alone emits human-readable formatted logs on `stderr` at that level, and omitting both keeps CLI stderr telemetry quiet (aside from existing error/status messages).
- **Per-stage granularity during batch ingestion**: Multi-document `ingest()` / `sync()` runs emit aggregated batch-scoped `INFO` `stage.end` summaries (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`) so default telemetry stays concise, while `--log-level DEBUG` (or host `DEBUG` collection) unlocks per-document timing attribution for `intake`, `clean`, `enrich`, and `chunk` under the same batch `correlation_id`.
- **Correlation nesting semantics**: If an outer `correlation_id` is already active when a pipeline function starts (e.g., CLI `ask` wrapping `retrieve` + `answer_detailed`, or a host service setting its own correlation ID), the inner operation reuses that active `correlation_id` by default rather than minting an unrelated ID.
- **Out of Scope**: OpenTelemetry SDK or collector exporter integrations, distributed cross-process trace headers (W3C Trace Context over HTTP), log file rotation/persistence daemons, configurable custom PII scrubbing DSLs on log lines, and logging raw prompt/completion transcripts for debugging.
