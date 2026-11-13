# Phase 1 Data Model & Artifact Alignment Specification

**Feature**: `003-baseline-housekeeping` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

No persistent storage schemas, ChromaDB vector collections, or ingestion manifest JSON schemas change in Stage 0. The data structures below govern the new `docpipe-maestro query --json` CLI output envelope, the reconciled public export catalog, the constitution v1.2.0 metadata model, and the distribution archive manifest.

---

## 1. Structured Query Result Envelope (`query --json`)

Produced by `docpipe_maestro.cli:main` when invoked with subcommand `query` and flag `--json` (`args.as_json is True`).

### Top-Level Fields

| Field | JSON Type | Source | Constraints |
|---|---|---|---|
| `query` | `string` | `args.question` | Non-empty query string as supplied to `retrieve()` |
| `collection` | `string` | `args.collection` | Target collection identifier (`"default"` or configured/CLI override) |
| `expand_parent` | `boolean` | `args.expand_parent` | `true` for deduplicated parent sections (default); `false` for `--no-expand-parent` raw child chunks |
| `results` | `array<RetrievedChunkJSON>` | `retrieve(...)` return sequence | Ordered highest score to lowest; `[]` when collection is empty or all matches fall below `--threshold` |

### `RetrievedChunkJSON` Element Fields

| Field | JSON Type | Source (`RetrievedChunk` / `ChunkMetadata`) | Constraints |
|---|---|---|---|
| `id` | `string` | `item.id` | Deterministic 16-char hex content-addressed chunk ID |
| `parent_id` | `string \| null` | `item.parent_id` | `null` when `metadata.type == "parent"` (`expand_parent: true`); non-empty 16-char parent ID when `metadata.type == "child"` (`expand_parent: false`) |
| `score` | `number` | `float(item.score)` | Normalized cosine similarity in `[0.0, 1.0]` preserved at full numeric precision |
| `text` | `string` | `item.text` | Parent section text or child chunk text (including `[Source: ...]` header on child chunks) |
| `metadata` | `object` (`ChunkMetadata`) | `dict(item.metadata)` | Contains `type` (`"parent"` \| `"child"`), `source`, `doc_version` (12-char sha256 prefix), `section`, `clause` (`string \| null`), `page` (`integer \| null`), `chunk_index` (`integer`), `embed_model` (`string`) |

### State & Outcome Transitions

1. **Populated Query Match (`results` non-empty)**: Emits envelope on `stdout` with `results.length >= 1` (`id`, `parent_id`, `score`, `text`, `metadata` populated per item), `stderr` clean, exit code `0`.
2. **Zero Matches (empty collection or filtered out by `--threshold`)**: Emits envelope on `stdout` with `"results": []`, `stderr` clean (never writes `"No matching sections found."` to `stdout`), exit code `0`.
3. **Validation or Runtime Error (`DocpipeError`, `ValueError`, `TypeError`)**: Writes single-line `Error: <message>` to `stderr`, emits nothing on `stdout`, exits with code `1`.
4. **Default Non-JSON Mode (`--json` omitted)**: Behavior unchanged (`No matching sections found.` or human-formatted sections + `---` dividers).

---

## 2. Constitutional Amendment Record (`v1.2.0`)

Governs `.specify/memory/constitution.md` progression from `1.1.0` → `1.2.0`:

| Field / Section | v1.1.0 State | v1.2.0 Target State |
|---|---|---|
| Top Sync Impact Report | `Version change: 1.0.0 -> 1.1.0` | Updated Amendment Log entry documenting `1.1.0 -> 1.2.0`, modified principles (`I`, `V`), modified constraints (`Quality Gates`, `Footprint`), and zero runtime breaking changes |
| Principle I (`Scope Discipline`) | `"minimal RAG pipeline library"` | Explicit clarification: `"minimal"` means minimal in feature surface and scope promise — **not** minimal in engineering rigor or safety guarantees |
| Principle V (`Exception Preservation`) | Reverse test noted as `"a release gate"` | Reverse test designated mandatory **Release Gate #1**; **Release Gate #2** (PII protection safety gate) explicitly reserved for Stage 4 implementation |
| Additional Constraints → `Quality Gates` | Reverse test unnumbered; API list covers 8 functions + `"shared types"` | Designates Release Gate #1 (`pytest -m reverse`) and reserves Release Gate #2 (PII gate); aligns Public API contract list with all functions (`ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, optional `answer`, `answer_detailed`), shared/result shapes, and `DocpipeError` hierarchy |
| Additional Constraints → `Footprint` | `"generation is an optional extra, not a core dependency"` | Removes obsolete `"optional extra"` claim; clarifies generation is **optional to invoke** at runtime while its unified client dependency ships in base install, preserving 16 GB RAM CPU-only constraint and additive extensibility |
| Version Footer | `Version: 1.1.0 \| Last Amended: 2026-11-12` | `Version: 1.2.0 \| Ratified: 2026-11-12 \| Last Amended: 2026-11-13` |

---

## 3. Reconciled Public Interface & Module Map (`PRODUCT.md`)

Ground truth derived from `src/docpipe_maestro/__init__.py` (`__all__` = 24 symbols) and file layout under `src/docpipe_maestro/`:

- **Phase 1 Callables (5)**: `ingest`, `sync`, `remove`, `status`, `reindex`
- **Phase 2 Callables (5)**: `retrieve`, `build_prompt`, `build_chat_messages`, `answer`, `answer_detailed`
- **Data & Result Types (8)**: `Chunk`, `EmbeddedChunk`, `RetrievedChunk`, `SourceRecord`, `IngestResult`, `SyncResult`, `CollectionStatus`, `GenerationResult`
- **Public Exceptions (5)**: `DocpipeError`, `UnsupportedFormatError`, `MissingExtraError`, `ModelMismatchError`, `MissingCredentialError`
- **Package Metadata (1)**: `__version__`

Active module layout for `PRODUCT.md` §20.1:

- Shared / Entry: `__init__.py`, `__main__.py`, `types.py`, `config.py`, `embedder.py`, `manifest.py`, `store.py`, `cli.py`
- Phase 1 (`ingest/`): `ingest/intake.py`, `ingest/clean.py`, `ingest/crossrefs.py`, `ingest/chunker.py`, `ingest/pipeline.py`
- Phase 2 (`query/`): `query/retriever.py`, `query/prompts.py`, `query/answer.py`

---

## 4. Distribution Inclusion Manifest (`sdist` & `wheel`)

| Artifact | Required Included Assets | Preserved Unchanged Settings |
|---|---|---|
| Source distribution (`dist/*.tar.gz`) | `PRODUCT.md`, `.specify/memory/constitution.md`, `docs/`, `src/`, `tests/`, `README.md`, `LICENSE`, `CHANGELOG.md` (zero `Product.md`) | Runtime `dependencies`, `optional-dependencies` (`pdf`, `docx`, `html`, `all`), `[project.urls]`, `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]` |
| Built wheel (`dist/*.whl`) | `docpipe_maestro/` Python package including `docpipe_maestro/py.typed`, `ingest/`, `query/` | Wheel package entry point `docpipe-maestro = "docpipe_maestro.cli:main"` and `Typing :: Typed` classifier |
