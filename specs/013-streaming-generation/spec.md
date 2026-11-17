# Feature Specification: Streaming Generation Support (`answer` & `ask --stream`)

**Feature Branch**: `feat/013-streaming-generation`  
**Created**: 2026-11-17  
**Status**: Draft  
**Input**: User description: "Implement roadmap item 6.2 (Streaming Generation Support) under Constitution v1.4.0 so callers can receive incremental text chunks synchronously during Phase 2 grounded generation and CLI `ask`: 1. Synchronous library streaming via `answer(..., stream=True)` returning `Iterator[str]`; 2. Upfront preflight & safety parity before stream iteration begins (including `has_context=False` short-circuit); 3. Stream error, truncation, and telemetry hygiene; 4. Real-time CLI `ask --stream` with stdout flushing, stderr isolation, and `--json` conflict handling; 5. Exclude HTTP/SSE servers, WebSockets, async frameworks, sessions, auth, and UIs per Constitution v1.4.0."

## Clarifications

### Session 2026-11-17

- Q: When `answer(..., stream=True)` is called, should the external LLM request start lazily on the first pulled chunk rather than eagerly at call time? → A: Run preflight validation and `guard_egress` eagerly at call time; open the LLM stream lazily on first iterator pull (Option A).
- Q: When `docpipe-maestro ask --stream` completes at a token limit with `finish_reason="length"` and `--fail-on-truncation` is off, should the CLI still print a truncation warning to `stderr`? → A: Emit the truncation warning on `stderr` after the streamed output via an internal metadata hook while keeping public `answer(..., stream=True) -> Iterator[str]` unchanged (Option A).
- Q: Should `--stream` on `docpipe-maestro ask` remain strictly a per-invocation CLI flag, or should it also be configurable via `docpipe.toml`? → A: Keep `--stream` strictly a per-invocation CLI flag (`default=False`, not read from `docpipe.toml`), matching `--json` and `--show-context` (Option A).

## Constitution Check

All requirements comply with [constitution.md](../../.specify/memory/constitution.md) (`v1.4.0`, ratified `2026-11-12`, last amended `2026-11-17`):

- **Scope Discipline (I)**: Exposes pull-based synchronous chunk iteration (`Iterator[str]`) via existing `answer()` and real-time terminal output via CLI `ask --stream` as permitted by v1.4.0, while keeping root public exports unchanged (`36` exports) and keeping HTTP/SSE APIs, WebSockets, async server frameworks, sessions, auth, and UIs excluded.
- **Two-Phase Architecture (II)**: Scoped strictly to Phase 2 optional generation and CLI `ask`, leaving Phase 1 ingestion and retrieval vector/lexical storage read-only and untouched.
- **Library Purity (III)**: Reads zero external configuration or policy files in library modules; `--stream` and TOML/CLI flag handling remain isolated in the CLI layer, and provider credentials remain environment-only.
- **Search Small, Return Big & Exception Preservation (IV, V)**: Reuses existing read-only parent retrieval cleanly and enforces `guard_egress()` pre-network PII scrubbing/blocking plus `local_only` validation before any network request or yielded chunk; Safety Gates (`reverse`, `pii`) remain green.
- **Provider Agnosticism & Local-First (VI)**: Works across local and cloud `provider/model` targets through the existing unified generation layer with zero new dependencies.
- **Structured Correctness (VII)**: Preserves existing `answer(...) -> str` default return behavior, normalizes streaming errors and truncation enforcement cleanly, and emits PII-safe correlated telemetry without logging raw generated content or secrets.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Synchronous Pull-Based Answer Streaming in Library Calls (Priority: P1)

A Python caller building a CLI utility or application pipeline wants to receive grounded answer text incrementally as tokens arrive from the language model instead of blocking until completion finishes. Calling `answer(..., stream=True)` returns a synchronous `Iterator[str]` yielding non-empty text chunks as the provider generates them, while default calls (`stream=False` or omitted) continue returning the complete stripped `str` answer unchanged and the root public export surface stays at `36` symbols.

**Why this priority**: Synchronous caller-pulled chunk iteration is the core library capability enabling responsive progressive rendering without changing any existing `answer()` callers or introducing async runtime complexity.

**Independent Test**: Can be validated directly by invoking `answer(prompt, stream=True)` against mock streaming responses (multiple deltas, blank role-only leading/trailing chunks, and `has_context=False`), verifying progressive non-empty `str` chunk yields, full joined text equivalence, and default `answer(prompt)` string return backward compatibility.

**Acceptance Scenarios**:

1. **Given** a valid prompt or role-separated message sequence and `has_context=True`, **When** a caller invokes `answer(prompt, stream=True)` and iterates the returned iterator chunk by chunk, **Then** each yielded item is a non-empty `str` text delta yielded in order without stripping internal/boundary whitespace inside tokens, and default `answer(prompt)` still returns a single complete stripped `str`.
2. **Given** a provider stream that emits non-content deltas (such as role-announcement frames with `None` or `""` content alongside metadata chunks), **When** iterating `answer(prompt, stream=True)`, **Then** empty deltas are skipped cleanly and only non-empty text deltas reach the caller.
3. **Given** an empty retrieval context (`has_context=False`), **When** a caller invokes `answer(prompt, has_context=False, stream=True)`, **Then** the returned iterator yields the canonical empty-context refusal once and completes with zero language-model provider requests.

---

### User Story 2 - Eager Preflight Validation, Safety Guarding, Error Normalization & Telemetry Hygiene (Priority: P1)

A security-conscious team invoking `answer(..., stream=True)` with `local_only=True`, custom `api_base`, parameter limits, or outbound PII policies needs identical fail-closed guarantees to non-streaming generation before any network connection opens, alongside credential-safe mid-stream error handling, truncation enforcement, and PII-safe observability logs. All validation and outbound PII inspection execute eagerly when `answer(..., stream=True)` is called (before any chunk is pulled or any provider request runs), while stream telemetry accurately spans the active generation session without logging raw prompt or generated token text.

**Why this priority**: Streaming must never bypass or delay safety gates until partial output has already been streamed or external egress has occurred.

**Independent Test**: Can be verified via offline safety and logging tests asserting immediate pre-network exceptions (`local_only` remote refusal, outbound `PiiBlockedError`, invalid generation parameter errors), outbound PII redaction across streamed messages, credential-scrubbed mid-stream provider exceptions, `fail_on_truncation` refusal on `finish_reason="length"`, and single correlated JSON telemetry events containing zero raw tokens or secrets.

**Acceptance Scenarios**:

1. **Given** a prompt containing sensitive entities and a blocking outbound PII policy—or a remote model with `local_only=True`, or invalid parameters (`timeout <= 0`, reserved `model_kwargs`, insecure plain-HTTP remote `api_base`)—**When** calling `answer(prompt, ..., stream=True)`, **Then** the corresponding typed `PiiBlockedError` or `DocpipeError` is raised immediately at call time before the caller consumes the first chunk and before any provider call is made.
2. **Given** an outbound PII policy configured to redact entities before remote generation, **When** calling `answer(prompt, model="openai/gpt-4o-mini", pii_policy=..., stream=True)`, **Then** outbound messages transmitted to the provider contain only redacted placeholders while emitting privacy-safe egress telemetry.
3. **Given** a streaming completion that raises an authentication/rate-limit/transport exception mid-stream containing a secret token or stops with `finish_reason="length"`, **When** iterating `answer(prompt, ..., fail_on_truncation=True, stream=True)`, **Then** mid-stream errors are normalized into typed `MissingCredentialError`/`DocpipeError` with secrets scrubbed, and `fail_on_truncation=True` raises `DocpipeError` cleanly upon reaching truncation at stream end.
4. **Given** logging is configured to capture structured stage telemetry, **When** consuming or aborting a streaming `answer(..., stream=True)` call, **Then** a correlated `stage.end` event for stage `"answer"` records status (`"ok"` or `"error"` with `error_type` on failure), duration, and optional finish/usage fields while emitting zero raw prompt text, generated tokens, PII, or credentials.

---

### User Story 3 - Real-Time Terminal Streaming via `docpipe-maestro ask --stream` (Priority: P2)

A terminal operator asking questions against an indexed knowledge base wants answers printed progressively to standard output as the language model generates them (`docpipe-maestro ask "<question>" --stream`), with immediate output flushing, retrieved section inspection (`--show-context`) and structured logs (`--log-json`) kept cleanly on standard error, truncation warnings reported on standard error, and conflicting JSON output mode (`--stream` combined with `--json`) refused clearly before retrieval or generation work begins.

**Why this priority**: Real-time terminal output eliminates perceived generation wait times in interactive CLI sessions while maintaining strict `stdout`/`stderr` separation for scripting safety.

**Independent Test**: Can be validated via CLI integration tests invoking `docpipe-maestro ask` with `--stream`, `--stream --show-context`, `--stream --log-json`, `--stream --fail-on-truncation`, `--stream` on empty context, and `--stream --json` conflict rejection, asserting progressive flushed writes, exit codes, and `stdout`/`stderr` isolation.

**Acceptance Scenarios**:

1. **Given** an indexed collection and matching context, **When** an operator runs `docpipe-maestro ask "What is the leave policy?" --stream`, **Then** text chunks are written sequentially and flushed immediately to `stdout` followed by a clean trailing newline, with exit code `0`.
2. **Given** `--stream` combined with `--show-context` and `--log-json`, **When** running `docpipe-maestro ask`, **Then** context summaries and JSON telemetry lines appear exclusively on `stderr` under one shared CLI correlation identifier while `stdout` contains only the streamed answer text.
3. **Given** an operator passes both `--stream` and `--json` to `docpipe-maestro ask`, **When** parsing CLI options, **Then** the command fails immediately with a non-zero exit status explaining that `--stream` and `--json` cannot be combined, performing zero retrieval or generation calls.
4. **Given** streaming generation hits `finish_reason="length"` under `ask --stream`, **When** `--fail-on-truncation` is false, **Then** a truncation warning is written to `stderr` after the streamed output with exit code `0`; when `--fail-on-truncation` is true, **Then** the command fails cleanly with exit status `1` and an error message on `stderr`.

---

### Edge Cases

- What happens when a streaming provider ends cleanly with zero non-empty text chunks (e.g., empty delta stream or reasoning-only stream truncated at token budget)? It MUST raise an explicit diagnostic error matching non-streaming empty-response behavior rather than silently returning nothing.
- What happens when a provider yields multiple finish/usage chunks or reports `finish_reason` on a penultimate chunk followed by a final usage-only chunk (`choices=[]` or empty delta)? Usage and finish state MUST preserve the last non-empty `finish_reason` observed across the stream without losing or crashing on trailing usage-only chunks.
- What happens when a provider chunk sets a refusal field (`delta.refusal` or choice refusal)? It MUST raise a typed generation error cleanly with sanitized context.
- What happens if a caller stops iterating `answer(..., stream=True)` early (breaks out of a loop / closes the iterator) or an unhandled exception occurs mid-stream? Underlying provider stream resources (when closeable) and active telemetry/correlation contexts MUST be cleaned up deterministically via `finally` / `.close()`, without leaking active correlation IDs or hanging handlers.
- What happens when `docpipe-maestro ask --stream` runs with `has_context=False` (zero retrieved chunks above threshold or empty collection)? It MUST stream/print the canonical refusal (`EMPTY_CONTEXT_REFUSAL`) cleanly to `stdout` and exit `0` with zero LLM network calls.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST extend `answer()` with an optional trailing keyword-only `stream: bool = False` option while keeping `answer(..., stream=False)` (default) returning a single stripped `str` and keeping root top-level exports unchanged at `36` symbols.
- **FR-002**: When `answer(..., stream=True)` is invoked, it MUST return a synchronous `Iterator[str]` yielding each non-empty text delta produced by the generation provider in arrival order without stripping whitespace within or at delta boundaries.
- **FR-003**: Preflight parameter validation (`timeout`, `temperature`, `max_tokens`, `model_kwargs` reserved-key checks, `api_base` validation), message normalization, `local_only` checks, and outbound `guard_egress()` PII redaction/blocking MUST execute eagerly at the call site of `answer(..., stream=True)` before returning the iterator, while opening the external LLM stream connection MUST be deferred lazily until the caller pulls the first chunk (so uniterated iterators perform zero provider network requests).
- **FR-004**: When `has_context=False` and `stream=True`, `answer()` MUST execute eager validation and `local_only` checks, invoke zero LLM completion requests, yield `EMPTY_CONTEXT_REFUSAL` once, and terminate cleanly.
- **FR-005**: Streaming generation MUST handle provider-specific empty deltas (`None` or `""`), trailing usage-only frames, provider refusals, empty-content/reasoning-only exhaustion errors, and mid-stream exceptions through the same normalized credential-safe error taxonomy (`MissingCredentialError`, `DocpipeError`, `PiiBlockedError`) as buffered generation.
- **FR-006**: When `fail_on_truncation=True` and the completed stream reports `finish_reason == "length"`, the iterator MUST raise `DocpipeError` cleanly upon reaching stream completion.
- **FR-007**: Streaming `answer(..., stream=True)` MUST preserve an active execution correlation context across iterator consumption, emit one correlated `stage.end` telemetry record for `"answer"` with completion metadata (`status`, `duration_ms`, optional `finish_reason`/`truncated`/token counts) upon finish, close, or failure, and emit zero raw prompts, streamed tokens, PII, or credentials.
- **FR-008**: CLI subcommand `docpipe-maestro ask` MUST accept `--stream` strictly as a per-invocation CLI boolean flag (default `False`, ignored if set in `docpipe.toml`) to invoke streaming generation, write each chunk to `stdout` immediately with unbuffered flushing, print a single clean trailing newline when finished, keep `--show-context` and `--log-json`/`--log-level` outputs strictly on `stderr`, emit the `stderr` truncation warning when `finish_reason == "length"` and `--fail-on-truncation` is off (using an internal metadata hook so public `answer(..., stream=True) -> Iterator[str]` stays unchanged), and handle `--fail-on-truncation` refusal and empty-context refusal consistently with non-streaming `ask`.
- **FR-009**: CLI `docpipe-maestro ask` MUST reject `--stream` and `--json` together with an explicit non-zero validation failure prior to retrieval or generation execution.
- **FR-010**: In compliance with Constitution v1.4.0 Principle I, HTTP servers, SSE endpoints, WebSockets, async runtime interfaces, persistent sessions, authentication layers, and UI components MUST remain outside feature scope.
- **FR-011**: Every user-facing documentation file (usage guides, CLI/API references, architecture notes, contributor/testing guide, roadmap backlog status, product overview, and `CHANGELOG.md` `## Unreleased` release notes) MUST be updated to document synchronous `answer(..., stream=True)` and CLI `ask --stream` behavior by completion.

### Key Entities

- **Generation Stream (`Iterator[str]`)**: Pull-based synchronous text delta iterator returned by `answer(..., stream=True)` emitting sequential non-empty response segments and guaranteeing cleanup of underlying provider stream resources and correlation scope on completion, early close, or error.
- **CLI Stream Mode (`ask --stream`)**: Real-time terminal output mode for `docpipe-maestro ask` mutually exclusive with `--json`, flushing answer deltas directly to `stdout` while keeping diagnostic context and telemetry isolated on `stderr`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In automated streaming integration tests, `answer(..., stream=True)` yields `100%` of non-empty response chunks sequentially and the concatenation matches expected streamed output character-for-character while preserving exact default `str` returns when `stream=False`.
- **SC-002**: Eager preflight safety checks reject `100%` of invalid parameters, `local_only` remote targets, and blocked outbound PII inputs immediately on call with zero yielded chunks and zero provider completion requests, passing all Safety Gates (`reverse` and `pii`).
- **SC-003**: Real-time CLI `ask --stream` writes chunks progressively with explicit stream flushes, produces clean parseable rejection on `--stream --json`, isolates all diagnostics and JSON logs strictly to `stderr`, and cleans up `100%` of early-closed or mid-stream-failing iterators with zero leaked correlation IDs or raw secrets.
- **SC-004**: Existing quality gates—formatter, linter, security static check, strict static type checking, all existing and new unit/CLI/logging/API-stability tests, and branch coverage threshold (`>= 80%`)—pass with `0` regressions.

## Assumptions

- `answer_detailed()` continues to return buffered `GenerationResult` metrics after full completion; `013-streaming-generation` scopes incremental text iteration strictly to `answer(..., stream=True)` and `docpipe-maestro ask --stream`.
- Because streamed chunks in CLI `--stream` mode are flushed incrementally to `stdout` before stream completion, truncation is surfaced via an internal stream-state hook: if `finish_reason="length"` occurs with `fail_on_truncation=False`, a truncation warning is emitted cleanly on `stderr` right after streaming finishes (and with `fail_on_truncation=True`, exits `1` via `DocpipeError` on `stderr`), while keeping `answer(..., stream=True) -> Iterator[str]` unchanged.
- CLI `--stream` is a CLI flag (`docpipe-maestro ask --stream`) rather than an automatic default, and when combined with `--json` is refused via standard mutually exclusive option parsing before any retrieval work runs.
- CLI `--stream` behaves strictly as a per-invocation CLI flag (`default=False`) alongside `--show-context` and `--json`, and is never loaded from `docpipe.toml` so config-backed automation runs using `--json` cannot suffer hidden option conflicts.
