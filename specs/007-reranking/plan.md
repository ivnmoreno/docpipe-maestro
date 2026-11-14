# Implementation Plan: Cross-Encoder Reranking

**Branch**: `007-reranking` (git `feat/007-reranking`) | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/007-reranking/spec.md`

## Summary

Add an optional, child-first local cross-encoder reranking stage (`CrossEncoderReranker` in `src/docpipe_maestro/query/reranker/cross_encoder.py`, registered lazily under `"cross_encoder"` in `RERANKERS`) backed by an isolated `[rerank]` extra (`sentence-transformers>=3.0.0`) in `pyproject.toml`. Wire opt-in parameters (`rerank=False`, `reranker="cross_encoder"`, `rerank_top_n=20`) through shared preflight validation into `retrieve()`, `evaluate()`, and CLI/TOML defaults (`--rerank` / `--no-rerank`, `--reranker`, `--rerank-top-n` on `query`, `ask`, `eval`). Reranked retrieval scales candidate child fetch expansion-aware (`max(rerank_top_n, top_k * 3)` when `expand_parent=True`, else `max(rerank_top_n, top_k)`), applies pre-rerank score thresholds before scoring, normalizes raw logits onto `[0.0, 1.0]` via overflow-safe sigmoid with thread-safe model caching, preserves parent `max(child.score)` aggregation and Release Gate #1 (`@pytest.mark.reverse`), emits rerank config fields in `EvalReport` only when `rerank=True` (keeping `docs/eval-baseline.json` untouched), and gates final retention on empirical live benchmarking per Clarification Q1.

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)  
**Primary Dependencies**: Optional `[rerank]` extra (`sentence-transformers>=3.0.0`, excluding core dependencies); stdlib `dataclasses`, `importlib.util`, `math`, `sys`, `threading`, `argparse`  
**Storage**: Zero new persisted state; Phase 2 retrieval and `eval --rerank` remain strictly read-only against existing manifests, ChromaDB vector collections, and SQLite FTS5 lexical indexes  
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests` across Python `3.10-3.13`  
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`) targeting local CPU/16 GB RAM execution when opted in and offline mocked execution in CI  
**Project Type**: Single Python library + CLI package (`src/docpipe_maestro/`, `tests/`, `docs/`)  
**Performance Goals**: Zero import/startup overhead (`0` `sentence_transformers`/`torch` imports during CLI parsing or non-reranked queries); thread-safe in-memory `CrossEncoder(model_name)` reuse per process across batch `eval` and repeat queries  
**Constraints**: Preserve 33-symbol top-level `docpipe_maestro.__all__`; keep library config discovery strictly inside `cli.py`; keep non-reranked `EvalReport` schema and `docs/eval-baseline.json` byte-unchanged; enforce ship-or-revert gate (both `default` and `fts5_hybrid` must individually achieve `Precision@5 > baseline`, or both `MRR > baseline` and `Precision@1 > baseline` with `Precision@5 >= baseline` on live local embeddings)  
**Scale/Scope**: Candidate child pool defaults to `20` (expansion-aware `max(rerank_top_n, top_k * 3)`), benchmarked on the curated 24-query policy corpus (`5` policy documents, `21` parent sections) and arbitrary user collections

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
| --- | --- | --- | --- |
| I. Scope Discipline | Strictly opt-in local `Reranker` stage behind existing `RERANKERS` registry; 33-symbol `docpipe_maestro.__all__` unchanged; `[rerank]` separated from `[all]` parser install; backed by objective live-benchmark revert gate (Clarification Q1) | PASS | PASS |
| II. Two-Phase Architecture | Lives exclusively in Phase 2 (`src/docpipe_maestro/query/reranker/`); zero imports from `docpipe_maestro.ingest.*` (enforced by `tests/test_library_purity.py`); read-only store/manifest handling preserved in `retrieve()` and `eval` | PASS | PASS |
| III. Library Purity | TOML defaults (`rerank`, `reranker`, `rerank_top_n`) resolved strictly in `cli.py`; zero config/dotenv reads inside `query/` or `eval/`; zero eager imports of `sentence_transformers`/`torch` at CLI parser or root import time | PASS | PASS |
| IV. Search Small, Return Big | Child-first ordering: fetch committed candidate children (`max(rerank_top_n, top_k * 3)` with `expand_parent`), pre-filter by `threshold`, rerank ALL candidate children via `CrossEncoderReranker`, then deduplicate unique parent sections weighted by `max(child.score)` | PASS | PASS |
| V. Exception Preservation | Parent sections with exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`) remain intact across reranking and cross-doc enrichment; Release Gate #1 (`@pytest.mark.reverse`) explicitly verified under reranking | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Uses local weights (`BAAI/bge-reranker-base` default, no cloud reranker API or third-party key required); offline CI tests run 100% network-free with mocks; default behavior unchanged when `[rerank]` absent | PASS | PASS |
| VII. Structured Correctness Over Speed | Canonical `EvalConfig` (`_EvalConfigRequired` + optional fields) defined in `src/docpipe_maestro/types.py`; chunks rebuilt via `dataclasses.replace` on `slots=True` `RetrievedChunk`; shared preflight helper; 100% test pass mandatory (`v1.2.2`) | PASS | PASS |

**Gate Outcome**: **PASS** (0 Constitution violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/007-reranking/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 dependency isolation, sigmoid, pool sizing & gate decisions
├── data-model.md        # Phase 1 constants, validation rules, RetrievedChunk & EvalConfig schemas
├── quickstart.md        # Phase 1 offline CI + live Ollama benchmark & drift validation guide
├── contracts/
│   └── reranker.md      # Phase 1 RERANKERS, CrossEncoderReranker, retrieve, eval, CLI & revert contracts
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
pyproject.toml                                        # Add optional [rerank] extra & mypy ignore_missing_imports override; lock uv.lock
src/docpipe_maestro/
├── config.py                                         # Add DEFAULT_RERANK_TOP_N = 20 and DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"
├── types.py                                          # Split EvalConfig into _EvalConfigRequired + total=False rerank fields
├── query/
│   ├── reranker/
│   │   ├── __init__.py                               # Lazy register_lazy("cross_encoder", ...), __getattr__, shared validate_rerank_options helper
│   │   └── cross_encoder.py                          # NEW CrossEncoderReranker (@RERANKERS.register("cross_encoder")), _load_cross_encoder cache -> _instantiate_cross_encoder, overflow-safe sigmoid
│   └── retriever.py                                  # Append rerank/reranker/rerank_top_n kwargs, preflight validate, expansion-aware pool, child-first rerank
├── eval/
│   └── harness.py                                    # Accept/validate/forward rerank options in evaluate() & conditional EvalConfig emission
└── cli.py                                            # Add --rerank/--no-rerank, --reranker, --rerank-top-n & TOML defaults across query, ask, eval; text header formatting

tests/
├── test_reranker.py                                  # NEW unit, mocked CrossEncoder, cache reuse, sigmoid/NaN, MissingExtraError, parent aggregation & reverse tests
├── test_api_stability.py                             # Update retrieve() expected signature with 3 appended keyword-only defaults
├── test_library_purity.py                            # Assert sentence_transformers & torch stay unloaded on import & CLI build_parser()
├── test_eval.py                                      # Add eval rerank=True/False config schema parity, invalid param & 0-byte persistence drift tests
└── test_cli.py                                       # Add CLI --rerank/--no-rerank/--reranker/--rerank-top-n & TOML override tests on query/ask/eval

docs/
├── eval-baseline.md                                  # Record live local benchmark comparison & ship/revert empirical table
├── cli-reference.md                                  # Document --rerank/--no-rerank, --reranker, --rerank-top-n & [rerank] installation
├── api-reference.md                                  # Document retrieve(..., rerank=...), CrossEncoderReranker & register_reranker usage
└── architecture.md                                   # Update Phase 2 pipeline diagram with optional child-first reranker stage (007-reranking)

README.md                                             # Document [rerank] install extra distinct from parser-only [all]
CHANGELOG.md                                          # Record feat(rerank) outcome (retained feature or empirical revert note)
```

**Structure Decision**: Activate the existing Phase 2 stub subpackage `src/docpipe_maestro/query/reranker/` (`cross_encoder.py` + lazy `__init__.py`) without adding extra modules or modifying top-level `__all__`, sharing preflight validation cleanly between `retrieve()` and `evaluate()` and keeping all TOML/CLI parsing confined strictly to `src/docpipe_maestro/cli.py`.

## Complexity Tracking

No Constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| — | — | — |
