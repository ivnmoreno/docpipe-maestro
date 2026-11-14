# Module & Stage Contracts: Enricher Stage & Cross-Reference Isolation

**Feature**: `008-enricher-stage` | **Branch**: `feat/008-enricher-stage`

## 1. Phase-Neutral Shared Module (`src/docpipe_maestro/_crossrefs.py`)

**Allowed imports**: Python standard library only (`re`, `collections.abc.Sequence`). MUST NOT import any `docpipe_maestro.ingest.*` or `docpipe_maestro.query.*` module.

### Public Constants & Functions

```python
CROSSREF_RE: re.Pattern[str]


def extract_section_num(label: str) -> str | None: ...
def truncate_excerpt(text: str, max_chars: int = 400) -> str: ...
def parse_crossref_match(match: re.Match[str]) -> tuple[list[str], str, str]: ...
def iter_clause_blocks(raw_text: str) -> list[tuple[str, str]]: ...
def index_section_targets(sections: Sequence[tuple[str, str]]) -> dict[str, tuple[str, int]]: ...
def extract_doc_crossrefs(text: str) -> list[tuple[str, list[str], str]]: ...
def match_source_key(
    doc_phrase: str,
    available_sources: Sequence[str],
    *,
    current_source: str | None = None,
) -> str | None: ...
```

---

## 2. Phase 1 Enricher Registry & Strategy (`src/docpipe_maestro/ingest/enricher/`)

### Package Init (`src/docpipe_maestro/ingest/enricher/__init__.py`)

```python
ENRICHERS: Registry[Enricher] = Registry("enricher")
register_enricher = ENRICHERS.register

ENRICHERS.register_lazy(
    "crossrefs",
    "docpipe_maestro.ingest.enricher.crossrefs",
    "CrossrefsEnricher",
)

__all__ = [
    "ENRICHERS",
    "CrossrefsEnricher",
    "register_enricher",
    "resolve_crossrefs",
]
```

- Uses `__getattr__` lazy loading matching `ingest/clean/__init__.py` and `ingest/chunker/__init__.py`.
- Importing `docpipe_maestro` or `docpipe_maestro.ingest.enricher` MUST NOT eagerly import `docpipe_maestro.ingest.enricher.crossrefs` until `"crossrefs"` is resolved via `ENRICHERS.resolve("crossrefs")` or explicitly accessed by attribute name.

### Built-In Enricher (`src/docpipe_maestro/ingest/enricher/crossrefs.py`)

```python
def resolve_crossrefs(doc: ParsedDocument) -> ParsedDocument: ...


@ENRICHERS.register("crossrefs")
class CrossrefsEnricher:
    name: str = "crossrefs"

    def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument: ...
```

- Conforms to `@runtime_checkable` `Enricher` protocol (`docpipe_maestro.ingest.stages.Enricher`).
- `CrossrefsEnricher.enrich(doc, ctx)` returns `resolve_crossrefs(doc)` preserving identical `[Crossref ...]` formatting, `max_chars=400` excerpt bounding, cycle/self-reference skip behavior, and `WARNING` logging on unresolved targets.

---

## 3. Silent Compatibility Shim (`src/docpipe_maestro/ingest/crossrefs.py`)

Preserves all five pre-Stage-3 imports with zero deprecation warnings:

```python
from docpipe_maestro._crossrefs import (
    extract_doc_crossrefs,
    index_section_targets,
    match_source_key,
    truncate_excerpt,
)
from docpipe_maestro.ingest.enricher.crossrefs import resolve_crossrefs

__all__ = [
    "extract_doc_crossrefs",
    "index_section_targets",
    "match_source_key",
    "resolve_crossrefs",
    "truncate_excerpt",
]
```

---

## 4. Phase 2 Consumer Contract (`src/docpipe_maestro/query/retriever.py`)

- Replaces `from docpipe_maestro.ingest.crossrefs import ...` with:
  ```python
  from docpipe_maestro._crossrefs import (
      extract_doc_crossrefs,
      index_section_targets,
      match_source_key,
      truncate_excerpt,
  )
  ```
- `_enrich_crossdoc_references(...)` behavior, output schema, and `follow_crossrefs` semantics remain 100% unchanged.
- Zero files under `src/docpipe_maestro/query/` may import `docpipe_maestro.ingest` or `docpipe_maestro.ingest.*` (direct or dynamic), and shared `src/docpipe_maestro/_crossrefs.py` may import zero `docpipe_maestro.ingest*` or `docpipe_maestro.query*` modules (enforced by AST scan in `tests/test_library_purity.py` to guarantee zero direct or transitive Phase 2 → Phase 1 dependencies).

---

## 5. Profile & Pipeline Orchestration Contracts

### `ChunkingProfile` (`src/docpipe_maestro/types.py`) & Profiles (`src/docpipe_maestro/config.py`)

- `ChunkingProfile.enrichers: tuple[str, ...] = ()`
- `__post_init__`: converts `enrichers` via `tuple(self.enrichers)`; if `self.resolve_crossrefs and not normalized`, sets `enrichers = ("crossrefs",)`.
- `DEFAULT.enrichers == ()` and `POLICY.enrichers == ("crossrefs",)`.

### `ingest()` and `sync()` (`src/docpipe_maestro/ingest/pipeline.py`)

- Signature of `ingest(...)` and `sync(...)` remains strictly unchanged (verified by `tests/test_api_stability.py`).
- No inline `if prof.resolve_crossrefs:` branch in `pipeline.py`.
- Shared private helpers:
  - `_resolve_enrichers(enricher_names: Sequence[str]) -> list[Enricher]`: returns `[]` for empty sequences; otherwise resolves and instantiates `[ENRICHERS.resolve(name)() for name in enricher_names]` up front alongside `CLEANERS`/`CHUNKERS`/`EMBEDDERS`/`STORES` before scanning/skipping files. Unregistered keys raise `RegistryError` immediately.
  - `_apply_enrichers(doc: ParsedDocument, enrichers: Sequence[Enricher], ctx: IngestContext) -> ParsedDocument`: applies `enrichers` sequentially in declared order between `cleaner_inst.clean(parsed)` and `chunker_inst.chunk(...)`.
- Both `ingest()` and `sync()` construct `IngestContext`:
  ```python
  ctx: IngestContext = {
      "collection": collection,
      "source": source_key,
      "content_hash": content_hash,
      "doc_version": doc_version,
      "embed_model": embed_model,
      "profile": prof.name,
  }
  ```
- Any exception raised during `_resolve_enrichers(...)` or `_apply_enrichers(...)` aborts the operation cleanly prior to creating/mutating `Store`, `LexicalIndex`, or `save_manifest(...)`.
