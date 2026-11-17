# Data Model: Dry-Run Preview Mode (`012-dry-run`)

**Feature**: `012-dry-run` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## Entities (`src/docpipe_maestro/types.py`)

### 1. `SyncResult` (Extended, Backward-Compatible)

Immutable dataclass returned by `sync(..., dry_run=False | True)`:

| Field | Type | Default | Description |
|---|---|---|---|
| `collection` | `str` | required | Target collection identifier |
| `embed_model` | `str` | required | Target `provider/model` embedding string |
| `added` | `list[str]` | required | Canonical source keys of newly discovered files |
| `updated` | `list[str]` | required | Canonical source keys of modified files |
| `skipped` | `list[str]` | required | Canonical source keys unchanged vs. manifest |
| `removed` | `list[str]` | required | Canonical source keys in manifest absent on disk |
| `dry_run` | `bool` | `False` | `True` when executed without mutations or embeddings |
| `estimated_children` | `int` | `0` | Total child chunks staged across `added` + `updated` |
| `estimated_parents` | `int` | `0` | Total parent sections staged across `added` + `updated` |
| `estimated_tokens` | `int` | `0` | Sum of `estimate_tokens(c.text)` for staged child chunks |
| `estimated_cost_usd` | `float \| None` | `None` | Offline embedding cost estimate (`0.0` local/empty, USD float if known, `None` if unlisted) |

Methods:
- `to_dict(self) -> dict[str, Any]`: Returns JSON-serializable dictionary copying `added`/`updated`/`skipped`/`removed` lists alongside preview fields.

Validation / invariants:
- Trailing new fields have safe defaults (`False`, `0`, `0`, `0`, `None`) so all existing callers constructing or unpacking `SyncResult` remain backward-compatible.
- In both live `sync()` and `dry_run=True`, `estimated_children`, `estimated_parents`, `estimated_tokens`, and `estimated_cost_usd` reflect the staged `added` + `updated` work consistently (with `dry_run=True` guaranteeing zero persistence writes and zero embedder calls).

---

### 2. `ReindexPreview` (New, Additive in `types.py` & `docpipe_maestro.ingest`)

Immutable dataclass returned by `reindex(..., dry_run=True)`:

| Field | Type | Default | Description |
|---|---|---|---|
| `collection` | `str` | required | Target collection identifier |
| `embed_model` | `str` | required | Target new `provider/model` string |
| `previous_embed_model` | `str \| None` | required | Locked `manifest.embed_model` prior to reindex (if any) |
| `total_sources` | `int` | required | Distinct active committed source count |
| `total_children` | `int` | required | Active committed child chunk count to re-embed |
| `total_parents` | `int` | required | Active committed parent section count preserved |
| `estimated_tokens` | `int` | required | Sum of `estimate_tokens(c.text)` across active children |
| `estimated_cost_usd` | `float \| None` | required | Offline embedding cost estimate (`0.0` local/empty, USD float if known, `None` if unlisted) |
| `dry_run` | `bool` | `True` | Always `True` for dry-run reindex reports |

Methods:
- `to_dict(self) -> dict[str, Any]`: Returns JSON-serializable dictionary covering all 9 fields.

Validation / invariants:
- Root `docpipe_maestro.__all__` remains unchanged at `36` exports; `ReindexPreview` is importable from `docpipe_maestro.types` and `docpipe_maestro.ingest`.
- Missing collection manifest (`not manifest_path.exists()`) or empty manifest (`not manifest.sources`) returns `ReindexPreview(..., previous_embed_model=manifest.embed_model, total_sources=0, total_children=0, total_parents=0, estimated_tokens=0, estimated_cost_usd=0.0, dry_run=True)` without creating missing persistence directories or instantiating `Store`.
