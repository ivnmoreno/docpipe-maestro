# Contract: Top-Level Public API & Compatibility Surface

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-11-13

## Top-Level Package Exports (`docpipe_maestro.__all__`)

All 24 baseline exports are preserved cleanly alongside `RegistryError` (inheriting from `DocpipeError`) and all eight lazy `register_*` extension entry points (33 exports total):

- **Functions**: `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, `answer`, `answer_detailed`
- **Extension Entry Points (Lazy)**: `register_parser`, `register_cleaner`, `register_enricher`, `register_chunker`, `register_embedder`, `register_store`, `register_searcher`, `register_reranker`
- **Data Shapes**: `Chunk`, `EmbeddedChunk`, `RetrievedChunk`, `SourceRecord`, `IngestResult`, `SyncResult`, `CollectionStatus`, `GenerationResult`
- **Exceptions**: `DocpipeError`, `MissingCredentialError`, `MissingExtraError`, `ModelMismatchError`, `RegistryError`, `UnsupportedFormatError`
- **Metadata**: `__version__`

---

## Public Callable Signatures

Every pre-existing parameter keeps its exact name, position/keyword status, type annotation, and default. New stage selector parameters added per Clarification Q1 / `FR-006` are strictly keyword-only defaulting to `"default"`:

```python
def ingest(
    path: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    force: bool = False,
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
) -> IngestResult: ...


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
) -> SyncResult: ...


def remove(
    source: str | Path,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    store: str = "default",
) -> bool: ...


def status(
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    store: str = "default",
) -> CollectionStatus: ...


def reindex(
    *,
    embed_model: str,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embedder: str = "default",
    store: str = "default",
) -> int: ...


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
) -> list[RetrievedChunk]: ...
```

Unchanged public callable signatures:
- `build_prompt(question: str, sections: Sequence[RetrievedChunk]) -> str`
- `build_chat_messages(question: str, sections: Sequence[RetrievedChunk]) -> list[dict[str, str]]`
- `answer_detailed(prompt: str | Sequence[Mapping[str, str]], *, model: str = DEFAULT_GENERATION_MODEL, api_base: str | None = None, has_context: bool = True, temperature: float | None = None, max_tokens: int | None = None, timeout: float = DEFAULT_REQUEST_TIMEOUT, model_kwargs: Mapping[str, Any] | None = None, fail_on_truncation: bool = False) -> GenerationResult`
- `answer(...) -> str` (matching identical parameters as `answer_detailed`)

Stage selector semantics note (`status`): `status(..., store="default")` validates any non-default `store` key via `STORES.resolve(store)` (raising `RegistryError` if unregistered) while reading source counts, chunk counts, and `embed_model` from the collection's shared JSON manifest (`manifest.json`), keeping `"default"` manifest-only without instantiating ChromaDB.

---

## Internal & Module-Level Compatibility Re-Exports

All existing import paths used across tests, CLI, and internal callers remain valid:

| Legacy Import Path | Preserved Symbols | Source / Delegation |
|--------------------|-------------------|---------------------|
| `docpipe_maestro.types` | All baseline shapes & exceptions + `RegistryError`, `IngestContext`, `ParsedClause`, `ParsedSection`, `ParsedDocument` | Canonical schema module |
| `docpipe_maestro.ingest.intake` | `PARSERS`, `register_parser`, `ParsedClause`, `ParsedSection`, `ParsedDocument`, `SUPPORTED_EXTENSIONS`, `detect_format`, `parse_file` | `parse_file` delegates via `_resolve.resolve_parser`; data types re-exported from `types.py` |
| `docpipe_maestro.ingest.clean` | `CLEANERS`, `register_cleaner`, `clean_text`, `clean_document`, `DefaultCleaner` (lazy or re-exported) | `ingest/clean/__init__.py` |
| `docpipe_maestro.ingest.chunker` | `CHUNKERS`, `register_chunker`, `chunk_document`, `estimate_tokens`, `DefaultChunker` (lazy or re-exported) | `ingest/chunker/__init__.py` |
| `docpipe_maestro.ingest.crossrefs` | `resolve_crossrefs`, `extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, `truncate_excerpt` | Unchanged module location (imports `ParsedDocument`, `ParsedSection` from `types.py` or `intake`) |
| `docpipe_maestro.embedder` | `EMBEDDERS`, `register_embedder`, `DEFAULT_REQUEST_TIMEOUT`, `embed_texts`, `embed_query`, `prepare_litellm`, `raise_litellm_error`, `validate_api_base`, `_item_field`, `_is_loopback_host` | Lazy `__getattr__` for heavy helpers; `DEFAULT_REQUEST_TIMEOUT` eager-safe |
| `docpipe_maestro.store` | `STORES`, `register_store`, `VectorStore`, `ChromaStore` | Lazy `__getattr__` in `store/__init__.py` so `chromadb` only imports on backend access |
