# Data Model: Pluggable Pipeline Stage Registries

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-13

## Overview

Per Constitution Principle VII ("Data shapes are defined once in `types.py` and imported everywhere; schema drift across modules is prohibited"), all cross-module data structures and public exceptions reside in `src/docpipe_maestro/types.py`. Compatibility re-exports remain available at legacy import paths (`docpipe_maestro.ingest.intake`, etc.). All `@dataclass(slots=True)` models remain slot-based (never use `.__dict__`).

---

## New & Relocated Entities

### 1. `RegistryError` (Public Exception in `types.py`)

- **Base Class**: `DocpipeError`
- **Exports**: `docpipe_maestro.types.RegistryError`, `docpipe_maestro._registry.RegistryError`, `docpipe_maestro.RegistryError` (in top-level `__all__`)
- **Semantics**: Raised when stage registration violates key uniqueness (live or deferred built-in) or when `resolve(key)` misses an unknown key (`KeyError` caught internally and re-raised via `raise RegistryError(...) from exc`).
- **Message Contract**:
  - Duplicate key: `f"registry '{name}' already has entry '{key}'"`
  - Unknown key: `f"registry '{name}' has no entry '{key}' (available: {available})"` where `available` is `", ".join(sorted(entries))` or `"<empty>"`.

### 2. `Registry[T]` (`src/docpipe_maestro/_registry.py`)

Generic named registry managing pluggable stage classes (`type[T]`).

| Field | Type | Visibility | Description |
|-------|------|------------|-------------|
| `_name` | `str` | Read-only property (`name`) | Logical stage category name (e.g., `"parser"`, `"cleaner"`, `"store"`). |
| `_entries` | `dict[str, type[T]]` | Private | Materialized `key -> class` registrations. |
| `_lazy_builtins` | `dict[str, tuple[str, str]]` | Private | Deferred `(module_path, attribute)` declarations imported on demand. |
| `_materializing` | `set[str]` | Private | Re-entrancy guard tracking keys currently importing their deferred built-in module. |

#### Lifecycle & State Transitions

```text
[Uninitialized]
   │
   ├── register_lazy(key, mod, attr) ──► [Declared Lazy]
   │                                           │
   │                                           ├── register(key) (outside materializing) ──► RegistryError
   │                                           │
   │                                           └── resolve(key) / key in reg / keys()
   │                                                    │
   │                                                    ▼
   │                                            [Materializing] ──(import + @register / attr)──► [Materialized]
   │
   └── register(key)(cls) ────────────────────────────────────────────────────────────────────────► [Materialized]
                                                                                                         │
                                                                                     register(key) ──────┴──► RegistryError
```

- Calling `clear()` resets `_entries`, `_lazy_builtins`, and `_materializing` strictly for explicit test isolation.

### 3. Relocated Intake Models (`ingest/intake.py` → `types.py`, re-exported in `ingest/intake/__init__.py`)

#### `ParsedClause` (`@dataclass(slots=True)`)

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `clause_label` | `str \| None` | *(required)* | Clause identifier label when detected, or `None`. |
| `text` | `str` | *(required)* | Extracted clause or paragraph text. |
| `page` | `int \| None` | `None` | 1-based page number for paginated documents (PDF), else `None`. |

#### `ParsedSection` (`@dataclass(slots=True)`)

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `source` | `str` | *(required)* | Normalized source key (relative POSIX path or filename). |
| `section_label` | `str` | *(required)* | Heading label containing the section (defaults to `"Introduction"` when absent). |
| `heading_level` | `int` | *(required)* | Hierarchical heading depth (`1`–`6`). |
| `raw_text` | `str` | *(required)* | Section body text prior to chunking. |
| `page` | `int \| None` | `None` | 1-based page number where applicable, else `None`. |
| `clauses` | `list[ParsedClause]` | `field(default_factory=list)` | Optional structured clause list. |

#### `ParsedDocument` (`@dataclass(slots=True)`)

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `source` | `str` | *(required)* | Normalized source key matching `ParsedSection.source`. |
| `format_name` | `str` | *(required)* | Canonical parser format identifier (`"md"`, `"txt"`, `"html"`, `"pdf"`, `"docx"`, or custom parser name). |
| `sections` | `list[ParsedSection]` | `field(default_factory=list)` | Ordered document sections processed cleanly by Phase 1 stages. |

### 4. `IngestContext` (`TypedDict` in `types.py`)

Uses Python 3.10-compatible two-step inheritance (`_IngestContextBase` + `total=False` extension bag) with zero `typing.NotRequired` or `typing_extensions` dependency:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `collection` | `str` | Yes | Target collection identifier. |
| `source` | `str` | Yes | Canonical normalized POSIX source key. |
| `content_hash` | `str` | Yes | Full `"sha256:<hex>"` digest of source file bytes. |
| `doc_version` | `str` | Yes | Deterministic 12-character hex prefix (`content_hash.split(":", 1)[1][:12]`). |
| `embed_model` | `str` | Yes | Active `provider/model` embedding identifier. |
| `profile` | `str` | Yes | Resolved canonical `ChunkingProfile.name` (e.g., `"DEFAULT"`, `"POLICY"`). |
| `extra` | `dict[str, Any]` | No | Optional extensibility bag for downstream `Enricher` stages (Stage 3/4). |

---

## Preserved Shared Shapes (`src/docpipe_maestro/types.py`)

The following entities and invariants remain bit-for-bit unchanged in Stage 1:

- **Exceptions**: `DocpipeError`, `UnsupportedFormatError(DocpipeError)`, `MissingExtraError(DocpipeError)`, `ModelMismatchError(DocpipeError)`, `MissingCredentialError(DocpipeError)`.
- **Chunk & Retrieval Types**: `ChunkType = Literal["child", "parent"]`, `ChunkMetadata(TypedDict)`, `make_chunk_id(...)`, `Chunk(@dataclass(slots=True))` (enforcing non-empty `parent_id` for children and `parent_id=None` for parents), `EmbeddedChunk(Chunk)`, `RetrievedChunk(EmbeddedChunk)` (`score` normalized onto `[0.0, 1.0]`).
- **Configuration & Manifest Types**: `ChunkingProfile(@dataclass(frozen=True, slots=True))` (keeping `name`, `chunk_size`, `overlap`, `clause_preserving`, `parent_child`, `resolve_crossrefs`), `SourceRecord`, `Manifest`.
- **Operation Results**: `IngestResult`, `SyncResult`, `CollectionStatus`, `GenerationResult`.
