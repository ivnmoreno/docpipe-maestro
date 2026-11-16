# Quickstart & Validation Guide: Structured JSON Logging

**Feature**: `011-structured-logging` (`feat/011-structured-logging`) | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/structured-logging.md](contracts/structured-logging.md)

## 1. Prerequisites

Run commands from the repository root with dev dependencies installed:

```bash
uv sync --all-extras --group dev
```

No external database servers, cloud API keys, or downloads are required to validate structured logging locally (tests use offline fakes for embeddings and completions).

---

## 2. Host Library Attaching Structured Telemetry

Verify silent defaults and correlated host capture referencing [contracts/structured-logging.md](contracts/structured-logging.md) and [data-model.md](data-model.md):

1. **Silent Default Verification**: Run `ingest()` and `retrieve()` in a clean process without configuring logging handlers; confirm root logger handlers, `stdout`, and `stderr` receive zero unsolicited log output.
2. **Host JSON Attachment**: Attach a custom handler formatted with `docpipe_maestro.log.JsonFormatter()` to `get_logger()` at `logging.INFO` (or `logging.DEBUG`), execute `ingest()` followed by `retrieve()`, and parse every captured line with `json.loads` to verify consistent envelope fields (`ts`, `level`, `logger`, `msg="stage.end"`, non-empty UUID `correlation_id`, nested `fields.duration_ms`).
3. **Concurrency Isolation**: Run concurrent `asyncio` tasks and worker threads each executing correlated flows under explicit or generated `correlation_id()` scopes; verify zero cross-task identifier contamination.

---

## 3. CLI `--log-json` & `--log-level` Separation Scenarios

Confirm `stdout` remains clean while `stderr` streams correlated NDJSON records across Phase 1 and Phase 2 commands:

```bash
# Phase 1 batch summary at INFO + per-doc DEBUG timing on stderr
uv run docpipe-maestro --log-json --log-level INFO ingest ./docs 2>ingest.log.jsonl
uv run docpipe-maestro --log-json --log-level DEBUG sync ./docs 2>sync.log.jsonl

# Phase 2 retrieval & QA with pure JSON stdout and NDJSON stderr
uv run docpipe-maestro --log-json --log-level INFO query "leave policy" --json >query.out.json 2>query.log.jsonl
uv run docpipe-maestro ask "When is leave allowed?" --json --log-json --log-level INFO >ask.out.json 2>ask.log.jsonl
```

Expected checks:
- `query.out.json` and `ask.out.json` parse directly via `json.load()` with zero log lines mixed in.
- Every line in `*.log.jsonl` parses via `json.loads()`, shares a single UUID `correlation_id` per invocation (`ask.log.jsonl` correlates `embed`, `search`, `answer` — plus `rerank` / `egress` when enabled), and excludes raw document content, questions, prompts, answers, raw PII, and API keys.
- Passing `--log-level INFO` without `--log-json` emits human-readable diagnostic lines to `stderr` only; repeating `cli.main()` in one Python process never duplicates stderr handlers.

---

## 4. Mandatory Automated Quality Gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/
uv run mypy src tests
uv run pytest -m reverse -v
uv run pytest -m pii -v
LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov
```

Expected: Zero formatting/lint/security/mypy errors, **Release Gate #1** (`reverse`) passing, **Release Gate #2** (`pii`) passing, and full suite passing with branch coverage `>= 80%`.
