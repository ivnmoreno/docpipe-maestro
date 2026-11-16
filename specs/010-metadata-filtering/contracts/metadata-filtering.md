# Interface Contracts: Structured Metadata Pre-Filtering (`where`)

**Feature**: `010-metadata-filtering`  
**Date**: 2026-11-16  
**Spec**: [spec.md](spec.md)

## 1. Public Library Signatures

### 1.1 `docpipe_maestro.query.retriever.retrieve` (and `docpipe_maestro.retrieve`)

```python
def retrieve(
    question: str,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    top_k: int = DEFAULT_TOP_K,
    threshold: float | None = None,
    expand_parent: bool = True,
    follow_crossrefs: bool = True,
    embedder: str = "default",
    store: str = "default",
    searcher: str = "default",
    rerank: bool = False,
    reranker: str = "cross_encoder",
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    local_only: bool = False,
    where: Mapping[str, Any] | None = None,
) -> list[RetrievedChunk]:
```

**Contract Guarantees**:
- `where` defaults to `None`; passing `None` or `{}` preserves exact existing unfiltered behavior.
- Validation of `where` executes **upfront** (before manifest empty check, embedder calls, or store writes/queries), raising `DocpipeError` (or `ValueError` via CLI catch) on invalid types, unknown keys, reserved `"type"`, invalid operators, malformed dates, or nested manifest keys.
- Manifest-level constraints (`profile`, `ingested_after`, `ingested_before`) resolve purely in memory against `manifest.sources`. When zero sources match (or intersection with top-level `source` filter is empty), `retrieve()` returns `[]` cleanly without calling `embed_query()` or querying stores.
- Resolved chunk-only `where` dictionary (`dict[str, object] | None`) is passed forward to `searcher_inst.search(..., where=resolved.chunk_where)`.
- Cross-document reference enrichment (`_enrich_crossdoc_references`), parent deduplication, threshold filtering, and reranking (`rerank=True`) continue operating unchanged over the filtered candidate set.

### 1.2 `docpipe_maestro.eval.harness.evaluate`

```python
def evaluate(
    fixture: str | Path | EvalFixture,
    *,
    collection: str | None = None,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    k_values: Sequence[int] = DEFAULT_EVAL_K_VALUES,
    expand_parent: bool = True,
    follow_crossrefs: bool = True,
    threshold: float | None = None,
    embedder: str = "default",
    store: str = "default",
    searcher: str = "default",
    rerank: bool = False,
    reranker: str = "cross_encoder",
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    local_only: bool = False,
    where: Mapping[str, Any] | None = None,
    **retrieve_kwargs: Any,
) -> EvalReport:
```

**Contract Guarantees**:
- Validates `where` syntactically via `validate_where(where, reject_reserved_type=True)` at the start of `_preflight_check` (before collection existence check) and resolves manifest filters after `check_model_lock` so malformed filters fail immediately with `0` retrieval/embedding work.
- Forwards `where=where` into every `retrieve(...)` invocation cleanly while keeping existing `EvalConfig` and `EvalReport` schemas unchanged.

### 1.3 Stability Contract (`tests/test_api_stability.py`)

- Update `test_public_callable_signatures_and_keyword_only_selectors` intentionally for:
  - `root.retrieve` trailing keyword-only parameter `("where", kw_only, None)`
  - `evaluate` trailing keyword-only parameter `("where", kw_only, None)` prior to `("retrieve_kwargs", VAR_KEYWORD, empty)`
- Preserve `len(root.__all__) == 36` unchanged (no new top-level symbols required).

## 2. Internal Searcher & Store Contracts

### 2.1 `Searcher.search` (`src/docpipe_maestro/query/stages.py`)

Already declares:
```python
def search(
    self,
    question: str,
    *,
    top_k: int,
    collection: str,
    persist_dir: str,
    embed_model: str,
    where: dict[str, object] | None = None,
) -> list[RetrievedChunk]: ...
```
- **DenseSearcher** (`src/docpipe_maestro/query/searcher/dense.py`): Resolves any convenience/manifest filters against `manifest` (if called directly outside `retrieve()`), short-circuits `[]` if empty allowlist before `embed_query()`, and passes `resolved.chunk_where` to `store_obj.query_children(..., where=...)`.
- **Fts5HybridSearcher** (`src/docpipe_maestro/query/searcher/hybrid.py`): Resolves any convenience/manifest filters against `manifest`, short-circuits `[]` if empty allowlist before `embed_query()`, passes `resolved.chunk_where` identically to BOTH `store_obj.query_children(..., where=...)` AND `lexical.search(..., where=...)`, and fuses matching results via RRF.
- **Third-party custom `Searcher` plugins**: `retrieve()` passes `resolved.chunk_where` (`dict[str, object] | None`) as keyword argument `where=...` cleanly because `Searcher` protocol already defines `where: dict[str, object] | None = None`.

### 2.2 `Store.query_children` (`src/docpipe_maestro/store/chroma.py`)

```python
def query_children(
    self,
    query_vector: list[float],
    *,
    top_k: int = 5,
    active_versions: dict[str, str] | None = None,
    where: dict[str, object] | None = None,
    include_embeddings: bool = False,
) -> list[RetrievedChunk]:
```
**Contract Guarantees**:
- Never ignores `where` (`_ = where` removed).
- Uses `build_chroma_child_where(where)` to construct:
  - `{"type": "child"}` when `where` is `None` or `{}`
  - `{"$and": [{"type": "child"}, normalized_user_where]}` otherwise (normalizing scalar fields into `{"$eq": val}`, rejecting unknown fields/invalid operators/empty `$in` lists/boolean integers, unwrapping 1-element `$and`/`$or`).
- Even if called directly with `{"type": "parent"}`, `{"$and": [{"type": "child"}, {"type": {"$eq": "parent"}}]}` returns `[]` and **never** returns parent placeholder vectors.

### 2.3 `LexicalIndex.search` (`src/docpipe_maestro/store/lexical.py`)

```python
def search(
    self,
    query: str,
    *,
    top_k: int = 20,
    active_versions: dict[str, str] | None = None,
    where: dict[str, object] | None = None,
) -> list[RetrievedChunk]:
```
**Contract Guarantees**:
- Compiles `where` via `compile_lexical_where(where)` into `(sql_fragment, params)`:
  - All column identifiers strictly allowlisted from `CHUNK_FILTER_FIELDS`.
  - All predicate values passed as parameterized `?` SQL arguments.
  - Handles optional fields (`page` `NULL`, `clause` `NULL` or `""`) to match ChromaDB semantics identically across `$eq`, `$ne`, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$and`, and `$or`.
  - Appends `AND ({sql_fragment})` after `WHERE chunks_fts MATCH ?` inside the existing FTS5 `bm25(...)` query, preserving `active_versions` checks before returning up to `top_k` results.

## 3. CLI Flag Contract (`src/docpipe_maestro/cli.py`)

- **Flag**: `--where KEY=VALUE` (repeatable via `action="append"`, `default=None`) attached to `query`, `ask`, and `eval` subparsers.
- **Boundary Purity (Principle III)**: All `--where` string splitting, key validation, integer coercion (`page`, `chunk_index`), ISO-8601 date validation, duplicate time-bound checks, and `$in` aggregation for repeated equality keys execute in `parse_cli_where(args.where)` inside the CLI invocation path before calling library entry points (`retrieve`, `evaluate`).
- **Exit Behavior**: Malformed `--where` expressions (missing `=`, empty key/value, invalid `page` integer, invalid date, unknown key, reserved `"type"`, duplicate `ingested_after`/`ingested_before`) raise `DocpipeError` / `ValueError`, caught by `main()` to print a single-line `Error: ...` message on `stderr` and return exit code `1` prior to embedding, storage, or LLM calls.
- **No-match Behavior**: When valid filters match zero documents in `query` (`No matching sections found.`), `ask` (refuses with `EMPTY_CONTEXT_REFUSAL` and `0` LLM calls), or `eval` (scores `0` retrieved hits cleanly as `0.0`), commands succeed with exit code `0` and emit zero errors.

## 4. Internal Pure Helper API (`src/docpipe_maestro/_filters.py`)

| Helper | Responsibility |
|---|---|
| `parse_cli_where(raw_items)` | Parse CLI `KEY=VALUE` strings, coerce `page`/`chunk_index`, validate dates, aggregate repeated equality keys into `$in`, reject duplicate `ingested_*` / invalid syntax |
| `validate_where(where, *, reject_reserved_type=True)` | Syntactic, key-allowlist, operator, and per-field schema validation across chunk, manifest, and logical nodes (usable before manifest/store lookup) |
| `resolve_retrieve_where(where, manifest, *, reject_reserved_type=True)` | Validate entire `where` AST via `validate_where()`, evaluate `profile`/`ingested_after`/`ingested_before` against `manifest.sources`, intersect top-level `source`, return `ResolvedWhere(chunk_where, short_circuit_empty)` |
| `build_chroma_child_where(where)` | Validate chunk-level predicates (`reject_reserved_type=False` for store defense-in-depth) and wrap in `{"$and": [{"type": "child"}, normalized]}` |
| `compile_lexical_where(where)` | Validate chunk-level predicates (`reject_reserved_type=False` for store defense-in-depth) and compile parameterized SQL `(clause, params)` matching ChromaDB semantics |
