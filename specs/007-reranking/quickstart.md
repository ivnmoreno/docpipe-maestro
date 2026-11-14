# Quickstart & Validation Guide: Cross-Encoder Reranking

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/reranker.md](contracts/reranker.md)

---

## 1. Offline Automated Verification (Zero Network, Zero Model Downloads)

Run the full quality and safety gates across the repository:

```bash
# 1. Verify lazy startup & library purity (no chromadb, litellm, torch, or sentence_transformers loaded)
uv run pytest tests/test_library_purity.py tests/test_api_stability.py -v

# 2. Run reranker unit, missing-extra, mocked CrossEncoder, CLI, and eval integration tests
LITELLM_LOCAL_MODEL_COST_MAP="true" uv run pytest tests/test_reranker.py tests/test_eval.py tests/test_cli.py -v

# 3. Verify Release Gate #1 (Exception Preservation) with reranking coverage
LITELLM_LOCAL_MODEL_COST_MAP="true" uv run pytest -m reverse -v

# 4. Run full CI quality matrix (formatting, lint, bandit security rules, strict typing, full branch coverage >= 80%)
uv run ruff format --check . && \
uv run ruff check . && \
uv run ruff check --select S src/ && \
uv run mypy src tests && \
LITELLM_LOCAL_MODEL_COST_MAP="true" uv run pytest -v --cov
```

Expected offline invariants:
- `0` network requests executed during tests (`mock_litellm_offline` + mocked `_instantiate_cross_encoder`).
- Existing `test_curated_policy_suite_and_baseline_replay` passes with zero changes to committed offline `docs/eval-baseline.json`.
- Missing `[rerank]` extra fails immediately with exit code `1` and single-line installation guidance on `stderr`.

---

## 2. Live Local Benchmark & Governance Gate (`Q1`)

Prerequisites:
- Optional `[rerank]` extra installed (`uv sync --all-extras --group dev` or `pip install "docpipe-maestro[rerank]"`).
- Local Ollama running with `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).

Run read-only live comparison across all four configurations (`default` vs `fts5_hybrid`, with and without `--rerank`), verifying zero storage drift in `.docpipe/`:

```bash
SMOKE_DIR=$(mktemp -d)
DP=(uv run docpipe-maestro --no-config --persist-dir "$SMOKE_DIR")

# Phase 1 ingest curated policy evaluation suite
"${DP[@]}" ingest tests/fixtures/policy_corpus --profile POLICY --collection eval_policy
"${DP[@]}" ingest tests/fixtures/eval_corpus --profile POLICY --collection eval_policy

# Snapshot manifest + lexical file hashes prior to read-only eval sweeps
find "$SMOKE_DIR/manifests" "$SMOKE_DIR/lexical" -type f -exec sha256sum {} + | sort > /tmp/before_rerank.sha256

# Phase 2 baseline vs reranked comparison (default dense & fts5_hybrid)
"${DP[@]}" eval --fixture tests/fixtures/eval_policy_corpus.json --searcher default --no-rerank
"${DP[@]}" eval --fixture tests/fixtures/eval_policy_corpus.json --searcher default --rerank
"${DP[@]}" eval --fixture tests/fixtures/eval_policy_corpus.json --searcher fts5_hybrid --no-rerank
"${DP[@]}" eval --fixture tests/fixtures/eval_policy_corpus.json --searcher fts5_hybrid --rerank

# Confirm 0 byte drift across manifests & lexical DB
find "$SMOKE_DIR/manifests" "$SMOKE_DIR/lexical" -type f -exec sha256sum {} + | sort > /tmp/after_rerank.sha256
diff -u /tmp/before_rerank.sha256 /tmp/after_rerank.sha256 && echo "OK: zero storage drift"

# Spot-check live query + ask exception preservation with --rerank
"${DP[@]}" query "When are employees not entitled to annual leave?" --collection eval_policy --searcher fts5_hybrid --rerank --top-k 3

rm -rf "$SMOKE_DIR" /tmp/before_rerank.sha256 /tmp/after_rerank.sha256
```

Acceptance check per `FR-009` / Clarification **Q1**:
- Verify live `--rerank` shows **both** `default` and `fts5_hybrid` individually achieve strictly positive (`> 0.0`) improvement on `Precision@5`, **or** strictly positive (`> 0.0`) improvement on both `MRR` and `Precision@1` with zero `Precision@5` regression (`Precision@5 >= baseline`) against their respective live non-reranked runs. Record live metrics and retain/revert decision in `docs/eval-baseline.md`.
