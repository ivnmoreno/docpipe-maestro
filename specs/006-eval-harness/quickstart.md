# Quickstart Validation Guide: Retrieval Evaluation Harness

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/spec.md) | **Plan**: [plan.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/plan.md) | **Date**: 2026-11-14

## 1. Prerequisites

- Python `>= 3.10` with project dev environment synced (`uv sync`).
- No network access or live model download required for automated verification.

## 2. Automated Verification Scenarios (Offline)

1. **Pure Metric Calculations & Boundary Safety (`FR-001`)**:
   - Run unit tests verifying `precision_at_k`, `recall_at_k` (`|relevant|` denominator), `reciprocal_rank`, and `normalize_k_values` across:
     - exact matches, partial matches, and missed queries;
     - empty retrieved lists and empty relevant sets (`0.0` without `ZeroDivisionError`);
     - duplicate relevant IDs and duplicate retrieved IDs (clamped properly to `[0.0, 1.0]`);
     - unsorted/duplicate positive cutoffs (`[10, 3, 3]` -> `(3, 10)`) and invalid cutoffs (`[]`, `[0]`, `[-1]`, `[True]` -> `ValueError`).

2. **Read-Only Runner Integrity & Validation (`FR-002`, `FR-003`, `SC-001`, `SC-002`)**:
   - Seed an isolated `tmp_persist_dir` via `ingest` using `mock_litellm_offline`.
   - Snapshot SHA-256 hashes of every file under `tmp_persist_dir`.
   - Run `evaluate(...)` twice consecutively across both `"default"` and `"fts5_hybrid"` searchers:
     - Verify consecutive runs return 100% identical `EvalReport` dictionaries (`0.0` drift).
     - Verify zero files were added, deleted, or modified in `tmp_persist_dir`.
   - Verify fail-fast errors with zero store writes when:
     - fixture file is missing, malformed, has 0 queries, blank question, or empty `relevant_ids`;
     - target collection does not exist or has zero committed documents;
     - `embed_model` mismatches collection lock (`ModelMismatchError`);
     - `searcher` key is unknown (`RegistryError`).

3. **CLI Precedence, Output Modes & Startup Purity (`FR-005`, `FR-006`)**:
   - Verify `cli.build_parser()` does not import `chromadb`, `litellm`, `pypdf`, `docx`, or `bs4`.
   - Test collection resolution precedence cleanly: explicit `--collection` flag > non-empty fixture `collection` > TOML `[default]` `collection` > `"default"`.
   - Invoke `docpipe-maestro eval --fixture ... --k 1 3 5 --searcher fts5_hybrid --json` and verify valid JSON `EvalReport` on `stdout` and exit code `0`.
   - Invoke `docpipe-maestro eval --fixture ...` in default text mode and verify human-readable summary table on `stdout` and exit code `0`.
   - Invoke `eval` with missing collection, missing fixture, bad `--k 0`, and unknown `--searcher ghost`; verify single-line `Error: ...` on `stderr` and exit code `1`.

4. **Curated Policy Suite & Baseline Reproducibility (`FR-007`, `FR-008`, `SC-003`, `SC-004`)**:
   - Load `tests/fixtures/eval_policy_corpus.json` and assert `>= 20` queries covering `direct_lookup`, `paraphrased`, `exact_identifier`, and `>= 3` `rule_and_exception` queries whose `relevant_ids` exist as full parent sections in the seeded `"eval_policy"` collection.
   - Verify `tests/fixtures/policy_corpus/` hashes remain unchanged and `pytest -m reverse` passes unmodified.
   - Replay offline ingestion of `policy_corpus` + `eval_corpus` into `tmp_persist_dir` using `mock_litellm_offline`, run `evaluate(...)` for both `"default"` and `"fts5_hybrid"`, and verify exact equivalence against `docs/eval-baseline.json` (`modes["default"]` and `modes["fts5_hybrid"]`) across `aggregate`, `per_query`, and non-path `config` fields.

## 3. Full Repository Verification Gate (`FR-009`, `SC-005`)

Run all mandatory quality gates after implementation finishes (zero failures allowed):

```bash
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/
uv run mypy src tests
uv run pytest -m reverse -v
uv run pytest -v --cov
```

## 4. Manual CLI Live-Model Benchmark Workflow (Optional)

If evaluating an existing local collection backed by a running local Ollama instance:

```bash
# Ingest policy corpus once into a collection
uv run docpipe-maestro ingest tests/fixtures/eval_corpus --profile POLICY --collection local_eval --embed-model ollama/nomic-embed-text

# Run dense evaluation with JSON report
uv run docpipe-maestro eval --fixture tests/fixtures/eval_policy_corpus.json --collection local_eval --searcher default --json

# Compare against hybrid lexical search read-only
uv run docpipe-maestro eval --fixture tests/fixtures/eval_policy_corpus.json --collection local_eval --searcher fts5_hybrid
```
