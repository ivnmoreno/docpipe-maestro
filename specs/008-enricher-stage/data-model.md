# Data Model: First-Class Enricher Stage & Cross-Reference Migration

**Feature**: `008-enricher-stage` | **Date**: 2026-11-15 | **Branch**: `feat/008-enricher-stage`

## 1. Entities & Configuration Schemas (`src/docpipe_maestro/types.py`, `src/docpipe_maestro/config.py`)

### `ChunkingProfile` (`src/docpipe_maestro/types.py`)

Immutable (`frozen=True, slots=True`) configuration governing chunking rules and ordered Phase 1 post-clean enrichment.

| Field | Type | Default | Constraint / Normalization |
| --- | --- | --- | --- |
| `name` | `str` | required | Canonical uppercase profile identifier (e.g., `"DEFAULT"`, `"POLICY"`) |
| `chunk_size` | `int` | required | Target maximum child chunk budget in estimated tokens |
| `overlap` | `int` | required | Trailing word-token overlap scoped per parent section |
| `clause_preserving` | `bool` | required | Prevents mid-clause splitting in policy documents |
| `parent_child` | `bool` | required | Controls parent section emission alongside child chunks |
| `resolve_crossrefs` | `bool` | required | Preserved legacy flag; triggers auto-population when `enrichers` is empty |
| `enrichers` | `tuple[str, ...]` | `()` | Immutable ordered sequence of `ENRICHERS` registry keys to run post-clean |

#### Profile Normalization Rules (`__post_init__`)

| Input (`resolve_crossrefs`, `enrichers`) | Normalized `enrichers` | Pipeline Behavior |
| --- | --- | --- |
| `(False, ())` — e.g. `DEFAULT` | `()` | Skips enrichment; `0` `ENRICHERS.resolve(...)` calls |
| `(True, ("crossrefs",))` — e.g. `POLICY` | `("crossrefs",)` | Resolves and executes `"crossrefs"` |
| `(True, omitted / ())` — legacy custom profile | `("crossrefs",)` | Normalized at creation via `object.__setattr__`; executes `"crossrefs"` |
| `(False, ("custom",))` or `(True, ("custom",))` | `("custom",)` | Explicit non-empty `enrichers` governs directly without auto-adding `"crossrefs"` |
| `(*, ("first", "second", "first"))` | `("first", "second", "first")` | All entries resolved up front and executed sequentially in exact order |

### Built-In Profile Constants (`src/docpipe_maestro/config.py`)

- `DEFAULT`: `ChunkingProfile(..., resolve_crossrefs=False, enrichers=())` → `DEFAULT.enrichers == ()`.
- `POLICY`: `ChunkingProfile(..., resolve_crossrefs=True, enrichers=("crossrefs",))` → `POLICY.enrichers == ("crossrefs",)`.

---

### `IngestContext` (`src/docpipe_maestro/types.py`)

Existing `TypedDict` (`_IngestContextBase` required keys + optional `extra: dict[str, Any]` under `total=False`) constructed per non-unchanged document during both `ingest()` and `sync()`:

| Key | Value Source in `ingest()` & `sync()` | Type |
| --- | --- | --- |
| `collection` | `collection` argument | `str` |
| `source` | Canonical `source_key` | `str` |
| `content_hash` | Full `"sha256:<hex>"` digest from `classify_file` | `str` |
| `doc_version` | `content_hash.split(":", 1)[1][:12]` | `str` |
| `embed_model` | `embed_model` argument | `str` |
| `profile` | `prof.name` | `str` |

---

## 2. Phase 1 Stage Contract & Enricher Strategy (`src/docpipe_maestro/ingest/stages.py`, `src/docpipe_maestro/ingest/enricher/`)

### `Enricher` Protocol (unchanged in `src/docpipe_maestro/ingest/stages.py`)

- `@runtime_checkable class Enricher(Protocol)`
- Attribute: `name: str`
- Method: `enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument`

### `CrossrefsEnricher` (`src/docpipe_maestro/ingest/enricher/crossrefs.py`)

- Registered lazily in `ENRICHERS` under `"crossrefs"` and decorated with `@ENRICHERS.register("crossrefs")`.
- `name: str = "crossrefs"`
- `enrich(doc, ctx) -> ParsedDocument`: delegates to `resolve_crossrefs(doc)` using `ctx` to satisfy the `Enricher` protocol without altering intra-document cross-reference resolution semantics, `[Crossref ...]` output formatting, self-reference cycle exclusion, or `WARNING` logging for unresolved targets.

---

## 3. Phase-Neutral Cross-Reference Core (`src/docpipe_maestro/_crossrefs.py`)

Pure text-processing utilities shared identically between `ingest/enricher/crossrefs.py` (Phase 1) and `query/retriever.py` (Phase 2), with zero dependencies on either phase:

| Symbol | Signature | Purpose |
| --- | --- | --- |
| `CROSSREF_RE` | `re.Pattern[str]` | Matches intra-document `Section N`, `Article N`, `Clause N`, and `§N` references |
| `extract_section_num` | `(label: str) -> str \| None` | Extracts normalized section/dotted heading number while ignoring years/measurements |
| `truncate_excerpt` | `(text: str, max_chars: int = 400) -> str` | Word-boundary truncation appending `"..."` |
| `parse_crossref_match` | `(match: re.Match[str]) -> tuple[list[str], str, str]` | Produces `(lookup_keys, numeric_target, display_label)` |
| `index_section_targets` | `(sections: Sequence[tuple[str, str]]) -> dict[str, tuple[str, int]]` | Indexes normalized section and clause numbers to `(excerpt_text, section_idx)` |
| `extract_doc_crossrefs` | `(text: str) -> list[tuple[str, list[str], str]]` | Extracts explicit document-scoped cross-references outside `[Crossref ...]` lines |
| `match_source_key` | `(doc_phrase: str, available_sources: Sequence[str], *, current_source: str \| None = None) -> str \| None` | Unambiguously resolves cited document phrases to a target collection source key |

---

## 4. Phase 1 Pipeline Data Flow

```text
  file + manifest
        │
        ▼ (upfront before scanning/skipping files)
  CLEANERS.resolve(cleaner)()
  [ENRICHERS.resolve(name)() for name in prof.enrichers]   ──(unknown key)──▶ RegistryError (0 store/manifest writes)
  CHUNKERS.resolve(chunker)()
  EMBEDDERS.resolve(embedder)()
  STORES.resolve(store)
        │
        ▼ (per non-unchanged file, in-memory staged_docs loop)
  Parser.parse ─▶ Cleaner.clean ─▶ for e in enrichers: doc = e.enrich(doc, ctx) ─▶ Chunker.chunk ─▶ Embedder.embed
                                         │
                                    (any exception)
                                         ▼
                               Abort batch cleanly
                   (0 Chroma writes, 0 FTS5 writes, 0 manifest writes)
        │
        ▼ (only after ALL changed files succeed in memory)
  Store/Lexical stale sweep ─▶ add_chunks ─▶ save_manifest ─▶ delete_stale_versions ─▶ remove deletions
```
