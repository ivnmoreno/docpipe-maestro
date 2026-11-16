# Tasks: Structured Metadata Pre-Filtering (`where`)

**Input**: Design documents from `/specs/010-metadata-filtering/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/metadata-filtering.md](contracts/metadata-filtering.md), [quickstart.md](quickstart.md)

**Tests**: Included per repository Constitution Quality Gates (`v1.3.1`: every behavioral change ships with tests, Release Gate #1 `@pytest.mark.reverse`, Release Gate #2 `@pytest.mark.pii`, strict `mypy`, `ruff`, and `>= 80%` branch coverage).

**Organization**: Tasks are grouped by user story (`US1`, `US2`, `US3`) to enable independent implementation and verification of each increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`US1`, `US2`, `US3`; Setup, Foundational, and Polish have no story label)
- Every task includes exact file paths and quotes schema/validation constraints from `data-model.md`

---

## Phase 1: Setup (Shared Pure Infrastructure)

**Purpose**: Create the shared phase-neutral filter module skeleton and lock architectural import boundaries early.

- [X] T001 Scaffold `src/docpipe_maestro/_filters.py` importing only Python stdlib (`collections.abc`, `dataclasses`, `datetime`, `re`, `typing`) and `docpipe_maestro.types`, defining frozen field/operator constants (`CHUNK_STR_FIELDS = {"source", "doc_version", "section", "clause", "embed_model"}`, `CHUNK_INT_FIELDS = {"page", "chunk_index"}`, `MANIFEST_FILTER_FIELDS = {"profile", "ingested_after", "ingested_before"}`, `RESERVED_FILTER_FIELDS = {"type"}`, `COMPARISON_OPS = {"$eq", "$ne", "$in", "$nin", "$gt", "$gte", "$lt", "$lte"}`, `LOGICAL_OPS = {"$and", "$or"}`, `PROFILE_OPS = {"$eq", "$ne", "$in", "$nin"}`) and `@dataclass(frozen=True, slots=True) class ResolvedWhere(chunk_where: dict[str, object] | None, short_circuit_empty: bool)`
- [X] T002 [P] Update phase-neutral import guard in `tests/test_library_purity.py` (`test_phase2_query_does_not_import_phase1_stage_contracts`) to assert `src/docpipe_maestro/_filters.py` imports none of `docpipe_maestro.ingest`, `docpipe_maestro.query`, or `docpipe_maestro.store`, and verify `cli.build_parser()` leaves heavy deps (`chromadb`, `litellm`) unloaded

---

## Phase 2: Foundational (Blocking API, Validation & CLI Plumbing)

**Purpose**: Core validation/normalization orchestration and public entry-point wiring that ALL user stories build upon.

**⚠️ CRITICAL**: Complete before implementing story-specific store backends or tests.

- [X] T003 Implement recursive chunk filter validation & normalization in `src/docpipe_maestro/_filters.py` (`validate_where` / `normalize_chunk_where`): accept `None` or `{}` -> `None`; reject non-`Mapping` inputs via `DocpipeError`; reject unrecognized keys outside `CHUNK_FILTER_FIELDS | MANIFEST_FILTER_FIELDS | LOGICAL_OPS` listing valid filter keys; enforce per-field schema types across scalar values AND every `$eq`/`$ne`/`$gt`/`$gte`/`$lt`/`$lte` operand AND every `$in`/`$nin` list item (`str` only on `CHUNK_STR_FIELDS`; strict `isinstance(v, int) and not isinstance(v, bool)` only on `CHUNK_INT_FIELDS` — rejecting `{"page": {"$in": ["2"]}}` or `{"page": {"$gt": True}}`); normalize shorthand `{field: scalar}` into `{field: {"$eq": scalar}}`; reject empty `$in`/`$nin`/`$and`/`$or` lists; unwrap single-element `$and`/`$or` into its inner expression cleanly
- [X] T004 Implement top-level filter resolution coordinator `resolve_retrieve_where(where, manifest, *, reject_reserved_type=True)` in `src/docpipe_maestro/_filters.py` separating validated chunk expressions from top-level manifest keys (stubbing manifest source matching hook cleanly for US2 completion)
- [X] T005 Expose keyword-only `where: Mapping[str, Any] | None = None` on `retrieve()` in `src/docpipe_maestro/query/retriever.py`, validate/resolve upfront via `resolve_retrieve_where(where, manifest, reject_reserved_type=True)` (after `enforce_local_only` / `check_model_lock` and before `if not manifest.sources`), return `[]` immediately if `resolved.short_circuit_empty`, and forward `where=resolved.chunk_where` to `searcher_inst.search(...)`
- [X] T006 Implement `parse_cli_where(raw_items: Sequence[str] | None) -> dict[str, object] | None` in `src/docpipe_maestro/_filters.py`: split each item strictly on first `"="`, reject missing `"="`, blank key, or empty value via `DocpipeError`, reject `"type"` and unknown keys upfront, parse integer `page`/`chunk_index` strings strictly (rejecting floats/booleans/non-digits), aggregate repeated equality keys (`source`, `profile`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`) in insertion-order deduplication into `{"$in": [...]}`, and reject duplicate `ingested_after` / `ingested_before` flags
- [X] T007 Add repeatable `--where KEY=VALUE` flag via `_add_where_arg()` onto `query`, `ask`, and `eval` subparsers in `src/docpipe_maestro/cli.py`, parse `args.where` via `parse_cli_where()` strictly inside `cli.py` handlers before model/store calls, and pass `where=...` into `retrieve()` (`query`, `_handle_ask`) and `evaluate()` (`_handle_eval`)
- [X] T008 [P] Expose keyword-only `where: Mapping[str, Any] | None = None` on `evaluate()` (prior to `**retrieve_kwargs`) in `src/docpipe_maestro/eval/harness.py`, run syntactic/schema `validate_where(where, reject_reserved_type=True)` at the start of `_preflight_check()` (before checking `manifest_path.exists()`), resolve manifest filters against loaded manifest after `check_model_lock()`, and forward `where=where` into every `retrieve()` call
- [X] T009 [P] Intentionally update signature expectations in `tests/test_api_stability.py` (`test_public_callable_signatures_and_keyword_only_selectors`) for trailing keyword-only `("where", kw_only, None)` on `root.retrieve` and `evaluate` while asserting `len(root.__all__) == 36` remains unchanged

**Checkpoint**: Public `retrieve()`, `evaluate()`, CLI `--where`, and upfront validation contracts compile and pass `mypy` + `test_api_stability.py` + `test_library_purity.py`.

---

## Phase 3: User Story 1 - Filter Retrieval by Document & Structural Attributes (Priority: P1) 🎯 MVP

**Goal**: Enable accurate filtering by stored chunk attributes (`source`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`) across dense ChromaDB search, hybrid FTS5+BM25 search, reranking, evaluation, and CLI commands on existing collections without re-ingestion.

**Independent Test**: Run multi-document and multi-page retrieval, hybrid parity, reranking, evaluation, and CLI `--where` tests asserting only matching child chunks and their deduplicated expanded parent sections are returned.

- [X] T010 [US1] Implement `build_chroma_child_where(where)` in `src/docpipe_maestro/_filters.py` and update `ChromaStore.query_children()` in `src/docpipe_maestro/store/chroma.py` (removing `_ = where`) to pass `{"type": "child"}` when empty or `{"$and": [{"type": "child"}, normalized_where]}` when filtered
- [X] T011 [US1] Implement parameterized SQL predicate compiler `compile_lexical_where(where) -> tuple[str, list[object]]` in `src/docpipe_maestro/_filters.py` restricting column names strictly to `CHUNK_FILTER_FIELDS`, binding values via `?` placeholders, treating `page IS NULL` / `(clause IS NULL OR clause = '')` as absent (excluded from `$eq`/`$in`/`$gt`/`$gte`/`$lt`/`$lte` and included in `$ne`/`$nin`), and returning `("1 = 0", [])` for empty-clause equality
- [X] T012 [US1] Add optional keyword-only `where: dict[str, object] | None = None` to `LexicalIndex.search()` in `src/docpipe_maestro/store/lexical.py`, appending compiled `AND ({sql_fragment})` predicates after `WHERE chunks_fts MATCH ?` alongside existing `active_versions` commit filtering
- [X] T013 [US1] Update `DenseSearcher.search()` (`src/docpipe_maestro/query/searcher/dense.py`) and `Fts5HybridSearcher.search()` (`src/docpipe_maestro/query/searcher/hybrid.py`) to forward chunk `where` filters consistently to `store_obj.query_children(..., where=...)` and `lexical.search(..., where=...)`
- [X] T014 [P] [US1] Add chunk-attribute retrieval tests (`source`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`, multi-key conjunctive dicts, `{}` normalized as `None`, parent expansion, cross-doc refs, empty collections) in `tests/test_retriever.py`
- [X] T015 [P] [US1] Add `default` vs `fts5_hybrid` equality parity tests including chunks lacking `clause`/`page` in `tests/test_hybrid_search.py`
- [X] T016 [P] [US1] Add test verifying `retrieve(..., rerank=True, where=...)` restricts candidates before reranking in `tests/test_reranker.py`
- [X] T017 [P] [US1] Add `evaluate(..., where=...)` filtered evaluation metric tests in `tests/test_eval.py`
- [X] T018 [P] [US1] Add CLI `--where` tests on `query` (multi-filter, literal `=` inside values, `--where page=2`), `ask` (zero-match `EMPTY_CONTEXT_REFUSAL` without LLM calls), `eval`, and repeated identical-key `--where source=a --where source=b` set membership in `tests/test_cli.py`

**Checkpoint**: User Story 1 is independently runnable and testable end-to-end as an MVP (`query`, `ask`, `eval`, dense, hybrid, reranked).

---

## Phase 4: User Story 2 - Filter Existing Collections by Chunking Profile & Ingestion Window (Priority: P1)

**Goal**: Resolve top-level `profile`, `ingested_after`, and `ingested_before` constraints in memory from collection `Manifest.sources` with zero re-ingestion, intersect explicit `source` predicates cleanly, and short-circuit immediately to `[]` with zero embedder calls when no documents match.

**Independent Test**: Run tests on multi-profile, multi-timestamp collections confirming manifest-level filtering, UTC/offset/naive/`YYYY-MM-DD` date parsing, explicit `source` intersection, rejected nested manifest keys & duplicate CLI `ingested_*` bounds, and `embedder` mock call count == `0` on empty allowlists.

- [X] T019 [US2] Implement Python `3.10+` UTC ISO-8601 parser `_parse_iso_timestamp(raw, *, end_of_day_if_date: bool)` in `src/docpipe_maestro/_filters.py` (replacing trailing `"Z"`/`"z"` with `"+00:00"`, expanding `YYYY-MM-DD` to `00:00:00+00:00` for `ingested_after` and `23:59:59.999999+00:00` for `ingested_before`, attaching `timezone.utc` when naive, rejecting blank/malformed strings) and case-insensitive `profile` matcher (`str`, `$eq`, `$ne`, `$in`, `$nin` over non-blank strings)
- [X] T020 [US2] Complete manifest resolution inside `resolve_retrieve_where()` in `src/docpipe_maestro/_filters.py`: enforce top-level-only placement (raise `DocpipeError` if `profile`, `ingested_after`, or `ingested_before` appears inside `$and`/`$or` branches or if unsupported operators wrap `profile`/`ingested_*`), filter `manifest.sources` (`profile` casefold match + `>= after_dt` and `<= before_dt` inclusive UTC bounds), intersect surviving sources with top-level `source` (`str`, `$eq`, `$in`, `$ne`, `$nin`), return `ResolvedWhere(None, short_circuit_empty=True)` when empty (never generating `$in: []`), or inject `{"source": {"$eq": s}}` / `{"source": {"$in": allowlist}}` conjunctively with remaining chunk predicates
- [X] T021 [US2] Wire `resolve_retrieve_where(where, manifest)` right after `check_model_lock()` and BEFORE `lexical.exists()`/`has_indexed_rows()` or `embed_query()` inside direct calls on `DenseSearcher.search()` (`src/docpipe_maestro/query/searcher/dense.py`) and `Fts5HybridSearcher.search()` (`src/docpipe_maestro/query/searcher/hybrid.py`), returning `[]` immediately on `short_circuit_empty=True`, and validate `ingested_after`/`ingested_before` syntax eagerly inside `parse_cli_where()` in `src/docpipe_maestro/_filters.py`
- [X] T022 [P] [US2] Add tests for manifest `profile` (scalar, lowercase/mixed-case normalization, `$in`, `$ne`, `$nin`), `ingested_after`/`ingested_before` (`Z`, timezone offsets, naive, same-day `YYYY-MM-DD` inclusive bounds), `source` intersection conflicts, invalid nested `{"$or": [{"profile": "POLICY"}, {"page": 1}]}`, and spy assertions proving `embed_query` call count == `0` on empty intersections in `tests/test_retriever.py` and `tests/test_hybrid_search.py`
- [X] T023 [P] [US2] Add CLI tests for `--where profile=policy`, `--where ingested_after=...`, `--where ingested_before=...`, invalid ISO dates, duplicate `--where ingested_after=...`, and `--where profile=DEFAULT --where profile=POLICY` in `tests/test_cli.py`

**Checkpoint**: User Story 2 works cleanly on existing collections with zero re-ingestion and zero wasted embedding calls.

---

## Phase 5: User Story 3 - Child-Only Search Safety, Operator Parity & Validation (Priority: P1)

**Goal**: Guarantee reserved `"type"` rejection upfront + store-level `type="child"` defense-in-depth, enforce full 10-operator parity (`$eq`, `$ne`, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$and`, `$or`) across ChromaDB and FTS5 SQLite (specifically handling missing optional `page` and empty `clause`), and fail fast cleanly on malformed CLI/API inputs.

**Independent Test**: Run adversarial `"type"` override tests across CLI/`retrieve`/`evaluate`/direct `ChromaStore`, structured operator matrix tests comparing dense vs hybrid results on sparse/null `page` & `clause` chunks, and negative validation tests.

- [X] T024 [US3] Audit and harden `resolve_retrieve_where()` (`reject_reserved_type=True` checking nested `"type"` keys inside `$and`/`$or`), `build_chroma_child_where()` (`reject_reserved_type=False` always producing `{"$and": [{"type": "child"}, normalized]}` even on direct store calls), and strict rejection of `bool` operands across every operator and `$in`/`$nin` list item (`{"page": {"$gt": True}}`, `{"page": {"$in": ["2"]}}`), empty `$in`/`$nin`/`$and`/`$or`, mismatched field operand types, and unknown `$` operators in `src/docpipe_maestro/_filters.py`
- [X] T025 [US3] Finalize edge-case SQL compilation for nested `$and`/`$or` trees and nullable/optional columns (`page` `NULL`, `clause` `NULL` or `""`) under `$ne`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte` in `compile_lexical_where()` (`src/docpipe_maestro/_filters.py`) and `LexicalIndex.search()` (`src/docpipe_maestro/store/lexical.py`)
- [X] T026 [P] [US3] Add security & negative validation tests in `tests/test_retriever.py` and `tests/test_store.py` verifying upfront reserved-key errors on `where={"type": "parent"}` / nested `{"$or": [{"type": "parent"}, {"page": 1}]}`, direct `ChromaStore.query_children(..., where={"type": "parent"}) == []` with zero leaked parent vectors, `bool` `page=True`/`chunk_index=False` rejection, unknown field errors listing valid keys, and `evaluate()` upfront error on malformed `where`
- [X] T027 [P] [US3] Add parity matrix tests in `tests/test_hybrid_search.py` comparing `searcher="default"` and `searcher="fts5_hybrid"` identically across `$eq`, `$ne`, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$and`, and `$or` on collections mixing populated and absent `page`/`clause` chunks
- [X] T028 [P] [US3] Add negative CLI validation tests in `tests/test_cli.py` asserting exit code `1` and clear `stderr` diagnostics on `--where bad`, `--where =x`, `--where k=`, `--where page=abc`, `--where chunk_index=1.5`, `--where typo=foo`, `--where type=parent`, and bad dates across `query`, `ask`, and `eval`

**Checkpoint**: All three User Stories (`US1`, `US2`, `US3`) pass strict validation, parity, and safety invariants independently.

---

## Phase 6: Polish, Documentation & Full Quality Gates

**Purpose**: Sync user/reference documentation and run all static checks, mandatory release gates, and coverage suites.

- [X] T029 [P] Document `where: Mapping[str, Any] | None = None` on `retrieve()` and `evaluate()`, supported chunk/manifest keys, structured operators, empty-allowlist short-circuiting, and validation exceptions in `docs/api-reference.md`
- [X] T030 [P] Document repeatable `--where KEY=VALUE` usage across `query`, `ask`, and `eval` (including integer parsing, `profile`, ISO-8601 UTC date/time bounds, repeated equality `$in` behavior, and reserved `"type"` rejection) in `docs/cli-reference.md`
- [X] T031 [P] Update `README.md` CLI and Python usage snippets to illustrate metadata filtering (`where=` and `--where`) cleanly without altering honest PII documentation assertions
- [X] T032 Execute quickstart validation scenarios from `specs/010-metadata-filtering/quickstart.md` and run static formatting, lint, security, and strict type checks (`uv run --no-sync ruff format --check . && uv run --no-sync ruff check . && uv run --no-sync ruff check --select S src/ && uv run --no-sync mypy src tests`)
- [X] T033 **REQUIRED**: Run Release Gate #1 (`uv run --no-sync pytest -m reverse -v`), Release Gate #2 (`uv run --no-sync pytest -m pii -v`), and full test suite with branch coverage (`LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -v --cov`) confirming 0 failures, 0 skips, and >= 80% total branch coverage after all edits

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Starts immediately (`T001` -> `T002`)
- **Foundational (Phase 2)**: Depends on Setup (`T001`) — BLOCKS all user stories (`T003` -> `T004` -> `T005`/`T006` -> `T007`/`T008` -> `T009`)
- **User Story 1 (Phase 3)**: Depends on Foundational completion (`T009`)
  - Backend wiring sequence: `T010` -> `T011` -> `T012` -> `T013`
  - Parallel test suite after `T013`: `T014`, `T015`, `T016`, `T017`, `T018`
- **User Story 2 (Phase 4)**: Depends on Foundational completion (`T009`) and store parity from `T010`–`T013` (if manifest intersects explicit `source` passed to Chroma/FTS5)
  - Core manifest sequence: `T019` -> `T020` -> `T021`
  - Parallel tests after `T021`: `T022`, `T023`
- **User Story 3 (Phase 5)**: Depends on `T010`–`T013` and `T020` (`_filters.py`, `chroma.py`, `lexical.py`)
  - Hardening sequence: `T024` -> `T025`
  - Parallel tests after `T025`: `T026`, `T027`, `T028`
- **Polish (Phase 6)**: Docs (`T029`, `T030`, `T031`) can run in parallel once implementation contracts stabilize; `T032` and `T033` run strictly last after all edits.

---

## Parallel Example: User Story 1 Tests

```bash
# Once T010-T013 complete, launch all US1 tests in parallel (distinct files):
Task: "T014 [P] [US1] Chunk-attribute dense retrieval tests in tests/test_retriever.py"
Task: "T015 [P] [US1] Dense vs fts5_hybrid parity tests in tests/test_hybrid_search.py"
Task: "T016 [P] [US1] Reranked filtered retrieval test in tests/test_reranker.py"
Task: "T017 [P] [US1] Filtered evaluate() tests in tests/test_eval.py"
Task: "T018 [P] [US1] CLI --where query/ask/eval tests in tests/test_cli.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (`T001`–`T002`) + Phase 2 (`T003`–`T009`) so API signatures, purity checks, and upfront validation exist.
2. Complete Phase 3 (`T010`–`T018`) for chunk-attribute filtering across dense, hybrid, rerank, eval, and CLI.
3. Validate User Story 1 tests independently before moving to manifest filters (`US2`) and operator edge parity (`US3`).

### Incremental Delivery

1. Setup + Foundational → stable contracts & purity gates
2. User Story 1 (`US1`) → chunk metadata filtering across dense, hybrid, rerank, eval & CLI
3. User Story 2 (`US2`) → existing-collection `profile` & ISO-8601 `ingested_*` manifest filtering + zero-embedder short-circuiting
4. User Story 3 (`US3`) → reserved `"type"` enforcement, direct store defense-in-depth, and complete 10-operator SQL/Chroma parity
5. Polish (`Phase 6`) → docs alignment, Release Gates #1/#2, strict `ruff`/`mypy`, and full `pytest --cov` pass
