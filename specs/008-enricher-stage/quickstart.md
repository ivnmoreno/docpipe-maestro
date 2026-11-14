# Quickstart & Validation Guide: First-Class Enricher Stage

**Feature**: `008-enricher-stage` | **Branch**: `feat/008-enricher-stage`

## Prerequisites

- Environment synced cleanly (`uv sync --extra all --group dev` or active `.venv`)
- Working directory at repository root on branch `feat/008-enricher-stage`
- All checks run offline with zero network calls or API keys required

---

## Validation Scenarios

### 1. Phase 2 Isolation & Lazy Import Guard (`SC-001`)

Verify zero Phase 2 (`query/`) static or dynamic imports reference `docpipe_maestro.ingest*`, and confirm `ingest/enricher/crossrefs.py` stays unloaded on root/registry/CLI startup:

```bash
uv run pytest tests/test_library_purity.py -v
```

**Expected**: `test_phase2_query_does_not_import_phase1_stage_contracts` and `test_top_level_register_exports_and_cli_avoid_heavy_deps` pass with zero violations.

### 2. Cross-Reference Parity, Golden Output & Silent Re-Exports (`SC-002`, `FR-010`)

Verify unchanged intra-doc/cross-doc resolution, cycle prevention, unresolved warnings, strict `-Werror` clean imports on `docpipe_maestro.ingest.crossrefs`, API stability, and golden retrieval parity:

```bash
uv run pytest tests/test_crossrefs.py tests/test_extended_complex.py tests/test_api_stability.py tests/test_golden_refactor.py tests/test_retriever.py -Werror -v
```

**Expected**: All tests pass with zero warnings emitted by legacy `docpipe_maestro.ingest.crossrefs` imports.

### 3. Reverse Safety Gate (`Release Gate #1`)

Verify exception preservation (`except`, `unless`, `not entitled`, `subject to`, `provided that`) under `POLICY` profile with migrated `"crossrefs"` enricher:

```bash
uv run pytest -m reverse -v
```

**Expected**: `100%` of `@pytest.mark.reverse` tests pass.

### 4. Custom Enricher Ordering, Context Delivery, Profile Normalization & Atomic Abort (`SC-003`, `SC-004`, `SC-005`)

Verify built-in `"crossrefs"` registration on `ENRICHERS`, ordered execution across `ingest` and `sync`, complete `IngestContext` (`collection`, `source`, `content_hash`, `doc_version`, `embed_model`, `profile`), legacy `resolve_crossrefs=True` profile normalization, upfront `RegistryError` on unchanged sync runs, `DEFAULT` skipping (`0` enrichers), `POLICY` parity, and zero store/lexical/manifest mutations on failing enrichers:

```bash
uv run pytest tests/test_registry.py tests/test_invariants_stage1.py tests/test_sync_lifecycle.py -v
```

**Expected**: All existing and Stage 3 enricher tests pass.

### 5. Mandatory Repository Quality Gate (`Constitution v1.2.2`)

Run linting, security checks, strict type checking, and the full test suite with coverage threshold:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/
uv run mypy src tests
uv run pytest --cov=docpipe_maestro
```

**Expected**: Zero formatting/lint/security/mypy issues, `100%` passing test suite, and coverage cleanly above `80%` branch minimum.
