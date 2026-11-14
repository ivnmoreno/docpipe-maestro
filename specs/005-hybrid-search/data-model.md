# Phase 1 Data Model: Hybrid Lexical Search

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/spec.md) | **Date**: 2026-11-14

## 1. Collocated SQLite FTS5 Schema (`LexicalIndex`)

Stored per collection at `<persist_dir>/lexical/<safe_collection>.db`. Owned exclusively for writes by Phase 1 (`ingest`, `sync`, `remove`, `reindex`) and opened in strict URI read-only mode (`mode=ro`) by Phase 2 (`Fts5HybridSearcher`).

### Table: `chunks_fts` (SQLite FTS5 Virtual Table)

Tokenizer: `tokenize='unicode61'`

| Column | Indexed | Type / Encoding | Source | Notes |
| --- | --- | --- | --- | --- |
| `chunk_id` | `UNINDEXED` | `TEXT` | `Chunk.id` | 16-char deterministic sha256 hex ID |
| `parent_id` | `UNINDEXED` | `TEXT` | `Chunk.parent_id` | Parent section ID (required non-empty for child chunks) |
| `source` | `UNINDEXED` | `TEXT` | `Chunk.metadata["source"]` | Canonical relative POSIX source key |
| `doc_version` | `UNINDEXED` | `TEXT` | `Chunk.metadata["doc_version"]` | 12-char hex version prefix for staging/active filtering |
| `section` | Indexed (weight `1.5`) | `TEXT` | `Chunk.metadata["section"]` | Section heading title |
| `clause` | Indexed (weight `2.0`) | `TEXT` | `Chunk.metadata["clause"]` or `""` | Structural clause label if present (empty string if `None`) |
| `page` | `UNINDEXED` | `INTEGER` or `NULL` | `Chunk.metadata["page"]` | Source page number or `NULL` |
| `chunk_index` | `UNINDEXED` | `INTEGER` | `Chunk.metadata["chunk_index"]` | Ordinal index within parent |
| `embed_model` | `UNINDEXED` | `TEXT` | `Chunk.metadata["embed_model"]` | Model identifier carried through metadata |
| `content` | Indexed (weight `1.0`) | `TEXT` | `Chunk.text` | Child chunk body (including `[Source: ...]` context prefix) |

### Validation & Permissions Invariants

- **Path Safety**: `<collection>` passes `validate_collection_name()` and resolved DB path must satisfy `is_relative_to(lexical_dir.resolve())` (same contract as `manifest.py`).
- **Permissions**: `<persist_dir>/lexical/` created with `0o700`; `<collection>.db` created/chmodded to `0o600` (best-effort `contextlib.suppress(OSError)`).
- **Idempotent Staging**: `add_chunks(chunks)` writes only `"child"` chunks inside an explicit SQLite transaction (`DELETE FROM chunks_fts WHERE chunk_id = ?` then `INSERT`), avoiding duplicate `chunk_id` rows if staged twice.
- **Version Isolation & Sweep**:
  - `search()` filters candidate rows strictly against `active_versions` (`active_versions.get(source) == doc_version`).
  - `delete_stale_versions(source, active_doc_version)` deletes rows matching `source = ? AND doc_version != ?`.
  - `delete_by_source(source)` deletes all rows matching `source = ?`.
  - `sweep_uncommitted(active_versions)` deletes all rows whose `(source, doc_version)` is not active, returning deleted row count (`int`).
  - `reset()` drops and recreates `chunks_fts` cleanly during `reindex()`.

---

## 2. Fusion Entities (`Fts5HybridSearcher`)

### `RRF Constants` (Fixed v1 Balanced Defaults per Q2/Q3)

- `RRF_K: int = 60`
- `DENSE_WEIGHT: float = 0.5`
- `LEXICAL_WEIGHT: float = 0.5`
- `MAX_RRF_SCORE: float = (DENSE_WEIGHT + LEXICAL_WEIGHT) / (RRF_K + 1)` (`1.0 / 61`)

### Candidate Fusion State

For each unique `chunk_id` in $\text{Dense}(c) \cup \text{Lexical}(c)$:
- `dense_rank: int | None` (1-indexed position from `DenseSearcher` / `Store.query_children`)
- `lexical_rank: int | None` (1-indexed position from `LexicalIndex.search`)
- `raw_rrf`: sum of `weight / (RRF_K + rank)` over available signals
- `normalized_score`: `max(0.0, min(1.0, raw_rrf / MAX_RRF_SCORE))`
- Output: `RetrievedChunk` sorted by `(-normalized_score, id)` sliced to `top_k`, with canonical `ChunkMetadata` preserved intact and `vector=[]`.

---

## 3. State Transitions Across Lifecycles

1. **`ingest()` / `sync()`**:
   - Before writing new chunks: `lexical.sweep_uncommitted(active_versions)` removes orphans left by crashed prior runs.
   - Staging write: `store_obj.add_chunks(embedded)` + `lexical.add_chunks(child_chunks)`. Invisible to concurrent queries until manifest commits.
   - Commit: `save_manifest(persist_path, manifest)` (atomic `os.replace`).
   - Cleanup: `store_obj.delete_stale_versions(...)` + `lexical.delete_stale_versions(...)`; for deleted sources in `sync()`, `store_obj.delete_by_source(...)` + `lexical.delete_by_source(...)`.
2. **`remove()`**:
   - Removes source from vector store, removes source from `LexicalIndex` (when DB exists), updates manifest.
3. **`reindex()`**:
   - Rebuilds vector collection (`reset_collection` + `add_chunks`) AND rebuilds `LexicalIndex` (`reset` + `add_chunks(active_children)`), enabling existing legacy collections to opt into hybrid search seamlessly.
4. **`retrieve(..., searcher="fts5_hybrid")`**:
   - Phase 2 strictly read-only: checks manifest lock, confirms lexical DB readiness if committed child chunks exist, runs dense + read-only FTS5 queries, normalizes RRF scores, applies `threshold`, expands parents (`max(child.score)`), deduplicates, and resolves optional 1-hop crossrefs.
