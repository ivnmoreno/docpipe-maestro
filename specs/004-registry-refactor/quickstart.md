# Quickstart Validation Guide: Pluggable Pipeline Stage Registries

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-13

## Prerequisites

- Branch `refactor/004-registry-refactor` checked out at repo root
- Python `>=3.10` environment synced via `uv` (`uv sync --all-extras --dev`)
- Reference contracts:
  - [Registry API Contract](contracts/registry-api.md)
  - [Stage Protocols Contract](contracts/stage-protocols.md)
  - [Public API & Compatibility Contract](contracts/public-api.md)
  - [Data Model](data-model.md)

---

## Scenario 1: Capture Pre-Refactor Golden Snapshot (Pre-Wiring Step)

Before modifying `pipeline.py` or `retriever.py`, capture the deterministic baseline retrieval snapshot against `tests/fixtures/policy_corpus/` using the offline `deterministic_embed` double in `tests/conftest.py` and save it as `tests/fixtures/golden_query_stage1.json`:

- Ingest `tests/fixtures/policy_corpus/` with profile `"POLICY"` into a temporary collection.
- Execute representative queries covering direct lookups, cross-document/intra-document references, and exception clauses (`expand_parent=True`).
- Record sorted result payloads (`id`, `parent_id`, `score`, `text`, `metadata`).

Expected outcome after the refactor: `tests/test_golden_refactor.py` asserts identical `id`, `parent_id`, `score`, `text`, and `metadata` against `tests/fixtures/golden_query_stage1.json`.

---

## Scenario 2: Validate Registry & Exception Contracts

Verify registry behavior across both isolated `Registry[T]` instances and the eight package-level registries via `tests/test_registry.py`:

- Registering a custom class under a new key succeeds, exposes sorted `keys()`, supports `key in registry`, and resolves via `resolve(key)`.
- Registering a duplicate key — including a key matching an unmaterialized lazy built-in (`"default"`, `"md"`, `"pdf"`, etc.) — fails immediately with `RegistryError` (catching either `RegistryError` or `DocpipeError`).
- Resolving an unknown key catches the internal lookup miss and raises `RegistryError` listing every available key in sorted order (or `<empty>` on `ENRICHERS`, `SEARCHERS`, and `RERANKERS`).

---

## Scenario 3: End-to-End Custom Stage Extension Without Orchestrator Edits

Verify additive extensibility using top-level exports documented in [contracts/public-api.md](contracts/public-api.md):

1. Register a custom `Parser` via `@register_parser("rst")` claiming `.rst` extensions, ingest a `.rst` document with `ingest(doc_path, ...)`, and retrieve sections with `retrieve(...)` without modifying `pipeline.py` or `retriever.py`.
2. Register a custom `Cleaner` / `Chunker` / `Embedder` / `Store` via `@register_cleaner`, `@register_chunker`, `@register_embedder`, or `@register_store`, and invoke `ingest(..., cleaner="custom", ...)` / `retrieve(..., store="custom", ...)` cleanly.

---

## Scenario 4: Verify Startup Laziness & AST Library Purity

Confirm Principle III and startup performance invariants:

- Execute subprocess startup check verifying neither `chromadb` nor `litellm` loads when importing `docpipe_maestro`, accessing `docpipe_maestro.register_*`, or running `docpipe_maestro.cli.build_parser()`.
- Run `tests/test_library_purity.py` to AST-scan all modules under `src/docpipe_maestro/` (excluding `cli.py`) for forbidden config/env imports (`tomllib`, `tomli`, `toml`, `configparser`, `dotenv`) while allowing document/manifest file reads.
- Run `tests/test_api_stability.py` to confirm all 33 exports in `docpipe_maestro.__all__` preserve exact required signatures and newly added stage selectors are keyword-only defaulting to `"default"`.

---

## Scenario 5: Full Quality & Release Gate Verification

Run all repository quality gates locally prior to review/merge:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/
uv run mypy src tests
uv run pytest -m reverse -v
uv run pytest -v --cov
```

Expected outcomes:
- Formatting, linting, security rules (`--select S`), and strict static type checks (`mypy --strict` targeting Python 3.10 across `src` and `tests`) pass with zero errors or warnings.
- Mandatory Release Gate #1 (`pytest -m reverse -v`) passes 100% unmodified (`8/8` cases).
- Full test suite (all existing Stage 0 tests unmodified + `test_registry.py` + `test_api_stability.py` + `test_library_purity.py` + `test_golden_refactor.py` + Stage 1 invariant assertions) passes with `>= 80%` branch coverage.
