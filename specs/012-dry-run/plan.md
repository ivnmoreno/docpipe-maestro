# Implementation Plan: Dry-Run Preview Mode for `sync` and `reindex`

**Branch**: `012-dry-run` (git `feat/012-dry-run`) | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/012-dry-run/spec.md`

## Summary

Add non-mutating `--dry-run` preview support (and matching `--json` CLI output) to both `sync()` and `reindex()` so operators and Python callers can inspect file deltas (`added`, `updated`, `skipped`, `removed`), chunk volumes, deterministic offline token totals (`estimate_tokens`), and offline cost estimates (`estimate_embedding_cost`) before performing any disk/database mutations or embedding calls. Both paths enforce full preflight parity (`--local-only`, model lock checking, format validation, and `PiiBlockedError` enforcement without writing `.audit.jsonl` entries on dry runs) while keeping `docpipe_maestro.__all__` unchanged at `36` exports.

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)  
**Primary Dependencies**: Existing core dependencies only (`litellm` local `model_cost` map via `prepare_litellm()`, stdlib `json`/`math`/`pathlib`, existing `estimate_tokens`) — zero new third-party dependencies  
**Storage**: Strictly read-only in dry-run mode (zero creation of missing `.docpipe/` directories, zero `manifest.json` updates even on `mtime`/`size` drift, zero `.audit.jsonl` appends, zero `ChromaStore` / `LexicalIndex` writes or resets; `reindex(dry_run=True)` reads `chroma.sqlite3` via lazy `?mode=ro` SQLite connection for `store="default"` to guarantee `0`-byte immutability across cold CLI processes and read-only directories, delegating to `Store` only for custom store backends)  
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `pytest -m pii` (Release Gate #2), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests`  
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`)  
**Project Type**: Single Python library + CLI package (`src/docpipe_maestro/`, `tests/`, `docs/`)  
**Performance Goals**: Zero embedding network/subprocess calls in `dry_run=True`; `$0.00` local cost check skips importing `litellm`; single-pass parsing/chunking matching live `sync()` timing without embedding or vector I/O  
**Constraints**: Preserve Principle II phase separation (`embedder/default.py` owns `estimate_embedding_cost`; `cli.py` owns `--dry-run`/`--json` formatting); preserve `len(docpipe_maestro.__all__) == 36` root stability invariant; maintain 100% backward-compatible `SyncResult` construction and default `reindex(...) -> int` return behavior; zero raw PII emission  
**Scale/Scope**: `types.py` (`SyncResult` + `ReindexPreview`), `store/_readonly.py` (`read_chroma_active_preview_rows`), `embedder/default.py` + `embedder/__init__.py` (`estimate_embedding_cost`), `ingest/pipeline.py` + `ingest/__init__.py` (`sync(..., dry_run=...)`, `reindex(..., dry_run=...)`), `cli.py` (`sync`/`reindex` `--dry-run` + `--json`), `tests/`, and docs (`docs/cli-reference.md`, `docs/api-reference.md`, `docs/architecture.md`, `docs/README.md`, `docs/future-features.md`, `PRODUCT.md`, `README.md`, `CHANGELOG.md`)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verified against `.specify/memory/constitution.md` (`v1.3.1`, ratified `2026-11-12`, last amended `2026-11-15`):

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
|---|---|---|---|
| I. Scope Discipline | Exposed strictly via existing `sync`/`reindex` library functions and CLI subcommands; keeps root `__all__` at `36` exports | PASS | PASS |
| II. Two-Phase Architecture | Scoped strictly to Phase 1 workflows (`ingest/pipeline.py`, `embedder/default.py`, `types.py`, `cli.py`); zero Phase 2 changes | PASS | PASS |
| III. Library Purity | Zero config/policy file reads in library modules; `--dry-run`/`--json` live strictly in `cli.py`; zero credentials required | PASS | PASS |
| IV. Search Small, Return Big | Uses identical Phase 1 `DefaultChunker` parent/child construction so chunk counts match live execution accurately | PASS | PASS |
| V. Exception Preservation & Safety Gates | Preserves `UnsupportedFormatError`, `ModelMismatchError`, `RegistryError`, local-only `DocpipeError`, and `PiiBlockedError` (with `audit_mode=None` preventing audit writes in dry-run); Release Gates #1 & #2 stay green | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Executes `0` embedder calls and `0` network calls (`prepare_litellm()` sets `LITELLM_LOCAL_MODEL_COST_MAP=true` for cloud lookups; local models return `0.0` without importing `litellm`) | PASS | PASS |
| VII. Structured Correctness & Quality Gates | Shared dataclasses in `types.py`; `@overload` preserves strict `int` return type for default `reindex()`; tested via byte-hash drift & zero-call assertions | PASS | PASS |

**Gate Outcome**: **PASS** (0 violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/012-dry-run/
├── plan.md                             # This file (/speckit-plan output)
├── research.md                         # Phase 0 research decisions
├── data-model.md                       # Phase 1 SyncResult & ReindexPreview schemas
├── quickstart.md                       # Phase 1 validation scenarios
├── contracts/
│   └── dry-run.md                      # Phase 1 Python & CLI contracts
├── checklists/
│   └── requirements.md                 # Completed spec quality checklist (16/16)
├── spec.md                             # Feature specification
└── tasks.md                            # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
src/docpipe_maestro/
├── types.py                            # Extend SyncResult (to_dict + preview metrics), add ReindexPreview
├── embedder/
│   ├── __init__.py                     # Re-export estimate_embedding_cost
│   └── default.py                      # Add offline estimate_embedding_cost() using prepare_litellm()
├── store/
│   └── _readonly.py                    # Lazy stdlib ?mode=ro SQLite reader for zero-byte reindex previews
├── ingest/
│   ├── __init__.py                     # Export ReindexPreview alongside pipeline entry points
│   └── pipeline.py                     # Add dry_run: bool = False to sync() & reindex() with read-only paths
└── cli.py                              # Add --dry-run and --json flags & handlers for sync and reindex

tests/
├── test_api_stability.py               # Update sync/reindex signature checks; validate SyncResult & ReindexPreview
├── test_sync_lifecycle.py              # Zero-mutation, zero-embedder, token/cost, PII-block & missing-dir tests
├── test_cli.py                         # CLI sync/reindex --dry-run & --json integration tests
└── test_logging.py                     # Verify dry-run telemetry emits store preview and skips embed stage
```
