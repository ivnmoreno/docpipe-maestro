# Data Model & Validation Rules: Structured Metadata Pre-Filtering (`where`)

**Feature**: `010-metadata-filtering`  
**Date**: 2026-11-16  
**Spec**: [spec.md](spec.md)

## 1. Existing Stored Metadata Shapes (Unchanged — Zero Migration)

| Source Layer | Field | Runtime Type | Storage Representation | Nullable / Absent Behavior |
|---|---|---|---|---|
| `ChunkMetadata` (ChromaDB + SQLite `chunks_fts`) | `source` | `str` | POSIX relative source key | Required |
| `ChunkMetadata` (ChromaDB + SQLite `chunks_fts`) | `doc_version` | `str` | 12-char sha256 prefix | Required |
| `ChunkMetadata` (ChromaDB + SQLite `chunks_fts`) | `section` | `str` | Section heading label | Required |
| `ChunkMetadata` (ChromaDB + SQLite `chunks_fts`) | `clause` | `str \| None` | Chroma: omitted if `None`; FTS5: `""` if `None` | Optional; treated as absent when omitted/`None`/`""` |
| `ChunkMetadata` (ChromaDB + SQLite `chunks_fts`) | `page` | `int \| None` | Chroma: omitted if `None`; FTS5: `INTEGER` or `NULL` | Optional; `NULL` in FTS5 when absent |
| `ChunkMetadata` (ChromaDB + SQLite `chunks_fts`) | `chunk_index` | `int` | Non-negative 0-based ordinal | Required |
| `ChunkMetadata` (ChromaDB + SQLite `chunks_fts`) | `embed_model` | `str` | Embedding `provider/model` | Required |
| `ChunkMetadata` (ChromaDB internal) | `type` | `"child" \| "parent"` | Chroma metadata only (`"child"` or `"parent"`) | Reserved internal invariant; rejected if supplied by caller |
| `SourceRecord` (Collection Manifest) | `profile` | `str` | Canonical profile name (e.g. `"DEFAULT"`, `"POLICY"`) | Per-source manifest entry |
| `SourceRecord` (Collection Manifest) | `ingested_at` | `str` | UTC ISO-8601 timestamp (`datetime.isoformat()`) | Per-source manifest entry |

## 2. Logical Filter Entities (`src/docpipe_maestro/_filters.py`)

### 2.1 Field Classifications & Allowed Scalar Types

- `CHUNK_STR_FIELDS`: `frozenset({"source", "doc_version", "section", "clause", "embed_model"})`
- `CHUNK_INT_FIELDS`: `frozenset({"page", "chunk_index"})`
- `CHUNK_FILTER_FIELDS`: `CHUNK_STR_FIELDS | CHUNK_INT_FIELDS`
- `MANIFEST_FILTER_FIELDS`: `frozenset({"profile", "ingested_after", "ingested_before"})`
- `RESERVED_FILTER_FIELDS`: `frozenset({"type"})`
- `COMPARISON_OPS`: `frozenset({"$eq", "$ne", "$in", "$nin", "$gt", "$gte", "$lt", "$lte"})`
- `LOGICAL_OPS`: `frozenset({"$and", "$or"})`
- `PROFILE_OPS`: `frozenset({"$eq", "$ne", "$in", "$nin"})`

### 2.2 Validation Rules per Operand

| Key Category | Scalar Input | Operator Input | Rejected Inputs (`DocpipeError`) |
|---|---|---|---|
| String chunk fields (`source`, `doc_version`, `section`, `clause`, `embed_model`) | `str` -> `{"$eq": val}` | `$eq`/`$ne`: `str`; `$in`/`$nin`: non-empty `list[str]` (range ops `$gt`–`$lte` require integer fields) | Non-`str`, `None`, range ops `$gt`–`$lte`, empty `$in`/`$nin`, unknown `$op` |
| Integer chunk fields (`page`, `chunk_index`) | strictly `int` and `not isinstance(v, bool)` -> `{"$eq": val}` | `$eq`/`$ne`/`$gt`/`$gte`/`$lt`/`$lte`: strict `int`; `$in`/`$nin`: non-empty `list[int]` (no `bool`) | `bool`, `float`, `str` (unless parsed cleanly at CLI boundary first), `None`, empty list |
| Logical compound keys (`$and`, `$or`) | Forbidden | Non-empty `list` of valid mapping sub-expressions | Empty list, non-list elements, non-mapping children, nested manifest keys, nested `"type"` |
| `profile` (top-level manifest key) | non-blank `str` | `$eq`/`$ne`: non-blank `str`; `$in`/`$nin`: non-empty `list` of non-blank `str` | Nested inside `$and`/`$or`, empty string, numeric/bool, range ops (`$gt`..`$lte`) |
| `ingested_after`, `ingested_before` (top-level manifest keys) | Valid ISO-8601 `str` (date or datetime) | Rejected (`$eq`, `$in`, etc. forbidden) | Nested inside `$and`/`$or`, non-`str`, blank or invalid ISO-8601 string, any operator dict |
| `"type"` | Rejected (`DocpipeError`) | Rejected (`DocpipeError`) | Any occurrence in user filter mappings or CLI `--where` |
| Unknown key | Rejected (`DocpipeError`) | Rejected (`DocpipeError`) | Any key outside `CHUNK_FILTER_FIELDS \| MANIFEST_FILTER_FIELDS \| LOGICAL_OPS` |

### 2.3 CLI `--where KEY=VALUE` Record Parsing

```text
raw CLI items: Sequence[str] | None
  └─ parse_cli_where(items):
       1. For each item:
            - Requires "=" in item; key, value = item.split("=", 1) (preserves '=' inside value)
            - Reject empty/whitespace key or empty value
            - Reject reserved key "type" and any key not in (CHUNK_FILTER_FIELDS | MANIFEST_FILTER_FIELDS)
       2. Coerce typed values at CLI boundary only:
            - page, chunk_index -> strict int parser (rejects floats, bools, text; accepts optional '-'/'+' digits like "0", "2")
            - ingested_after, ingested_before -> validate ISO-8601 upfront; reject duplicate flags
            - string keys / profile -> keep raw value string (note section titles keep literal characters)
       3. Aggregate per key:
            - single value for key -> {key: val}
            - repeated identical equality key -> {key: {"$in": deduplicated_values_in_order}}
```

### 2.4 Filter Normalization & State Flow

```text
Caller Input (`where` dict or None/{})
  │
  ├─► None or {} ──► ResolvedWhere(chunk_where=None, short_circuit_empty=False)
  │
  └─► validate_where(where, reject_reserved_type=True)
        ├─ Fails fast on invalid types, unknown keys, reserved "type", invalid ops, nested manifest keys
        ├─ Splits top-level into:
        │     - manifest constraints (`profile`, `ingested_after`, `ingested_before`)
        │     - chunk predicate expressions (with shorthand normalized to `{$eq: val}`, 1-item `$and`/`$or` unwrapped)
        └─► resolve_against_manifest(manifest.sources):
              ├─ Case 1: No manifest constraints
              │    └─► ResolvedWhere(chunk_where=normalized_chunk_where, short_circuit_empty=False)
              └─ Case 2: Manifest constraints present
                   ├─ Filter SourceRecord entries by profile (casefold) & parsed UTC ingested_at bounds
                   ├─ Intersect allowlist against top-level `source` (`$eq`/`$in`/`$ne`/`$nin`) if applicable
                   ├─ If allowlist is empty ─► ResolvedWhere(chunk_where=None, short_circuit_empty=True)
                   └─ Else inject `{"source": {"$eq": s}}` (if len==1) or `{"source": {"$in": sorted_sources}}`
                      conjunctively alongside remaining chunk predicates
                        └─► ResolvedWhere(chunk_where=combined_dict, short_circuit_empty=False)
```

### 2.5 Timestamp Parsing Rules (`ingested_after` / `ingested_before`)

1. Trailing `"Z"` / `"z"` is normalized to `"+00:00"` prior to `datetime.fromisoformat()` for Python 3.10 compatibility.
2. Date-only format (`^\d{4}-\d{2}-\d{2}$`):
   - Validated calendar date via `date.fromisoformat()`
   - `ingested_after` -> `YYYY-MM-DDT00:00:00+00:00`
   - `ingested_before` -> `YYYY-MM-DDT23:59:59.999999+00:00`
3. Naive full datetime (`tzinfo is None`) -> attaches `timezone.utc`.
4. Offset-aware datetime -> converted cleanly via `.astimezone(timezone.utc)` for comparison against manifest `SourceRecord.ingested_at` timestamps.
5. Note on `SourceRecord.ingested_at`: parsed with the same UTC normalization helper so legacy/naive or `"Z"`-suffixed manifest timestamps never crash comparison.
