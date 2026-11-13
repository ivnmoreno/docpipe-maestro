# Phase 0 Research: Pluggable Pipeline Stage Registries

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-13

## Research Summary

This refactor replaces direct orchestrator-to-implementation imports in `src/docpipe_maestro/ingest/pipeline.py` and `src/docpipe_maestro/query/retriever.py` with a uniform Strategy + Registry extension mechanism across six Phase 1 ingestion stages (`Parser`, `Cleaner`, `Enricher`, `Chunker`, `Embedder`, `Store`) and two Phase 2 retrieval stages (`Searcher`, `Reranker`), while guaranteeing zero behavioral drift across all 14 load-bearing safety, persistence, security, and lazy-import invariants.

No external library dependencies are added. All design questions raised by `Technical Context`, `.specify/memory/constitution.md` (`v1.2.1`), and the baseline codebase inspection have been resolved below.

---

## Decisions & Trade-Offs

### R1: Deferred Built-In Uniqueness Guard in `Registry[T]`

- **Decision**: Maintain separate internal `_entries: dict[str, type[T]]`, `_lazy_builtins: dict[str, tuple[str, str]]`, and `_materializing: set[str]` structures inside `Registry[T]`. Reject duplicate keys in `register(key)` whenever `key in _entries or (key in _lazy_builtins and key not in _materializing)`, and reject duplicates in `register_lazy(key, ...)` whenever `key in _entries or key in _lazy_builtins`. During `_materialize_key(key)`, track `key` inside `_materializing` within a `try/finally` block around `importlib.import_module` and `getattr`, and populate `_entries[key]` if not already populated by the module's decorator.
- **Rationale**: User Story 1 Scenario 2 and `FR-002` require rejecting duplicate registration immediately even when a deferred built-in has not yet been imported. Checking `_lazy_builtins` naively inside `register()` would raise against a built-in's own `@REG.register(key)` decorator when `_materialize_key(key)` imports its module; guarding via `_materializing` solves both cases cleanly without eagerly importing heavy dependencies like `chromadb` or `litellm`.
- **Alternatives considered**:
  - Calling `_materialize_all()` inside `register()` — rejected because registering a custom stage in tests or user setup would eagerly trigger importing `chromadb`, `litellm`, and optional extras (`pypdf`, `python-docx`, `beautifulsoup4`).
  - Checking only `_entries` inside `register()` — rejected because duplicate keys colliding with unmaterialized built-ins would pass silently or crash later on demand instead of failing immediately at registration time.

### R2: Exception Hierarchy Placement (`RegistryError` inheriting `DocpipeError`)

- **Decision**: Define `class RegistryError(DocpipeError):` inside `src/docpipe_maestro/types.py`, re-export it from `src/docpipe_maestro/_registry.py`, and export `RegistryError` in `docpipe_maestro/__init__.py` (`__all__`). Inside `Registry.resolve(key)`, materialize the target key first; on `KeyError`, call `_materialize_all()`, construct a diagnostic listing `", ".join(sorted(self._entries)) or "<empty>"`, and `raise RegistryError(...) from exc`.
- **Rationale**: Clarification Q2 requires `RegistryError` to inherit from `DocpipeError` and be publicly exported, with internal `KeyError` misses converted into `RegistryError` diagnostics. Keeping `RegistryError` in `types.py` honors Constitution Principle VII ("Data shapes [and exceptions] are defined once in `types.py`") and keeps `cli.py`'s unified `except (DocpipeError, ValueError, TypeError):` handler catching unknown/duplicate stage errors cleanly with exit code `1`.
- **Alternatives considered**:
  - Defining `RegistryError(Exception)` inside `_registry.py` without `DocpipeError` — rejected per Clarification Q2 and because unhandled non-`DocpipeError` exceptions would crash CLI commands with tracebacks.
  - Multiple inheritance `class RegistryError(DocpipeError, KeyError)` — rejected per Clarification Q2 because `KeyError.__str__` wraps messages in quotes and conflates caller catch semantics.

### R3: Lazy Subpackage Exports & Startup Import Isolation

- **Decision**: Preserve zero-eager-import startup guarantees (`tests/test_cli.py`) by keeping every registry `__init__.py` lightweight (`_registry` + stage protocol imports + `register_lazy(...)` only) and resolving compatibility helper/class exports lazily via module `__getattr__` where heavy runtime dependencies exist:
  - `src/docpipe_maestro/__init__.py`: Keep `register_parser`, `register_cleaner`, `register_enricher`, `register_chunker`, `register_embedder`, `register_store`, `register_searcher`, and `register_reranker` in `_REGISTER_EXPORTS` handled inside `__getattr__` (alongside `TYPE_CHECKING` imports for `mypy --strict`). Preserve `_DocpipeModule` so importing `docpipe_maestro.ingest.*` never shadows `docpipe_maestro.ingest`.
  - `src/docpipe_maestro/store/__init__.py`: Declare `STORES`, `register_store`, and lazy `"default"` built-in; resolve `VectorStore` and `ChromaStore` via `__getattr__` from `docpipe_maestro.store.chroma` so importing `register_store` does not load `chromadb`.
  - `src/docpipe_maestro/embedder/__init__.py`: Declare `EMBEDDERS`, `register_embedder`, `DEFAULT_REQUEST_TIMEOUT`, and lazy `"default"` built-in pointing to `docpipe_maestro.embedder.default` (`LiteLLMEmbedder`); re-export shared helpers (`embed_texts`, `embed_query`, `prepare_litellm`, `raise_litellm_error`, `validate_api_base`, `_item_field`, `_is_loopback_host`) via `__getattr__` without importing `litellm` at module top level. Note: naming the built-in module `embedder/default.py` instead of `embedder/litellm.py` prevents module-name confusion with the third-party `litellm` package.
  - `src/docpipe_maestro/ingest/intake/__init__.py`, `clean/__init__.py`, `chunker/__init__.py`: Declare their registries and lazy built-ins while re-exporting `parse_file`, `detect_format`, `SUPPORTED_EXTENSIONS`, `ParsedClause`, `ParsedSection`, `ParsedDocument`, `clean_text`, `clean_document`, `chunk_document`, and `estimate_tokens`.
- **Rationale**: `tests/test_cli.py::test_cli_lazy_imports_avoid_heavy_deps_on_parser_init` asserts neither `chromadb` nor `litellm` appears in `sys.modules` after `docpipe_maestro.cli.build_parser()`, and `cli.py` imports `DEFAULT_REQUEST_TIMEOUT` from `docpipe_maestro.embedder` at import time. Removing old flat files (`embedder.py`, `store.py`, `ingest/intake.py`, `ingest/clean.py`, `ingest/chunker.py`) when creating the replacement subpackages eliminates Python module-vs-package shadowing.
- **Alternatives considered**:
  - Eagerly importing `ChromaStore` inside `store/__init__.py` — rejected because `from docpipe_maestro import register_store` or `register_store` discovery would immediately load `chromadb` at startup.
  - Keeping flat `ingest/intake.py` alongside `parsers/` — rejected because uniform subpackages per stage (`intake/`, `clean/`, `enricher/`, `chunker/`, `embedder/`, `store/`, `query/searcher/`, `query/reranker/`) make Phase 1 vs Phase 2 stage architecture self-evident per Constitution Principle II.

### R4: Python 3.10 Compatibility & `mypy --strict` Protocol Alignment

- **Decision**:
  1. Construct `IngestContext` in `src/docpipe_maestro/types.py` using two-step stdlib `TypedDict` inheritance (`_IngestContextBase` with required `collection`, `source`, `content_hash`, `doc_version`, `embed_model`, `profile`; `class IngestContext(_IngestContextBase, total=False): extra: dict[str, Any]`) rather than `typing.NotRequired` (Python 3.11+).
  2. Align `Store` and `Embedder` shared protocols (`src/docpipe_maestro/_stages.py`, re-exported in `ingest/stages.py`) and `ChromaStore` (`store/chroma.py`) with the actual codebase and `mypy --strict` variance rules:
     - `Store.__init__(self, persist_dir: Path, collection_name: str) -> None`
     - `Store.get_all_children(self) -> list[EmbeddedChunk]` (avoids invariant `list[EmbeddedChunk]` vs `list[Chunk]` failure in mypy)
     - `Store.delete_stale_versions(self, source: str, active_doc_version: str) -> None` (preserves exact existing keyword/positional parameter name)
     - `Store.sweep_uncommitted(self, active_versions: dict[str, str]) -> int` (`ChromaStore.sweep_uncommitted` returns count of purged `stale_ids`, defaulting to `0`, compatible with existing callers ignoring return value)
     - `Store.query_children` retains `where: dict[str, object] | None = None` as an optional keyword parameter with `None` default (`ChromaStore` accepts it cleanly for forward compatibility with Stage 7 while leaving `where={"type": "child"}` behavior unchanged in Stage 1).
  3. Align `Embedder.embed_query` parameter name (`text: str`, matching existing `embedder.embed_query(text, *, model, api_base=None)`).
  4. Never access `.__dict__` on `@dataclass(slots=True)` models (`ParsedClause`, `ParsedSection`, `ParsedDocument`, `Chunk`, `EmbeddedChunk`, `RetrievedChunk`, `ChunkingProfile`, `SourceRecord`, `Manifest`); inspect fields directly or use `dataclasses.replace`.
- **Rationale**: `pyproject.toml` targets `requires-python = ">=3.10"` and `[tool.mypy]` runs with `strict = true`, `python_version = "3.10"`, covering both `src` and `tests` with zero external typing shim dependencies (`typing_extensions` is not in runtime `dependencies`).
- **Alternatives considered**:
  - Adding `typing-extensions` to `dependencies` — rejected to keep core dependencies unchanged (`Zero behavior/dependency drift`).
  - Leaving `Store.get_all_children -> list[Chunk]` — rejected because `mypy --strict` treats `list` return types as invariant and fails structural subtyping against `ChromaStore`.

### R5: Built-In Registry Keys, Extension Routing, and Content-Sniffing Fallback

- **Decision**: Register single-default built-in implementations (`DefaultCleaner`, `DefaultChunker`, `LiteLLMEmbedder`, `ChromaStore`) under key `"default"` in `CLEANERS`, `CHUNKERS`, `EMBEDDERS`, and `STORES`, matching Clarification Q1 / `FR-006`. Register built-in intake parsers (`MarkdownParser`, `TextParser`, `HtmlParser`, `PdfParser`, `DocxParser`) under keys matching `detect_format()` return strings: `"md"`, `"txt"`, `"html"`, `"pdf"`, and `"docx"`. Route file parsing through `_resolve.resolve_parser(path: Path, preferred: str | None = None) -> Parser`:
  1. If `preferred is not None`: instantiate `PARSERS.resolve(preferred)()`.
  2. Verify `path.is_file()` (raising `UnsupportedFormatError` if missing/directory, matching existing `detect_format` contract).
  3. If `path.suffix`: materialize `PARSERS` (`PARSERS.keys()`) and match `path.suffix.lower()` against `cls.extensions`, checking custom non-built-in registered keys in sorted order before built-in defaults (`"docx"`, `"html"`, `"md"`, `"pdf"`, `"txt"`) so user extensions deterministically override built-ins; raise `UnsupportedFormatError` if unclaimed.
  4. If `path.suffix == ""`: call `detect_format(path)` (preserving `%PDF-`, `PK\x03\x04` ZIP-bomb-checked DOCX, HTML root, Markdown heading, UTF-8 plain text heuristics) and instantiate `PARSERS.resolve(fmt)()`.
  Update `parse_file(path, *, source_key)` compatibility helper to delegate directly to `resolve_parser(path).parse(path, source_key=source_key)`.
- **Rationale**: Preserves exact extensionless magic-byte detection and zip-bomb/UTF-8 error behavior tested by `tests/test_intake_clean.py` and `tests/test_security_hardening.py` while letting any custom `@register_parser` extension participate in automatic extension routing during `ingest` and `sync`.
- **Alternatives considered**:
  - Mapping extensions inside a hardcoded dict in `_resolve.py` — rejected because user-registered custom parsers (e.g., `.rst`) would not route dynamically without editing `_resolve.py`.

### R6: Orchestrator Stage Resolution Semantics (`pipeline.py` & `retriever.py`)

- **Decision**:
  - In Phase 1 `pipeline.py`:
    - `ingest(...)` and `sync(...)` add keyword-only `cleaner: str = "default"`, `chunker: str = "default"`, `embedder: str = "default"`, `store: str = "default"`. After profile/manifest/model-lock/file-discovery validation, resolve `cleaner_inst = CLEANERS.resolve(cleaner)()`, `chunker_inst = CHUNKERS.resolve(chunker)()`, `embedder_inst = EMBEDDERS.resolve(embedder)()`, and `store_cls = STORES.resolve(store)` before entering the per-document parsing loop. Still instantiate `store_obj = store_cls(persist_path, collection)` strictly **after** in-memory staging completes, preserving crash-safe pre-write invariants.
    - Inside the per-document loop, parse via `resolve_parser(file_path).parse(file_path, source_key=source_key)`, clean via `cleaner_inst.clean(parsed)`, preserve `if prof.resolve_crossrefs: cleaned = resolve_crossrefs(cleaned)` (migration to `ENRICHERS` stays out of scope until Stage 3), chunk via `chunker_inst.chunk(...)`, and embed child texts via `embedder_inst.embed_texts(texts, model=embed_model)`.
    - `remove(..., store: str = "default")`: validate `if store != "default": STORES.resolve(store)` when checking early return (`source_key not in manifest.sources`), and resolve `STORES.resolve(store)(persist_path, collection)` when deleting.
    - `status(..., store: str = "default")`: validate `if store != "default": STORES.resolve(store)` against `STORES` while reading source metrics from the shared collection JSON manifest and keeping `store="default"` strictly manifest-only (zero ChromaDB initialization overhead).
    - `reindex(..., embedder: str = "default", store: str = "default")`: resolve `embedder_inst = EMBEDDERS.resolve(embedder)()` and `store_obj = STORES.resolve(store)(persist_path, collection)`.
  - In Phase 2 `retriever.py`:
    - `retrieve(..., embedder: str = "default", store: str = "default")`: validate `if embedder != "default": EMBEDDERS.resolve(embedder)` and `if store != "default": STORES.resolve(store)` before early empty/zero return; resolve `embedder_inst = EMBEDDERS.resolve(embedder)()` and `store_obj = STORES.resolve(store)(persist_path, collection)`; type `_enrich_crossdoc_references(..., store: Store, active_versions: dict[str, str])` against the `Store` protocol imported from phase-neutral `docpipe_maestro._stages` (per Constitution Principle II) instead of concrete `ChromaStore`.
- **Rationale**: Fail-fast validation catches misspelled custom stage names (`RegistryError`) before expensive embedding calls, preserves identical execution order and zero eager Chroma startup on early manifest-only paths, and keeps `_enrich_crossdoc_references` decoupled from any concrete backend.
- **Alternatives considered**:
  - Eagerly calling `STORES.resolve("default")` on `status()` — rejected because `status()` previously only reads JSON manifests and shouldn't import `chromadb` unnecessarily.

### R7: Automated Verification Guards & Golden Baseline Capture

- **Decision**: Add four new Stage 1 test suites plus invariant coverage without modifying existing baseline test assertions:
  1. `tests/test_registry.py`: Verify `Registry` decorator registration, lazy materialization, duplicate rejection (live and unmaterialized built-in keys), missing-key `RegistryError(DocpipeError)` messages (`available` sorted keys and `<empty>`), membership (`in`), sorted `keys()`, `clear()`, empty contract registries (`ENRICHERS`, `SEARCHERS`, `RERANKERS`), and custom registered `Parser`, `Cleaner`, `Chunker`, `Embedder`, `Store` round-trips through `ingest` + `retrieve`.
  2. `tests/test_api_stability.py`: Inspect all 33 exports in `docpipe_maestro.__all__` (`24` baseline exports + `RegistryError` + `8` `register_*` decorators) and assert exact parameter names, kinds (`POSITIONAL_OR_KEYWORD` / `KEYWORD_ONLY`), and defaults on `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, `answer`, and `answer_detailed`, verifying newly added stage selector parameters are strictly keyword-only defaulting to `"default"`.
  3. `tests/test_library_purity.py`: AST-scan all Python files under `src/docpipe_maestro/` excluding `cli.py` for forbidden config/env imports (`tomllib`, `tomli`, `toml`, `configparser`, `dotenv`) and dynamic `importlib.import_module` targets, while allowing `open`/`Path.read_*` document/manifest I/O; also verify top-level `register_*` access leaves `chromadb` and `litellm` absent from `sys.modules`.
  4. `tests/test_golden_refactor.py` + `tests/fixtures/golden_query_stage1.json`: Capture deterministic offline query snapshot from unmodified baseline retrieval on `tests/fixtures/policy_corpus/` using `mock_litellm_offline`, commit snapshot, and assert bit-for-bit equality of `id`, `parent_id`, `score`, `text`, and `metadata` post-refactor, alongside explicit regression assertions for unguarded §1.3 invariants (`sweep_uncommitted` orphan purging on crash recovery and empty-only file `embed_dim is None`).
- **Rationale**: Satisfies `FR-009` and `SC-001`–`SC-006`, guarantees true pre/post refactor equivalence if golden fixture is captured prior to editing orchestrators, and prevents accidental regressions in Principles II, III, and §1.3 invariants.
- **Alternatives considered**:
  - Generating the golden snapshot after refactoring — rejected because post-hoc snapshots cannot prove zero drift relative to Stage 0 baseline.
