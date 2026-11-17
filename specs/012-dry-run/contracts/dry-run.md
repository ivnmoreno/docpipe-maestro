# Contracts: Dry-Run Preview Mode (`012-dry-run`)

**Feature**: `012-dry-run` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## 1. Python Library Contracts

### 1.1 `estimate_embedding_cost` (`docpipe_maestro.embedder.default` & `docpipe_maestro.embedder`)

```python
def estimate_embedding_cost(embed_model: str, estimated_tokens: int) -> float | None:
    """Estimate offline USD embedding cost from bundled LiteLLM pricing metadata."""
```

Behavioral requirements:
1. If `estimated_tokens <= 0`: returns `0.0` without importing `litellm`.
2. If `is_local_target(embed_model)` is `True` (`ollama/`, `ollama_chat/`, `local/`): returns `0.0` without importing `litellm`.
3. Otherwise calls `prepare_litellm()`, looks up `litellm.model_cost` by `embed_model.strip()`, lowercased key, and unprefixed suffix (`split("/", 1)[-1]`). Returns `round(estimated_tokens * float(input_cost_per_token), 10)` when finite numeric `>= 0.0`, else `None`. Never performs network calls.

### 1.2 `sync(..., *, dry_run: bool = False)` (`docpipe_maestro.ingest.pipeline` & root `docpipe_maestro`)

```python
def sync(
    directory: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
    dry_run: bool = False,
) -> SyncResult: ...
```

Behavioral requirements:
1. Runs all upfront validation identically (`local_only`, `validate_pii_policy`, `target.is_dir()`, `load_manifest`, `check_model_lock`, registry resolutions for `CLEANERS`/`ENRICHERS`/`CHUNKERS`/`EMBEDDERS`/`STORES`).
2. Discovers files (`allow_empty=True`), classifies into `new`/`changed`/`unchanged`, and computes `removed_keys`.
3. For each `new` / `changed` file, runs `_extract_document_chunks(..., persist_path=None if dry_run else persist_path, audit_mode=None if dry_run else "sync")`, collecting `staged_chunks` (without calling `embedder_inst.embed_texts`).
4. Both live `sync()` (`dry_run=False`) and preview `sync(..., dry_run=True)` compute `estimated_children`, `estimated_parents`, `estimated_tokens = sum(estimate_tokens(c.text) for child in staged)`, and `estimated_cost_usd = estimate_embedding_cost(embed_model, estimated_tokens)` (with local/loopback models and empty `0`-token batches returning `0.0` without importing `litellm`).
5. When `dry_run=True`:
   - Never instantiates `store_cls(persist_path, collection)` or `LexicalIndex(persist_path, collection)`, never calls `save_manifest` (even on `mtime`/`size` drift), never calls `append_audit_record`, and never invokes `embedder_inst`.
   - Emits Phase 1 prep summaries (`intake`, `clean`, `enrich`, `chunk`) and a read-only `store` `stage_event(..., operation="sync", dry_run=True, ...)`; emits no `embed` stage event.
   - Returns `SyncResult(..., dry_run=True, estimated_children=..., estimated_parents=..., estimated_tokens=..., estimated_cost_usd=...)`.

### 1.3 `reindex(..., *, dry_run: bool = False)` (`docpipe_maestro.ingest.pipeline` & root `docpipe_maestro`)

```python
@overload
def reindex(
    *,
    embed_model: str,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embedder: str = "default",
    store: str = "default",
    local_only: bool = False,
    dry_run: Literal[False] = False,
) -> int: ...


@overload
def reindex(
    *,
    embed_model: str,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embedder: str = "default",
    store: str = "default",
    local_only: bool = False,
    dry_run: Literal[True],
) -> ReindexPreview: ...


@overload
def reindex(
    *,
    embed_model: str,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embedder: str = "default",
    store: str = "default",
    local_only: bool = False,
    dry_run: bool = False,
) -> int | ReindexPreview: ...
```

Behavioral requirements:
1. Validates `local_only`, `manifest`, and registry keys (`EMBEDDERS.resolve`, `STORES.resolve`) upfront.
2. When `dry_run=True`:
   - If `not manifest_path(persist_path, collection).exists()` or `not manifest.sources`: returns zero-work `ReindexPreview(..., total_sources=0, total_children=0, total_parents=0, estimated_tokens=0, estimated_cost_usd=0.0, dry_run=True)` without instantiating `store_cls` or creating `.docpipe/`.
   - When `store == "default"`: inspects active committed children/parents via lazy stdlib `sqlite3` URI read-only connection (`?mode=ro`) on `chroma.sqlite3` (returning `([], 0)` without instantiating `ChromaStore` if `chroma.sqlite3` or the collection row is absent), guaranteeing **0 bytes** modified across standalone CLI processes and read-only directories (`?mode=ro&immutable=1` fallback only when filesystem itself denies lock/WAL file writes in read-only directory). Delegates to `store_cls(persist_path, collection).get_all_children()` / `get_all_parents()` only when `store != "default"` (custom `STORES` backends). Never calls `embedder_inst`, `reset_collection()`, `add_chunks()`, `LexicalIndex`, or `save_manifest()`.
   - Emits `INFO` `stage.end` for `store` (`operation="reindex", dry_run=True, chunks=..., sources=..., estimated_tokens=...`) and no `embed` event.
3. Root `docpipe_maestro.__all__` remains strictly unchanged at `36` exports; `ReindexPreview` is exported from `docpipe_maestro.ingest` and `docpipe_maestro.types`.

---

## 2. CLI Contracts (`src/docpipe_maestro/cli.py`)

### 2.1 `docpipe-maestro sync`
Added flags:
- `--dry-run` (`store_true`, default `False`)
- `--json` (`store_true`, `dest="as_json"`, default `False`)

Output behavior:
- `--dry-run` (human text): prints concise `[Dry Run]` summary with `added`, `updated`, `skipped`, `removed`, `children`, `parents`, `estimated_tokens`, `estimated_cost_usd` (formatted `$0.000000` or `unavailable`), plus source details when changed files exist.
- `--json` (live or `--dry-run`): emits `json.dumps(sres.to_dict(), indent=2)` cleanly to `stdout`.

### 2.2 `docpipe-maestro reindex`
Added flags:
- `--dry-run` (`store_true`, default `False`)
- `--json` (`store_true`, `dest="as_json"`, default `False`)

Output behavior:
- `--dry-run` (human text): prints concise `[Dry Run]` summary with collection, target model, previous model, `sources`, `children`, `parents`, `estimated_tokens`, `estimated_cost_usd`.
- `--dry-run --json`: emits `json.dumps(preview.to_dict(), indent=2)` cleanly to `stdout`.
- Live `--json`: emits `{"collection": ..., "embed_model": ..., "reindexed_children": count, "dry_run": false}` cleanly to `stdout`.
