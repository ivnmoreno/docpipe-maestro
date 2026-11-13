# Quickstart & Validation Guide: Core RAG Pipeline

**Feature**: `001-core-rag-pipeline` | **Date**: 2026-11-12

This guide provides end-to-end validation scenarios verifying that `docpipe-maestro` satisfies all acceptance criteria, safety gates, and offline execution rules.

---

## 1. Environment Setup (Clean Install Validation)

### Core + Format Extras + Dev Tools
```bash
uv venv --python 3.12
uv pip install -e ".[all]" --group dev
```

### Verify Local Runtime (Zero Outbound Network Execution)
For full local execution with Ollama:
```bash
ollama pull nomic-embed-text
ollama pull llama3.2
```

---

## 2. Static & Safety Release Gate Checks

Run CI quality gates (must all pass cleanly before release):

```bash
# Linting and formatting
uv run ruff check .
uv run ruff format --check .

# Strict static type checking
uv run mypy src tests

# Full test suite including the mandatory Reverse Safety Test
uv run pytest
```

### Mandatory Reverse Safety Test Verification
```bash
uv run pytest tests/test_reverse_safety.py -v
```
**Expected Outcome**: 100% of fixture policy queries containing exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`) retrieve parent sections containing both the rule and its exception text (`SC-001`).

---

## 3. End-to-End Local CLI Scenarios

See [cli.md](contracts/cli.md) for full flag documentation.

### Scenario A: Multi-Format Ingestion & Retrieval-Only Search (US-1)
```bash
docpipe-maestro ingest ./sample_docs --profile POLICY --collection handbook
docpipe-maestro status --collection handbook
docpipe-maestro query "How many days of annual leave do employees receive?" --collection handbook
docpipe-maestro query "annual leave" --no-expand-parent --collection handbook
```
**Expected Outcome**:
- PDF, DOCX, HTML, Markdown, and TXT documents index with zero errors.
- `docpipe-maestro query` returns deduplicated parent sections ordered by `max(score)` descending, carrying `source`, `section`, `clause`, and `page` metadata (`SC-004`, `SC-007`).
- `--no-expand-parent` returns individual child chunks with `[Source: ... | Section: ...]` context headers.

### Scenario B: Grounded Local & Cloud Generation (US-3)
```bash
# Local-first default (zero cloud credentials or external network)
docpipe-maestro ask "How many days of leave does a new hire get?" --collection handbook

# Out-of-domain threshold short-circuit (zero LLM call)
docpipe-maestro ask "What is the recipe for chocolate cake?" --threshold 0.85 --collection handbook

# Cloud provider override via env var (zero code changes)
export OPENAI_API_KEY="sk-..."
docpipe-maestro ask "Summarize the leave policy." --model openai/gpt-4o-mini --collection handbook
```
**Expected Outcome**:
- Local run cites the general rule *and* new-hire exception.
- Threshold short-circuit returns deterministic `"Not found in the provided context."` without calling the LLM.
- No API key ever appears in stdout, stderr, or logs.

### Scenario C: Incremental Sync, Shrinking File & Model Migration (US-4)
```bash
# 1. Modify a file (delete a clause), touch an unchanged file, and delete another file
docpipe-maestro sync ./sample_docs --profile POLICY --collection handbook

# 2. Verify model lock refuses mismatched query model
docpipe-maestro query "annual leave" --embed-model openai/text-embedding-3-small --collection handbook

# 3. Explicitly migrate embeddings across the collection
docpipe-maestro reindex --model openai/text-embedding-3-small --collection handbook
```
**Expected Outcome**:
- Touched unchanged file is skipped (0 embeddings recomputed).
- Shrinking file removes 100% of deleted clause records (zero orphans, `SC-002`).
- Deleted file is purged from store and manifest.
- Mismatched embedding model is refused until `docpipe-maestro reindex` updates the manifest lock.

---

## 4. Python Library API Validation (US-3 / Integration)

See [python-api.md](contracts/python-api.md) and [data-model.md](data-model.md) for exact signatures and data shapes:
1. Call `ingest(path, profile="POLICY", collection="app")` -> verify `IngestResult`.
2. Call `retrieve(question, collection="app", top_k=5, threshold=0.3)` -> verify `list[RetrievedChunk]` with normalized scores in `[0.0, 1.0]`.
3. Call `build_prompt(question, sections)` -> verify pure sub-millisecond execution with zero network calls (`SC-005`).
4. Optionally call `answer(prompt, model="ollama/llama3.2", has_context=bool(sections))` -> verify grounded string response.
