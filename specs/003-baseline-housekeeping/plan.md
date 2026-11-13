# Implementation Plan: Baseline Housekeeping and Alignment

**Branch**: `chore/003-baseline-housekeeping` (`003-baseline-housekeeping`) | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from [specs/003-baseline-housekeeping/spec.md](spec.md)

## Summary

Establish a clean, self-consistent documentation, governance, packaging, and CLI baseline before executing subsequent modular refactoring stages. Specifically:
1. Finalize the `Product.md` → `PRODUCT.md` casing rename across Git, `pyproject.toml`, `README.md`, `docs/README.md`, `docs/future-features.md`, and `tests/test_extended_complex.py`.
2. Reconcile `PRODUCT.md` (§7.3, §7.5, §14.3, §16 #10, §18 #19, and §20.1) so generation is accurately presented as an optional runtime capability bundled in core dependencies, all **24 shipped symbols** in `docpipe_maestro.__all__` appear in §7.5, and §20.1 maps the actual `ingest/` and `query/` subpackage layout.
3. Amend `.specify/memory/constitution.md` from `1.1.0` to `1.2.0` with a dated Sync Impact Report clarifying Principle I (*"minimal in promise, not in rigor"*), designating `@pytest.mark.reverse` as mandatory **Release Gate #1** while reserving **Release Gate #2** for future PII safety, syncing Quality Gates' public API contract list with shipped exports, and removing the stale optional-extra generation wording from Footprint.
4. Update `README.md` (`POLICY` profile table to disclose heuristic PDF clause boundary detection, repository tree `PRODUCT.md` casing, and CLI §6 `query --json` example) and `docs/cli-reference.md`.
5. Add `--json` (`dest="as_json"`) to `docpipe-maestro query` in `src/docpipe_maestro/cli.py`, emitting the structured envelope `{"query", "collection", "expand_parent", "results"}` with `id`, `parent_id`, `score`, `text`, and `metadata` per item (or `results: []` on empty matches, and plain `Error: ...` on `stderr` + exit `1` on failures), covered by automated tests in `tests/test_cli.py` and baseline link/parity checks.

## Technical Context

**Language/Version**: Python `>=3.10` (`requires-python = ">=3.10"`, strict `mypy` targeting Python 3.10, running on Python 3.11)  
**Primary Dependencies**: No new dependencies; preserves existing `pyproject.toml` runtime pins (`chromadb>=1.5.9`, `litellm>=1.108.0`, `python-dotenv>=1.0.0`, `langchain-text-splitters>=0.3.0`, `tomli>=2.0.0`) and optional parser extras (`pdf = ["pypdf>=6.21.3"]`, `docx`, `html`, `all`)  
**Storage**: No changes to ChromaDB persistent storage or JSON manifest formats; Phase 2 retrieval remains strictly read-only  
**Testing**: `pytest>=8.0.0`, `pytest-cov` (`branch = true`, `fail_under = 80`), `ruff` (format/lint/`--select S`), `mypy --strict` (`src` and `tests`), `pytest -m reverse` (Release Gate #1), `python -m build`, `twine check`  
**Target Platform**: Cross-platform local workstations and CI runners (Linux/macOS/Windows)  
**Project Type**: Python library + `docpipe-maestro` CLI (`src/` layout managed with `hatchling` + `hatch-vcs`)  
**Performance Goals**: Zero measurable latency overhead on default `docpipe-maestro query`; JSON serialization operates in-memory over `top_k` retrieved chunks (`O(k)`)  
**Constraints**: Preserve all existing dependencies, project URLs, and `[tool.*]` configs in `pyproject.toml`; preserve existing `docpipe-maestro query` plain-text output when `--json` is omitted; zero changes to ingestion/chunking/retrieval scoring logic; no Stage 1 registry abstractions or PII implementation  
**Scale/Scope**: Surgical housekeeping release across 1 CLI source file (`src/docpipe_maestro/cli.py`), 2 test files (`tests/test_cli.py`, `tests/test_extended_complex.py`), `pyproject.toml` (1 line), `.specify/memory/constitution.md`, and Markdown documentation (`PRODUCT.md`, `README.md`, `docs/README.md`, `docs/cli-reference.md`, `docs/future-features.md`)

## Constitution Check

*GATE: Evaluated against `.specify/memory/constitution.md` before Phase 0 research and re-verified after Phase 1 design (this stage also executes the documented governance amendment `1.1.0` → `1.2.0` per the Governance protocol).*

| Principle / Constraint | Compliance Status | How Satisfied in Design |
|---|---|---|
| **I. Scope Discipline (NON-NEGOTIABLE)** | PASS | Adds only `--json` parity to existing `query` CLI command (matching `status --json` / `ask --json`) plus truthful docs/packaging alignment; no server, UI, or framework concepts added, and clarifies *"minimal in promise, not in rigor"*. |
| **II. Two-Phase Architecture** | PASS | `cli.py` `query` path calls read-only Phase 2 `retrieve(...)`; no Phase 1 store writes or cross-phase leakage introduced; `PRODUCT.md` §20.1 updated to make Phase 1 (`ingest/`) vs Phase 2 (`query/`) layout legible. |
| **III. Library Purity** | PASS | Only `cli.py` formats CLI `--json` output and reads `--config` TOML / `.env`; core `query/retriever.py` remains untouched and pure. |
| **IV. Search Small, Return Big (NON-NEGOTIABLE)** | PASS | `query --json` preserves default `expand_parent=True` (deduplicated parent sections) and exposes `"expand_parent"` explicitly alongside `parent_id` so child/parent structure remains inspectable without altering retrieval logic. |
| **V. Exception Preservation** | PASS | Existing reverse-safety corpus rules and tests remain untouched and enforced via `@pytest.mark.reverse` as explicit mandatory **Release Gate #1**; **Release Gate #2** (PII gate) cleanly reserved for future Stage 4. |
| **VI. Provider Agnosticism & Local-First** | PASS | Preserves `ollama/nomic-embed-text` / `ollama/llama3.2` local offline defaults; clarifies in constitution and `PRODUCT.md` that core `litellm` support is bundled while generation remains optional to invoke. |
| **VII. Structured Correctness Over Speed** | PASS | `query --json` serializes directly from `RetrievedChunk` & typed `ChunkMetadata` (`id`, `parent_id`, `score`, `text`, `metadata`) defined in `types.py`; no duplicate data definitions introduced. |
| **Data, Quality Gates & Footprint** | PASS | No secrets touched; existing runtime/optional dependency bounds, URLs, and 16 GB RAM CPU-only local footprint preserved; dist build includes `PRODUCT.md`, `constitution.md`, `docs/`, and `py.typed`; all CI gates enforced. |

**Post-Design Re-Check**: Phase 0 & Phase 1 design artifacts ([research.md](research.md), [data-model.md](data-model.md), [contracts/cli-query-json.md](contracts/cli-query-json.md), [contracts/baseline-alignment.md](contracts/baseline-alignment.md), and [quickstart.md](quickstart.md)) comply cleanly with all constitutional principles (`v1.1.0` and target `v1.2.0`) with zero violations or waivers needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-baseline-housekeeping/
├── plan.md                              # This file (/speckit-plan command output)
├── research.md                          # Phase 0 research & verified repo findings
├── data-model.md                        # Query JSON envelope, constitution v1.2.0, API/layout & dist models
├── quickstart.md                        # End-to-end verification commands (SC-001..SC-006)
├── contracts/
│   ├── cli-query-json.md                # Exact CLI query --json schema & error/empty-match contract
│   └── baseline-alignment.md            # Documentation, casing, constitution & sdist reconciliation matrix
├── checklists/
│   └── requirements.md                  # Spec quality checklist (16/16 passing)
└── spec.md                              # Clarified feature specification
```

### Source Code & Repository Targets (repository root)

```text
.specify/memory/constitution.md          # Amend v1.1.0 -> v1.2.0 (Principle I, Release Gate #1/#2, Quality Gates API, Footprint)
PRODUCT.md                               # Canonical filename (replaces Product.md); align §7.3, §7.5, §14.3, §16, §18, §20.1
README.md                                # POLICY heuristic PDF clause note, repo tree PRODUCT.md, CLI query --json snippet
pyproject.toml                           # Update sdist include "Product.md" -> "PRODUCT.md" only; preserve all other sections

docs/
├── README.md                            # Fix Product Description link target to ../PRODUCT.md
├── cli-reference.md                     # Document docpipe-maestro query --json flags, schema, empty & error behavior
└── future-features.md                   # Fix Product.md reference -> PRODUCT.md

src/docpipe_maestro/
└── cli.py                               # Add `--json` (`dest="as_json"`) to `p_query` & JSON envelope emission

tests/
├── test_cli.py                          # Test `query --json` (parent, --no-expand-parent, empty threshold, errors, non-JSON parity)
└── test_extended_complex.py             # Fix `REPO_ROOT / "Product.md"` -> `REPO_ROOT / "PRODUCT.md"`
```

**Structure Decision**: Retain the existing single-package Python `src/` layout (`docpipe_maestro`) and two-phase `ingest/` + `query/` structure verbatim; apply strictly surgical updates to CLI argument handling/formatting, packaging sdist inclusion, documentation, constitution, and CLI/integration tests.

## Complexity Tracking

> No constitutional violations detected pre-research or post-design; no waivers or complexity justifications required.
