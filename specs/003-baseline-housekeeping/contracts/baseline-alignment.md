# Baseline Documentation, Governance & Packaging Alignment Contract

**Feature**: `003-baseline-housekeeping` | **Date**: 2026-11-13 | **Spec**: [spec.md](../spec.md)

This contract defines the exact required state of repository truth documents and packaging metadata after Stage 0 completion.

---

## 1. Filename Casing Alignment (`Product.md` → `PRODUCT.md`)

| Target File | Location | Required Change |
|---|---|---|
| Git index / root file | `Product.md` → `PRODUCT.md` | Track strictly as `PRODUCT.md` with zero `Product.md` remaining in index |
| Packaging manifest | `pyproject.toml` (`[tool.hatch.build.targets.sdist].include`) | Replace `"Product.md"` with `"PRODUCT.md"`; keep all deps, extras, URLs, ruff/mypy/pytest/coverage unchanged |
| Repository overview | `README.md` (`## Repository Structure`) | Replace `Product.md` with `PRODUCT.md` |
| Documentation index | `docs/README.md` (`## Project & Design Context`) | Replace `../Product.md` with `../PRODUCT.md` |
| Future features doc | `docs/future-features.md` (intro paragraph) | Replace `` `Product.md` `` with `` `PRODUCT.md` `` |
| Integration test | `tests/test_extended_complex.py` (docstring + copy call) | Update `REPO_ROOT / "Product.md"` → `REPO_ROOT / "PRODUCT.md"` (and `corpus / "PRODUCT.md"`) |

---

## 2. `PRODUCT.md` Section Reconciliation

| Section | Required Alignment |
|---|---|
| **§7.3 Phase 2 — Optional Generation** | Clarify generation is optional for callers to invoke at runtime, while provider support (`litellm`) is bundled in the core install (remove *"not part of the core install"* claim). |
| **§7.5 Public Library API** | Catalog all **24 symbols** exported by `src/docpipe_maestro/__init__.py` (`__all__`): `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, `answer`, `answer_detailed`, `Chunk`, `EmbeddedChunk`, `RetrievedChunk`, `SourceRecord`, `IngestResult`, `SyncResult`, `CollectionStatus`, `GenerationResult`, `DocpipeError`, `UnsupportedFormatError`, `MissingExtraError`, `ModelMismatchError`, `MissingCredentialError`, `__version__`. Remove `(optional extra)` tag on `answer`. |
| **§14.3, §16 #10, §18 #19** | Reconcile companion dependency/decision bullets inside `PRODUCT.md` so no conflicting `"generation is an optional extra"` wording remains inside the document. |
| **§20.1 Module Responsibilities** | Update flat module names to exact package layout: `__init__.py`, `__main__.py`, `types.py`, `config.py`, `manifest.py`, `embedder.py`, `store.py`, `cli.py`, `ingest/intake.py`, `ingest/clean.py`, `ingest/crossrefs.py`, `ingest/chunker.py`, `ingest/pipeline.py`, `query/retriever.py`, `query/prompts.py`, `query/answer.py`. |

---

## 3. Governance Constitution (`.specify/memory/constitution.md` → `v1.2.0`)

| Area | Contracted Content |
|---|---|
| **Sync Impact Report (top HTML comment)** | Record `1.1.0 -> 1.2.0`, amendment rationale (baseline rigor clarification, Release Gate #1/#2 numbering, full API parity, Footprint alignment), and zero breaking runtime changes. |
| **Principle I (`Scope Discipline`)** | Explicitly preserve positioning quote while adding: `"Minimal"` constrains feature surface and scope promise — **never** engineering rigor or safety testing discipline. |
| **Principle V & Quality Gates** | Label `@pytest.mark.reverse` explicitly as **Release Gate #1** (mandatory); explicitly reserve **Release Gate #2** for future PII protection gate (`@pytest.mark.pii` planned). Sync Quality Gates Public API list with all exported callables (`ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, optional `answer`, `answer_detailed`), shared/result types, and `DocpipeError` hierarchy. |
| **Additional Constraints → `Footprint`** | Keep `16 GB RAM with no GPU` local target and additive format/backend extensibility; remove obsolete *"generation is an optional extra, not a core dependency"* line (noting generation invocation is optional while unified client support ships in core). |
| **Metadata Footer** | `**Version**: 1.2.0 \| **Ratified**: 2026-11-12 \| **Last Amended**: 2026-11-13` |

---

## 4. `README.md` & `docs/cli-reference.md` Documentation Contract

- **`README.md` (`### 5. Chunking Profiles`)**: `POLICY` profile **Clause Preservation** row (and concise note underneath) explicitly clarifies that PDF clause boundary detection uses heuristic rules based on extracted text layout rather than deterministic PDF structural tagging.
- **`README.md` (`### 6. Semantic Search Without an LLM`)**: Demonstrates `--json` option cleanly alongside existing `query` examples.
- **`docs/cli-reference.md` (`### docpipe-maestro query`)**: Adds `[--json]` to synopsis, explains the `--json` option, documents the JSON envelope (`query`, `collection`, `expand_parent`, `results`) matching [cli-query-json.md](cli-query-json.md), and covers `--no-expand-parent`, empty `results: []`, and `Error: ...` failure behavior.
