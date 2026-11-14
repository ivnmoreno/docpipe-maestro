# Quickstart Validation Guide: Hybrid Lexical Search

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/005-hybrid-search/spec.md) | **Date**: 2026-11-14

## 1. Prerequisites

- Python `>=3.10` with `uv` environment synced (`uv sync`).
- Built-in SQLite FTS5 enabled (verified standard in project environment).

## 2. Automated Verification Scenarios (Offline)

1. **Exact-Match & Hybrid Retrieval Quality**:
   - Ingest sample corpus with exact identifiers (`SEV-1`, `AES-256`, `Clause 1.2`) offline (`mock_litellm_offline`).
   - Run `retrieve(query, searcher="fts5_hybrid")` and assert exact-token matches rank first, parent sections expand properly, exception clauses remain intact, and normalized scores lie strictly within `[0.0, 1.0]`.
2. **Baseline Backwards Compatibility**:
   - Run `tests/test_golden_refactor.py` (`searcher="default"`) and confirm bit-for-bit equivalence with `tests/fixtures/golden_query_stage1.json`.
3. **Lifecycle Synchronization & Crash Safety**:
   - Perform `ingest` -> modify/delete files -> `sync` -> `remove` -> verify removed terms return zero lexical hits.
   - Inject uncommitted orphan rows in SQLite FTS5 and verify queries filter them out while subsequent `ingest`/`sync` sweeps purge them.
   - Simulate a legacy collection lacking `<persist_dir>/lexical/<collection>.db`: verify `retrieve(..., searcher="fts5_hybrid")` raises `DocpipeError` recommending `reindex`, then run `reindex(...)` and confirm `searcher="fts5_hybrid"` succeeds.
4. **Query Sanitization Edge Cases**:
   - Execute queries containing hyphens (`SEV-1`), dots (`1.2`), unbalanced quotes, wildcards (`*`), operators (`AND`, `OR`, `NOT`), empty strings, and punctuation-only inputs cleanly without raising SQLite operational errors.
5. **CLI & Startup Purity**:
   - Run `docpipe-maestro query "..." --searcher fts5_hybrid` and `docpipe-maestro ask "..." --searcher fts5_hybrid`.
   - Verify unknown `--searcher ghost` exits with status `1` and helpful error on `stderr`.
   - Run full quality gates:
     ```bash
     uv run ruff format --check .
     uv run ruff check .
     uv run ruff check --select S src/
     uv run mypy src tests
     uv run pytest -m reverse -v
     uv run pytest -v --cov
     ```

## 3. Manual CLI Smoke Test (Local Corpus)

If testing against an existing pre-005 local collection in `.docpipe`:

```bash
# Re-index existing collection once to build its collocated FTS5 index
uv run docpipe-maestro reindex --model ollama/nomic-embed-text

# Compare pure vector vs hybrid retrieval
uv run docpipe-maestro query "SEV-1 error rate" --searcher default
uv run docpipe-maestro query "SEV-1 error rate" --searcher fts5_hybrid

# Ask grounded question using hybrid retrieval
uv run docpipe-maestro ask "What clause governs emergency flight cancellation caps?" --searcher fts5_hybrid
```
