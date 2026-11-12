# Public Python Library API Contract

**Package**: `docpipe_maestro` | **Contract Version**: `0.1.0`

Per Constitution Principle I and Quality Gates, every core capability MUST be reachable through this public surface exported from `docpipe_maestro.__init__`.

---

## 1. Exported Symbols (`__all__`)

### Data Types (imported from `docpipe_maestro.types`)
- `Chunk`
- `EmbeddedChunk`
- `RetrievedChunk`
- `IngestResult`
- `SyncResult`
- `CollectionStatus`
- `SourceRecord`

### Exceptions (imported from `docpipe_maestro.types`)
- `DocpipeError(Exception)` — base exception for library errors
- `UnsupportedFormatError(DocpipeError)` — unknown or corrupted input format
- `MissingExtraError(DocpipeError)` — optional format parser or generation extra missing
- `ModelMismatchError(DocpipeError)` — collection `embed_model` differs from requested model
- `MissingCredentialError(DocpipeError)` — required provider environment variable unset (never prints secret values)

### Phase 1 — Ingestion & Corpus Lifecycle (`docpipe_maestro.ingest`)

```python
def ingest(
    path: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    embed_model: str = "ollama/nomic-embed-text",
    force: bool = False,
) -> IngestResult: ...
```
- Accepts a single file or directory.
- **Atomic Batch Rule**: Validates and parses *all* target files before modifying the store; any corrupted or unsupported file aborts immediately (`UnsupportedFormatError` / `MissingExtraError`).
- **Hash Fast-Path**: Skips files whose `sha256` matches the manifest unless `force=True`.
- **Model Lock**: Raises `ModelMismatchError` if `collection` is already locked to a different `embed_model`.

```python
def sync(
    directory: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    embed_model: str = "ollama/nomic-embed-text",
) -> SyncResult: ...
```
- Three-way reconciliation between `directory` and the collection manifest: ingests new files, skips unchanged files, replaces modified files via staged delete-then-reinsert, and purges records/manifest entries for files deleted from `directory`.

```python
def remove(
    source: str | Path,
    *,
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
) -> bool: ...
```
- Deletes all child and parent records for `source` from ChromaDB and removes its entry from the manifest. Returns `True` if removed, `False` if absent.

```python
def status(
    *,
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
) -> CollectionStatus: ...
```
- Read-only inspection of the manifest and collection metadata (`embed_model`, `embed_dim`, indexed sources, hashes, timestamps, chunk counts).

```python
def reindex(
    *,
    embed_model: str,
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
) -> int: ...
```
- Re-embeds all existing stored child chunks directly from ChromaDB using `embed_model`, updates parent zero-vector dimensions if dimensionality changed, updates `embed_model` metadata on all records and manifest, and swaps cleanly. Returns count of re-embedded child chunks.

---

### Phase 2 — Retrieval, Prompting & Optional Generation (`docpipe_maestro.query`)

```python
def retrieve(
    question: str,
    *,
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    embed_model: str = "ollama/nomic-embed-text",
    top_k: int = 5,
    threshold: float | None = None,
    expand_parent: bool = True,
) -> list[RetrievedChunk]: ...
```
- **Read-Only Store**: Performs zero mutations to ChromaDB or manifest.
- **Model Lock Check**: Verifies `embed_model` matches `manifest.embed_model` (if corpus non-empty), raising `ModelMismatchError` on mismatch.
- **Child-Only Search**: Queries `where={"type": "child"}` on normalized cosine similarity `[0.0, 1.0]`, verifies committed `doc_version` against manifest, filters `score >= threshold` if provided.
- **Parent Expansion**: When `expand_parent=True`, expands unique `parent_id`s by fetching parents by ID, assigns `max(child.score)` per parent, and returns sorted descending by `score`. When `expand_parent=False`, returns matched children sorted descending by `score`.

```python
def build_prompt(
    question: str,
    sections: Sequence[RetrievedChunk],
) -> str: ...
```
- **Pure Function**: Zero I/O, zero network calls, zero side effects, sub-millisecond execution.
- Formats retrieved sections with source attribution metadata (`source`, `section`, `clause`, `page`) and strict grounding instructions requiring the model to answer solely from the provided context and state if the answer is absent.

```python
def answer(
    prompt: str,
    *,
    model: str = "ollama/llama3.2",
    api_base: str | None = None,
    has_context: bool = True,
) -> str: ...
```
- Optional generation capability (lazily loaded from `docpipe_maestro.query.answer`).
- **Empty Context Short-Circuit**: When `has_context=False` (or retrieved sections were empty), returns a deterministic refusal message (`"Not found in the provided context."`) immediately without invoking the LLM.
- Delegates `provider/model` resolution directly to `litellm.completion`, reading provider credentials exclusively from environment variables.
