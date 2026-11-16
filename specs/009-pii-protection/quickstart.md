# Validation Quickstart: PII Protection & Release Gate #2

**Feature**: `009-pii-protection` (`feat/009-pii-protection`)  
**Date**: 2026-11-15  
**Contracts**: [contracts/pii-protection.md](contracts/pii-protection.md) | **Data Model**: [data-model.md](data-model.md)

## 1. Prerequisites & Branch Setup

Ensure you are working on `feat/009-pii-protection` (keeping `main` synced with `origin/main`):

```bash
uv sync --all-extras --group dev
```

*(Base deterministic recognizers and offline CI require zero `[pii]` downloads; all verification scenarios below run completely offline without network calls.)*

## 2. Offline Quality & Safety Gates

Run formatting, lint, security checks, strict type checking, and both mandatory release gates:

```bash
# 1. Code formatting, lint, Bandit-equivalent security rules & strict typing
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/
uv run mypy src tests

# 2. Release Gate #1 — Exception preservation reverse safety gate
uv run pytest -m reverse -v

# 3. Release Gate #2 — PII protection & outbound egress safety gate
uv run pytest -m pii -v

# 4. Library purity & full suite (>=80% branch coverage; 100% tests passing required)
LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov
```

## 3. End-to-End CLI & DPO Audit Verification (Offline / Mocked or Local Ollama)

### A. Strict `--local-only` Refusal of Remote Providers / Non-Loopback Endpoints

```bash
# Rejected cleanly before network I/O with exit status 1
docpipe-maestro ask "Summarize leave policy" --model openai/gpt-4o-mini --local-only
docpipe-maestro ingest ./docs --embed-model openai/text-embedding-3-small --local-only
docpipe-maestro ask "Summarize leave policy" --model openai/local-model --api-base https://remote.example.com/v1 --local-only
```

Loopback OpenAI-compatible servers remain allowed under `--local-only`:

```bash
# Accepted by locality check (fails only if no server is listening locally)
docpipe-maestro ask "Summarize leave policy" --model openai/local-vllm --api-base http://127.0.0.1:8000/v1 --local-only
```

### B. Policy-Driven Ingestion Scrubbing & DPO `.audit.jsonl` Inspection

Create a sample policy file `pii_policy.json`:

```json
{
  "types": {
    "US_SSN": "block",
    "CREDIT_CARD": "block",
    "EMAIL_ADDRESS": "tokenize",
    "ES_DNI": "tokenize",
    "IBAN_CODE": "redact",
    "PHONE_NUMBER": "redact",
    "IP_ADDRESS": "redact"
  },
  "min_confidence": 0.6,
  "languages": ["en", "es"],
  "egress": "redact",
  "token_salt_env": "DOCPIPE_PII_SALT"
}
```

Verify ingestion behavior & audit guarantees:
1. Run `DOCPIPE_PII_SALT=test-salt docpipe-maestro ingest <redacted-doc> --pii-policy pii_policy.json --collection pii_demo`.
2. Inspect `.docpipe/manifests/` permissions (`stat -c '%a' .docpipe/manifests` -> `700` on POSIX) and inspect `.docpipe/manifests/pii_demo.audit.jsonl`: verify valid JSON lines with `collection`, `source`, `doc_version`, `threshold`, `entity_counts`, `actions`, `blocked: false`, and **zero raw PII values**.
3. Run ingestion on a synthetic document containing a `US_SSN` -> confirm exit status `1`, error message names only source & `US_SSN` (zero digits), `.docpipe/manifests/pii_demo.audit.jsonl` records `"blocked": true`, and collection chunk count remains unchanged.
