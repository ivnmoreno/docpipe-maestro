# Research Decisions: Structured Metadata Pre-Filtering (`where`)

**Feature**: `010-metadata-filtering` (`feat/010-metadata-filtering`)  
**Date**: 2026-11-16  
**Spec**: [spec.md](spec.md)

## 1. Where Pure Filter Parsing, Validation & Compilation Live

- **Decision**: Create a new phase-neutral module `src/docpipe_maestro/_filters.py` importing exclusively Python stdlib (`collections.abc`, `datetime`, `typing`) and `docpipe_maestro.types` (`DocpipeError`, `Manifest`).
- **Rationale**:
  - `tests/test_library_purity.py` enforces strict boundaries: `query/` may never import `ingest/`, no non-`cli.py` module may read TOML/`.env`/policy files, and `cli.build_parser()` must not eagerly import `chromadb`, `litellm`, or heavy ML packages.
  - Putting shared filter normalization/SQL-compilation in `_filters.py` lets `cli.py` (lazy CLI `--where` parser), `query/retriever.py`, `eval/harness.py`, `query/searcher/{dense,hybrid}.py`, `store/chroma.py`, and `store/lexical.py` share one single source of truth with zero duplicated validation logic and zero circular or phase-crossing imports.
- **Alternatives Considered**:
  - Placing filter logic inside `query/retriever.py` -> would create backward dependency from `store/` into `query/` or force duplication in `ChromaStore`, `LexicalIndex`, and `cli.py`.
  - Adding filter logic to `manifest.py` -> couples query-operator AST parsing (`$and`, `$or`, `$in`, SQL compilation) into persistence utilities unrelated to manifests.

## 2. ChromaDB `1.5.9` `where` Operator & Normalization Constraints

- **Decision**: Normalize user convenience dicts and structured operators via `normalize_chunk_where()` before calling ChromaDB `collection.query(...)`, and wrap `ChromaStore.query_children()` unconditionally with `{"$and": [{"type": "child"}, normalized_where]}` when a filter is present.
- **Empirical Verification (`chromadb 1.5.9` via `EphemeralClient`)**:
  - Shorthand predicates (`{"source": "a.md"}`) work inside `{"$and": [{"type": "child"}, {"source": "a.md"}]}`, and converting scalar fields into explicit `{"field": {"$eq": val}}` is equally accepted and uniform across nested operators.
  - ChromaDB **raises `ValueError`** if `$and` or `$or` contains `< 2` expressions (`"Expected where value for $and or $or to be a list with at least two where expressions"`). Our normalizer rejects empty `$and`/`$or` (`[]`) upfront and unwraps single-element `len == 1` `$and`/`$or` nodes (which can also occur when manifest keys are stripped from a compound top-level mapping) into their inner expression cleanly before hitting Chroma.
  - ChromaDB **raises `ValueError`** if `$in` or `$nin` receives `[]` (`"Expected where operand value to be a non-empty list"`). Validation rejects explicit empty `$in`/`$nin` lists upfront; meanwhile, when manifest resolution (`profile`, `ingested_after`, `ingested_before`) intersected with explicit `source` produces `0` matching documents, retrieval short-circuits and returns `[]` before invoking the embedder or `ChromaStore`.
  - ChromaDB silently accepts Python `bool` (`{"page": True}` -> returns `[[]]`) because `bool` subclasses `int`. Upfront type validation checks `not isinstance(val, bool)` for `page` and `chunk_index` integers.
  - Missing optional keys (`clause`, `page` omitted by `_serialize_metadata` when `None`): in Chroma `1.5.9`, `{"page": {"$ne": 2}}`, `{"page": {"$nin": [2]}}`, and `{"clause": {"$ne": "1.1"}}` **do match** chunks whose `page` or `clause` key was omitted (`c2`), whereas `{"clause": ""}` returns `[]` and `{"clause": {"$ne": ""}}` returns all child chunks.
- **Alternatives Considered**:
  - Passing raw caller dicts unmodified straight to ChromaDB -> would crash on `{}` / 1-item `$and` after manifest key extraction, allow silent typo keys, or hit empty-`$in` errors.

## 3. SQLite `3.53.1` FTS5 Parity with ChromaDB Semantics

- **Decision**: Extend `LexicalIndex.search(..., where: dict[str, object] | None = None)` and pass `where` from `Fts5HybridSearcher.search()` so dense and lexical queries apply the exact same predicates using allowlisted column names and parameterized SQL `WHERE` clauses (`?` placeholders).
- **Empirical Verification (`sqlite3 3.53.1` with `chunks_fts` schema from `store/lexical.py`)**:
  - In `chunks_fts`, `page` is inserted as `INTEGER` or `NULL`, `chunk_index` as `INTEGER`, and **`clause` as `TEXT` storing `""` when `metadata["clause"] is None`** (`c.metadata["clause"] or ""` in `lexical.py#L181`).
  - Under standard SQLite semantics, `NULL != 2` evaluates to `NULL` (falsy), causing naive `WHERE page != 2` to return `[]` instead of chunks lacking a page number—diverging from ChromaDB (`[['c2']]`). Similarly, `clause = ''` represents an absent clause in `chunks_fts` rather than a literal `""` value, so naive `clause < 'z'` or `clause = ''` would mismatch ChromaDB.
  - Therefore, SQL compilation in `compile_lexical_where()` handles nullable/optional columns (`page` and `clause`) explicitly:
    - Absent values (`page IS NULL`; `clause IS NULL OR clause = ''`) are **excluded** by `$eq`, `$in`, `$gt`, `$gte`, `$lt`, `$lte`, and **included** by `$ne` and `$nin`.
    - Required columns (`source`, `doc_version`, `section`, `chunk_index`, `embed_model`) use direct parameterized predicates (`=`, `!=`, `IN`, `NOT IN`, `<`, `<=`, `>`, `>=`) with `IS NULL` negation safety preserved.
    - Only allowlisted columns in `CHUNK_FILTER_FIELDS` are interpolated as SQL identifiers; all operand values bind strictly via `?` parameters (`ruff --select S` safe).
  - Note: Existing FTS5 databases on disk do not need any DDL change or re-ingestion because `chunks_fts` already indexes/stores `chunk_id`, `parent_id`, `source`, `doc_version`, `section`, `clause`, `page`, `chunk_index`, and `embed_model`.
- **Alternatives Considered**:
  - Post-filtering lexical results in memory inside `Fts5HybridSearcher` -> risks returning `0` lexical hits for selective filters when the top `candidate_k` unfiltered BM25 matches belong to other documents.
  - Rejecting `$ne`/`$gt`/`$or` in `fts5_hybrid` -> creates inconsistent UX across `--searcher default` vs `--searcher fts5_hybrid`.

## 4. Reserved `"type"` Key Defense-in-Depth & Unrecognized Field Validation

- **Decision**: Separate caller boundary validation (`reject_reserved_type=True` in `_filters.resolve_retrieve_where`, `evaluate`, and `parse_cli_where`) from low-level store safety (`build_chroma_child_where` / `compile_lexical_where` with mandatory `type='child'` conjunction).
- **Rationale**:
  - Clarifications Q1 & Q2 require rejecting unknown metadata keys and reserved `"type"` upfront at retrieval/evaluation/CLI boundaries with clear validation messages listing valid fields, preventing silent false-empty results.
  - Simultaneously preserving mandatory `{"$and": [{"type": "child"}, user_where]}` inside `ChromaStore.query_children()` guarantees Constitution §IV (`Search Small, Return Big`) cannot be violated even if a downstream caller invokes `ChromaStore.query_children()` directly with `where={"type": "parent"}`.
- **Alternatives Considered**:
  - Allowing `"type"` inside `retrieve()` -> misleads callers passing `--where type=parent` with an empty list instead of telling them parent filtering is reserved.

## 5. Manifest Attribute Resolution (`profile`, `ingested_after`, `ingested_before`)

- **Decision**: Resolve manifest keys at top level only inside `resolve_retrieve_where(where, manifest)` without reading or mutating any persisted chunk records:
  - Validate the entire `where` structure first (so `{"profile": "NOPE", "unknown": "x"}` still raises validation errors before returning `[]`).
  - Match `profile` (scalar or top-level `$eq`, `$ne`, `$in`, `$nin` of non-empty strings) case-insensitively (`rec.profile.strip().casefold()`) against each `SourceRecord.profile`.
  - Parse `ingested_after` / `ingested_before` across Python `3.10+` safely (normalizing trailing `"Z"` / `"z"` to `"+00:00"` before `datetime.fromisoformat()`, because Python `3.10` `fromisoformat()` does not accept `"Z"` natively). Date-only strings (`YYYY-MM-DD`, checked via regex before `.fromisoformat()`) expand to `00:00:00+00:00` (`ingested_after`) and `23:59:59.999999+00:00` (`ingested_before`); timezone-naive datetimes default to `timezone.utc`. Reject non-string, malformed, or operator-wrapped values, and reject `ingested_after > ingested_before`? Wait: if `ingested_after > ingested_before`, either return `[]` naturally (0 sources match `rec_dt >= after and rec_dt <= before`) cleanly! Checking `len == 0` handles impossible time windows seamlessly as an empty allowlist (`[]`).
  - Reject any manifest key nested inside `$and` / `$or` sub-expressions or paired with unsupported operators (like `$gt` on `profile`).
  - Intersect surviving manifest sources with top-level `source` (`str`, `$eq`, `$in`, `$ne`, `$nin`) or combine `{"source": {"$in": allowlist}}` (simplified to `{"source": {"$eq": s}}` if singleton) conjunctively with remaining chunk predicates. When `allowlist` is empty (even if `manifest.sources` was non-empty), short-circuit immediately before `embed_query()` or `store.query_children()`.
- **Alternatives Considered**:
  - Persisting `profile` / `ingested_at` onto Chroma chunks -> breaks existing on-disk v0.1 collections unless re-ingested, and ChromaDB `$gt`/`$lt` does not accept ISO-8601 strings (numeric operands only).

## 6. Public API Surface & CLI Integration

- **Decision**:
  - Add keyword-only `where: Mapping[str, Any] | None = None` to `retrieve()` (`src/docpipe_maestro/query/retriever.py`) and explicitly to `evaluate()` (`src/docpipe_maestro/eval/harness.py`, before `**retrieve_kwargs`, running validation in `_preflight_check` so invalid filters fail fast before iterating queries).
  - Preserve `Searcher.search(..., where: dict[str, object] | None = None)` and `Store.query_children(..., where: dict[str, object] | None = None)` already in `query/stages.py` and `_stages.py` cleanly, passing the normalized chunk `dict[str, object]` produced by `resolve_retrieve_where()`. Also allow `DenseSearcher.search()` and `Fts5HybridSearcher.search()` to normalize/resolve convenience or manifest keys if invoked directly outside `retrieve()`.
  - Add repeatable `--where KEY=VALUE` (`action="append"`, `default=None`) via a single helper `_add_where_arg()` onto `query`, `ask`, and `eval` parsers in `src/docpipe_maestro/cli.py`. Keep JSON response schemas (`--json`) backward-compatible and unchanged.
  - Update `tests/test_api_stability.py` explicitly for `retrieve(..., where=None)` and `evaluate(..., where=None)`, keeping root `__all__` at 36 symbols unchanged.
- **Alternatives Considered**:
  - Relying solely on `evaluate(..., **retrieve_kwargs)` without validating `where` upfront -> delays validation errors until `retrieve()` inside query #1 (or fails to validate at all if fixture checks fail differently). Explicit `where` in `evaluate()` matches every other `retrieve()` option (`rerank`, `local_only`, `searcher`, `threshold`).
