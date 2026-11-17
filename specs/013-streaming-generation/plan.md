# Implementation Plan: Streaming Generation Support (`answer` & `ask --stream`)

**Branch**: `013-streaming-generation` (git `feat/013-streaming-generation`) | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from [spec.md](spec.md)

## Summary

Add pull-based synchronous text chunk streaming to Phase 2 grounded generation (`answer(..., stream=True) -> Iterator[str]`) and real-time unbuffered terminal output via CLI `docpipe-maestro ask --stream` under Constitution `v1.4.0`. Eagerly validate all generation parameters (including reserving `"stream"` in `_RESERVED_MODEL_KWARGS`), normalize messages, and execute `guard_egress` (`local_only` and outbound PII scrubbing/blocking) at call time before returning the iterator, while opening the upstream provider stream lazily on first iterator pull, preserving trailing usage/finish frames across chunks, normalizing errors and `fail_on_truncation`, deterministically cleaning up stream resources and `stage_event`/`correlation_id` contexts on completion or early `.close()`, keeping root `docpipe_maestro.__all__` at `36` exports, and updating every user-facing documentation file (`README.md`, `PRODUCT.md`, `docs/*`, `CHANGELOG.md`).

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)  
**Primary Dependencies**: Existing core dependencies only (`litellm.completion(..., stream=True)` via `prepare_litellm()`, stdlib `collections.abc.Iterator`, `sys`, `contextlib`) — zero new third-party dependencies  
**Storage**: Strictly read-only / none (Phase 2 generation only; zero Phase 1 storage, manifest, or lexical changes)  
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `pytest -m pii` (Release Gate #2), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests`  
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`)  
**Project Type**: Single Python library + CLI package (`src/docpipe_maestro/`, `tests/`, `docs/`)  
**Performance Goals**: Zero artificial buffering or chunk consolidation on yielded deltas; immediate `stdout.flush()` per chunk in CLI `--stream` mode; zero provider/LiteLLM imports when `has_context=False` or when uniterated  
**Constraints**: Enforce Constitution `v1.4.0` (`Iterator[str]` sync streaming only; zero HTTP/SSE/WebSocket servers, UIs, or async frameworks); preserve `len(docpipe_maestro.__all__) == 36` root API invariant; preserve default `answer(...) -> str`; ignore `stream` in `docpipe.toml`; reject `--stream --json` together cleanly; zero raw PII/prompt/token/credential emission in logs or errors  
**Scale/Scope**: `query/answer.py` (`@overload` `answer(..., stream=...)`, `_GenerationStreamState`, `_stream_answer_with_state`, shared `_prepare_generation_request`), `cli.py` (`p_ask` mutually exclusive `--stream` / `--json`, `_handle_ask`), `tests/` (`test_prompts_answer.py`, `test_cli.py`, `test_pii_safety.py`, `test_logging.py`, `test_api_stability.py`), and all user-facing docs (`README.md`, `PRODUCT.md`, `docs/README.md`, `docs/cli-reference.md`, `docs/api-reference.md`, `docs/architecture.md`, `docs/development.md`, `docs/future-features.md`, `CHANGELOG.md`)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verified against `.specify/memory/constitution.md` (`v1.4.0`, ratified `2026-11-12`, last amended `2026-11-17`):

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
|---|---|---|---|
| I. Scope Discipline | Sync caller-pulled `Iterator[str]` in `answer()` and CLI `ask --stream` only; HTTP/SSE, WebSockets, async frameworks, UIs excluded; root `__all__` stays `36` | PASS | PASS |
| II. Two-Phase Architecture | Scoped strictly to Phase 2 (`query/answer.py`, `cli.py` `ask`); Phase 1 and stores remain untouched and read-only | PASS | PASS |
| III. Library Purity | Zero config file reads in library modules; `--stream` stays strictly CLI-only (never read from `docpipe.toml`); credentials remain env-only | PASS | PASS |
| IV. Search Small, Return Big | Reuses Phase 2 parent retrieval and ChatML prompt assembly unchanged | PASS | PASS |
| V. Exception Preservation & Safety Gates | Eager `local_only` & `guard_egress` PII blocking before network I/O/iteration; `raise_litellm_error` scrubs secrets mid-stream; Release Gates #1 (`reverse`) & #2 (`pii`) stay green | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Delegates streaming uniformly across local/cloud `provider/model` targets via `litellm.completion(..., stream=True)` with zero new deps | PASS | PASS |
| VII. Structured Correctness & Quality Gates | `@overload` preserves strict `str` vs `Iterator[str]` typing; preserves chunk whitespace, trailing usage/finish state, deterministic cleanup, and PII-free telemetry | PASS | PASS |

**Gate Outcome**: **PASS** (0 violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/013-streaming-generation/
├── plan.md                             # This file (/speckit-plan output)
├── research.md                         # Phase 0 design decisions
├── data-model.md                       # Phase 1 interfaces & CLI mode matrix
├── quickstart.md                       # Phase 1 validation scenarios
├── contracts/
│   └── streaming-generation.md         # Phase 1 Python & CLI streaming contracts
├── checklists/
│   └── requirements.md                 # Completed spec quality checklist (16/16)
├── spec.md                             # Feature specification (clarified)
└── tasks.md                            # Phase 2 output (/speckit-tasks - not created here)
```

### Source & User-Facing Files (repository root)

```text
src/docpipe_maestro/
├── query/
│   └── answer.py                       # Add stream: bool = False @overloads, eager preflight + pull-started stream, cleanup & telemetry
└── cli.py                              # Add mutually exclusive --stream on p_ask and streaming _handle_ask path

tests/
├── test_prompts_answer.py              # Sync delta yields, empty frames, usage-only frames, refusals, eager safety, truncation, early close
├── test_pii_safety.py                  # Eager outbound PII block/redact parity on answer(..., stream=True) & zero-chunk leaks
├── test_logging.py                     # Correlated answer telemetry across complete/close/error streams with zero raw tokens/secrets
├── test_cli.py                         # ask --stream flushing, --show-context/--log-json stderr isolation, truncation warning/fail, --stream --json exit 2, TOML ignore
└── test_api_stability.py               # Update root.answer parameter check (stream=False) and verify len(root.__all__) == 36

User-facing docs:
├── README.md                           # Add CLI `ask --stream` and Python `answer(..., stream=True)` examples
├── PRODUCT.md                          # Document `--stream` on `ask` and `stream` support on `answer`
├── docs/README.md                      # Sync API/CLI/roadmap summaries through 013-streaming-generation
├── docs/cli-reference.md               # Document `--stream` flag, mutual exclusion with `--json`, and stderr/flush semantics on `ask`
├── docs/api-reference.md               # Document `answer(..., stream=...)` overloads, `_GenerationStreamState`/cleanup guarantees, and reserved `"stream"` kwarg
├── docs/architecture.md                # Note Phase 2 sync streaming flow & `stage.end` telemetry (`stream=True`, `closed_early`)
├── docs/development.md                 # Verify streaming mock helper notes if applicable
├── docs/future-features.md             # Mark §6.2 Streaming Generation Support and Summary Matrix row Implemented (`013-streaming-generation`)
└── CHANGELOG.md                        # Add `013-streaming-generation` entry + v1.4.0 constitution note in `## Unreleased`
```
