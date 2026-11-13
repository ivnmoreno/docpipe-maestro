# Contract: Stage Protocols & Parser Resolution

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-11-13

## Phase 1 Stage Protocols (`src/docpipe_maestro/ingest/stages.py`)

Defines Phase 1 `@runtime_checkable` protocols (`Parser`, `Cleaner`, `Enricher`, `Chunker`) and re-exports shared `Embedder` and `Store` protocols from `docpipe_maestro._stages`. All protocols are verified under `mypy --strict` (`python_version = "3.10"`).

### `Parser`

```python
@runtime_checkable
class Parser(Protocol):
    name: str
    extensions: tuple[str, ...]

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument: ...
```

- Constructor: zero required arguments (`cls()`).
- Built-in parsers (`extensions`):
  - `MarkdownParser` (`key="md"`, `extensions=(".md", ".markdown")`)
  - `TextParser` (`key="txt"`, `extensions=(".txt",)`)
  - `HtmlParser` (`key="html"`, `extensions=(".html", ".htm")`)
  - `PdfParser` (`key="pdf"`, `extensions=(".pdf",)`)
  - `DocxParser` (`key="docx"`, `extensions=(".docx",)`)

### `Cleaner`

```python
@runtime_checkable
class Cleaner(Protocol):
    name: str

    def clean(self, doc: ParsedDocument) -> ParsedDocument: ...
```

- Constructor: zero required arguments (`cls()`).
- Built-in: `DefaultCleaner` (`key="default"`).

### `Enricher`

```python
@runtime_checkable
class Enricher(Protocol):
    name: str

    def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument: ...
```

- Constructor: zero required arguments (`cls()`).
- Built-ins in Stage 1: none (`ENRICHERS` starts empty; `resolve_crossrefs` stays explicit in Stage 1 until Stage 3).

### `Chunker`

```python
@runtime_checkable
class Chunker(Protocol):
    name: str

    def chunk(
        self,
        doc: ParsedDocument,
        *,
        profile: ChunkingProfile,
        doc_version: str,
        embed_model: str,
    ) -> list[Chunk]: ...
```

- Constructor: zero required arguments (`cls()`).
- Built-in: `DefaultChunker` (`key="default"`).

---

## Shared Stage Protocols (`src/docpipe_maestro/_stages.py`)

Defines phase-neutral `@runtime_checkable` protocols shared across Phase 1 (`ingest/`), `embedder/`, `store/`, and Phase 2 (`query/`) so Phase 2 modules never import Phase 1 `ingest/` protocol definitions (Constitution Principle II). Re-exported from `docpipe_maestro.ingest.stages` for convenience.

### `Embedder`

```python
@runtime_checkable
class Embedder(Protocol):
    name: str

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        api_base: str | None = None,
    ) -> list[list[float]]: ...

    def embed_query(
        self,
        text: str,
        *,
        model: str,
        api_base: str | None = None,
    ) -> list[float]: ...
```

- Constructor: zero required arguments (`cls()`).
- Built-in: `LiteLLMEmbedder` (`key="default"`). Parameter name `text` in `embed_query` preserves compatibility with `docpipe_maestro.embedder.embed_query`.

### `Store`

```python
@runtime_checkable
class Store(Protocol):
    name: str

    def __init__(self, persist_dir: Path, collection_name: str) -> None: ...
    def add_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None: ...
    def query_children(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        active_versions: dict[str, str] | None = None,
        where: dict[str, object] | None = None,
        include_embeddings: bool = False,
    ) -> list[RetrievedChunk]: ...
    def get_by_ids(
        self, ids: Sequence[str], *, include_embeddings: bool = False
    ) -> list[EmbeddedChunk]: ...
    def get_parents_by_source(
        self,
        source: str,
        *,
        active_doc_version: str | None = None,
        include_embeddings: bool = False,
    ) -> list[EmbeddedChunk]: ...
    def delete_by_source(self, source: str) -> None: ...
    def delete_stale_versions(self, source: str, active_doc_version: str) -> None: ...
    def sweep_uncommitted(self, active_versions: dict[str, str]) -> int: ...
    def get_all_children(self) -> list[EmbeddedChunk]: ...
    def get_all_parents(self) -> list[EmbeddedChunk]: ...
    def reset_collection(self) -> None: ...
```

- Constructor: `(persist_dir: Path, collection_name: str)`.
- Built-in: `ChromaStore` (`key="default"`, aliased as `VectorStore`).
- Note on Stage 1 alignment:
  - `get_all_children` returns `list[EmbeddedChunk]` (`EmbeddedChunk` subclasses `Chunk` while respecting `mypy` invariant `list` typing).
  - `delete_stale_versions` keeps existing parameter name `active_doc_version`.
  - `sweep_uncommitted` returns `int` count of purged records (`0` when none/empty).
  - `query_children` accepts optional `where: dict[str, object] | None = None` (default `None`, behavior unchanged in Stage 1: Chroma filter remains `{"type": "child"}`).

---

## Phase 2 Protocols (`src/docpipe_maestro/query/stages.py`)

```python
@runtime_checkable
class Searcher(Protocol):
    name: str

    def search(
        self,
        question: str,
        *,
        top_k: int,
        collection: str,
        persist_dir: str,
        embed_model: str,
        where: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]: ...


@runtime_checkable
class Reranker(Protocol):
    name: str

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]: ...
```

- Built-ins in Stage 1: none (`SEARCHERS` and `RERANKERS` remain empty until Stages 5 and 6).

---

## Parser Resolution Contract (`src/docpipe_maestro/_resolve.py`)

```python
def resolve_parser(path: Path, preferred: str | None = None) -> Parser: ...
```

Resolution precedence:
1. When `preferred is not None`: return `PARSERS.resolve(preferred)()` immediately.
2. When `not path.is_file()`: raise `UnsupportedFormatError(f"Path is not a readable file: {path}")`.
3. When `ext := path.suffix.lower()` is non-empty:
   - Materialize registered parsers (`keys = PARSERS.keys()`).
   - Partition materialized keys into custom non-built-in keys (`sorted(k for k in keys if k not in _BUILTIN_PARSER_KEYS)`) followed by built-in keys (`sorted(k for k in keys if k in _BUILTIN_PARSER_KEYS)`), where `_BUILTIN_PARSER_KEYS = frozenset({"docx", "html", "md", "pdf", "txt"})`.
   - Instantiate and return the first parser matching `ext` in its lowercased `extensions` (so custom registered parsers deterministically override built-in extensions, with ties among custom parsers resolved in sorted key order).
   - Raise `UnsupportedFormatError(f"Unsupported file extension {ext!r} for {path.name}")` if none match.
4. When `ext == ""` (extensionless file):
   - Call `fmt = detect_format(path)` (preserving `%PDF-`, ZIP-bomb-validated DOCX, HTML root, Markdown heading, and UTF-8 text detection).
   - Instantiate and return `PARSERS.resolve(fmt)()`.
