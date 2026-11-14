# docpipe-maestro — Refactor & Upgrade Program

**Version:** 2.0.0 (Codebase-aligned SpecKit edition)
**Status:** Active
**Owner:** ivnmoreno
**Constitution:** [`.specify/memory/constitution.md`](.specify/memory/constitution.md) (currently `v1.1.0`)
**Baseline Commit:** `34c7d7e` (`main`, post-`002-online-llm-customization`)
**Last modified:** 2026-11-13

---

## 0. How to Execute This Program

This document is the **master roadmap and specification source** for evolving `docpipe-maestro` from its current `v0.1.x` baseline (`001` + `002`) into a modular, measured, privacy-capable RAG pipeline (`v0.2.0`) through sequential, isolated SpecKit stages.

Each stage (`0` through `8`) MUST be executed in isolation:
1. Checkout updated `main` and create the stage's type-prefixed branch (e.g., `git checkout -b chore/003-baseline-housekeeping`).
2. Invoke `/speckit-specify` with the stage's **`/speckit-specify` Prompt Block** verbatim so SpecKit creates its exclusive `specs/0NN-<short-name>/spec.md` and quality checklist without leaking implementation details into `spec.md`.
3. Run `/speckit-plan` using the stage's **Implementation Blueprint (`/speckit-plan` Notes)** and the target contracts in §3.
4. Run `/speckit-tasks` and `/speckit-implement`, verify all CI quality gates locally, merge to `main`, and update §4 Progress Tracking.

### Locked Architectural Decisions

| Area | Decision | Rationale |
|---|---|---|
| **Branch Naming** | Type-prefixed (`chore/003-...`, `refactor/004-...`, `feat/005-...`) | Matches shipped `feat/002-online-llm-gateways` history while mapping 1:1 to `specs/003`–`specs/011` |
| **PII Engine (Stage 4)** | Hybrid: built-in zero-download regex/checksum recognizers + optional `[pii]` Presidio NER backend | Keeps offline defaults & Python `3.10–3.13` CI deterministic without forced spaCy model downloads |
| **Rerank Target (Stage 5)** | Child-first: cross-encoder rescores top-N candidate child chunks (sigmoid-normalized to `[0.0, 1.0]`), then deduplicates/expands to top-K parents → crossrefs | Aligns with Principle IV ("Search Small, Return Big"), short-context bi/cross-encoder limits, and `RetrievedChunk.score` invariants |
| **Lexical Backend (Stage 6)** | Stdlib SQLite FTS5 (`.docpipe/fts/<collection>.sqlite3`) | Zero new dependency, native `bm25()`, parameterized SQL `doc_version` filtering, zero `pickle` (`ruff --select S`-clean) |
| **Constitution Governance** | Reconcile Principles I & V + Footprint in Stage 0 (`v1.2.0`); formalize Release Gate #2 in Stage 4 (`v1.3.0`) | Keeps existing codebase alignment clean without premature renumbering |

### 0.1 Non-Negotiable Execution Rules

1. **Follow SpecKit boundary discipline.** Pass only the stage's **`/speckit-specify` Prompt Block** to `/speckit-specify` so `spec.md` remains technology-agnostic and passes SpecKit's Content Quality checklist; use the stage's **Implementation Blueprint (`/speckit-plan` Input)** during `/speckit-plan`.
2. **Do not break `@dataclass(slots=True)`.** `Chunk`, `EmbeddedChunk`, `RetrievedChunk`, `ChunkingProfile`, and `ParsedDocument` use `slots=True`. Never access `.__dict__` or unpack `**obj.__dict__`; always use `dataclasses.replace(...)` or explicit construction.
3. **Preserve `types.py` as the single schema & exception module.** All shared dataclasses, `TypedDict`s, and `DocpipeError` subclasses live in `src/docpipe_maestro/types.py`. Do **not** import from a non-existent `docpipe_maestro.exceptions` module.
4. **Preserve content-addressed `doc_version` (`sha256_hex[:12]`).** Never replace `doc_version: str` with sequential integers.
5. **Preserve lazy CLI startup imports.** Importing `docpipe_maestro` or initializing the CLI parser (`--help`) must never eagerly import `chromadb` or `litellm` (guarded by `tests/test_cli.py`).
6. **Preserve public API signatures & backward compatibility.** New parameters on public functions (`ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, `answer`, `answer_detailed`) must be **keyword-only with defaults** preserving current behavior. Internal module restructures (e.g., `store.py` → `store/`) must provide re-export shims so existing imports pass unmodified.
7. **Run all tests after implementation and pass every CI quality gate on every stage.** Running all tests across the repository after implementation completes is a mandatory requirement—100% of tests must pass (`0` failures) before a stage is considered done: `uv run ruff format --check .`, `uv run ruff check .`, `uv run ruff check --select S src/`, `uv run mypy src tests` (`strict = true`), `uv run pytest -m reverse -v`, and `uv run pytest -v --cov` (`>= 80%` branch coverage) across Python `3.10–3.13`.
8. **Amend the constitution *before* writing conflicting code.** Never silently bypass a principle.
9. **Enforce the one-sentence positioning test:**

> **docpipe-maestro is a minimal RAG pipeline: it ingests any document, chunks it correctly, embeds it, stores it, retrieves the right sections, and optionally generates a grounded answer. It is the engine — not the app, not the framework.**

---

## 1. Current Baseline Assessment (`main` @ `34c7d7e`)

### 1.1 Already Shipped (v0.1.x + Feature 002)

- **Distribution / Import / CLI**: `docpipe-maestro` / `docpipe_maestro` / CLI entry point `docpipe-maestro` with 7 subcommands (`ingest`, `sync`, `status`, `remove`, `reindex`, `query`, `ask`).
- **Packaging (`pyproject.toml`)**: `hatchling>=1.25.0` + `hatch-vcs>=0.4.0`; `license = "MIT"`, `license-files = ["LICENSE"]`, no conflicting license classifier; `[generation]` extra already removed; `[project.urls]` (`Homepage`, `Repository`, `Issues`, `Changelog`, `Documentation`); `python-dotenv>=1.0.0`, `chromadb>=1.5.9`, `litellm>=1.108.0`, `langchain-text-splitters>=0.3.0`, `tomli`; extras `pdf` (`pypdf>=6.21.3`), `docx`, `html`, `all`; `[tool.commitizen]`, `[tool.coverage.*]` (`fail_under = 80`), `[tool.mypy]` (`strict = true`), `[tool.pytest.ini_options]` (`--strict-markers`, `filterwarnings = ["error"]`), and `src/docpipe_maestro/py.typed`.
- **Two-Phase Package Layout**:
  - `src/docpipe_maestro/__init__.py` (lazy `__getattr__` + `_DocpipeModule` wrapper)
  - Shared modules: `types.py`, `config.py`, `embedder.py`, `manifest.py`, `store.py` (`VectorStore`)
  - Phase 1 (`ingest/`): `intake.py` (`ParsedClause`, `ParsedSection`, `ParsedDocument`, `detect_format`, `parse_file`), `clean.py` (`clean_text`, `clean_document`), `crossrefs.py` (`resolve_crossrefs` + cross-doc helper functions), `chunker.py` (`estimate_tokens`, `chunk_document`), `pipeline.py` (`ingest`, `sync`, `remove`, `status`, `reindex`)
  - Phase 2 (`query/`): `retriever.py` (`retrieve`, `_enrich_crossdoc_references`), `prompts.py` (`build_prompt`, `build_chat_messages`), `answer.py` (`answer`, `answer_detailed`)
  - CLI (`cli.py`): sole TOML/`docpipe.toml` & `.env` reader; supports `--config`, `--no-config`, `--collection`, `--persist-dir`, `ask` telemetry/flags (`--api-base`, `--temperature`, `--max-tokens`, `--timeout`, `--fail-on-truncation`, `--show-context`, `--json`).

### 1.2 Existing `specs/` Directory Registry

New SpecKit feature folders start at **`003`**:

| # | Spec Folder | Feature Branch | Status |
|---|---|---|---|
| `001` | `specs/001-core-rag-pipeline/` | `main` (v0.1 baseline) | **Merged** |
| `002` | `specs/002-online-llm-customization/` | `feat/002-online-llm-gateways` | **Merged (`34c7d7e`)** |
| `003` | `specs/003-baseline-housekeeping/` | `chore/003-baseline-housekeeping` | **Stage 0 (Next)** |
| `004` | `specs/004-registry-refactor/` | `refactor/004-registry-refactor` | Stage 1 |
| `005` | `specs/005-eval-harness/` | `feat/005-eval-harness` | Stage 2 |
| `006` | `specs/006-enricher-stage/` | `feat/006-enricher-stage` | Stage 3 |
| `007` | `specs/007-pii-protection/` | `feat/007-pii-protection` | Stage 4 |
| `008` | `specs/008-reranking/` | `feat/008-reranking` | Stage 5 |
| `009` | `specs/009-hybrid-search/` | `feat/009-hybrid-search` | Stage 6 |
| `010` | `specs/010-metadata-filtering/` | `feat/010-metadata-filtering` | Stage 7 |
| `011` | `specs/011-structured-logging/` | `feat/011-structured-logging` | Stage 8 |

*(Note: when invoking `/speckit-specify`, pass `GIT_BRANCH_NAME` / `--short-name` or branch manually per stage so branches follow the table cleanly and `feature_numbering: sequential` allocates `003`–`011` in order.)*

### 1.3 Load-Bearing Invariants Every Stage MUST Preserve

| # | Invariant | Authoritative Source | Guard / Test |
|---|---|---|---|
| 1 | Content-addressed `doc_version` = `sha256_hex[:12]` | `pipeline.py`, `manifest.py` | Existing sync/manifest tests |
| 2 | `sweep_uncommitted(active_versions)` runs before ingest writes | `pipeline.py`, `store.py` | Crash-recovery tests |
| 3 | `manifest.embed_dim` locks only when `dim > 0` | `pipeline.py` | Empty-file batch tests |
| 4 | Manifest model lock raises `ModelMismatchError` on ingest/retrieve | `manifest.py`, `pipeline.py`, `retriever.py` | Model-lock tests |
| 5 | `retrieve()` checks committed `(source, doc_version)` against manifest; `query_children` over-fetches `2x` when filtering | `store.py`, `retriever.py` | Staged-isolation tests |
| 6 | `_TAG_RE` matches only recognized HTML tags & comments (preserves `<collection>`, `<`/`>`) | `ingest/clean.py` | `tests/test_security_hardening.py` |
| 7 | Section-scoped overlap resets at every section boundary (`overlap` fits within `chunk_size`) | `ingest/chunker.py` | `tests/test_chunker.py` |
| 8 | `make_chunk_id` includes `doc_version` and `parent_id` | `types.py` | `tests/test_chunker.py`, sync tests |
| 9 | Child chunks carry `[Source: ... | Section: ...]` header & `parent_id`; parents stored with `type="parent"`, never returned raw | `chunker.py`, `store.py`, `retriever.py` | `tests/test_reverse_safety.py` |
| 10 | Hidden HTML prompt-injection filtering (`display:none`, `[hidden]`, `aria-hidden`, `<template>`), deep-nesting safety, and DOCX ZIP-bomb limits | `ingest/intake.py` | `tests/test_security_hardening.py` |
| 11 | Ingest directory traversal skips symlinks; collection names reject path traversal; persist dir restricted (`0o700`) | `pipeline.py`, `manifest.py` | `tests/test_security_hardening.py` |
| 12 | `validate_api_base()` allows loopback HTTP (`localhost`/`127.0.0.1`/`::1`) and blocks non-loopback HTTP; errors redact secret patterns + active env secrets; `LITELLM_LOCAL_MODEL_COST_MAP=true` supported | `embedder.py`, `answer.py` | `tests/test_security_hardening.py` |
| 13 | CLI parser initialization does not eagerly import `chromadb` or `litellm` | `__init__.py`, `cli.py` | `tests/test_cli.py` |
| 14 | Mandatory Release Gate #1 (`@pytest.mark.reverse`) passes unmodified | `tests/test_reverse_safety.py` | CI + PR gate |

---

## 2. Stage Map & Dependency Graph

```text
Stage 0 (003-baseline-housekeeping)
   └──► Stage 1 (004-registry-refactor)
           ├──► Stage 2 (005-eval-harness)
           │       ├──► Stage 5 (008-reranking)
           │       └──► Stage 6 (009-hybrid-search)
           ├──► Stage 3 (006-enricher-stage)
           │       └──► Stage 4 (007-pii-protection)
           ├──► Stage 7 (010-metadata-filtering)
           └──► Stage 8 (011-structured-logging)
```

| Stage | Spec Folder | Branch | Effort | Risk | Key Deliverable |
|---|---|---|---|---|---|
| **0** | `specs/003-baseline-housekeeping/` | `chore/003-baseline-housekeeping` | 0.5 day | Low | Fix docs/casing drift, commit `PRODUCT.md`, add `query --json`, reconcile Constitution & backlog |
| **1** | `specs/004-registry-refactor/` | `refactor/004-registry-refactor` | 2–3 days | Low | Pluggable `Registry[T]` + protocols across ingest & query, zero behavior change, stability & purity tests |
| **2** | `specs/005-eval-harness/` | `feat/005-eval-harness` | 1.5–2 days | Low | `docpipe_maestro.eval`, CLI `eval` command, deterministic fixture suite, `docs/eval-baseline.{json,md}` |
| **3** | `specs/006-enricher-stage/` | `feat/006-enricher-stage` | 1 day | Low | First-class `Enricher` stage, shared crossref utilities decoupled from `ingest/`, profile `enrichers` |
| **4** | `specs/007-pii-protection/` | `feat/007-pii-protection` | 3–4 days | Medium | PII detection/redaction/tokenization enricher, egress guard, audit log, `--local-only`, PII release gate #2 |
| **5** | `specs/008-reranking/` | `feat/008-reranking` | 1 day | Low | Local cross-encoder reranker (`[rerank]`), `--rerank` / `rerank=True`, revert criterion vs Stage 2 baseline |
| **6** | `specs/009-hybrid-search/` | `feat/009-hybrid-search` | 2 days | Medium | Lexical + dense `Searcher` + RRF fusion, crash-safe versioned lexical index (no pickle), `--search-mode` |
| **7** | `specs/010-metadata-filtering/` | `feat/010-metadata-filtering` | 1 day | Low | `retrieve(..., where=...)` + `--where`, manifest-backed `profile`/`ingested_*` translation, `$and` child guard |
| **8** | `specs/011-structured-logging/` | `feat/011-structured-logging` | 1 day | Low | JSON logger + `correlation_id` contextvar, PII-safe stage timing events, `--log-json` / `--log-level` |

---

## 3. Target Contracts Reference (For Stages 1–8 `/speckit-plan`)

These contracts fix every type/signature mismatch against `main` and pass `mypy --strict` and `ruff --select S`. Implementations must preserve them.

### 3.1 Generic `Registry` (`src/docpipe_maestro/_registry.py`)

```python
from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Generic, TypeVar

T = TypeVar("T")


class RegistryError(Exception):
    """Raised when a registry registration or resolution operation fails."""


class Registry(Generic[T]):
    """Named registry of pluggable pipeline stage classes with optional lazy built-ins."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._entries: dict[str, type[T]] = {}
        self._lazy_builtins: dict[str, tuple[str, str]] = {}

    @property
    def name(self) -> str:
        return self._name

    def register(self, key: str) -> Callable[[type[T]], type[T]]:
        def _decorator(cls: type[T]) -> type[T]:
            if key in self._entries:
                raise RegistryError(f"registry '{self._name}' already has entry '{key}'")
            self._entries[key] = cls
            return cls

        return _decorator

    def register_lazy(self, key: str, module_path: str, attr: str) -> None:
        """Declare a built-in entry loaded on first resolve() or keys() inspection."""
        self._lazy_builtins[key] = (module_path, attr)

    def _materialize_all(self) -> None:
        for key, (mod_path, attr) in list(self._lazy_builtins.items()):
            if key not in self._entries:
                getattr(import_module(mod_path), attr)

    def _materialize_key(self, key: str) -> None:
        if key not in self._entries and key in self._lazy_builtins:
            mod_path, attr = self._lazy_builtins[key]
            getattr(import_module(mod_path), attr)

    def resolve(self, key: str) -> type[T]:
        self._materialize_key(key)
        try:
            return self._entries[key]
        except KeyError as exc:
            self._materialize_all()
            available = ", ".join(sorted(self._entries)) or "<empty>"
            raise RegistryError(
                f"registry '{self._name}' has no entry '{key}' (available: {available})"
            ) from exc

    def __contains__(self, key: str) -> bool:
        self._materialize_key(key)
        return key in self._entries

    def keys(self) -> list[str]:
        self._materialize_all()
        return sorted(self._entries)

    def clear(self) -> None:
        """Testing helper — clear runtime entries without touching declarations outside tests."""
        self._entries.clear()
        self._lazy_builtins.clear()
```

**Why lazy built-ins matter:** Declaring built-ins via `register_lazy(...)` inside stage `__init__.py` files avoids circular imports *and* preserves instant CLI startup (`docpipe-maestro --help` never imports `chromadb` or `litellm`).

### 3.2 Phase 1 Protocols (`src/docpipe_maestro/ingest/stages.py`)

```python
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from docpipe_maestro.types import (
    Chunk,
    ChunkingProfile,
    EmbeddedChunk,
    IngestContext,
    ParsedDocument,
    RetrievedChunk,
)


@runtime_checkable
class Parser(Protocol):
    name: str
    extensions: tuple[str, ...]

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument: ...


@runtime_checkable
class Cleaner(Protocol):
    name: str

    def clean(self, doc: ParsedDocument) -> ParsedDocument: ...


@runtime_checkable
class Enricher(Protocol):
    name: str

    def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument: ...


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
        question: str,
        *,
        model: str,
        api_base: str | None = None,
    ) -> list[float]: ...


@runtime_checkable
class Store(Protocol):
    name: str

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
    def delete_stale_versions(self, source: str, keep_version: str) -> None: ...
    def sweep_uncommitted(self, active_versions: dict[str, str]) -> int: ...
    def get_all_children(self) -> list[Chunk]: ...
    def get_all_parents(self) -> list[EmbeddedChunk]: ...
    def reset_collection(self) -> None: ...
```

*(Note: `where: dict[str, object] | None = None` on `Store.query_children` can be introduced cleanly with `default=None` in Stage 1 or added in Stage 7; `Store` factory constructors accept `(persist_dir: Path, collection_name: str)`.)*

### 3.3 Phase 2 Protocols (`src/docpipe_maestro/query/stages.py`)

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from docpipe_maestro.types import RetrievedChunk


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

### 3.4 Types & Exceptions Evolution (`src/docpipe_maestro/types.py`)

Keep all shared shapes as dataclasses / `TypedDict`s in `types.py`:
- **Stage 1**:
  - Relocate `ParsedClause`, `ParsedSection`, `ParsedDocument` (`@dataclass(slots=True)`) from `ingest/intake.py` to `types.py` (re-exporting in `ingest/intake.py`). Keep `sections: list[ParsedSection]` as canonical representation (do **not** replace with a flat `text` dict).
  - Add `IngestContext(TypedDict)`: `collection: str`, `source: str`, `content_hash: str`, `doc_version: str` (`sha256_hex[:12]`), `embed_model: str`, `profile: str`, plus optional extension bag via `extra: dict[str, Any]` (or optional fields such as `pii_policy` in Stage 4).
- **Stage 3**:
  - Extend existing `@dataclass(frozen=True, slots=True) class ChunkingProfile` with `enrichers: tuple[str, ...] = ()` (`DEFAULT` has `()`, `POLICY` has `("crossrefs",)`). Retain `resolve_crossrefs: bool` for backward-compatible construction (keeping custom `ChunkingProfile(..., resolve_crossrefs=True)` working smoothly).
- **Stage 4**:
  - Add `class PiiBlockedError(DocpipeError)` in `types.py`.
  - Add `PiiPolicy(TypedDict, total=False)` (`types: dict[str, Literal["redact", "tokenize", "block"]]`, `min_confidence: float`, `languages: list[str]`, `on_error: Literal["fail", "continue"]`, `egress: Literal["redact", "block", "allow"]`, `token_salt_env: str`), `PiiDetection(TypedDict)`, and `PiiAuditRecord(TypedDict)` (`doc_version: str`).

### 3.5 Parser Extension + Content-Sniffing Resolution (`_resolve.py`)

`resolve_parser(path: Path, preferred: str | None = None) -> Parser`:
1. If `preferred is not None`: instantiate `PARSERS.resolve(preferred)()`.
2. If `path.suffix`: match lowercase `path.suffix` against `cls.extensions` across registered `PARSERS`. Raise `UnsupportedFormatError` if unknown extension.
3. If `path.suffix == ""` (extensionless file): delegate format detection via `detect_format(path)` (existing magic-byte + UTF-8 heuristic in `intake.py`) to map `{"pdf", "docx", "html", "md", "txt"}` to the registered parser key! This preserves 100% compatibility with extensionless fixture & security tests.

---

## Stage 0 — Baseline Housekeeping & Alignment

- **Spec Folder**: `specs/003-baseline-housekeeping/`
- **Git Branch**: `chore/003-baseline-housekeeping`
- **Depends on**: None (`main` @ `34c7d7e`)
- **Effort**: 0.5 day | **Risk**: Low
- **Constitutional Impact**: §I wording, §V gate reservation, Footprint note reconciliation (`1.1.0` → `1.2.0`)

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: chore/003-baseline-housekeeping

Establish a clean, accurate documentation, packaging, and CLI baseline for docpipe-maestro before starting the modular registry refactor program.

Context: Following the core pipeline implementation (001) and online LLM customization (002), several documentation and metadata drifts remain across the repository:
1. Product.md was renamed in working intent to PRODUCT.md but git/packaging/doc references still point to Product.md.
2. PRODUCT.md §7.3 and constitution.md "Footprint" still claim generation is an optional dependency extra, even though the [generation] extra was removed because LiteLLM powers both embeddings and completions in the core install.
3. PRODUCT.md §7.5 omits shipped public symbols (build_chat_messages, answer_detailed, GenerationResult), and §20.1 still lists pre-refactor flat filenames instead of ingest/ and query/ subpackages.
4. README.md's POLICY profile table does not explicitly note that PDF clause detection is heuristic.
5. The query CLI command lacks a structured JSON output mode (--json), whereas status and ask already support --json; upcoming evaluation dataset authoring requires machine-readable chunk IDs from query.

User Scenarios:
1. A contributor reads PRODUCT.md, README.md, and .specify/memory/constitution.md and sees one consistent, truthful description of files, public exports, package footprint, CLI commands, and safety gates.
2. A developer runs `docpipe-maestro query "<question>" --json` and receives machine-readable JSON with chunk IDs, parent IDs, similarity scores, and citation metadata so evaluation fixtures and integrations can consume retrieved sections cleanly.
3. Packaging builds (wheel + sdist) include PRODUCT.md, .specify/memory/constitution.md, docs/, and py.typed without stale filename warnings or broken links.

Functional Requirements:
- Commit the Product.md -> PRODUCT.md casing rename consistently across pyproject.toml sdist includes, docs/README.md, README.md, and any cross-links.
- Update PRODUCT.md §7.3 (generation is optional to invoke, included in core dependencies), §7.5 (add build_chat_messages, answer_detailed, GenerationResult), and §20.1 (accurately map ingest/ and query/ subpackages).
- Update .specify/memory/constitution.md to v1.2.0 with an Amendment Log entry:
  - Clarify Principle I ("minimal in promise, not in rigor").
  - Reserve Release Gate #2 in Principle V / Quality Gates (reverse test is mandatory gate #1; PII safety gate reserved as #2).
  - Reconcile Additional Constraints -> Footprint (remove obsolete "generation is an optional extra" claim while preserving the 16 GB RAM CPU constraint).
- Note in README.md's POLICY profile table that PDF clause boundary detection is heuristic.
- Add a `--json` flag to the `docpipe-maestro query` CLI subcommand returning structured retrieved chunk metadata (including chunk `id`, `parent_id`, `score`, `text`, and `metadata`), documented in docs/cli-reference.md.
- Preserve existing pyproject.toml dependency pins (python-dotenv, chromadb>=1.5.9, litellm>=1.108.0, pypdf>=6.21.3), urls, and test/lint configs without regression.

Success Criteria:
- Zero broken internal markdown file links across README.md, PRODUCT.md, docs/, and .specify/memory/constitution.md.
- `uv run pytest -m reverse -v`, full test suite (`>=80%` branch coverage), ruff format/lint/`--select S`, `mypy src tests`, `python -m build`, and `twine check dist/*` all pass.
- `docpipe-maestro query "<q>" --json` emits valid JSON parseable by `jq` and matches documented schema.

Out of scope: Any change to retrieval/chunking behavior, introducing Stage Registries, or modifying existing retrieval/reverse-safety test assertions.
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Targeted `pyproject.toml` delta only**: Update `"Product.md"` → `"PRODUCT.md"` in `[tool.hatch.build.targets.sdist].include` and optionally add `"REFACTOR_PROGRAM.md"`. Do **not** alter dependencies, URLs, or `[tool.ruff]`/`[tool.pytest]`/`[tool.coverage]` sections.
- **`cli.py`**: Add `--json` (`dest="as_json"`) to `p_query`, emitting JSON array or object with `{ "query": ..., "results": [{"id", "parent_id", "score", "text", "metadata"}] }`, and test it in `tests/test_cli.py`.
- **Verification**:
  - `uv run ruff format --check . && uv run ruff check . && uv run ruff check --select S src/`
  - `uv run mypy src tests`
  - `uv run pytest -m reverse -v && uv run pytest -v --cov`
  - `uv run python -m build && uv run twine check dist/* && unzip -l dist/docpipe_maestro-*.whl | grep py.typed`
- **Reference Commit**: `chore(baseline): align docs, casing, constitution v1.2.0, and add query --json`

---

## Stage 1 — Registry Pattern Refactor (Zero Behavior Change)

- **Spec Folder**: `specs/004-registry-refactor/`
- **Git Branch**: `refactor/004-registry-refactor`
- **Depends on**: Stage 0
- **Effort**: 2–3 days | **Risk**: Low
- **Constitutional Impact**: Enforces Principle II & VII cleanly; keeps Principle III strict

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: refactor/004-registry-refactor

Refactor docpipe-maestro's ingestion and retrieval pipeline stages to use a uniform Strategy + Registry extension pattern with zero behavioral changes.

Context: Currently, format parsing, text cleaning, chunking, embedding, and vector storage are wired via direct function/class imports inside pipeline.py and retriever.py. Adding a new document format, enricher, lexical searcher, or reranker requires modifying orchestrator modules directly, violating additive extensibility. At the same time, docpipe-maestro has 14 load-bearing behavioral, crash-safety, and security invariants (including reverse safety, model locking, staged doc_version commits, HTML prompt-injection filtering, secret scrubbing, and lazy CLI imports) that MUST remain 100% intact.

User Scenarios:
1. A library user registers a custom format parser, cleaner, or store via public extension registries without forking or editing core pipeline modules, and ingest/query routes through it.
2. A contributor inspects the package layout and sees uniform, typed interfaces for Phase 1 stages (Parser, Cleaner, Enricher, Chunker, Embedder, Store) and Phase 2 stages (Searcher, Reranker).
3. Existing CLI commands, library API callers, and internal unit test imports experience identical behavior, outputs, and startup latency as Stage 0.

Functional Requirements:
- Introduce a generic named Registry mechanism supporting decorator registration, lazy built-in declarations (so CLI parser startup avoids importing heavy ML/DB libraries), duplicate-key rejection, helpful KeyError diagnostics, membership checks, and sorted key listing.
- Define clean Phase 1 interfaces (Parser, Cleaner, Enricher, Chunker, Embedder, Store) and Phase 2 interfaces (Searcher, Reranker) whose signatures carry all required existing parameters (`source_key`, `profile`, `doc_version`, `embed_model`, `api_base`, manifest lifecycle methods, and similarity scores).
- Convert built-in intake parsers, cleaner, chunker, embedder, and Chroma store into registered default implementations under stage subpackages, while preserving compatibility re-exports for existing module-level helpers (`parse_file`, `clean_text`, `clean_document`, `chunk_document`, `VectorStore`, etc.) and extensionless magic-byte format detection.
- Export all 8 public extension points lazily from the top-level package (`register_parser`, `register_cleaner`, `register_enricher`, `register_chunker`, `register_embedder`, `register_store`, `register_searcher`, `register_reranker`).
- Update Phase 1 orchestrator (pipeline) and Phase 2 orchestrator (retriever) to resolve stages through registries while keeping all 14 core & security invariants untouched.
- Add automated guards for: (a) Registry register/resolve/error contracts, (b) Public API signature stability, (c) AST Library Purity (forbidding config/dotenv loaders outside cli.py while allowing document/manifest file reads), (d) Offline deterministic golden query equivalence before/after refactor, and (e) Regression coverage for any unguarded §1.3 invariants.

Success Criteria:
- Every existing test from the baseline suite passes unmodified alongside the new registry, API stability, and library purity suites.
- CLI help/parser startup still avoids importing heavy vector/LLM dependencies (`chromadb`, `litellm`).
- Golden retrieval output on an offline-seeded fixture corpus is identical before and after refactor.
- Mandatory Reverse Safety Gate, ruff format/lint/`--select S`, `mypy src tests` (`strict = true`), and >=80% branch coverage all pass.

Out of scope: Changing chunk boundaries, scoring formulas, CLI flags, or implementing new enrichers/rerankers/searchers (only interface protocols and empty registries are created for Enricher, Searcher, and Reranker).
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Modules**:
  - Create `_registry.py` (§3.1), `_resolve.py` (§3.5, using `detect_format` fallback when `path.suffix == ""` and importing exceptions from `docpipe_maestro.types`).
  - Create `ingest/stages.py` (§3.2), `query/stages.py` (§3.3).
  - Relocate `ParsedClause`, `ParsedSection`, `ParsedDocument` to `types.py` (+ `IngestContext`); re-export from `ingest/intake.py`.
  - Stage subpackages with lazy registrations (`PARSERS`, `CLEANERS`, `ENRICHERS`, `CHUNKERS`, `EMBEDDERS`, `STORES`, `SEARCHERS`, `RERANKERS`).
    - **Collision guard**: When moving `store.py` → `store/chroma.py` and `ingest/chunker.py` → `ingest/chunker/default.py` (etc.), re-export `VectorStore`, `chunk_document`, `estimate_tokens`, etc. in their package `__init__.py` so existing tests and external callers keep working without edits.
  - `__init__.py`: Expose `register_*` via `__getattr__` + `_DocpipeModule` so lazy-loading guarantees in `tests/test_cli.py` pass cleanly.
- **Corrected Tests to Create**:
  - `tests/test_registry.py`: registration, resolution, duplicate-key error, missing-key error listing available keys, lazy-entry materialization.
  - `tests/test_api_stability.py`: Inspect **every** symbol in `docpipe_maestro.__all__` (`ingest(path, ...)`, `sync(directory, ...)`, `remove(source, ...)`, `status(...)`, `reindex(embed_model=...)`, `retrieve(question, ...)`, `build_prompt(question, sections)`, `build_chat_messages(question, sections)`, `answer(prompt, ...)`, `answer_detailed(prompt, ...)`) validating exact required parameters AND verifying all additional parameters are keyword-only with defaults.
  - `tests/test_library_purity.py`: AST-check `src/docpipe_maestro/` (excluding `cli.py`) for `ast.Import` / `ast.ImportFrom` / `ast.Call` referencing `tomllib`, `tomli`, `toml`, `configparser`, or `dotenv` (do **not** ban `open`/`Path.read_text` since `intake.py` and `manifest.py` legitimately read documents and manifests!).
  - `tests/test_golden_refactor.py`: Seeds `tests/fixtures/policy_corpus` using `mock_litellm_offline` (`conftest.py`), compares `retrieve()` JSON against a committed fixture snapshot `tests/fixtures/golden_query_stage1.json`.
- **Reference Commits**:
  1. `refactor(registry): add Registry, stage protocols, resolve helpers, and shared intake types`
  2. `refactor(stages): register built-in ingest, embedder, and store adapters with re-exports`
  3. `refactor(pipeline): route ingest and retrieve through stage registries`
  4. `test(gates): add registry, API stability, library purity, and offline golden regression tests`

---

## Stage 2 — Retrieval Evaluation Harness

- **Spec Folder**: `specs/005-eval-harness/`
- **Git Branch**: `feat/005-eval-harness`
- **Depends on**: Stage 1 (and Stage 0's `query --json`)
- **Effort**: 1.5–2 days | **Risk**: Low
- **Constitutional Impact**: Supports §V / Quality Gates; Phase 2 read-only retrieval only

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: feat/005-eval-harness

Add a deterministic, strictly read-only retrieval evaluation harness and baseline benchmark suite for docpipe-maestro.

Context: Stages 5 (reranking) and 6 (hybrid search) alter retrieval ranking and recall. Without an objective quantitative baseline across realistic policy queries (direct lookups, paraphrased questions, exact clause identifiers, and exception-dependent rules), ranking changes cannot be validated or safely reverted.

User Scenarios:
1. A developer runs `docpipe-maestro eval --fixture <file> --collection <name> --json` and obtains repeatable precision@k, recall@k, MRR, and per-query diagnostics without modifying the vector store or manifest.
2. A developer curates ground-truth relevant chunk IDs using `docpipe-maestro query "<question>" --json` across at least 20 labeled queries covering direct lookup, paraphrased semantic queries, exact section/clause identifiers, and rule+exception queries (verified to target full parent sections).
3. A Python consumer calls `docpipe_maestro.eval.evaluate(...)` across configurable retrieval parameters (embedding model, parent expansion, k cutoffs, and future search/rerank hooks) to benchmark retrieval configurations deterministically.

Functional Requirements:
- Implement pure, zero-I/O metric functions for Precision@K, Recall@K, and Mean Reciprocal Rank (MRR), including safe handling of empty retrieved lists and empty relevant sets.
- Implement an evaluation runner that reads a JSON query fixture (`collection`, `profile`, list of `{question, relevant_ids, notes}`), queries `retrieve()` in strict read-only mode (propagating `persist_dir`, `embed_model`, `expand_parent`, and extensible retrieval keyword args cleanly), and returns typed aggregate and per-query metrics.
- Expose a CLI `eval` subcommand (`docpipe-maestro eval --fixture ... --collection ... [--k ...] [--embed-model ...] [--json]`) conforming to existing global `--collection`/`--persist-dir`/`--config` conventions and clean `DocpipeError` error handling.
- Create `tests/fixtures/eval_policy_corpus.json` with 20+ human-verified queries over the repository's policy fixtures (including >=3 rule+exception queries where `relevant_ids` includes the full enclosing parent section).
- Record an initial reproducible baseline in `docs/eval-baseline.json` and human summary in `docs/eval-baseline.md`.
- Preserve read-only guarantees on `.docpipe/` (store sqlite & manifest hashes remain unchanged after evaluation).

Success Criteria:
- Repeated runs of `eval` on the same collection produce identical metric outputs.
- Evaluation runs cause zero file modifications inside `.docpipe/`.
- Pure metric unit tests and offline deterministic harness integration tests (using a self-contained test fixture collection seeded with `mock_litellm_offline`) pass with strict typing (`mypy --strict`).
- Running all tests across the entire test suite after implementation completes is mandatory; 100% of tests must pass with zero failures.

Out of scope: LLM-as-a-judge answer evaluation, faithfulness scoring, or automatic CI downloads of live embedding models.
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Modules**:
  - `src/docpipe_maestro/eval/__init__.py`
  - `src/docpipe_maestro/eval/metrics.py` (`precision_at_k`, `recall_at_k`, `reciprocal_rank`)
  - `src/docpipe_maestro/eval/harness.py` (`EvalQuery`, `PerQueryResult`, `EvalConfig`, `EvalReport` `TypedDict`s — zero bare `dict`; `evaluate(..., k_values: Sequence[int] = (1, 3, 5, 10), embed_model: str = DEFAULT_EMBED_MODEL, expand_parent: bool = True, **retrieve_kwargs: Any)` or explicit typed retrieval params!)
  - Modify `src/docpipe_maestro/cli.py` to add `eval` subcommand; update `docs/cli-reference.md`.
  - Create `tests/fixtures/eval_policy_corpus.json` + `tests/test_eval.py` (with self-contained `tmp_persist_dir` + `mock_litellm_offline` ingestion rather than assuming an undefined global fixture!).
  - Create `docs/eval-baseline.json` (queried programmatically by Stage 5/6) + `docs/eval-baseline.md`.
  - Mandatory final verification: run the entire test suite after implementation (`uv run pytest -m reverse -v && uv run pytest -v --cov`); all tests must pass.
- **Reference Commit**: `feat(eval): add read-only retrieval evaluation harness and baseline`

---

## Stage 3 — First-Class Enricher Stage & Crossref Migration

- **Spec Folder**: `specs/006-enricher-stage/`
- **Git Branch**: `feat/006-enricher-stage`
- **Depends on**: Stage 1
- **Effort**: 1 day | **Risk**: Low
- **Constitutional Impact**: Enforces Principle II (`ingest/` vs `query/` isolation!)

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: feat/006-enricher-stage

Formalize post-clean, pre-chunk document transformation as a first-class Enricher pipeline stage and migrate intra-document cross-reference resolution into it while preserving clean phase boundaries.

Context: Currently, cross-reference resolution runs via a hardcoded `if prof.resolve_crossrefs:` branch in `pipeline.py`, while `query/retriever.py` also directly imports pure helper functions from `ingest/crossrefs.py` for query-time cross-document enrichment. Simply moving `ingest/crossrefs.py` under `ingest/enricher/` would leave Phase 2 retrieval coupled to a Phase 1 enricher module, violating Principle II (Two-Phase Architecture).

User Scenarios:
1. A developer implements a custom post-clean document transformation (such as PII scrubbing in Stage 4) by registering a class in the Enricher registry and listing its name on a ChunkingProfile, without editing `pipeline.py`.
2. Users ingesting with `POLICY` get identical intra-document `[Crossref ...]` enrichment as before; users ingesting with `DEFAULT` run zero enrichers.
3. Profiles define an ordered sequence of enrichers executed deterministically between Clean and Chunk inside Phase 1 transactional staging.

Functional Requirements:
- Extract shared pure crossref pattern matching, source matching, target indexing, and bounded excerpt truncation into a shared phase-neutral module so both Phase 1 (`CrossrefsEnricher`) and Phase 2 (`retriever._enrich_crossdoc_references`) share one implementation without cross-phase imports.
- Move intra-document cross-reference resolution into `CrossrefsEnricher` registered under `"crossrefs"` in `ENRICHERS`, preserving compatibility re-exports for existing unit test imports if required.
- Add `enrichers: tuple[str, ...] = ()` to the frozen `ChunkingProfile` dataclass (`DEFAULT.enrichers == ()`, `POLICY.enrichers == ("crossrefs",)`), preserving existing profile attributes cleanly.
- Update Phase 1 `pipeline.py` to resolve and execute `profile.enrichers` in declared list order between cleaning and chunking, passing `IngestContext` (including `doc_version: str`), aborting prior to store writes if any enricher fails.
- Preserve existing crossref resolution output, cycle prevention, unresolved warning logs, and reverse safety behavior.

Success Criteria:
- No Phase 2 module (`query/`) imports from `ingest/`.
- Golden retrieval output, existing crossref unit tests, and the Reverse Safety Gate pass with zero regressions.
- Custom test enrichers execute in profile-declared order, and failing enrichers abort ingest cleanly before touching the store/manifest.

Out of scope: Adding new enrichers beyond migrating `crossrefs` (PII enrichment ships in Stage 4).
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Key Fix over Draft**:
  - Extract pure helpers (`extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, `truncate_excerpt`, regexes) into `src/docpipe_maestro/_crossrefs.py` (shared module, matching `types.py` / `config.py`).
  - Update [`query/retriever.py`](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/src/docpipe_maestro/query/retriever.py#L14-L19) to import from `docpipe_maestro._crossrefs` (eliminating its Phase 2 → Phase 1 dependency on `ingest/`!).
  - Implement `CrossrefsEnricher` in `src/docpipe_maestro/ingest/enricher/crossrefs.py` (`@ENRICHERS.register("crossrefs")`), and keep a lightweight deprecation/compat shim or re-export cleanly if `tests/test_crossrefs.py` imports `resolve_crossrefs` from `ingest.crossrefs` (or keep `resolve_crossrefs` thin).
  - Keep `ChunkingProfile` as frozen `@dataclass(frozen=True, slots=True)` with `enrichers: tuple[str, ...] = ()`. In `pipeline.py`, call `resolve_profile(profile)` and loop `for name in prof.enrichers:` (honoring legacy custom `ChunkingProfile(resolve_crossrefs=True, enrichers=())` if needed via a clean compatibility check).
- **Reference Commit**: `feat(enricher): formalize Enricher stage and decouple shared crossref helpers`

---

## Stage 4 — PII Protection & Release Gate #2

- **Spec Folder**: `specs/007-pii-protection/`
- **Git Branch**: `feat/007-pii-protection`
- **Depends on**: Stage 3
- **Effort**: 3–4 days | **Risk**: **Medium**
- **Constitutional Impact**: Amends `.specify/memory/constitution.md` (`v1.2.0` → `v1.3.0`) **first** to formalize PII Safety Gate as Release Gate #2 and egress guarantees

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: feat/007-pii-protection

Add configurable PII detection, redaction/tokenization/blocking on ingestion, an outbound PII egress guard for remote LLMs, a `--local-only` privacy mode, structured zero-value audit logs, and Release Gate #2 (`@pytest.mark.pii`).

Context: Policy, HR, and legal corpora frequently contain personal data (emails, phone numbers, IBANs, credit card numbers, SSNs, national IDs). Storing unredacted PII in vector indexes or sending unredacted retrieved context to remote LLM providers creates privacy and compliance risk. Furthermore, `docpipe-maestro` is a library (Principle III): it must receive PII policy structures programmatically rather than reading policy files inside library modules.

User Scenarios:
1. A compliance engineer configures a `PiiPolicy` blocking `US_SSN` / `CREDIT_CARD` and redacting/tokenizing `IBAN_CODE`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IP_ADDRESS`, and jurisdiction identifiers (e.g., Spanish DNI `ES_DNI`); block-mode violations halt ingestion cleanly before vector storage or manifest commit, naming source and entity type without printing raw PII values.
2. When PII is tokenized (`tokenize`), identical sensitive values hash consistently (via salted/keyed digest, never character-offset hashing) into deterministic non-reversible tokens (e.g., `[EMAIL_ADDRESS_a1b2c3d4]`) across sections and documents, scrubbed from both section text and section titles *before* child header generation.
3. A user runs `docpipe-maestro ask ... --local-only`, rejecting any non-local LLM or remote `api_base` before any network request is made; when a remote cloud provider *is* permitted, the egress guard applies the configured PII policy across all outbound chat/prompt messages before sending to the provider.
4. A DPO or auditor inspects `.docpipe/manifests/<collection>.audit.jsonl` and verifies entity counts, actions, confidence thresholds, source keys, and `doc_version` (`sha256_hex[:12]`) are logged with **zero raw PII values**.

Functional Requirements:
- Amend `.specify/memory/constitution.md` to `v1.3.0` FIRST to formally define Release Gate #2 (`@pytest.mark.pii`) alongside Gate #1 (`@pytest.mark.reverse`).
- Support deterministic built-in pattern/checksum recognizers (email, IBAN checksum, credit card Luhn, US SSN, IP address, phone heuristic, Spanish DNI, extensible recognizer registry) AND optional `[pii]` NER backend (`presidio-analyzer` / `presidio-anonymizer`) with multi-language support (never hardcoding `"en"` alone).
- Implement `PiiEnricher` operating section-by-section (headings + body text) on `ParsedDocument` pre-chunking; accept `PiiPolicy` via `IngestContext` / runtime arguments (no library file reads); raise `PiiBlockedError(DocpipeError)` on block-mode matches so transactional ingestion aborts cleanly.
- Implement value-based salted/HMAC token generation for `tokenize` mode (independent of character offset) and audit log append to `.docpipe/manifests/<collection>.audit.jsonl` with restricted directory permissions (`0o700`) and zero raw PII text.
- Implement `query/egress.py` applying PII policy to both plain string prompts and role-separated `list[dict[str, str]]` chat messages (`build_chat_messages`) before remote `answer()` / `answer_detailed()` calls, reusing `validate_api_base` / `_is_loopback_host` so local OpenAI-compatible loopback servers count as local while cloud providers (`openai/`, `groq/`, remote `api_base`, etc.) trigger egress guarding and fail cleanly on `--local-only` with `DocpipeError`.
- Expose CLI flags `--local-only` and `--pii-policy` (read in `cli.py` only, passed as `PiiPolicy` dict to library).
- Add `tests/test_pii_safety.py` (`@pytest.mark.pii`) with synthetic fixtures and document limitations honestly in `SECURITY.md`, `PRODUCT.md`, and `README.md`.

Success Criteria:
- `pytest -m pii -v` verifies blocked entities halt ingestion, redacted/tokenized entities never appear in stored chunks, audit JSONL logs contain counts/metadata with zero raw PII strings, and egress guard blocks `--local-only` remote calls.
- Both `@pytest.mark.reverse` and `@pytest.mark.pii` release gates pass, along with offline CI checks across Python `3.10–3.13` without requiring external network downloads at test runtime.
- No "GDPR compliant" or "100% accurate detection" overclaims appear in documentation.

Out of scope: LLM-based PII detection (deferred Tier 2), automatic spaCy model downloads in offline mode, or reading PII config files directly inside library modules.
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Key Fixes over Draft**:
  - **Hybrid built-in + `[pii]` dependency design**: Zero-download validated regex/checksum recognizers (`EMAIL_ADDRESS`, `IBAN_CODE`, Luhn `CREDIT_CARD`, `US_SSN`, `IP_ADDRESS`, `PHONE_NUMBER`, `ES_DNI`) work offline in base installs and CI; installing `[pii]` (`presidio-analyzer>=2.2.0`, `presidio-anonymizer>=2.2.0`) augments detection with NER entities (`PERSON`, `LOCATION`, `ORGANIZATION`) when configured, without importing `presidio_analyzer` at package import time.
  - **Fix `_detect()` language loop**: Configure analyzer for `policy.get("languages", ["en", "es"])` (or iterate supported recognizers explicitly registered on `RecognizerRegistry`) instead of hardcoding `language="en"`, ensuring `SpainDNIRecognizer` (`SUPPORTED_LANGUAGE="es"`) executes.
  - **Fix `_token_id()`**: Hash `hmac.new(salt.encode(), matched_value.encode(), "sha256").hexdigest()[:8]` (falling back to process/collection salt passed via `PiiPolicy` / env at CLI boundary) rather than character offsets `start:end`.
  - **Process `ParsedSection.label` & `ParsedSection.raw_text`**: Since `chunker.py` builds `[Source: ... | Section: <label>]`, scrub `sec.label` as well as `sec.raw_text`!
  - **Fix `guard_egress`**: Accept `str | Sequence[Mapping[str, str]]` so `build_chat_messages()` output is guarded cleanly without collapsing system/user roles. Use `_is_loopback_host` + prefix rules for `_is_local(model, api_base)`. Raise `DocpipeError` (not `RuntimeError`) so CLI handles errors cleanly.
- **Reference Commit Series**:
  1. `docs(constitution): amend §V for Release Gate #2 PII safety (v1.3.0)`
  2. `feat(types): add PiiBlockedError, PiiPolicy, PiiDetection, PiiAuditRecord`
  3. `feat(pii): add PII recognizers, salted tokenization, PiiEnricher, and audit log`
  4. `feat(query): add PII egress guard for messages and --local-only enforcement`
  5. `feat(cli): add --local-only and --pii-policy options`
  6. `test(pii): add @pytest.mark.pii release gate and synthetic PII fixtures`
  7. `docs(security): document PII scope, thresholds, DPO audit log, and limitations`

---

## Stage 5 — Cross-Encoder Reranking

- **Spec Folder**: `specs/008-reranking/`
- **Git Branch**: `feat/008-reranking`
- **Depends on**: Stage 1, Stage 2 (`docs/eval-baseline.json`)
- **Effort**: 1 day | **Risk**: Low
- **Constitutional Impact**: Preserves Principle IV ("Search Small, Return Big") & Gate #1

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: feat/008-reranking

Add an optional local cross-encoder reranking stage to the Phase 2 retrieval pipeline, validated quantitatively against the Stage 2 evaluation baseline.

Context: Initial vector similarity bi-encoder search captures broad semantic closeness cleanly, but struggles with fine-grained term interaction and negation sensitivity among top candidates. Rescoring top candidates with a local cross-encoder increases top-k precision while keeping the default install lightweight and offline-safe when reranking is disabled.

User Scenarios:
1. A user runs `docpipe-maestro query "<q>" --rerank` or `retrieve(..., rerank=True)` and receives higher-precision top-k results rescored by the local cross-encoder (`BAAI/bge-reranker-base` by default).
2. A user without the `[rerank]` extra runs default retrieval unchanged with zero behavioral impact; invoking `--rerank` / `rerank=True` without the extra installed fails immediately with an actionable `MissingExtraError`.
3. Maintainers run the Stage 2 evaluation harness with `--rerank` against `docs/eval-baseline.json`; if `precision@5` does not exceed the baseline, Stage 5 is reverted rather than shipped as dead complexity.

Functional Requirements:
- Implement `CrossEncoderReranker` in `query/reranker/` registered under `"cross_encoder"` in `RERANKERS`, raising `MissingExtraError` when optional `[rerank]` (`sentence-transformers`) dependency is missing, and caching loaded model instances by model name across calls.
- Integrate optional reranking (`rerank: bool = False`, `reranker: str = "cross_encoder"`, `rerank_top_n: int = 20`) into `retrieve()` and CLI (`--rerank` on `query` and `ask`, forwarded cleanly into `eval`).
- Apply committed manifest `doc_version` filtering AND vector similarity `threshold` *before* reranking; update returned chunk scores using `dataclasses.replace(..., score=...)` with scores sigmoid-normalized onto `[0.0, 1.0]` (matching `RetrievedChunk.score` contract).
- Preserve deduplicated parent expansion (`expand_parent=True`), `_enrich_crossdoc_references`, and Release Gate #1 (`@pytest.mark.reverse`).
- Benchmark against `docs/eval-baseline.json` and enforce the explicit revert criterion if `precision@5 <= baseline`.

Success Criteria:
- Unit and mocked cross-encoder tests pass offline without downloading HF weights during CI; CLI parser startup avoids importing `sentence_transformers`.
- Optional `[rerank]` install works cleanly across supported Python versions.
- Evaluation harness proves measurable `precision@5` gain over Stage 2 baseline (or stage is cleanly reverted with finding recorded in `docs/eval-baseline.md`).

Out of scope: Cloud reranker APIs (Cohere, Jina), LLM-based rerankers, or enabling `--rerank` as default without explicit user opt-in.
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Key Fixes over Draft**:
  - Replace `RetrievedChunk(**{**chunk.__dict__, ...})` with `dataclasses.replace(chunk, score=float(normalized_score))` (sigmoid `1 / (1 + math.exp(-raw_score))` so `RetrievedChunk.score` stays within `[0.0, 1.0]`).
  - Cache `CrossEncoder(model_name)` in a thread-safe module cache so repeated `retrieve()`/`eval` calls do not reload weights per query.
  - Child-first rerank pipeline: retrieve top `rerank_top_n` committed children -> apply optional vector `threshold` -> `rerank` children -> deduplicate & expand unique parent sections weighted by `max(child.score)` -> `_enrich_crossdoc_references`.
  - Compare `--rerank` eval JSON output directly against `docs/eval-baseline.json`.
- **Reference Commit**: `feat(rerank): add local cross-encoder reranker and eval comparison`

---

## Stage 6 — Hybrid Lexical + Vector Search (RRF)

- **Spec Folder**: `specs/009-hybrid-search/`
- **Git Branch**: `feat/009-hybrid-search`
- **Depends on**: Stage 1, Stage 2 (`docs/eval-baseline.json`)
- **Effort**: 2 days | **Risk**: **Medium**
- **Constitutional Impact**: Must uphold Principle II, Crash-Safe Staged Manifest Protocol, and `ruff --select S`

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: feat/009-hybrid-search

Add a crash-safe lexical search index and Reciprocal Rank Fusion (RRF) hybrid retrieval mode (`vector`, `keyword`, `hybrid`) to complement dense semantic search on exact identifiers and proper nouns.

Context: Dense embeddings perform well semantically but frequently miss exact clause codes (`§4.2.1`, `ES91...`), error identifiers, acronyms, or part numbers. Combining lexical matching with vector similarity via RRF improves recall@10 on exact-match queries while keeping default `vector` behavior unchanged. Persistence must avoid unsafe deserialization (`pickle`) banned by repository security checks and must obey the exact same committed-`doc_version` transactional envelope as the vector store.

User Scenarios:
1. A user searches for an exact section or policy code (`docpipe-maestro query "Clause 4.2.1" --search-mode hybrid`) and finds the exact match ranked highly alongside semantically related clauses.
2. Ingest, sync, remove, and reindex lifecycle operations keep the lexical index synchronized per `(source, doc_version)` without exposing uncommitted chunks to Phase 2 queries during mid-batch failures.
3. Users without `--search-mode` (default `vector`) experience identical retrieval behavior to prior stages.

Functional Requirements:
- Implement `VectorSearcher` (`"vector"`), `KeywordSearcher` / `Bm25Searcher` (`"keyword"` / `"bm25"`), and `HybridSearcher` (`"hybrid"`) registered in `SEARCHERS` using Reciprocal Rank Fusion (`rrf_k = 60` default) and `dataclasses.replace(..., score=...)`.
- Persist lexical index without `pickle` using transactional SQLite FTS5 storage inside `.docpipe/fts/` storing `(id, source, doc_version, parent_id, section, clause, page, text)` with committed `doc_version` filtering identical to `VectorStore.query_children`.
- Wire lexical index add/version-sweep/remove/sync/reindex lifecycle into Phase 1 transactional commit order (write new `doc_version` rows -> atomic `save_manifest` -> delete stale versions in both Chroma and lexical store; `sweep_uncommitted` cleans orphaned lexical records on startup).
- Expose `search_mode: Literal["vector", "keyword", "hybrid"] = "vector"` on `retrieve()` and `--search-mode` on CLI `query`, `ask`, and `eval`, while preserving `check_model_lock` (except optional keyword-only skips if explicitly specified), `expand_parent`, optional reranking (Stage 5), and `_enrich_crossdoc_references`.
- Benchmark `vector` vs `keyword` vs `hybrid` against `docs/eval-baseline.json` and keep `vector` as default unless hybrid strictly improves `recall@10` without regressing reverse safety.

Success Criteria:
- Exact identifier benchmark queries succeed in `hybrid`/`keyword` mode where vector-only scored lower.
- Simulated crash between index write and `save_manifest()` leaves prior committed version queryable via both vector and lexical paths, and subsequent `ingest`/`sync` sweeps orphans cleanly.
- Zero `ruff --select S` (`pickle`/SQL injection) violations; `mypy --strict` and all gates pass.

Out of scope: Learned fusion weights, SPLADE/sparse neural embeddings, or breaking existing vector-only defaults without measured gain.
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Key Fixes over Draft**:
  - **SQLite FTS5 instead of `.pkl` (`pickle`)**: Persist lexical index using stdlib `sqlite3` FTS5 (`.docpipe/fts/<collection>.sqlite3` inside `ensure_private_dir()`, parameterized queries only, storing `doc_version` + `source` for committed-version filtering and BM25 ranking). Zero extra `[bm25]` dependency, zero `pickle`, and fully `ruff --select S`-compliant.
  - **Orchestration boundary**: Keep `retrieve()` as the Phase 2 entry orchestrator (loads manifest, checks `check_model_lock`, runs `Searcher` returning scored child candidates, optionally applies Stage 5 `Reranker`, expands unique parent sections, and calls `_enrich_crossdoc_references`) instead of letting `HybridSearcher.__init__` bypass `manifest.py`.
- **Reference Commit**: `feat(search): add SQLite FTS5 lexical index and RRF hybrid search mode`

---

## Stage 7 — Metadata Pre-Filtering (`where`)

- **Spec Folder**: `specs/010-metadata-filtering/`
- **Git Branch**: `feat/010-metadata-filtering`
- **Depends on**: Stage 1 (works cleanly with Stage 6 if merged before Stage 7)
- **Effort**: 1 day | **Risk**: Low
- **Constitutional Impact**: Upholds Principle IV (must never bypass `type="child"` filter)

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: feat/010-metadata-filtering

Expose structured metadata filtering (`where`) on retrieval queries and CLI commands, supporting both stored chunk metadata fields and manifest-derived document attributes safely without breaking existing collections.

Context: Users querying multi-document corpora frequently need to scope retrieval to a specific source document, section, version, ingestion window (`ingested_after` / `ingested_before`), or chunking `profile`. Currently, `VectorStore.query_children` hardcodes `where={"type": "child"}` and exposes no user filter. Importantly, existing `ChunkMetadata` records store `source`, `section`, `clause`, `page`, `doc_version`, and `embed_model`, whereas `profile` and `ingested_at` live in the collection manifest (`SourceRecord`), and ChromaDB range operators (`$gt`/`$lt`) only accept numeric operands rather than ISO-8601 strings.

User Scenarios:
1. A developer calls `retrieve("leave days", where={"source": "hr_policy.md"})` or `docpipe-maestro query "leave days" --where source=hr_policy.md` and gets sections strictly from that document.
2. A developer filters by `--where profile=POLICY` or `--where ingested_after=2026-11-13T00:00:00Z` on an existing collection without having to delete and re-ingest existing chunks.
3. No user-supplied filter can accidentally defeat the `type="child"` invariant or return raw parent placeholders.

Functional Requirements:
- Add optional keyword-only `where: Mapping[str, Any] | None = None` parameter to `retrieve()` (default `None`) and repeatable `--where key=value` CLI flags on `query`, `ask`, and `eval`.
- Support convenience filter keys cleanly:
  - Chunk-level keys (`source`, `section`, `clause`, `page`, `doc_version`) -> translated safely to backend predicates (`{"field": {"$eq": val}}` and SQL equivalents in FTS5 when hybrid search is present).
  - Manifest-level keys (`profile`, `ingested_after`, `ingested_before` with ISO-8601 parsing) -> resolved in memory against `manifest.sources` into a constrained `source` allowlist (`{"source": {"$in": matching_sources}}`, returning `[]` immediately without hitting the store if no sources match!).
  - Direct raw Chroma `where` dict pass-through when advanced operators (`$in`, `$ne`, etc.) are provided via Python API.
- Always combine user predicates with `{"$and": [{"type": "child"}, user_where]}` inside `VectorStore.query_children` so `"type": "child"` can never be overwritten, and apply committed `doc_version` filtering before returning results.
- Reject malformed CLI `--where` syntax cleanly via `DocpipeError` / `ValueError`.

Success Criteria:
- Filtered retrieval returns only matching committed children (and their expanded parents) on existing collections with zero re-ingestion migration required.
- Empty allowlist results (`ingested_after` in future or unknown `profile`) cleanly return empty results without error.
- Attempts to pass `where={"type": "parent"}` never return parent placeholder zero vectors.

Out of scope: Schema migration CLI tools, custom arbitrary user tag injection at ingest time, or adding new required fields to `ChunkMetadata` that invalidate existing v0.1 collections.
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Key Fixes over Draft**:
  - Keeping `profile`, `ingested_after`, and `ingested_before` resolved via `manifest.sources` -> `matching_sources` (`{"source": {"$in": ...}}` or immediate `[]`) avoids breaking existing ChromaDB collections AND avoids Chroma's crash on string `$gt`/`$lt` operators!
  - Combine inside `VectorStore.query_children` using `where_clause = {"type": "child"} if not user_where else {"$and": [{"type": "child"}, user_where]}`.
  - Apply the same source/section/doc_version filter semantics consistently in Stage 6's SQLite FTS5 / keyword searcher if Stage 6 lands first.
- **Reference Commit**: `feat(retrieve): expose safe metadata filtering via retrieve(where=...) and --where`

---

## Stage 8 — Structured JSON Logging & Correlation Tracing

- **Spec Folder**: `specs/011-structured-logging/`
- **Git Branch**: `feat/011-structured-logging`
- **Depends on**: Stage 1 (coordinates with Stage 4 PII redaction if merged)
- **Effort**: 1 day | **Risk**: Low
- **Constitutional Impact**: Preserves Principle III (`NullHandler`, zero stdout pollution from library)

### SpecKit `/speckit-specify` Prompt Block

```text
GIT_BRANCH_NAME: feat/011-structured-logging

Add opt-in structured JSON logging and per-operation correlation IDs across Phase 1 and Phase 2 pipeline stages without configuring root loggers, leaking stdout noise, or logging raw secrets/PII.

Context: Embedded library consumers and operators running batch syncs or latency-sensitive queries need per-stage timing and outcome telemetry (`intake`, `clean`, `enrich`, `chunk`, `embed`, `store`, `search`, `rerank`, `egress`, `answer`) tied together by a single request/batch correlation ID. As a library, `docpipe-maestro` must attach only `NullHandler` by default and let host applications or CLI flags (`--log-json`, `--log-level`) opt into emission.

User Scenarios:
1. A host Python application attaches its own JSON handler to the `"docpipe_maestro"` logger and observes correlated `stage.end` timing events for every `ingest()` and `retrieve()` call without library calls altering the application's root logger.
2. A CLI user runs `docpipe-maestro --log-json --log-level INFO ingest ./docs` and sees structured single-line JSON log events on `stderr`, leaving `stdout` clean for normal or `--json` command output.
3. Sensitive payloads (API keys, raw questions, prompt text, raw chunk content) are excluded from default structured event fields so telemetry never creates a PII or credential leak.

Functional Requirements:
- Implement `log.py` with `JsonFormatter`, `get_logger()` (attaching `logging.NullHandler()` only), async-safe `ContextVar`-backed `correlation_id()` context manager, and typed `stage_event(logger, stage, **fields: Any)` timing helper (`duration_ms`).
- Instrument Phase 1 (`ingest`, `sync`) and Phase 2 (`retrieve`, `answer_detailed`) entry points with `correlation_id()`, and emit stage duration + safe count/status metadata across active pipeline stages.
- Nest custom event attributes cleanly under `"fields"` (or guard reserved JSON keys `"ts"`, `"level"`, `"logger"`, `"msg"`, `"correlation_id"`) so structured attributes cannot overwrite core envelope fields.
- Never log raw document text, raw user questions, prompts, or provider secrets at `INFO`/`DEBUG` telemetry level by default.
- Add global CLI flags `--log-json` and `--log-level {DEBUG,INFO,WARNING,ERROR}` (emitted to `stderr`, configured solely inside `cli.py`).
- Document tracing behavior in `docs/architecture.md` and `docs/cli-reference.md`.

Success Criteria:
- `pytest` confirms root logger handlers and stdout remain untouched during library calls.
- All JSON log records parse cleanly with `json.loads`, share a non-empty UUID `correlation_id` across a single `ingest`/`retrieve` invocation, and contain zero sensitive raw document/query payloads.
- Full `mypy --strict`, `ruff`, reverse gate, and PII gate (if Stage 4 merged) pass.

Out of scope: OpenTelemetry exporter dependencies, distributed remote tracing servers, or persistent log file rotation inside the library.
```

### Implementation Blueprint (`/speckit-plan` Notes)

- **Key Fixes over Draft**:
  - `def stage_event(logger: logging.Logger, stage: str, **fields: Any) -> Iterator[None]:` passes `mypy --strict`.
  - Nest `"fields": event_fields` inside JSON payload (no `payload.update(...)` overwriting `"msg"` or `"correlation_id"`).
  - Add `--log-json` and `--log-level` to `cli.py`'s shared `common` parent parser (consistent with `--config`, `--collection`, `--persist-dir` working before or after any subcommand) writing to `sys.stderr`.
- **Reference Commit**: `feat(log): add structured JSON stage logging and correlation IDs`

---

## 4. Progress Tracking

| Stage | Spec Path | Branch | PR / Commit | Status |
|---|---|---|---|---|
| 0 | `specs/003-baseline-housekeeping/` | `chore/003-baseline-housekeeping` | *(pending)* | Ready |
| 1 | `specs/004-registry-refactor/` | `refactor/004-registry-refactor` | *(pending)* | Blocked on Stage 0 |
| 2 | `specs/005-eval-harness/` | `feat/005-eval-harness` | *(pending)* | Blocked on Stage 1 |
| 3 | `specs/006-enricher-stage/` | `feat/006-enricher-stage` | *(pending)* | Blocked on Stage 1 |
| 4 | `specs/007-pii-protection/` | `feat/007-pii-protection` | *(pending)* | Blocked on Stage 3 |
| 5 | `specs/008-reranking/` | `feat/008-reranking` | *(pending)* | Blocked on Stage 1, 2 |
| 6 | `specs/009-hybrid-search/` | `feat/009-hybrid-search` | *(pending)* | Blocked on Stage 1, 2 |
| 7 | `specs/010-metadata-filtering/` | `feat/010-metadata-filtering` | *(pending)* | Blocked on Stage 1 |
| 8 | `specs/011-structured-logging/` | `feat/011-structured-logging` | *(pending)* | Blocked on Stage 1 |
