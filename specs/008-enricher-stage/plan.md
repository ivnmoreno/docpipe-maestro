# Implementation Plan: First-Class Enricher Stage & Cross-Reference Migration

**Branch**: `008-enricher-stage` (git `feat/008-enricher-stage`) | **Date**: 2026-11-15 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/008-enricher-stage/spec.md`

## Summary

Formalize post-clean, pre-chunk document transformation as a first-class, registry-driven Stage 3 pipeline step while preserving strict Phase 1 / Phase 2 module isolation. Extract pure cross-reference regexes, section-number parsing, clause-block iteration, target indexing, document-scoped extraction, source matching, and bounded excerpt truncation into phase-neutral `src/docpipe_maestro/_crossrefs.py`. Move intra-document cross-reference resolution into `CrossrefsEnricher` (`src/docpipe_maestro/ingest/enricher/crossrefs.py`) registered lazily under `"crossrefs"` in `ENRICHERS`, keep `src/docpipe_maestro/ingest/crossrefs.py` as a silent five-symbol compatibility re-export shim, and point `src/docpipe_maestro/query/retriever.py` at `_crossrefs.py` so zero Phase 2 `query/` modules import from `ingest/`. Extend `ChunkingProfile` (`src/docpipe_maestro/types.py`) with `enrichers: tuple[str, ...] = ()` (`DEFAULT.enrichers == ()`, `POLICY.enrichers == ("crossrefs",)` in `config.py`), normalizing legacy `resolve_crossrefs=True` profiles via `__post_init__` without conditional `crossrefs` branches in `pipeline.py`. Update both `ingest()` and `sync()` in `src/docpipe_maestro/ingest/pipeline.py` via shared `_resolve_enrichers` / `_apply_enrichers` helpers that resolve declared enrichers up front before scanning/skipping files, run repeated or distinct enrichers in exact sequence with full `IngestContext` (including `doc_version`), and abort transactionally before touching ChromaDB, FTS5 `LexicalIndex`, or the manifest on any failure.

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)  
**Primary Dependencies**: Zero new third-party dependencies; stdlib only (`collections.abc`, `dataclasses`, `importlib`, `logging`, `re`, `typing`) alongside existing internal registries (`Registry`, `Enricher`, `IngestContext`)  
**Storage**: Existing transactional Phase 1 staging into ChromaDB, SQLite FTS5 `LexicalIndex`, and JSON collection manifest; any enricher lookup or execution error aborts in memory prior to store/lexical/manifest writes  
**Testing**: `pytest` (`-Werror` configured via `filterwarnings = ["error"]`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests`  
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`)  
**Project Type**: Single Python library + CLI package (`src/docpipe_maestro/`, `tests/`)  
**Performance Goals**: Zero extra registry/import cost on `DEFAULT` profile (`0` `ENRICHERS.resolve(...)` lookups; `ingest/enricher/crossrefs.py` stays unloaded until resolved or imported)  
**Constraints**: Preserve locked 33-symbol `docpipe_maestro.__all__`, locked `ingest()`/`sync()` call signatures, zero `query/` imports from `docpipe_maestro.ingest*`, silent compatibility re-exports in `ingest/crossrefs.py` (no deprecation warnings), upfront enricher resolution before skip checks, and sequential duplicate-name execution  
**Scale/Scope**: Core Stage 3 pipeline refactor covering `DEFAULT`, `POLICY`, and arbitrary custom `ChunkingProfile` sequences; new enrichers (such as PII scrubbing) remain explicitly deferred to Stage 4

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
| --- | --- | --- | --- |
| I. Scope Discipline | Realizes existing Stage 3 `Enricher` contract (`register_enricher` already in 33-symbol `__all__`); no extra CLI flags, config knobs, or Stage 4 PII logic; zero changes to `docpipe_maestro.__all__` or `ingest()`/`sync()` signatures | PASS | PASS |
| II. Two-Phase Architecture | Extracts pure crossref utilities to phase-neutral `src/docpipe_maestro/_crossrefs.py`; `query/retriever.py` stops importing `ingest.crossrefs`; AST boundary guard in `tests/test_library_purity.py` tightened to block the entire `docpipe_maestro.ingest` namespace inside `query/` AND verify `_crossrefs.py` imports zero `ingest.*`/`query.*` modules (preventing transitive coupling) | PASS | PASS |
| III. Library Purity | Zero config/dotenv I/O; built-in `"crossrefs"` registered lazily via `ENRICHERS.register_lazy(...)` matching `CLEANERS`/`CHUNKERS`; `ingest/enricher/crossrefs.py` verified absent from `sys.modules` on package/CLI startup | PASS | PASS |
| IV. Search Small, Return Big | Preserves chunker parent-child linking, child indexing, and Phase 2 parent expansion / cross-document `[Crossref ...]` enrichment unchanged | PASS | PASS |
| V. Exception Preservation | Preserves single-pass `[Crossref ...]` output, cycle/self-reference skips, and unresolved warning logs identically; Release Gate #1 (`@pytest.mark.reverse`) explicitly re-verified | PASS | PASS |
| VI. Provider Agnosticism & Local-First | 100% stdlib, zero network calls or provider credentials introduced; full verification runs offline | PASS | PASS |
| VII. Structured Correctness Over Speed | `ChunkingProfile` extended in `src/docpipe_maestro/types.py` (`__post_init__` normalization using `object.__setattr__` on `frozen=True, slots=True`); `IngestContext` strictly typed per `types.py`; upfront resolution + shared `_resolve_enrichers`/`_apply_enrichers` helpers preserve batch atomicity; 100% test pass mandatory (`v1.2.2`) | PASS | PASS |

**Gate Outcome**: **PASS** (0 Constitution violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/008-enricher-stage/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 architectural boundary, normalization & pipeline decisions
├── data-model.md        # Phase 1 ChunkingProfile, IngestContext, Enricher & _crossrefs schemas
├── quickstart.md        # Phase 1 verification commands and expected outcomes
├── contracts/
│   └── enricher.md      # Phase 1 _crossrefs, ENRICHERS, CrossrefsEnricher, shim & pipeline contracts
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/docpipe_maestro/
├── _crossrefs.py                        # NEW phase-neutral pure cross-reference regexes, parsing, indexing & matching
├── types.py                             # MODIFY ChunkingProfile: add enrichers: tuple[str, ...] = () & __post_init__ normalization
├── config.py                            # MODIFY POLICY: set explicit enrichers=("crossrefs",) (DEFAULT keeps empty ())
├── ingest/
│   ├── __init__.py                      # MODIFY docstring cleanly ("...cleaning, enricher, chunking, and pipeline.")
│   ├── crossrefs.py                     # MODIFY to silent 5-symbol compatibility re-export shim (_crossrefs + enricher.crossrefs)
│   ├── enricher/
│   │   ├── __init__.py                  # MODIFY add register_lazy("crossrefs", ...) & lazy __getattr__ exports
│   │   └── crossrefs.py                 # NEW CrossrefsEnricher (@ENRICHERS.register("crossrefs")) + resolve_crossrefs(doc)
│   └── pipeline.py                      # MODIFY replace hardcoded resolve_crossrefs branch via _resolve_enrichers/_apply_enrichers + IngestContext
└── query/
    └── retriever.py                     # MODIFY import crossref helpers from docpipe_maestro._crossrefs instead of ingest.crossrefs

tests/
├── test_crossrefs.py                    # KEEP legacy import checks + ADD CrossrefsEnricher direct protocol & parity tests
├── test_library_purity.py               # MODIFY tighten query/ AST guard to full docpipe_maestro.ingest namespace + lazy enricher check
├── test_registry.py                     # MODIFY update ENRICHERS default keys expectation ("crossrefs") & ADD ordering/context/sync/abort tests
└── test_invariants_stage1.py            # KEEP / VERIFY or ADD legacy resolve_crossrefs=True normalization & atomic store/manifest abort coverage
```

**Structure Decision**: Single library package structure following existing Stage 0 (`ingest/clean/`, `ingest/chunker/`, `_resolve.py`, `_stages.py`) and Stage 1/2 (`query/searcher/`, `query/reranker/`) patterns. Zero new packages outside existing `docpipe_maestro` namespaces.

## Complexity Tracking

> Zero Constitution violations — no deviations or extra abstractions needed.
