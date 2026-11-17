# Phase 0 Research: Dry-Run Preview Mode for `sync` and `reindex`

**Feature**: `012-dry-run` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## Research Decisions

### 1. Public API Surface & Root Export Stability (`36` Exports)

- **Decision**: Keep `docpipe_maestro.__all__` unchanged at `36` exports. Add trailing keyword-only `dry_run: bool = False` to both `sync()` and `reindex()` in `docpipe_maestro.ingest.pipeline`. Extend `SyncResult` (already in root `__all__`) with additive defaulted fields (`dry_run`, `estimated_children`, `estimated_parents`, `estimated_tokens`, `estimated_cost_usd`) plus `to_dict()`, and define `ReindexPreview` in `docpipe_maestro.types` (re-exported from `docpipe_maestro.ingest`) using Python `@overload` (`Literal[False] = False -> int`, `Literal[True] -> ReindexPreview`, `bool -> int | ReindexPreview`).
- **Rationale**: Preserves CI/release invariants (`assert len(dp.__all__) == 36` in `.github/workflows/ci.yml`, `.github/workflows/release.yml`, and `tests/test_api_stability.py`), keeps existing callers expecting `reindex(...) -> int` 100% static-type compatible, and keeps preview metrics cleanly attached to `SyncResult` without creating redundant `preview_sync` wrapper functions.
- **Alternatives Considered**:
  - Adding `ReindexPreview` to root `__all__`: unnecessary root export growth (`36 -> 37`) when specialized modules (`docpipe_maestro.eval`, `docpipe_maestro.log`, `docpipe_maestro.ingest`) already house feature-specific types.
  - Adding separate `dry_run_sync` / `dry_run_reindex` functions: diverges from `--dry-run` CLI semantics and duplicates entry-point validation.

### 2. Zero-Mutation Persistence Guarantees

- **Decision**:
  - `sync(..., dry_run=True)`: Resolve all strategy classes (`CLEANERS`, `ENRICHERS`, `CHUNKERS`, `EMBEDDERS`, `STORES`) and load `manifest = load_manifest(persist_path, collection)` read-only, check model lock (`check_model_lock`), run `_discover_files`, `classify_file`, and `_extract_document_chunks(..., audit_mode=None)` without instantiating `store_cls(persist_path, collection)` or `LexicalIndex(persist_path, collection)` and without invoking `save_manifest`, `append_audit_record`, or `embedder_inst`.
  - `reindex(..., dry_run=True)`: Validate `local_only`, resolve `embedder` and `store` strategies upfront, and load `manifest = load_manifest(persist_path, collection)` plus `manifest_path(persist_path, collection).exists()` **before** opening any database. Return a zero-work `ReindexPreview` immediately if the collection manifest does not exist or has no committed sources (preventing missing `.docpipe/` auto-creation). When committed sources exist under `store == "default"` and `chroma.sqlite3` is present, read active committed child texts directly via stdlib `sqlite3` (`db_path.resolve().as_uri() + "?mode=ro"`, `uri=True`, imported lazily so `docpipe_maestro` startup never eagerly loads `sqlite3`), falling back cleanly to `store_cls(persist_path, collection)` only for custom non-default `STORES` backends or absent DB files.
- **Rationale**: In `sync()`, instantiating `ChromaStore.__init__` calls `ensure_private_dir()`, which would create `.docpipe/` on disk even before writes; skipping instantiation completely avoids directory creation, avoids opening SQLite, preserves manifest `mtime`/`size` on drifted unchanged files (`manifest_dirty`), and passing `audit_mode=None` prevents `PiiBlockedError` from appending `.audit.jsonl` during dry runs while still raising `PiiBlockedError` cleanly. For `reindex(..., dry_run=True)`, opening `PersistentClient` in a fresh CLI subprocess would touch ~10 SQLite header bytes in `chroma.sqlite3` on startup; reading `collections`/`segments`/`embeddings`/`embedding_metadata` via `sqlite3` `?mode=ro` was verified empirically across standalone subprocesses with `0` bytes changed and works even on read-only persistence directories.
- **Alternatives Considered**:
  - Calling `ChromaStore.get_all_children()` unconditionally: touches SQLite header bytes when invoked from a cold CLI process or fails on read-only directories.

### 3. Deterministic Offline Token & Cost Estimation

- **Decision**:
  - Compute `estimated_tokens = sum(estimate_tokens(c.text) for c in child_chunks)` across newly added and updated files for `sync`, and across active committed child chunks for `reindex`.
  - Implement `estimate_embedding_cost(embed_model: str, estimated_tokens: int) -> float | None` in `docpipe_maestro.embedder.default` (re-exported via `docpipe_maestro.embedder`): return `0.0` immediately when `estimated_tokens <= 0` or `is_local_target(embed_model)` is `True` (without importing `litellm`); otherwise call `prepare_litellm()`, look up `litellm.model_cost` by normalized model key (`embed_model` then unprefixed suffix), and return `round(estimated_tokens * float(input_cost_per_token), 10)` if present and finite `>= 0.0`, else `None`.
- **Rationale**: Verified locally against `litellm.model_cost` with `LITELLM_LOCAL_MODEL_COST_MAP="true"`: `openai/text-embedding-3-small` resolves `input_cost_per_token = 2e-08` and `openai/text-embedding-3-large` resolves `1.3e-07`, while local models (`ollama/nomic-embed-text`) pay `$0.00` without touching `litellm` (preserving fast lazy-import startup and air-gapped safety). Unrecognized cloud models return `None` cleanly instead of guessing or making network requests.
- **Alternatives Considered**:
  - Introducing `tiktoken` encoding calls or remote pricing APIs: heavier runtime coupling or network calls violating Constitution Principle VI; `estimate_tokens()` is already the canonical offline estimator in `ingest/chunker/default.py`.

### 4. CLI Flags & JSON Output Consistency

- **Decision**: Add both `--dry-run` (`store_true`) and `--json` (`store_true`, `dest="as_json"`) to `sync` and `reindex` subparsers in `src/docpipe_maestro/cli.py`.
- **Rationale**: Every inspection/preview subcommand (`status`, `query`, `ask`, `eval`) already uses `--json` via `dest="as_json"`; bringing `sync` and `reindex` into parity enables machine-readable CI/automation checks on `--dry-run` while keeping human output concise and clear (`[Dry Run] ...`).
- **Alternatives Considered**:
  - Supporting `--json` only alongside `--dry-run`: unnecessary restriction; `SyncResult.to_dict()` and `{"collection": ..., "embed_model": ..., "reindexed_children": count, "dry_run": False}` make `--json` clean across both modes.
