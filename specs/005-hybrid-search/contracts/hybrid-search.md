# Contract: Hybrid Searcher, Lexical Index & CLI Interface

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/spec.md) | **Plan**: [plan.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/plan.md) | **Date**: 2026-11-14

## 1. Searcher Registry (`src/docpipe_maestro/query/searcher/__init__.py`)

Built-in registrations declared lazily via `SEARCHERS.register_lazy` (keeping `chromadb`, `litellm`, and `sqlite3` unloaded at import time):

| Registry Key | Class | Module | Notes |
| --- | --- | --- | --- |
| `"default"` | `DenseSearcher` | `docpipe_maestro.query.searcher.dense` | Encapsulates baseline dense vector child search (zero behavior change) |
| `"fts5_hybrid"` | `Fts5HybridSearcher` | `docpipe_maestro.query.searcher.hybrid` | Combines dense vector candidates + FTS5 BM25 candidates via RRF (`k=60`, `0.5`/`0.5`) |

Both implementations satisfy `isinstance(cls(), Searcher)` (`docpipe_maestro.query.stages.Searcher`) and require zero mandatory constructor arguments (`cls()`), while accepting optional `*, embedder: str = "default", store: str = "default"` for backend selector forwarding from `retrieve()`.

---

## 2. Public `retrieve` Signature Extension (`src/docpipe_maestro/query/retriever.py`)

```python
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
    searcher: str = "default",
) -> list[RetrievedChunk]: ...
```

### Contract Guarantees

- `searcher` is `KEYWORD_ONLY` with default `"default"`, preserving all existing positional/keyword callers.
- Unknown `searcher` key raises `RegistryError` listing available keys (`default`, `fts5_hybrid`, plus custom entries).
- When `searcher="default"` and `embedder`/`store` resolve cleanly, dense child results match Stage 1 golden outputs bit-for-bit.
- When `searcher="fts5_hybrid"`:
  - Loads manifest and validates model lock (`ModelMismatchError` takes precedence over search).
  - If `not manifest.sources or top_k <= 0`: returns `[]`.
  - If `manifest` records committed child chunks (`sum(len(s.chunk_ids) for s in manifest.sources.values()) > 0`) and no populated lexical DB exists at `<persist_dir>/lexical/<safe_collection>.db`, raises `DocpipeError` with explicit `reindex` / `--force` remediation guidance.
  - Otherwise fuses dense candidates and FTS5 BM25 candidates (`candidate_k = max(top_k * 2, 20)` inside searcher where `top_k` passed by `retrieve` is `child_top_k`), normalizes scores by `MAX_RRF_SCORE = 1.0 / 61.0` into `[0.0, 1.0]`, and sorts deterministically by `(-score, id)`.
- Downstream `threshold`, `expand_parent`, parent deduplication (`max(child.score)`), and `follow_crossrefs` run identically across all searchers.

---

## 3. Lexical Index (`src/docpipe_maestro/store/lexical.py`)

```python
def sanitize_fts_query(query: str) -> str: ...


class LexicalIndex:
    def __init__(self, persist_dir: Path, collection_name: str) -> None: ...
    def exists(self) -> bool: ...
    def has_indexed_rows(self) -> bool: ...
    def add_chunks(self, chunks: Sequence[Chunk | EmbeddedChunk]) -> None: ...
    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        active_versions: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]: ...
    def delete_by_source(self, source: str) -> None: ...
    def delete_stale_versions(self, source: str, active_doc_version: str) -> None: ...
    def sweep_uncommitted(self, active_versions: dict[str, str]) -> int: ...
    def reset(self) -> None: ...
```

### FTS5 Sanitization Rules

- Extracts Unicode word tokens including internal technical separators (`[^\W]+(?:[.\-:/][^\W]+)*`), preserving codes like `SEV-1`, `AES-256`, `IR-RB-012`, `1.2`, `HTTP/2`.
- Deduplicates preserving order and caps at 64 terms.
- Quotes every term as an FTS5 double-quoted string (escaping embedded `"` -> `""`) and joins with ` OR `.
- Empty or punctuation-only queries return `""` (`search()` returns `[]` without touching SQLite).
- Phase 2 `search()` opens SQLite using URI `mode=ro` so read-only queries never create or modify DB files.

---

## 4. CLI & Optional TOML Contract (`src/docpipe_maestro/cli.py`)

- `query` and `ask` subcommands accept `--searcher` (`default=cfg_searcher`, defaulting to `"default"`).
- Optional project TOML (`docpipe.toml` / `--config`) supports top-level `searcher = "fts5_hybrid"` validated via `_cfg_str(cfg, "searcher", "default")`.
- Parsing `--help` or `build_parser()` does not import `chromadb`, `litellm`, or `sqlite3`.
- Invalid `--searcher` values catch `RegistryError` cleanly inside `cli.main`, emitting a single-line `"Error: ..."` to `stderr` with exit status `1`.
