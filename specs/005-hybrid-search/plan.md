# Implementation Plan: Hybrid Lexical Search with Reciprocal Rank Fusion

**Branch**: `feature/005-hybrid-search` | **Date**: 2026-11-14 | **Spec**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/spec.md)

**Input**: Feature specification from `/specs/005-hybrid-search/spec.md`

## Summary

Implement a built-in hybrid retrieval strategy combining dense ChromaDB vector search with collocated SQLite FTS5 BM25 lexical search using Reciprocal Rank Fusion (`k=60`, balanced `0.5`/`0.5` weights, normalized against theoretical dual-rank maximum into `[0.0, 1.0]`). Maintain a read-only Phase 2 boundary by keeping all lexical writes inside Phase 1 lifecycle operations (`ingest`, `sync`, `remove`, `reindex`) via `src/docpipe_maestro/store/lexical.py`, lazily register `"default"` (`DenseSearcher`) and `"fts5_hybrid"` (`Fts5HybridSearcher`) in `SEARCHERS`, extend `retrieve(..., *, searcher="default")` and CLI `query`/`ask` `--searcher` flags (plus TOML default), and verify zero regressions across all invariants and release gates.

## Technical Context

**Language/Version**: Python `>=3.10` (strictly typed under `mypy --strict`, `python_version = "3.10"`)
**Primary Dependencies**: Zero new third-party dependencies; uses Python standard library `sqlite3` (FTS5 + `bm25()`) alongside existing `chromadb`, `litellm`
**Storage**: Collocated per-collection SQLite DB at `<persist_dir>/lexical/<safe_collection>.db` (`0o700` dir, `0o600` file, `uri` `mode=ro` reads in Phase 2) paired with existing ChromaDB store and JSON manifest
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `ruff`, `mypy src tests`
**Target Platform**: Linux / macOS / Windows local Python 3.10+ environments with built-in SQLite FTS5 support
**Project Type**: Minimal RAG pipeline library + CLI (`src/docpipe_maestro/`, `tests/`)
**Performance Goals**: `< 20 ms` added query overhead on collections up to 5,000 child chunks via single-query FTS5 `bm25()` + unindexed provenance storage
**Constraints**: Strict read-only Phase 2 (`mode=ro` SQLite URI + zero Phase 2 writes/backfills); lazy imports (`chromadb`, `litellm`, `sqlite3` unloaded on CLI `--help` / registry import); parameterized SQL (`S608` clean); no config file loading outside `cli.py`
**Scale/Scope**: Single library/CLI package extending `store/`, `ingest/pipeline.py`, `query/searcher/`, `query/retriever.py`, `cli.py`, and test suites

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Pre-Design | Post-Design |
| --- | --- | --- | --- |
| I. Scope Discipline | Minimal RAG surface; fixed `k=60` / `0.5` weights without parameter bloat; no HTTP/UI/app chrome | PASS | PASS |
| II. Two-Phase Architecture | Lexical writes strictly in `ingest/` + `store/`; `query/` opens SQLite strictly `mode=ro`; unindexed collections fail cleanly instructing `reindex` | PASS | PASS |
| III. Library Purity | Only `cli.py` reads TOML `searcher` default; `store/lexical.py`, `searcher/`, `retriever.py` never touch user config/dotenv | PASS | PASS |
| IV. Search Small, Return Big | FTS5 indexes/searches child chunks only; `retrieve()` expands matches to deduplicated parent sections scored by `max(child.score)` | PASS | PASS |
| V. Exception Preservation | Hybrid retrieval preserves full parent sections + exception clauses; Release Gate #1 (`@pytest.mark.reverse`) passes unmodified + extended coverage for hybrid | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Built-in stdlib SQLite FTS5 requires zero network calls, accounts, or daemons; works 100% offline with local embeddings | PASS | PASS |
| VII. Structured Correctness | Single canonical `Chunk` / `RetrievedChunk` / `ChunkMetadata` schemas from `types.py`; 2-phase `doc_version` commit envelope + `sweep_uncommitted` prevent orphan leaks | PASS | PASS |

**Gate Outcome**: **PASS** (0 violations before Phase 0; 0 violations after Phase 1 design).

## Project Structure

### Documentation (this feature)

```text
specs/005-hybrid-search/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 architecture & formula decisions
├── data-model.md        # FTS5 schema, RRF entities, lifecycle state transitions
├── quickstart.md        # Validation scenarios and CLI smoke commands
├── contracts/
│   └── hybrid-search.md # Registry, API, LexicalIndex, and CLI/TOML contracts
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/docpipe_maestro/
├── cli.py                            # Add --searcher to query & ask + TOML 'searcher' default
├── store/
│   ├── __init__.py                   # Export lazy LexicalIndex alongside STORES / ChromaStore / VectorStore
│   └── lexical.py                    # NEW: Collocated SQLite FTS5 index + sanitize_fts_query + mode=ro reads
├── ingest/
│   └── pipeline.py                   # Sync LexicalIndex in ingest, sync, remove, reindex (staging + sweep + reset)
└── query/
    ├── retriever.py                  # Add searcher: str = "default" kw-only param & resolve via SEARCHERS
    └── searcher/
        ├── __init__.py               # Register lazy built-ins: "default" & "fts5_hybrid"
        ├── dense.py                  # NEW: DenseSearcher (built-in "default")
        └── hybrid.py                 # NEW: Fts5HybridSearcher (built-in "fts5_hybrid", RRF fusion)

tests/
├── test_hybrid_search.py             # NEW: FTS5 sanitization, RRF scoring, threshold, lifecycle, CLI, legacy error, perf/recall tests
├── test_reverse_safety.py            # Untouched Stage 0 baseline tests (Release Gate #1)
├── test_registry.py                  # Update Stage 1 searcher check from empty -> built-in ("default", "fts5_hybrid") + protocol checks
└── test_api_stability.py             # Update expected retrieve() signature (+ ("searcher", kw_only, "default"))
```

**Structure Decision**: Extends the Strategy + Registry package layout established in `004-registry-refactor` without adding top-level directories, keeping `store/` as the shared collocated storage layer and `query/searcher/` as the pluggable Phase 2 strategy package.

## Complexity Tracking

No Constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| — | — | — |
