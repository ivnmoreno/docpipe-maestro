# Python API Reference

This document specifies the complete public Python API of **`docpipe_maestro`**. Per Library Purity rules, **no library function ever reads a configuration file** — all configuration is passed via explicit keyword arguments and environment variables (for provider API keys).

```python
import docpipe_maestro
from docpipe_maestro import (
    ingest,
    sync,
    remove,
    status,
    reindex,
    retrieve,
    build_prompt,
    build_chat_messages,
    answer,
    answer_detailed,
    register_parser,
    register_cleaner,
    register_enricher,
    register_chunker,
    register_embedder,
    register_store,
    register_searcher,
    register_reranker,
    Chunk,
    EmbeddedChunk,
    RetrievedChunk,
    SourceRecord,
    IngestResult,
    SyncResult,
    CollectionStatus,
    GenerationResult,
    DocpipeError,
    UnsupportedFormatError,
    MissingExtraError,
    ModelMismatchError,
    MissingCredentialError,
    RegistryError,
)
```

---

## 1. Phase 1: Offline Ingestion & Corpus Lifecycle

### `ingest(...) -> IngestResult`

```python
def ingest(
    path: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    embed_model: str = "ollama/nomic-embed-text",
    force: bool = False,
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
) -> IngestResult
```

Atomically ingests a single file or directory tree (recursively sorted by relative POSIX path) into ChromaDB, updates the collocated SQLite FTS5 lexical index (`<persist_dir>/lexical/<collection>.db`), and updates the collocated manifest.

- **Batch Atomicity**: Parses, cleans, chunks, and embeds all changed files in memory *before* creating or modifying `VectorStore`. Any unsupported file or missing parser extra aborts the entire run cleanly.
- **Fast-Path & Hash Check**: Files with unchanged `(size, mtime)` skip disk hashing unless `force=True`; changed timestamps with identical `sha256` refresh manifest metadata without re-embedding.
- **Self-Exclusion**: Any directory matching `persist_dir` nested under `path` is automatically skipped.
- **Empty Directories**: Raises `UnsupportedFormatError` if `path` does not exist or yields zero files.

**Raises**: `UnsupportedFormatError`, `MissingExtraError`, `ModelMismatchError`, `MissingCredentialError`, `RegistryError`, `DocpipeError`.

---

### `sync(...) -> SyncResult`

```python
def sync(
    directory: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    embed_model: str = "ollama/nomic-embed-text",
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
) -> SyncResult
```

Performs three-way reconciliation between `directory` and `<persist_dir>/manifests/<collection>.json`:

1. **Added**: New files on disk are parsed, chunked, embedded, and inserted into both vector and lexical stores.
2. **Updated**: Modified files (different `sha256`) undergo staged delete-then-reinsert under a new `doc_version`, preventing orphaned clauses if the file shrank.
3. **Skipped**: Files matching manifest hashes (even after `touch`) are skipped.
4. **Removed**: Source keys tracked in the manifest that no longer exist under `directory` are purged from ChromaDB, SQLite FTS5, and the manifest. (An empty existing directory cleanly purges all tracked sources.)

**Raises**: `UnsupportedFormatError` (if `directory` is not an existing directory or contains an invalid file), `MissingExtraError`, `ModelMismatchError`, `MissingCredentialError`, `RegistryError`, `DocpipeError`.

---

### `remove(...) -> bool`

```python
def remove(
    source: str | Path,
    *,
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    store: str = "default",
) -> bool
```

Deletes all child chunks, parent sections, lexical FTS5 entries (when present), and the manifest entry matching `Path(source).as_posix()`.

- **Returns**: `True` if the source was tracked and purged; `False` if not present in the collection manifest.

---

### `status(...) -> CollectionStatus`

```python
def status(
    *,
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    store: str = "default",
) -> CollectionStatus
```

Read-only inspection of the manifest for `collection`. Does not initialize embeddings or mutate storage.

- **Returns**: `CollectionStatus` with `embed_model`, `embed_dim`, aggregate `total_sources`, `total_children`, `total_parents`, and sorted `sources: list[SourceRecord]`.

---

### `reindex(...) -> int`

```python
def reindex(
    *,
    embed_model: str,
    collection: str = "default",
    persist_dir: str | Path = ".docpipe",
    embedder: str = "default",
    store: str = "default",
) -> int
```

Migrates an existing collection to a new embedding model (and/or builds its collocated FTS5 lexical index) without re-parsing source files from disk:

1. Reads all committed child and parent chunks directly from ChromaDB.
2. Embeds all child chunks in memory under the new `embed_model` (if the collection is empty, updates `manifest.embed_model`, sets `embed_dim=None`, resets the lexical DB, and returns `0`).
3. Rebuilds parent zero-vector placeholders matching the new vector dimension `len(new_vectors[0])`.
4. Resets the ChromaDB collection and SQLite FTS5 lexical index, inserts rebuilt records, and updates the manifest lock, `embed_dim`, and timestamps.

- **Returns**: Number of committed child chunks re-embedded.
- **Raises**: `MissingCredentialError`, `RegistryError`, `DocpipeError`.

---

## 2. Phase 2: Online Retrieval, Prompting & Optional Generation

### `retrieve(...) -> list[RetrievedChunk]`

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
    follow_crossrefs: bool = True,
    embedder: str = "default",
    store: str = "default",
    searcher: str = "default",
) -> list[RetrievedChunk]
```

Read-only retrieval enforcing the collection's embedding model lock:

- Checks `manifest.embed_model` via `check_model_lock()`; raises `ModelMismatchError` if locked to a different model.
- Resolves `searcher` via `SEARCHERS`:
  - `"default"` (`DenseSearcher`): queries dense child chunks exclusively (`where={"type": "child"}`) with `include_embeddings=False`, filtering out uncommitted `doc_version` entries (`score` is cosine similarity in `[0.0, 1.0]`).
  - `"fts5_hybrid"` (`Fts5HybridSearcher`): fuses dense vector candidates with read-only SQLite FTS5 BM25 candidates (`candidate_k = max(child_top_k * 2, 20)`) using Reciprocal Rank Fusion (`k = 60`, weights `0.5` / `0.5`), normalized by theoretical maximum `1 / 61` into `[0.0, 1.0]` (dual rank-1 agreement `== 1.0`; single-signal rank-1 `== 0.5`). Short-circuits whitespace/punctuation-only queries to `[]`, and raises `DocpipeError` recommending `reindex` if a non-empty collection lacks an FTS5 index.
- Returns `[]` immediately without calling the embedder if the collection is empty or `top_k <= 0`.
- Applies optional score cutoff `score >= threshold` (`[0.0, 1.0]`).
- When `expand_parent=True`, searches `top_k * 3` child candidates, assigns each unique `parent_id` `max(child.score)` across its matched children, resolves the top `top_k` parent sections via `get_by_ids(..., include_embeddings=False)`, and returns up to `top_k` unique parents sorted descending by `score`.
- When `expand_parent=True` and `follow_crossrefs=True`, resolves explicit cross-document section/clause citations (e.g., `Section 4.1 of the Compliance Policy`) in one non-recursive pass when the target section is absent from top-`k` results.
- When `expand_parent=False`, returns matched child chunks sorted descending by `score`.

**Raises**: `ModelMismatchError`, `MissingCredentialError`, `RegistryError`, `DocpipeError`.

---

### `build_prompt(...) -> str`

```python
def build_prompt(
    question: str,
    sections: Sequence[RetrievedChunk],
) -> str
```

Pure, deterministic function (zero disk I/O, zero network calls) constructing a grounded prompt:

- Formats each retrieved section with `[1] Source: ... | Section: ...` plus `| Clause: ...` and `| Page: ...` when non-`None`.
- Separates sections with `---`.
- Instructs the LLM to answer *only* from provided context, preserve conditional exceptions and carve-outs (`unless`, `except`, `subject to`, `provided that`, `until`, emergency overrides), cite source/section (and page only when `Page:` is present in context), and state explicitly when the answer is absent. If `sections` is empty, inserts `(No relevant context sections retrieved.)`.

---

### `build_chat_messages(...) -> list[dict[str, str]]`

```python
def build_chat_messages(
    question: str,
    sections: Sequence[RetrievedChunk],
) -> list[dict[str, str]]
```

Pure, deterministic function (zero disk I/O, zero network calls) returning a two-element ChatML structure:

- `[{"role": "system", "content": ...}, {"role": "user", "content": ...}]`
- Isolates grounding instructions inside the `system` role and keeps untrusted document chunks plus the user question inside the `user` role.
- Shares the exact same provenance block formatter as `build_prompt()`.

---

### `answer(...) -> str` & `answer_detailed(...) -> GenerationResult`

```python
def answer(
    prompt: str | Sequence[Mapping[str, str]],
    *,
    model: str = "ollama/llama3.2",
    api_base: str | None = None,
    has_context: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = 120.0,
    model_kwargs: Mapping[str, Any] | None = None,
    fail_on_truncation: bool = False,
) -> str


def answer_detailed(
    prompt: str | Sequence[Mapping[str, str]],
    *,
    model: str = "ollama/llama3.2",
    api_base: str | None = None,
    has_context: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = 120.0,
    model_kwargs: Mapping[str, Any] | None = None,
    fail_on_truncation: bool = False,
) -> GenerationResult
```

Lazily loaded (`__getattr__` on `docpipe_maestro`) completion wrappers powered by `litellm.completion` (`answer()` delegates to `answer_detailed().text`):

- **Empty Context Refusal**: Validates inputs first, then immediately returns `EMPTY_CONTEXT_REFUSAL` (`"Not found in the provided context."`) — or a `GenerationResult` carrying it with zero token telemetry — with zero LLM calls when `has_context=False`.
- **Truncation Guard & Telemetry**: `answer_detailed()` captures `finish_reason`, `truncated` (`finish_reason == "length"`), `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `total_tokens`, and wall `elapsed_seconds`. Passing `fail_on_truncation=True` raises `DocpipeError` when the provider stops due to token limit (`finish_reason == "length"`).
- **Reasoning-Model Parameter Safety**: `temperature` (`>= 0.0`) and `max_tokens` (`>= 1`) are omitted completely from the LiteLLM request when `None` (while explicit `temperature=0.0` is preserved verbatim). `timeout` defaults to `120.0` seconds.
- **Extra Generation Controls (`model_kwargs`)**: Forwarded to `litellm.completion` (e.g., `top_p`, `frequency_penalty`), excluding reserved/conflicting keys (`model`, `messages`, `prompt`, `api_base`, `base_url`, `api_key`, `temperature`, `max_tokens`, `timeout`, `num_retries`) which raise `DocpipeError`.
- **Transport Security (`api_base`)**: Plain `http://` is permitted only for loopback hosts (`localhost`, `127.0.0.0/8`, `::1`); remote endpoints must use `https://`.
- **Provider Examples**:

```python
from docpipe_maestro import answer, answer_detailed, build_chat_messages, retrieve

sections = retrieve("What is the leave policy?", top_k=5)
messages = build_chat_messages("What is the leave policy?", sections)

# Groq serverless inference (reads GROQ_API_KEY from environment)
groq_reply = answer(
    messages,
    model="groq/llama-3.3-70b-versatile",
    temperature=0.0,
    max_tokens=512,
    timeout=30.0,
    has_context=bool(sections),
)

# Detailed result with token telemetry and strict truncation checking
detailed = answer_detailed(
    messages,
    model="together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
    temperature=0.2,
    model_kwargs={"top_p": 0.9},
    has_context=bool(sections),
    fail_on_truncation=True,
)
print(detailed.text, detailed.total_tokens, detailed.elapsed_seconds)
```

- **Fail-Fast Resilience & Privacy**: Passes `num_retries=0` so HTTP `429` fails fast with a sanitized `DocpipeError`; HTTP `401`/`403` raise `MissingCredentialError`; empty `choices`, populated `message.refusal`, or `None`/whitespace-only `content` raise `DocpipeError`; active env secrets and token patterns are scrubbed from error chains.

**Raises**: `MissingExtraError` (if import fails), `MissingCredentialError`, `DocpipeError`.

---

## 3. Configuration & Profiles (`docpipe_maestro.config`)

### Defaults

| Constant | Value |
|---|---|
| `DEFAULT_COLLECTION` | `"default"` |
| `DEFAULT_PERSIST_DIR` | `".docpipe"` |
| `DEFAULT_EMBED_MODEL` | `"ollama/nomic-embed-text"` |
| `DEFAULT_GENERATION_MODEL` | `"ollama/llama3.2"` |
| `DEFAULT_TOP_K` | `5` |

### Built-In Chunking Profiles

| Constant | `name` | `chunk_size` | `overlap` | `clause_preserving` | `parent_child` | `resolve_crossrefs` |
|---|---|---|---|---|---|---|
| `DEFAULT` | `"DEFAULT"` | `512` | `64` | `False` | `True` | `False` |
| `POLICY` | `"POLICY"` | `1000` | `80` | `True` | `True` | `True` |

You may pass `"DEFAULT"`, `"POLICY"` (case-insensitive string resolved via `resolve_profile`), or construct a custom frozen `ChunkingProfile` instance in Python:

```python
from docpipe_maestro import ingest
from docpipe_maestro.types import ChunkingProfile

custom = ChunkingProfile(
    name="STRICT_MANUAL",
    chunk_size=750,
    overlap=50,
    clause_preserving=True,
    parent_child=True,
    resolve_crossrefs=True,
)
ingest("./manual.md", profile=custom, collection="manuals")
```

---

## 4. Shared Data Models (`docpipe_maestro.types`)

### `ChunkMetadata` (`TypedDict`)

| Key | Type | Notes |
|---|---|---|
| `type` | `Literal["child", "parent"]` | Mandatory filter field in ChromaDB |
| `source` | `str` | Canonical source key (filename or relative POSIX path) |
| `doc_version` | `str` | 12-character `sha256` hex prefix of raw file bytes |
| `section` | `str` | Section heading label (`"Introduction"` fallback if untitled) |
| `clause` | `str \| None` | Clause label (e.g., `"2.1"`, `"Clause 4"`) or `None` |
| `page` | `int \| None` | 1-based page number (PDF) or `None` |
| `chunk_index` | `int` | 0-based position within parent (for children) or section ordinal (for parents) |
| `embed_model` | `str` | `provider/model` used during embedding |

### `Chunk`, `EmbeddedChunk`, `RetrievedChunk`

- `Chunk(id: str, text: str, parent_id: str | None, metadata: ChunkMetadata)`:
  - Validates invariants in `__post_init__`: raises `ValueError` if `"child"` lacks a non-empty `parent_id` or if `"parent"` has `parent_id is not None`.
- `EmbeddedChunk(Chunk)`: adds `vector: list[float]`.
- `RetrievedChunk(EmbeddedChunk)`: adds `score: float` in `[0.0, 1.0]`.

### Generation, Operation & Manifest Records

- `GenerationResult`: `text: str`, `model: str`, `finish_reason: str | None`, `truncated: bool`, `prompt_tokens: int | None`, `completion_tokens: int | None`, `reasoning_tokens: int | None`, `total_tokens: int | None`, `elapsed_seconds: float`
- `IngestResult`: `collection: str`, `embed_model: str`, `ingested: list[str]`, `skipped: list[str]`, `chunks_written: int`, `parents_written: int`
- `SyncResult`: `collection: str`, `embed_model: str`, `added: list[str]`, `updated: list[str]`, `skipped: list[str]`, `removed: list[str]`
- `CollectionStatus`: `collection: str`, `embed_model: str | None`, `embed_dim: int | None`, `total_sources: int`, `total_children: int`, `total_parents: int`, `sources: list[SourceRecord]`
- `SourceRecord`: `source`, `content_hash`, `doc_version`, `size`, `mtime`, `ingested_at`, `embed_model`, `profile`, `chunk_ids`, `parent_ids` (supports `.to_dict()` / `.from_dict()`).

---

## 5. Exception Hierarchy & Extension Registries

```text
DocpipeError (Exception)
├── UnsupportedFormatError   # Unknown extension, missing file/dir, corrupted/binary content
├── MissingExtraError        # Optional dependency missing (pypdf, python-docx, bs4, etc.)
├── ModelMismatchError       # Requested embed_model conflicts with manifest.embed_model
├── MissingCredentialError   # Provider rejected missing or invalid API key env var
└── RegistryError            # Unregistered stage key or colliding stage registration
```

Eight lazy extension decorators are re-exported from `docpipe_maestro` (`register_parser`, `register_cleaner`, `register_enricher`, `register_chunker`, `register_embedder`, `register_store`, `register_searcher`, `register_reranker`). For retrieval, built-in `SEARCHERS` keys are `"default"` (`DenseSearcher`) and `"fts5_hybrid"` (`Fts5HybridSearcher`).

Example defensive wrapper for an application backend:

```python
from docpipe_maestro import (
    DocpipeError,
    MissingCredentialError,
    ModelMismatchError,
    UnsupportedFormatError,
    answer,
    build_prompt,
    retrieve,
)


def rag_answer(question: str, *, collection: str) -> tuple[str, list[str]]:
    try:
        sections = retrieve(question, collection=collection, top_k=5, threshold=0.35)
        prompt = build_prompt(question, sections)
        reply = answer(prompt, has_context=bool(sections))
        citations = [f"{s.metadata['source']} :: {s.metadata['section']}" for s in sections]
        return reply, citations
    except ModelMismatchError as exc:
        raise RuntimeError(f"Index needs reindex before querying: {exc}") from exc
    except MissingCredentialError as exc:
        raise RuntimeError("LLM/embedding API key environment variable is not configured.") from exc
    except (UnsupportedFormatError, DocpipeError) as exc:
        raise RuntimeError(f"RAG pipeline error: {exc}") from exc
```
