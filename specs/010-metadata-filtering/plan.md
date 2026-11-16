# Implementation Plan: Structured Metadata Pre-Filtering (`where`)

**Branch**: `010-metadata-filtering` (git `feat/010-metadata-filtering`) | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/010-metadata-filtering/spec.md`

## Summary

Expose safe, uniform metadata pre-filtering across programmatic retrieval (`retrieve(..., where=...)`), evaluation (`evaluate(..., where=...)`), and CLI subcommands (`query`, `ask`, and `eval` via repeatable `--where KEY=VALUE`) without breaking or migrating existing v0.1 collections. A new phase-neutral module `src/docpipe_maestro/_filters.py` validates filter expressions upfront (rejecting unrecognized fields, reserved `"type"`, malformed CLI expressions, non-integer `page`/`chunk_index`, malformed ISO-8601 timestamps, nested manifest keys, and unsupported operators), resolves top-level manifest attributes (`profile` case-insensitively and `ingested_after`/`ingested_before` inclusive UTC bounds) in memory against `Manifest.sources`, intersects explicit `source` constraints (short-circuiting immediately to `[]` with zero embedding/store calls when empty), wraps ChromaDB queries safely in `{"$and": [{"type": "child"}, normalized_where]}` inside `ChromaStore.query_children()`, and compiles identical parameterized SQL `WHERE` predicates (including Chroma-equivalent `NULL` / empty-string `clause`/`page` handling) inside `LexicalIndex.search()` for full `default` vs `fts5_hybrid` parity.

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)  
**Primary Dependencies**: Core runtime deps already installed (`chromadb>=1.5.9`, stdlib `sqlite3`, `datetime`, `re`, `collections.abc`) — zero new third-party dependencies  
**Storage**: Read-only queries against existing persisted ChromaDB collections (cos-space children + parent placeholders), collocated SQLite FTS5 `chunks_fts` index (`<persist_dir>/lexical/<collection>.db`), and JSON collection manifests (`<persist_dir>/manifests/<collection>.json`) — zero schema changes or re-ingestion required  
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `pytest -m pii` (Release Gate #2), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests` across Python `3.10–3.13`  
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`)  
**Project Type**: Single Python library + CLI package (`src/docpipe_maestro/`, `tests/`, `docs/`)  
**Performance Goals**: Zero additional latency or imports when `where` is `None` or `{}`; O(|manifest.sources|) in-memory manifest pre-resolution; empty allowlists short-circuit in `< 1 ms` with `0` embedder calls and `0` vector/lexical queries  
**Constraints**: Preserve Principle II phase separation (`query/` never imports `ingest/`; `_filters.py` imports neither `ingest/`, `query/`, nor `store/`); preserve Principle III (no TOML/config IO outside `cli.py`); preserve Constitution §IV child-only invariant; zero SQL injection surface (allowlisted column identifiers + `?` parameter bindings only); backward-compatible CLI `--json` output schemas  
**Scale/Scope**: 7 stored chunk attributes (`source`, `doc_version`, `section`, `clause`, `page`, `chunk_index`, `embed_model`), 3 top-level manifest attributes (`profile`, `ingested_after`, `ingested_before`), 10 structured Chroma-style operators (`$eq`, `$ne`, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$and`, `$or`), 3 CLI subcommands (`query`, `ask`, `eval`), `retrieve()` & `evaluate()` entry points, both `DenseSearcher` & `Fts5HybridSearcher` + `rerank=True` composition

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verified against `.specify/memory/constitution.md` (`v1.3.1`, ratified `2026-11-12`, last amended `2026-11-15`):

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
|---|---|---|---|
| I. Scope Discipline | Exposes `where` strictly through existing `retrieve()`, `evaluate()`, internal `Searcher`/`Store`/`LexicalIndex` protocols, and CLI `--where` flags; keeps root `__all__` at 36 exports; custom ingest-time user tags and schema migrations stay out of scope | PASS | PASS |
| II. Two-Phase Architecture | Strictly Phase 2 read-only retrieval against existing chunk metadata, SQLite `chunks_fts`, and collection manifests; phase-neutral `_filters.py` imports only stdlib + `types.py` (zero `query -> ingest` coupling) | PASS | PASS |
| III. Library Purity | Core library modules accept structured `where: Mapping[str, Any]` dicts only; `--where KEY=VALUE` string parsing and CLI type coercion live in `_filters.parse_cli_where()` invoked solely from `cli.py` | PASS | PASS |
| IV. Search Small, Return Big (NON-NEGOTIABLE) | Rejects reserved `"type"` upfront in `retrieve`/`evaluate`/`cli`, AND `ChromaStore.query_children()` unconditionally wraps normalized predicates inside `{"$and": [{"type": "child"}, normalized_where]}` while preserving parent expansion & deduplication | PASS | PASS |
| V. Exception Preservation & Safety Gates | Filtered retrieval preserves exception markers during parent expansion, leaves Release Gate #1 (`@pytest.mark.reverse`) and Release Gate #2 (`@pytest.mark.pii`) untouched and green, and keeps pre-chunking PII protections intact | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Filtering executes identically across local/cloud embedders and offline dense/hybrid searchers with `0` extra network calls (and `0` embedder calls on empty manifest intersections) | PASS | PASS |
| VII. Structured Correctness & Quality Gates / Footprint | Reuses canonical `ChunkMetadata`/`SourceRecord` from `types.py` without schema drift; adds `0` runtime dependencies; intentionally updates `tests/test_api_stability.py` for `retrieve` & `evaluate` keyword-only `where=None`; full static/test/doc gates verified | PASS | PASS |

**Gate Outcome**: **PASS** (0 Constitution violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/010-metadata-filtering/
├── plan.md                        # This file (/speckit-plan output)
├── research.md                    # Phase 0 empirical ChromaDB/FTS5 & architecture decisions
├── data-model.md                  # Phase 1 field rules, operator validation, manifest/timestamp state flow
├── quickstart.md                  # Phase 1 offline test & smoke validation guide
├── contracts/
│   └── metadata-filtering.md      # Phase 1 public API, searcher/store, lexical SQL, and CLI contracts
├── checklists/
│   └── requirements.md            # Spec quality validation checklist (16/16 passing)
└── tasks.md                       # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/docpipe_maestro/
├── _filters.py                    # NEW phase-neutral pure filter parser, validator, manifest allowlist resolver, Chroma normalizer, & parameterized SQL compiler
├── cli.py                         # Add repeatable --where KEY=VALUE on query, ask, eval; parse via _filters.parse_cli_where and forward where=...
├── eval/
│   └── harness.py                 # Add keyword-only where=None to evaluate(); preflight-validate in _preflight_check & forward to retrieve()
├── query/
│   ├── retriever.py               # Add keyword-only where=None to retrieve(); preflight validate/resolve manifest allowlist, short-circuit empty, pass to Searcher
│   └── searcher/
│       ├── dense.py               # Support manifest/chunk where normalization when called directly and forward chunk_where to store.query_children()
│       └── hybrid.py              # Support manifest/chunk where normalization; short-circuit empty; forward chunk_where identically to dense + lexical.search()
└── store/
    ├── chroma.py                  # Replace `_ = where` in ChromaStore.query_children() with mandatory {"$and": [{"type": "child"}, normalized]}
    └── lexical.py                 # Add where=None to LexicalIndex.search() compiling allowlisted SQL predicates with NULL/"" parity

tests/
├── test_retriever.py              # Add dense, manifest (profile/ingested_*), operator, empty short-circuit, reserved "type", and unknown key tests
├── test_hybrid_search.py          # Add dense vs fts5_hybrid parity tests across scalar/op/$ne/$nin/$gt/$lt/$and/$or and missing clause/page cases
├── test_store.py                  # Add direct ChromaStore.query_children() $and defense-in-depth and LexicalIndex.search() SQL unit tests
├── test_reranker.py               # Verify --where / where=... composes cleanly with rerank=True
├── test_eval.py                   # Add evaluate(..., where=...) filtered retrieval & upfront preflight failure tests
├── test_cli.py                    # Add CLI tests for --where on query, ask, eval (repeated flags, '=' in values, invalid syntax/type/date/type=parent)
├── test_api_stability.py          # Update expected signatures for retrieve(..., where=None) and evaluate(..., where=None)
└── test_library_purity.py         # Guard _filters.py phase neutrality (no ingest/query/store imports) & zero heavy CLI startup imports

README.md                          # Document where= parameter & CLI --where examples/supported attributes
docs/
├── api-reference.md               # Document retrieve(..., where=...), evaluate(..., where=...), supported fields, operators & errors
└── cli-reference.md               # Document repeatable --where KEY=VALUE across query, ask, and eval
```

**Structure Decision**: Keep all shared pure validation, manifest resolution, Chroma normalization, and parameterized SQL predicate compilation in a single phase-neutral `src/docpipe_maestro/_filters.py` module alongside existing `_crossrefs.py` and `_pii.py`, avoiding duplication across `cli.py`, `retriever.py`, `eval/harness.py`, `searcher/`, and `store/` while preserving strict DAG modularity.

## Complexity Tracking

No Constitution Check violations require justification; all constraints are satisfied directly within existing module boundaries and with zero external dependencies.
