# Validation Quickstart: Structured Metadata Pre-Filtering (`where`)

**Feature**: `010-metadata-filtering`  
**References**: [spec.md](spec.md) | [data-model.md](data-model.md) | [contracts/metadata-filtering.md](contracts/metadata-filtering.md)

## 1. Automated Quality & Safety Gates (Offline Verification)

Run the full repository checks from the project root on branch `feat/010-metadata-filtering`:

```bash
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync ruff check --select S src/
uv run --no-sync mypy src tests
uv run --no-sync pytest -m reverse -v
uv run --no-sync pytest -m pii -v
LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -v --cov
```

**Expected outcomes**:
- `ruff format`, `ruff check`, `ruff --select S src/`, and strict `mypy` pass with zero issues.
- **Release Gate #1** (`pytest -m reverse`) and **Release Gate #2** (`pytest -m pii`) pass 100%.
- Full test suite passes with >= 80% branch coverage, including intentional signature checks in `tests/test_api_stability.py` and phase/import purity checks in `tests/test_library_purity.py`.

## 2. Offline Smoke Scenarios (Chunk, Manifest & Hybrid Parity)

### Scenario A — Multi-Document Chunk Filtering (Dense & Hybrid)
1. Ingest two documents into an isolated persist directory (`hr_policy.md` under `POLICY` profile, `guide.md` under `DEFAULT` profile).
2. Run `docpipe-maestro query "leave policy" --where source=hr_policy.md --persist-dir <dir>` with `--searcher default` and again with `--searcher fts5_hybrid`.
3. Verify all returned records have `metadata["source"] == "hr_policy.md"`, including when `--rerank` is enabled.

### Scenario B — Manifest Filtering Without Re-Ingestion (`profile` & `ingested_*`)
1. Query the existing pre-ingested collection using `--where profile=POLICY` and `--where ingested_after=2026-11-13` (and `--where ingested_before=2026-11-13`).
2. Verify results strictly belong to sources recorded with matching manifest provenance in `<dir>/manifests/<collection>.json`.
3. Query with a future date (`--where ingested_after=2099-01-01`) or unknown profile (`--where profile=NOPE`) and verify immediate empty completion (`No matching sections found.`) with zero embedder calls and zero storage errors.

### Scenario C — Adversarial & Malformed Input Rejection
1. Run `docpipe-maestro query "leave" --where type=parent --persist-dir <dir>` and verify exit code `1` with reserved-key error before search.
2. Run `docpipe-maestro query "leave" --where page=abc`, `--where secton=Leave`, `--where broken`, `--where ingested_after=bad-date`, `--where ingested_after=2026-01-01 --where ingested_after=2026-02-01` and verify exit code `1` with actionable error diagnostics on `stderr`.

### Scenario D — Evaluation & Question Answering (`ask` / `eval`)
1. Run `docpipe-maestro ask "What is the leave exception?" --where profile=POLICY --persist-dir <dir>` and confirm cited sources match `POLICY` documents; run `--where source=guide.md` on a question absent from `guide.md` and confirm clean `EMPTY_CONTEXT_REFUSAL` without LLM calls when retrieval returns empty.
2. Run `docpipe-maestro eval --fixture <fixture.json> --where profile=POLICY --persist-dir <dir> --json` and confirm metrics reflect filtered retrieval.
