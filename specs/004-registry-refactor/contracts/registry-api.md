# Contract: Registry API & Stage Instances

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-11-13

## Generic `Registry[T]` (`src/docpipe_maestro/_registry.py`)

`RegistryError` (imported from `docpipe_maestro.types`, inheriting from `DocpipeError`) is re-exported alongside `Registry`.

```python
class Registry(Generic[T]):
    def __init__(self, name: str) -> None: ...

    @property
    def name(self) -> str: ...

    def register(self, key: str) -> Callable[[type[T]], type[T]]: ...
    def register_lazy(self, key: str, module_path: str, attr: str) -> None: ...
    def resolve(self, key: str) -> type[T]: ...
    def __contains__(self, key: str) -> bool: ...
    def keys(self) -> list[str]: ...
    def clear(self) -> None: ...
```

### Behavioral Guarantees

1. **Key Uniqueness (`register`)**:
   - Registers a concrete stage class `cls` under string `key` and returns `cls` unmodified (usable as a class decorator or direct `reg.register(key)(cls)` call).
   - Immediately raises `RegistryError` if `key` already exists in `_entries` **or** in `_lazy_builtins` (when not currently inside `_materializing`), without overwriting the existing entry or triggering unrelated lazy imports.
2. **Deferred Built-In Declaration (`register_lazy`)**:
   - Records `(module_path, attr)` without importing `module_path`.
   - Raises `RegistryError` if `key` is already declared or registered.
   - `_materialize_key(key)` imports `module_path` and accesses `attr` only on demand; if `key` was not already written into `_entries` by a decorator inside `module_path`, assigns `attr` into `_entries[key]`.
3. **Resolution & Error Diagnostics (`resolve`)**:
   - Materializes `key` if declared lazy, returning the concrete class `type[T]`.
   - Catches `KeyError`, materializes all lazy built-ins for that registry, and raises `RegistryError(f"registry '{self._name}' has no entry '{key}' (available: {available})") from exc`, where `available` is sorted comma-joined keys or `"<empty>"`.
4. **Inspection & Test Isolation (`__contains__`, `keys`, `clear`)**:
   - `key in reg` materializes only `key` (if declared lazy) and returns membership boolean without raising.
   - `reg.keys()` materializes all declared built-ins and returns lexicographically sorted registered keys.
   - `reg.clear()` clears runtime entries and lazy declarations exclusively for test cleanup.

---

## Stage Registry Instances & Built-In Keys

| Phase | Registry Constant | Module Location | Type Parameter | Built-In Keys (Stage 1) | Top-Level Lazy Decorator Export |
|-------|-------------------|-----------------|----------------|-------------------------|---------------------------------|
| Phase 1 | `PARSERS` | `docpipe_maestro.ingest.intake` | `Parser` | `"docx"`, `"html"`, `"md"`, `"pdf"`, `"txt"` | `register_parser` |
| Phase 1 | `CLEANERS` | `docpipe_maestro.ingest.clean` | `Cleaner` | `"default"` | `register_cleaner` |
| Phase 1 | `ENRICHERS` | `docpipe_maestro.ingest.enricher` | `Enricher` | *(empty)* | `register_enricher` |
| Phase 1 | `CHUNKERS` | `docpipe_maestro.ingest.chunker` | `Chunker` | `"default"` | `register_chunker` |
| Shared | `EMBEDDERS` | `docpipe_maestro.embedder` | `Embedder` | `"default"` | `register_embedder` |
| Shared | `STORES` | `docpipe_maestro.store` | `Store` | `"default"` | `register_store` |
| Phase 2 | `SEARCHERS` | `docpipe_maestro.query.searcher` | `Searcher` | *(empty)* | `register_searcher` |
| Phase 2 | `RERANKERS` | `docpipe_maestro.query.reranker` | `Reranker` | *(empty)* | `register_reranker` |

---

## Lazy Startup Invariant

- Accessing `docpipe_maestro.register_*`, importing `docpipe_maestro`, or running `docpipe_maestro.cli.build_parser()` **MUST NOT** trigger importing `chromadb`, `litellm`, `pypdf`, `docx`, or `bs4`.
- Built-in heavy libraries only load when `STORES.resolve("default")` / `VectorStore` is resolved (`chromadb`), when `prepare_litellm()` executes for non-direct providers (`litellm`), or when `PdfParser` / `DocxParser` / `HtmlParser.parse()` runs.
