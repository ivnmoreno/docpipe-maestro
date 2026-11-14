# Research & Design Decisions: First-Class Enricher Stage & Cross-Reference Migration

**Feature**: `008-enricher-stage` | **Date**: 2026-11-15 | **Branch**: `feat/008-enricher-stage`

## Overview

Phase 0 investigation inspected all existing cross-reference call sites (`ingest/crossrefs.py`, `query/retriever.py`), stage registries (`_registry.py`, `ingest/stages.py`, `ingest/clean/`, `ingest/chunker/`, `ingest/enricher/`), profile definitions (`types.py`, `config.py`), ingestion/synchronization orchestration (`ingest/pipeline.py`), public API stability guards (`tests/test_api_stability.py`), and Phase 1/Phase 2 purity guards (`tests/test_library_purity.py`, `tests/test_registry.py`). Zero unresolved `NEEDS CLARIFICATION` items remain.

---

## Decision 1: Phase-Neutral Shared Cross-Reference Module (`src/docpipe_maestro/_crossrefs.py`)

- **Decision**: Extract all pure cross-reference pattern definitions, section-number parsing, clause block extraction, target indexing, document-scoped reference extraction, source-key matching, and word-boundary excerpt truncation into `src/docpipe_maestro/_crossrefs.py` (phase-neutral alongside `_registry.py`, `_resolve.py`, and `_stages.py`).
- **Rationale**:
  - `src/docpipe_maestro/query/retriever.py` currently imports `extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, and `truncate_excerpt` from `docpipe_maestro.ingest.crossrefs`, which couples Phase 2 retrieval directly to a Phase 1 `ingest/` submodule.
  - All extracted functions operate strictly on plain strings, sequences of `(label, text)` tuples, and regex matches—requiring zero `docpipe_maestro.ingest.*` or `docpipe_maestro.query.*` imports and zero heavy optional dependencies.
  - Naming `_crossrefs.py` with a leading underscore matches the codebase's established convention for phase-neutral internal shared modules (`_registry.py`, `_resolve.py`, `_stages.py`) per Constitution Principle II ("The file tree must make the phase of every module legible without opening it").
- **Alternatives considered**:
  - Keeping pure helpers inside `ingest/enricher/crossrefs.py` and re-exporting through `ingest/crossrefs.py` → Rejected because Phase 2 `query/retriever.py` would still import from `docpipe_maestro.ingest.*`, violating Principle II and `FR-008`.
  - Duplicating pure regex/indexing helpers inside `query/retriever.py` → Rejected due to regex/truncation drift risk between intra-doc and cross-doc enrichment and explicit `FR-007` requirement for a single canonical implementation.
  - Exporting them under `types.py` or `config.py` → Rejected because text-matching/formatting algorithms do not belong in pure dataclass schema (`types.py`) or static constant (`config.py`) modules.

---

## Decision 2: Lazy Built-In Registration of `CrossrefsEnricher` on `ENRICHERS`

- **Decision**: Implement `CrossrefsEnricher` inside `src/docpipe_maestro/ingest/enricher/crossrefs.py` decorated with `@ENRICHERS.register("crossrefs")`, and register it lazily on `ENRICHERS` in `src/docpipe_maestro/ingest/enricher/__init__.py` via `ENRICHERS.register_lazy("crossrefs", "docpipe_maestro.ingest.enricher.crossrefs", "CrossrefsEnricher")` plus lazy `__getattr__` exports for `CrossrefsEnricher` and `resolve_crossrefs`.
- **Rationale**:
  - Directly matches the established Stage 0/Stage 1/Stage 2 registry package idiom used in `ingest/clean/__init__.py`, `ingest/chunker/__init__.py`, `query/searcher/__init__.py`, and `query/reranker/__init__.py`.
  - Calling `import docpipe_maestro` or `register_enricher(...)` never eagerly imports `ingest/enricher/crossrefs.py`; `DEFAULT` profile runs never materialize `"crossrefs"` at all (`ENRICHERS.resolve(...)` is never called for empty sequences).
  - Keeping `resolve_crossrefs(doc: ParsedDocument) -> ParsedDocument` in `ingest/enricher/crossrefs.py` preserves exact `ParsedDocument`/`ParsedSection` types, exact unresolved-reference `WARNING` logging, exact self-reference skip sets, and exact single-pass cycle-safe `[Crossref ...]` formatting.
- **Impact on Existing Registry Tests**:
  - `tests/test_registry.py::test_top_level_eight_registries_empty_defaults_and_protocol_conformance` currently asserts `ENRICHERS.keys() == []` because `ENRICHERS` had zero built-ins in Stage 0. Just like `SEARCHERS` (Stage 1) and `RERANKERS` (Stage 2), Stage 3 updates this assertion to verify `ENRICHERS.keys() == ["crossrefs"]` and `available: crossrefs` error formatting, alongside `TagEnricher` custom registration tests.
- **Alternatives considered**:
  - Eagerly importing `CrossrefsEnricher` inside `ingest/enricher/__init__.py` → Rejected because lazy loading via `Registry.register_lazy` avoids unnecessary startup work on `DEFAULT` ingestion or query-only processes.

---

## Decision 3: `ChunkingProfile.enrichers` & Legacy `resolve_crossrefs` Normalization

- **Decision**: Add `enrichers: tuple[str, ...] = ()` as the final defaulted field on the frozen, slotted dataclass `ChunkingProfile` (`src/docpipe_maestro/types.py`), explicitly set `enrichers=("crossrefs",)` on `POLICY` and keep `DEFAULT.enrichers == ()` in `src/docpipe_maestro/config.py`, and add `__post_init__` normalization in `ChunkingProfile`:
  - Convert `enrichers` via `tuple(self.enrichers)` so custom runtime sequences remain immutable and hashable.
  - When `self.resolve_crossrefs` is `True` and `not normalized` (omitted or empty `()`), set `normalized = ("crossrefs",)` via `object.__setattr__(self, "enrichers", normalized)`.
  - When `enrichers` is explicitly non-empty (regardless of `resolve_crossrefs`), honor the explicit `enrichers` sequence unmodified (per Clarification Q1 and Assumptions).
- **Rationale**:
  - Satisfies Clarification Q1 cleanly inside schema initialization (`types.py`) so `pipeline.py` dispatches **exclusively** via `prof.enrichers` with zero `if prof.resolve_crossrefs:` branches (`FR-004`).
  - Trailing default parameter keeps all existing 6-argument positional and keyword `ChunkingProfile(...)` instantiations 100% backward-compatible.
  - Confirmed Python `3.10+` supports `object.__setattr__` inside `__post_init__` on `@dataclass(frozen=True, slots=True)`.
- **Alternatives considered**:
  - Putting `if prof.resolve_crossrefs` fallback inside `pipeline.py` → Rejected because it violates `FR-004` by leaving legacy special-case `crossrefs` branching in pipeline orchestration.
  - Making `resolve_crossrefs` a computed `@property` and removing the field → Rejected because callers passing `ChunkingProfile(..., resolve_crossrefs=True)` as a dataclass constructor argument must continue succeeding (`FR-002`: "preserving all existing profile attributes cleanly").

---

## Decision 4: Upfront Enricher Dispatch & Transactional Pre-Persistence Staging in `pipeline.py`

- **Decision**: Extract two private shared helpers in `src/docpipe_maestro/ingest/pipeline.py` reused identically by both `ingest()` and `sync()`:
  1. `_resolve_enrichers(enricher_names: Sequence[str]) -> list[Enricher]`: returns `[]` immediately when `enricher_names` is empty (`DEFAULT` performs `0` registry lookups); otherwise resolves and instantiates `[ENRICHERS.resolve(name)() for name in enricher_names]` up front right alongside `CLEANERS`, `CHUNKERS`, `EMBEDDERS`, and `STORES` before file classification/skipping, allowing repeated names in exact declared order (Clarification Q2).
  2. `_apply_enrichers(doc: ParsedDocument, enrichers: Sequence[Enricher], ctx: IngestContext) -> ParsedDocument`: runs `for enricher in enrichers: doc = enricher.enrich(doc, ctx)` between `cleaner_inst.clean(parsed)` and `chunker_inst.chunk(...)`.
  Both `ingest()` and `sync()` construct `IngestContext` (`collection`, `source`, `content_hash`, `doc_version`, `embed_model`, `profile=prof.name`) per changed document right before `_apply_enrichers(...)`.
- **Rationale**:
  - Upfront resolution guarantees invalid profile enricher names fail fast with `RegistryError` even when zero files changed during `sync()` or `force=False` `ingest()` (Clarification Q2), matching all other stage registries (`CLEANERS`, `CHUNKERS`, `EMBEDDERS`, `STORES`).
  - Running `_apply_enrichers` inside the existing in-memory `staged_docs` loop guarantees any exception raised by an enricher (whether first, second, or on a later document in a multi-file batch) aborts cleanly prior to `Store(...)`, `LexicalIndex(...)`, stale sweeps, deletions, or `save_manifest(...)` writes in both `ingest()` and `sync()`.
  - Shared helper eliminates logic duplication between `ingest()` and `sync()`.
  - Preserves locked `ingest()` / `sync()` public function signatures asserted by `tests/test_api_stability.py`.
- **Note on `reindex()`**: Inspected `src/docpipe_maestro/ingest/pipeline.py` lines 517–617; `reindex()` re-embeds existing stored child/parent chunks directly from `Store` without re-parsing, cleaning, enriching, or chunking, so no enricher stage executes during `reindex()`.
- **Alternatives considered**:
  - Duplicating the resolve/loop block separately in `ingest()` and `sync()` → Rejected to avoid logic duplication and drift.
  - Resolving enrichers inside the per-file changed loop → Rejected per Clarification Q2 and inconsistency with other upfront-resolved stages.

---

## Decision 5: Silent Legacy Helper Re-Exports & Strengthened Phase 2 Import Guard

- **Decision**:
  - Retain `src/docpipe_maestro/ingest/crossrefs.py` as a clean silent re-export shim exposing the exact 5 helpers (`extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, `truncate_excerpt` from `docpipe_maestro._crossrefs`; `resolve_crossrefs` from `docpipe_maestro.ingest.enricher.crossrefs`) with `__all__` and zero runtime deprecation warnings (Clarification Q3).
  - Switch `src/docpipe_maestro/query/retriever.py` line 17 from `docpipe_maestro.ingest.crossrefs` to `docpipe_maestro._crossrefs`.
  - Update `tests/test_library_purity.py::test_phase2_query_does_not_import_phase1_stage_contracts` so `query/**/*.py` forbids the entire `docpipe_maestro.ingest` namespace (both static imports `docpipe_maestro.ingest` / `docpipe_maestro.ingest.*` and dynamic `importlib.import_module("docpipe_maestro.ingest...")`), and add `docpipe_maestro.ingest.enricher.crossrefs` to the lazy-startup check in `test_top_level_register_exports_and_cli_avoid_heavy_deps`.
- **Rationale**:
  - Preserves 100% compatibility with `tests/test_api_stability.py`, `tests/test_crossrefs.py`, `tests/test_extended_complex.py`, and external callers under `filterwarnings = ["error"]` (`pyproject.toml:138`).
  - Converts Phase 2 → Phase 1 isolation from a manually maintained submodule exclusion list into a strict namespace invariant enforced by CI (`SC-001`).
- **Alternatives considered**:
  - Deleting `src/docpipe_maestro/ingest/crossrefs.py` → Rejected because `test_api_stability.py`, `test_crossrefs.py`, `test_extended_complex.py`, and `FR-010` explicitly require preserving those five legacy import entry points without deprecation warnings.
