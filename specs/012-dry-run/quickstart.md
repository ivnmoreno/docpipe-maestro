# Quickstart Validation Guide: Dry-Run Preview Mode (`012-dry-run`)

**Feature**: `012-dry-run` | **Date**: 2026-11-17

## Scenario 1: CLI `sync --dry-run` & `--json` Against Uninitialized or Mixed Corpus

```bash
# 1. Preview initial sync (uninitialized persist_dir must NOT be created)
docpipe-maestro sync ./docs --collection demo --persist-dir /tmp/dry-persist --dry-run --json

# 2. Verify /tmp/dry-persist was not created
test ! -e /tmp/dry-persist

# 3. Ingest normally, then edit one file, add one file, delete one file, touch one unchanged file
docpipe-maestro ingest ./docs --collection demo --persist-dir /tmp/dry-persist
docpipe-maestro sync ./docs --collection demo --persist-dir /tmp/dry-persist --dry-run --json
```

Expected:
- JSON reports `"dry_run": true`, accurate `"added"`, `"updated"`, `"skipped"`, `"removed"`, `"estimated_children"`, `"estimated_parents"`, `"estimated_tokens"`, and `"estimated_cost_usd"`.
- Zero files or hashes inside `/tmp/dry-persist` change.

## Scenario 2: CLI `reindex --dry-run` & Offline Cost Preview

```bash
# Preview re-embedding under a cloud model without API keys or network calls
docpipe-maestro reindex \
  --collection demo \
  --persist-dir /tmp/dry-persist \
  --model openai/text-embedding-3-small \
  --dry-run --json
```

Expected:
- JSON reports `"dry_run": true`, `"previous_embed_model": "ollama/nomic-embed-text"`, `"embed_model": "openai/text-embedding-3-small"`, active `"total_sources"`, `"total_children"`, `"total_parents"`, deterministic `"estimated_tokens"`, and non-null `"estimated_cost_usd"`.
- Manifest remains locked to `"ollama/nomic-embed-text"` and zero `litellm.embedding` requests run.

## Scenario 3: Library API Parity & Safety Verification

```bash
uv run --no-sync pytest tests/test_sync_lifecycle.py tests/test_cli.py tests/test_api_stability.py -v
uv run --no-sync pytest -m reverse -v
uv run --no-sync pytest -m pii -v
```
