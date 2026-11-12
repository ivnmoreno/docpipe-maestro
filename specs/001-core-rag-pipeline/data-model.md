# Data Model: Core RAG Pipeline

**Feature**: `001-core-rag-pipeline` | **Date**: 2026-11-12

All shared data shapes are defined once in `src/docpipe_maestro/types.py` and imported across Phase 1, Phase 2, and shared modules to prevent schema drift (Constitution Principle VII).

---

## 1. Core Public Types (`types.py`)

### 1.1 `ChunkMetadata` (TypedDict / dict mapping)

Structured metadata attached to every chunk and stored in the vector database.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `Literal["child", "parent"]` | Yes | Distinguishes searchable child chunks from parent sections (load-bearing filter field) |
| `source` | `str` | Yes | Normalized relative path from ingested root directory (or filename for single-file ingest) |
| `doc_version` | `str` | Yes | 12-char `sha256` content hash prefix identifying the committed document version |
| `section` | `str` | Yes | Section heading or identifier (e.g., `"Section 4: Annual Leave"`) |
| `clause` | `str \| None` | No | Clause label if detected (e.g., `"4.2"` or `"Clause 3.1"`), else `None` |
| `page` | `int \| None` | No | 1-based source page number for paginated formats (PDF), else `None` |
| `chunk_index` | `int` | Yes | 0-based position of the child within its parent section (`0` for parent records) |
| `embed_model` | `str` | Yes | `provider/model` identifier used to generate the collection's embeddings |

> **ChromaDB Serialization Rule**: ChromaDB rejects `None` metadata values. `store.py` strips keys whose value is `None` (`clause`, `page`) on write and restores `None` on read.

### 1.2 `Chunk`

The foundational text unit produced by Phase 1 chunking.

| Field | Type | Default | Constraints |
|---|---|---|---|
| `id` | `str` | required | Deterministic 16-char hex digest: `sha256(f"{source}\|{doc_version}\|{type}\|{section}\|{clause or ''}\|{chunk_index}\|{text}")[:16]` |
| `text` | `str` | required | Chunk content; children carry prepended header `[Source: <source> \| Section: <section> \| Clause: <clause>]` |
| `parent_id` | `str \| None` | `None` | ID of the parent `Chunk` for children; MUST be `None` for parent sections (`metadata["type"] == "parent"`) |
| `metadata` | `ChunkMetadata` | required | Must pass validation (`type` in `{"child", "parent"}`; `parent_id is not None` iff `type == "child"`) |

### 1.3 `EmbeddedChunk` (inherits `Chunk`)

A chunk paired with its vector representation.

| Field | Type | Constraints |
|---|---|---|
| *(all `Chunk` fields)* | — | Inherited |
| `vector` | `list[float]` | Real dense vector for `"child"` chunks; zero vector `[0.0] * dim` for `"parent"` records |

### 1.4 `RetrievedChunk` (inherits `EmbeddedChunk`)

A chunk returned from Phase 2 similarity search or parent expansion.

| Field | Type | Constraints |
|---|---|---|
| *(all `EmbeddedChunk` fields)* | — | Inherited |
| `score` | `float` | Normalized cosine similarity in `[0.0, 1.0]` (`1.0 - cosine_distance`); for expanded parents, `max(child.score)` across all matching children of that parent |

---

## 2. Configuration & Lifecycle Data Types (`types.py`)

### 2.1 `ChunkingProfile`

Immutable dataclass instantiated as constants (`DEFAULT`, `POLICY`) in `config.py`.

| Field | Type | `DEFAULT` | `POLICY` |
|---|---|---|---|
| `name` | `str` | `"DEFAULT"` | `"POLICY"` |
| `chunk_size` | `int` | `512` | `1000` |
| `overlap` | `int` | `64` | `80` |
| `clause_preserving` | `bool` | `False` | `True` |
| `parent_child` | `bool` | `True` | `True` |
| `resolve_crossrefs` | `bool` | `False` | `True` |

### 2.2 `SourceRecord` & `Manifest`

Database-collocated state stored at `<persist_dir>/manifests/<collection>.json`.

#### `SourceRecord`
| Field | Type | Description |
|---|---|---|
| `source` | `str` | Canonical source key (relative path or filename) |
| `content_hash` | `str` | Full `"sha256:<hex>"` digest of raw file bytes |
| `doc_version` | `str` | 12-char hex prefix matching `metadata["doc_version"]` in ChromaDB |
| `size` | `int` | File size in bytes at last commit |
| `mtime` | `float` | File modification timestamp (`st_mtime`) used strictly as fast-path hint |
| `ingested_at` | `str` | ISO-8601 UTC timestamp |
| `embed_model` | `str` | Embedding `provider/model` string |
| `profile` | `str` | Chunking profile name (`"DEFAULT"` or `"POLICY"`) |
| `chunk_ids` | `list[str]` | IDs of committed child chunks |
| `parent_ids` | `list[str]` | IDs of committed parent sections |

#### `Manifest`
| Field | Type | Description |
|---|---|---|
| `collection` | `str` | Target ChromaDB collection name |
| `embed_model` | `str \| None` | Collection-wide locked embedding model (`None` until first commit) |
| `embed_dim` | `int \| None` | Vector dimensionality locked at first commit |
| `sources` | `dict[str, SourceRecord]` | Map of `source` key → `SourceRecord` |

### 2.3 Operation Result Types

- **`IngestResult`**: `collection: str`, `embed_model: str`, `ingested: list[str]`, `skipped: list[str]`, `chunks_written: int`, `parents_written: int`
- **`SyncResult`**: `collection: str`, `embed_model: str`, `added: list[str]`, `updated: list[str]`, `skipped: list[str]`, `removed: list[str]`
- **`CollectionStatus`**: `collection: str`, `embed_model: str | None`, `embed_dim: int | None`, `total_sources: int`, `total_children: int`, `total_parents: int`, `sources: list[SourceRecord]`

---

## 3. Phase 1 Internal Intermediate Types (Not Exported)

- **`ParsedSection`** (produced by `intake.py` -> refined by `clean.py` & `crossrefs.py`):
  `source: str`, `section_label: str`, `heading_level: int`, `page: int | None`, `clauses: list[ParsedClause]`, `raw_text: str`
- **`ParsedClause`**:
  `clause_label: str | None`, `text: str`, `page: int | None`

---

## 4. State Transitions (Transactional Ingestion & Sync)

```text
[File on Disk]
   ├── Not in Manifest ──────────────────────► NEW     ──► Parse/Clean/Chunk/Embed (in-memory)
   ├── mtime & size match Manifest ──────────► SKIP    ──► No-op (0 disk reads)
   ├── mtime/size differ, sha256 matches ────► SKIP    ──► Refresh mtime/size in Manifest
   └── sha256 differs (or --force) ──────────► CHANGED ──► Parse/Clean/Chunk/Embed (in-memory)
                                                               │
                                                               ▼
                                                    Insert new version (doc_version=v2)
                                                               │
                                                               ▼
                                                    Atomic Manifest commit (os.replace)
                                                               │
                                                               ▼
                                                    Delete old records (doc_version != v2)
```

If any step prior to the atomic Manifest commit fails:
- Errors before Chroma write leave the store untouched.
- A crash during Chroma write leaves uncommitted `v2` records excluded by Phase 2 version verification and purged on next Phase 1 run, preserving `v1` 100% queryable.
