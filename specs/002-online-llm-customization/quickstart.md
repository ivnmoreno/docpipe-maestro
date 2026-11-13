# Validation Quickstart: Online LLM Answer Customization

**Feature**: `002-online-llm-customization` | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

This guide defines end-to-end validation steps to verify local-first defaults, online provider customization, `.env` credential hygiene, security guardrails, and quality gates once implementation is complete.

---

## 1. Local Credential Setup (Safe Workflow)

```bash
cp .env.example .env
chmod 600 .env
# Verify version control ignores .env and tracks .env.example
git status --ignored
```

Expected: `.env` appears under ignored files (never staged or tracked); `.env.example` contains only placeholder values.

---

## 2. Offline Deterministic Test Suite & Static Gates (CI Gate)

All automated tests run with zero outbound network calls:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/
uv run mypy src tests
uv run pytest -m reverse -v
LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov
```

Verify key test suites cover the contracts in [contracts/python-api.md](contracts/python-api.md) and [contracts/cli.md](contracts/cli.md):
- `tests/test_prompts_answer.py`: `build_chat_messages()` role separation, `answer()` accepting `str` and message lists, forwarding `temperature=0.0` / `max_tokens` / `timeout` / `model_kwargs`, omitting `temperature` and `max_tokens` when `None`, rejecting reserved keys in `model_kwargs`, `num_retries=0`, and safe error handling on empty choices / `refusal` / blank text.
- `tests/test_security_hardening.py`: loopback `http://` (`localhost`, `127.0.0.1`, `[::1]`) allowed while non-loopback `http://` fails pre-flight; redaction of `sk-`, `gsk_`, `AIza`, `Bearer`, `://user:pass@`, `?key=`/`?api_key=`/`?token=`, and opaque runtime env secrets (Together.ai / Azure); HTTP 401/403 → `MissingCredentialError` and HTTP 429 fail-fast `DocpipeError`.
- `tests/test_cli.py`: `--config` dir `.env` loading vs CWD `.env` loading (no parent traversal, shell env precedence), `--temperature` / `--max-tokens` / `--timeout` / `--api-base` flag parsing and `CLI > TOML > code defaults` precedence, and structured message dispatch from `ask`.

---

## 3. Manual Smoke Scenarios (Optional Live Provider Check)

Ensure a collection has been ingested locally first (`docpipe-maestro ingest ...`):

1. **Local-first default (offline, zero keys needed)**:
   ```bash
   uv run docpipe-maestro ask "What is the leave policy for new hires?"
   ```
2. **Groq serverless deterministic query (reads `.env` automatically)**:
   ```bash
   uv run docpipe-maestro ask "What is the leave policy?" \
     --model groq/llama-3.3-70b-versatile \
     --temperature 0.0 \
     --max-tokens 512 \
     --timeout 20.0
   ```
3. **Together.ai query via `docpipe.toml` + CLI override**:
   ```bash
   # Set model = "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo" and temperature = 0.5 in docpipe.toml
   uv run docpipe-maestro ask "What is the leave policy?" --config docpipe.toml --temperature 0.1
   ```
   Expected: `--temperature 0.1` overrides TOML `0.5`, using `.env` located alongside `docpipe.toml` (when present) without mutating Phase 1 data.
