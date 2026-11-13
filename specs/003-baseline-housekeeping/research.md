# Phase 0 Research: Baseline Housekeeping and Alignment

**Feature**: `003-baseline-housekeeping` | **Branch**: `chore/003-baseline-housekeeping` | **Date**: 2026-11-13

## Research Summary

All baseline reconciliation targets, documentation drifts, packaging rules, test touchpoints, and CLI `--json` conventions were verified directly against the working tree, package metadata (`pyproject.toml`), public package entry point (`src/docpipe_maestro/__init__.py`), shared types (`src/docpipe_maestro/types.py`), and CLI handler (`src/docpipe_maestro/cli.py`). Zero `NEEDS CLARIFICATION` items remain.

---

## Decision 1: Canonical `Product.md` → `PRODUCT.md` Rename & Stale Reference Sweep

- **Finding**: On disk, `PRODUCT.md` exists alongside a pending deletion of `Product.md` in git status (`D Product.md`, `?? PRODUCT.md`). Code/doc grep confirms **5 remaining project references** to `Product.md`:
  1. `pyproject.toml:82` (`[tool.hatch.build.targets.sdist].include`)
  2. `README.md:600` (`## Repository Structure` tree)
  3. `docs/README.md:23` (`## Project & Design Context` link `` `[Product Description](../Product.md)` ``)
  4. `docs/future-features.md:6` (prose reference `` `Product.md` ``)
  5. `tests/test_extended_complex.py:92` (`shutil.copy(REPO_ROOT / "Product.md", corpus / "Product.md")`, plus docstring line 86 phrasing)
- **Decision**: Stage the `Product.md` deletion + `PRODUCT.md` addition cleanly in git and update all 5 references to `PRODUCT.md`. Leave immutable historical artifacts under `specs/001-*` and `specs/002-*` untouched.
- **Rationale**: Prevents broken markdown links (`SC-001`), eliminates sdist build warnings on case-sensitive filesystems (`SC-005`), and fixes `tests/test_extended_complex.py::test_large_corpus_batching_real_docs_and_reindex` which reads the file directly from `REPO_ROOT`.
- **Alternatives Considered**: Keeping an alias copy or symlink alongside `PRODUCT.md` (rejected: duplicates tracked source-of-truth docs and fails portability on Windows/macOS case-insensitive filesystems).

---

## Decision 2: Complete Public Catalog & Module Layout Alignment in `PRODUCT.md`

- **Finding**: Auditing `src/docpipe_maestro/__init__.py` (`__all__`) and directory contents of `src/docpipe_maestro/` reveals three drifts inside `PRODUCT.md`:
  1. **Generation dependency claims**: Lines `249` (§7.3), `290` (§7.5 table), `506` (§14.3), `552` (§16 #10), `615` (§18 #19), and `654` (§20.1) still describe `answer()` / generation as an optional installation extra rather than an optional runtime capability whose provider client (`litellm`) ships in core dependencies.
  2. **Public Library API table (§7.5, lines `277–294`)**: Currently documents only 11 symbols (`ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `answer`, `Chunk`, `EmbeddedChunk`, `RetrievedChunk`), omitting 13 symbols shipped in `src/docpipe_maestro/__init__.py` (`__all__` has **24 symbols** total):
     - Added in `002`: `build_chat_messages`, `answer_detailed`, `GenerationResult`
     - Present since `001`: `SourceRecord`, `IngestResult`, `SyncResult`, `CollectionStatus`, `DocpipeError`, `UnsupportedFormatError`, `MissingExtraError`, `ModelMismatchError`, `MissingCredentialError`, `__version__`
  3. **Module Responsibilities table (§20.1, lines `638–655`)**: Lists legacy flat module filenames (`intake.py`, `clean.py`, `crossrefs.py`, `chunker.py`, `ingest.py`, `retriever.py`, `prompts.py`, `answer.py`) instead of the actual two-phase package layout (`__init__.py`, `__main__.py`, `ingest/intake.py`, `ingest/clean.py`, `ingest/crossrefs.py`, `ingest/chunker.py`, `ingest/pipeline.py`, `query/retriever.py`, `query/prompts.py`, `query/answer.py`).
- **Decision**: Update §7.3 (and reconcile §14.3, §16 #10, §18 #19 so `PRODUCT.md` is internally consistent), expand §7.5 cleanly to catalog all 24 exports in `__all__` (per Clarification Session 2026-11-13 Q2), and update §20.1 to match the exact `src/docpipe_maestro/` module paths.
- **Rationale**: Editing §7.3/§7.5 alone while leaving §14.3/§16/§18 contradictory would fail internal consistency checks (`SC-002`); listing all 24 exports enforces 100% `__all__` parity.
- **Alternatives Considered**: Adding only the 3 `002` generation symbols to §7.5 (rejected by user in Clarification Q2).

---

## Decision 3: Constitution Amendment (`v1.1.0` → `v1.2.0`)

- **Finding**: `.specify/memory/constitution.md` (`Version: 1.1.0`, last amended `2026-11-12`) exhibits three misalignments with baseline governance and shipped code:
  1. **Principle I (`Scope Discipline`)**: Reads *"The product is a minimal RAG pipeline library"* without stating explicitly that "minimal" bounds feature surface/scope, never engineering rigor or safety testing.
  2. **Principle V & Additional Constraints → Quality Gates**: Names *"a release gate"* for the reverse test without numbering **Release Gate #1 (Exception Preservation / reverse test)** and reserving **Release Gate #2 (PII Protection / privacy gate, planned)**; Quality Gates line `106–108` also omits newer public surface (`build_chat_messages`, `answer_detailed`, and shipped result/error types).
  3. **Additional Constraints → Footprint (`L113–114`)**: States *"generation is an optional extra, not a core dependency"*, contradicting core `litellm>=1.108.0` installation and README installation docs.
- **Decision**: Amend `.specify/memory/constitution.md` to `1.2.0` (`Last Amended: 2026-11-13`) updating its top HTML Sync Impact Report (Amendment Log), Principle I rigor clarification, Principle V / Quality Gates numbered gates (#1 mandatory reverse test, #2 reserved PII safety gate) + synced public API contract list, and Footprint wording (keeping 16 GB RAM CPU-only local footprint intact).
- **Rationale**: Follows `## Governance` amendment protocol (documented rationale, minor version bump, migration note confirming zero breaking runtime impact).
- **Alternatives Considered**: Deferring all constitution edits to Stage 4 (rejected: Stage 0 specifically establishes constitutional backing before refactoring starts).

---

## Decision 4: `README.md` `POLICY` Heuristic Disclosure & Tree Parity

- **Finding**: `README.md` (`L297–305`) `POLICY` profile table summarizes **Clause Preservation** as *"Enabled (never splits inside numbered clauses)"* without noting PDF clause boundary detection is heuristic. `README.md` (`L600`) displays `Product.md` in `## Repository Structure` (note `py.typed`, `.env.example`, `.pre-commit-config.yaml`, `LICENSE`, `README.md`, and `.specify/memory/constitution.md` are already displayed cleanly). `README.md` (`L386–408`) documents `docpipe-maestro query` without showing `--json`.
- **Decision**: Clarify in `README.md` `POLICY` table (and concise note underneath) that PDF clause boundary detection relies on text extraction heuristics rather than guaranteed structural PDF tagging; update `Product.md` → `PRODUCT.md` in the repository tree; add a short `docpipe-maestro query ... --json` usage snippet in §6 linking to `docs/cli-reference.md`.
- **Rationale**: Sets truthful expectations for scanned/multi-column/irregular PDFs while keeping `README.md` concise.
- **Alternatives Considered**: Leaving `README.md` §6 untouched (rejected: FR-009 notes CLI summaries listing `query` options should remain aligned with `docs/cli-reference.md`).

---

## Decision 5: `docpipe-maestro query --json` Schema, Score Precision & Error Contract

- **Finding**: In `src/docpipe_maestro/cli.py`:
  - `p_status` (`L194`) and `p_ask` (`L270`) define `--json` with `dest="as_json"`, emitting top-level JSON objects (`status`: `{"collection", "embed_model", ..., "sources": [...]}`; `ask`: `{"answer", ..., "sources": [...]}`) via `json.dumps(..., indent=2)`.
  - `p_query` (`L209–224`, handled at `L480–504`) lacks `--json`.
  - Global error handling (`L508–510`) catches `(DocpipeError, ValueError, TypeError)` cleanly, prints `Error: {exc}` to `stderr`, leaves `stdout` empty, and exits with code `1`.
- **Decision** (incorporating Clarification Session 2026-11-13 Q1 & Q3):
  - Add `--json` (`action="store_true"`, `dest="as_json"`, `default=False`) to `p_query`.
  - Emit pretty JSON (`json.dumps(payload, indent=2)`) with top-level keys `"query"`, `"collection"`, `"expand_parent"`, and `"results"`.
  - Map each `RetrievedChunk` in `"results"` to `{"id": item.id, "parent_id": item.parent_id, "score": float(item.score), "text": item.text, "metadata": dict(item.metadata)}`.
  - Keep `score` as full numeric `float(item.score)` (not 4-decimal rounded) so downstream Stage 2 evaluation tooling and threshold comparisons (`>= args.threshold`) retain exact retrieval scores from `retrieve()`.
  - Emit `"results": []` with exit code `0` on empty collections or threshold-filtered empty matches (zero prose on `stdout`).
  - Route validation/runtime exceptions through existing CLI handler (`Error: <exc>` on `stderr`, empty `stdout`, exit `1`).
  - Keep non-`--json` console output completely unchanged.
- **Rationale**: Balances consistency with `status --json` / `ask --json` object envelopes, preserves exact `RetrievedChunk` semantics for evaluation scripts, and avoids formatting drift.
- **Alternatives Considered**: `round(item.score, 4)` as in `ask --json` (rejected: lossy for automated threshold boundary checks and evaluation ranking deltas); bare list `[...]` or JSON error payloads (rejected in Clarifications Q1 and Q3).

---

## Decision 6: Packaging Inclusion & Verification Discipline

- **Finding**: `[tool.hatch.build.targets.wheel]` (`packages = ["src/docpipe_maestro"]`) already bundles `src/docpipe_maestro/py.typed` (confirmed existing on disk as 0-byte file). `[tool.hatch.build.targets.sdist].include` (`pyproject.toml:79–88`) already specifies `.specify/memory/constitution.md`, `docs/`, `README.md`, `LICENSE`, `CHANGELOG.md`, `src/`, `tests/`, and `Product.md` (the only wrong-cased line). Runtime pins (`chromadb>=1.5.9`, `litellm>=1.108.0`, `python-dotenv>=1.0.0`, `langchain-text-splitters>=0.3.0`, `tomli>=2.0.0`), optional parser extras (`pdf = ["pypdf>=6.21.3"]`, `docx`, `html`, `all`), URLs, and `[tool.ruff]` / `[tool.mypy]` / `[tool.pytest]` / `[tool.coverage]` configs must stay untouched.
- **Decision**: Edit strictly line `82` of `pyproject.toml` (`"Product.md"` → `"PRODUCT.md"`), and validate wheel + sdist build artifacts (`python -m build`, `twine check dist/*`) plus member listings for `PRODUCT.md`, `.specify/memory/constitution.md`, `docs/`, and `docpipe_maestro/py.typed`.
- **Rationale**: Zero risk to dependency resolution or CI matrix while closing the packaging casing drift completely.
- **Alternatives Considered**: Adding `REFACTOR_PROGRAM.md` to `sdist` (rejected: `REFACTOR_PROGRAM.md` is an internal maintainer refactor roadmap, not required in PyPI user source tarballs and omitted from FR-001/FR-010).
