# Implementation Plan: Structured JSON Logging & Correlation Tracing

**Branch**: `011-structured-logging` (git `feat/011-structured-logging`) | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/011-structured-logging/spec.md`

## Summary

Add opt-in, PII-safe structured JSON telemetry and execution-context-isolated correlation IDs across Phase 1 and Phase 2 pipeline stages without polluting root loggers or `stdout`. A new phase-neutral module `src/docpipe_maestro/log.py` (stdlib-only) exports `get_logger()` (`NullHandler`-only by default), `JsonFormatter` (fixed `{ts, level, logger, msg, correlation_id, fields}` JSON lines with traceback suppression), `TextFormatter`, `ContextVar`-backed `correlation_id()` / `get_correlation_id()`, and `stage_event(logger, stage, *, log_level=INFO, **fields)` timing helpers (`duration_ms`, `status`, `error_type`). All Phase 1 entry points (`ingest`, `sync`, `remove`, `status`, `reindex`) and Phase 2 entry points (`retrieve`, `answer_detailed`, `evaluate`) open/inherit `correlation_id()` scopes, emitting `INFO` batch summaries plus `DEBUG` per-doc details in Phase 1 (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`) and `INFO` stage events in Phase 2 (`embed`, `search`, `rerank`, `egress`, `answer`). `cli.py` adds CLI-only global `--log-json` and `--log-level {DEBUG,INFO,WARNING,ERROR}` flags attaching a temporary `StreamHandler(sys.stderr)` torn down cleanly in `finally`.

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)  
**Primary Dependencies**: Python standard library only (`contextvars`, `datetime`, `json`, `logging`, `os`, `time`, `uuid`, `collections.abc`, `contextlib`, `typing`) — zero new third-party dependencies  
**Storage**: Ephemeral stream emission (`stderr` in CLI, host-attached `logging.Handler` in library usage) — zero file log persistence or rotation (`Out of Scope` per spec)  
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `pytest -m pii` (Release Gate #2), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests`  
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`)  
**Project Type**: Single Python library + CLI package (`src/docpipe_maestro/`, `tests/`, `docs/`)  
**Performance Goals**: Near-zero overhead when logging is disabled (`NullHandler`-only); `time.perf_counter()` millisecond measurement (`duration_ms`); bounded `INFO` emission (`6` summary events per Phase 1 batch regardless of document count)  
**Constraints**: Preserve Principle II phase separation (`log.py` imports stdlib only; `query/` never imports `ingest/`); preserve Principle III (zero `docpipe.toml` log keys; no `basicConfig` or root logger mutation; root `__all__` stays at `36` exports); enforce zero raw PII, prompts, answers, chunk bodies, raw exception messages, or credentials across all `INFO`/`DEBUG` telemetry; `stdout` stays clean JSON under `--json`  
**Scale/Scope**: 10 canonical stage identifiers (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`, `search`, `rerank`, `egress`, `answer`), 5 Phase 1 entry points, 3 Phase 2 entry points + `guard_egress` + searchers, 8 CLI subcommands via shared parent parser, reference docs (`docs/architecture.md`, `docs/cli-reference.md`, `docs/api-reference.md`) and `CHANGELOG.md`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verified against `.specify/memory/constitution.md` (`v1.3.1`, ratified `2026-11-12`, last amended `2026-11-15`):

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
|---|---|---|---|
| I. Scope Discipline | Telemetry exposed passively via `docpipe_maestro.log` + existing CLI flags `--log-json` / `--log-level`; zero HTTP endpoints, collectors, or log rotation daemons; root `__all__` stays at 36 exports | PASS | PASS |
| II. Two-Phase Architecture | Shared phase-neutral `src/docpipe_maestro/log.py` imports only Python stdlib; Phase 2 retrieval/generation remain strictly read-only with zero Phase 1 imports | PASS | PASS |
| III. Library Purity | Zero config-file reads in `log.py`; `docpipe.toml` intentionally excludes `log_json`/`log_level`; `cli.py` is the sole boundary configuring transient `StreamHandler(sys.stderr)` cleaned up in `finally`; library attaches only `NullHandler` and never alters root logger | PASS | PASS |
| IV. Search Small, Return Big | Stage timing/correlation wrappers observe `retrieve()` and `searcher.search()` passively without changing child-only matching, parent deduplication, or score semantics | PASS | PASS |
| V. Exception Preservation & Safety Gates | Stage failure emits `ERROR` `stage.end` (`status="error"`, `error_type` class name only) and immediately re-raises original exception unmodified; Release Gate #1 (`reverse`) & Release Gate #2 (`pii`) stay green with zero raw PII/secret leaks even at `DEBUG` | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Completely offline stdlib implementation with `0` extra network calls and `0` runtime dependencies added | PASS | PASS |
| VII. Structured Correctness & Quality Gates | Typed `mypy --strict` helpers (`stage_event` returns `Iterator[dict[str, Any]]`); AST purity + handler isolation + async/thread `ContextVar` tests added alongside CLI & PII log leak tests | PASS | PASS |

**Gate Outcome**: **PASS** (0 Constitution violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/011-structured-logging/
├── plan.md                             # This file (/speckit-plan output)
├── research.md                         # Phase 0 research decisions & compatibility audit
├── data-model.md                       # Phase 1 envelope schema, Correlation Context & stage matrix
├── quickstart.md                       # Phase 1 runnable validation & verification guide
├── contracts/
│   └── structured-logging.md           # Phase 1 log module, stage instrumentation & CLI contracts
├── checklists/
│   └── requirements.md                 # Completed spec quality checklist (16/16)
├── spec.md                             # Clarified Stage 8 specification
└── tasks.md                            # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/docpipe_maestro/
├── log.py                              # [NEW] LOGGER_NAME, JsonFormatter, TextFormatter, get_logger,
│                                       #       ContextVar correlation_id/get_correlation_id, stage_event
├── ingest/
│   └── pipeline.py                     # [MODIFY] Add correlation_id() on ingest/sync/remove/status/reindex;
│                                       #          shared _StageMetrics accumulator + DEBUG/INFO stage_event hooks
├── query/
│   ├── retriever.py                    # [MODIFY] Wrap retrieve() in correlation_id(); stage_event for search & rerank
│   ├── searcher/
│   │   ├── dense.py                    # [MODIFY] Wrap embed_query() in stage_event("embed", operation="query")
│   │   └── hybrid.py                   # [MODIFY] Wrap embed_query() in stage_event("embed", operation="query")
│   ├── egress.py                       # [MODIFY] Wrap active remote PII scrub/block in stage_event("egress")
│   └── answer.py                       # [MODIFY] Wrap answer_detailed() in correlation_id(); litellm.completion in stage_event("answer")
├── eval/
│   └── harness.py                      # [MODIFY] Wrap evaluate() in correlation_id()
└── cli.py                              # [MODIFY] Add global --log-json & --log-level flags + _cli_logging_scope + outer correlation_id()

tests/
├── test_logging.py                     # [NEW] Formatter, NullHandler silence, root isolation, async/thread ContextVar,
│                                       #       all 10 stage events, failure error_type hygiene, PII/secret DEBUG scan, CLI stderr/stdout tests
├── test_cli.py                         # [MODIFY] Global --log-json / --log-level placement, invalid level rejection, stdout JSON purity
├── test_library_purity.py              # [MODIFY] Guard log.py against ingest/query/store/embedder & config imports
└── test_pii_safety.py                  # [MODIFY] Verify PII/egress telemetry leak invariants under DEBUG JSON logging

docs/
├── architecture.md                     # [MODIFY] Document docpipe_maestro.log module, NullHandler contract, JSON schema & stage names
├── cli-reference.md                    # [MODIFY] Document --log-json, --log-level, stderr isolation, and non-TOML behavior
└── api-reference.md                    # [MODIFY] Document docpipe_maestro.log public submodule exports while root __all__ stays at 36

CHANGELOG.md                            # [MODIFY] Add Stage 8 structured logging entry under ## Unreleased
```

**Structure Decision**: Maintain the existing flat phase-aware layout under `src/docpipe_maestro/`, introducing `log.py` at the package root alongside `_filters.py` and `_pii.py` so both Phase 1 (`ingest/`) and Phase 2 (`query/`, `eval/`) depend inward on a single stdlib-only shared utility.

## Complexity Tracking

No Constitution violations require justification.
