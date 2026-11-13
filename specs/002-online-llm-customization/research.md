# Research & Technical Decisions: Online LLM Answer Customization

**Feature**: `002-online-llm-customization` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

## Overview

All functional, security, credential-management, and failure-handling questions were resolved in [spec.md](spec.md) during `/speckit-clarify`. This document records implementation-level engineering decisions verified against the `docpipe-maestro` codebase and installed dependencies.

---

## 1. Explicit `python-dotenv` Dependency & CLI Discovery Scope

- **Decision**: Declare `python-dotenv>=1.0.0` explicitly in `pyproject.toml` `[project].dependencies`, and resolve `.env` strictly in `src/docpipe_maestro/cli.py` (`main()`) using `dotenv_path = (Path(known.config).parent if known.config else Path.cwd()) / ".env"`, calling `load_dotenv(dotenv_path=dotenv_path, override=False)` only when `dotenv_path.is_file()`.
- **Rationale**: Verified in the workspace environment that `python-dotenv 1.2.4` ships with PEP 561 `py.typed` metadata (compatible with `mypy --strict`) and is currently pulled transitively by `litellm`. Declaring it explicitly protects wheel/sdist installs from transitive dependency changes. Passing an explicit `dotenv_path` avoids `find_dotenv()` upward parent traversal (matching Clarification Q5 / `FR-007`), works identically whether installed in site-packages or run editable, respects pre-set shell environment variables (`override=False`), and preserves Constitution Principle III purity because core library modules (`answer.py`, `prompts.py`, `embedder.py`) never touch `.env` or TOML files.
- **Alternatives considered**:
  - Relying implicitly on `litellm`'s transitive dependency: fragile across `litellm` minor releases.
  - Bare `load_dotenv()` with no path argument: walks upward from the installed module path or CWD, risking accidental credential inheritance from unrelated parent directories.

---

## 2. Generation Parameter Validation, `model_kwargs` Isolation & Omission Safety

- **Decision**: Validate generation parameters upfront in `src/docpipe_maestro/query/answer.py`:
  1. `timeout`: numeric (`isinstance(timeout, (int, float))` and not `bool`), finite (`math.isfinite`), strictly `> 0.0`.
  2. `temperature`: `None` or numeric (`not bool`), finite, `>= 0.0`. Forward `"temperature"` ONLY when `temperature is not None` (preserving `0.0`).
  3. `max_tokens`: `None` or `int` (`not bool`), `>= 1`. Forward `"max_tokens"` ONLY when `max_tokens is not None`.
  4. `model_kwargs`: reject any intersection with reserved/conflicting keys `{"model", "messages", "prompt", "api_base", "base_url", "api_key", "temperature", "max_tokens", "timeout", "num_retries"}` with `DocpipeError`.
- **Rationale**: Upfront validation closes two critical safety gaps (Clarification Q1 / `FR-003`, `FR-004`): preventing a caller from bypassing `validate_api_base()` or prompt grounding via pass-through `model_kwargs` keys (`api_base`, `base_url`, `api_key`, `messages`), and preventing `"temperature"` leakage to reasoning models (e.g., `openai/o1`, `openai/o3-mini`) when `temperature=None`. Checking `is not None` ensures `temperature=0.0` is never treated as falsy.
- **Alternatives considered**:
  - Silently overwriting/dropping conflicting keys inside `model_kwargs`: hides security violations and caller configuration bugs.

---

## 3. Loopback-Aware HTTPS Enforcement (`validate_api_base`)

- **Decision**: Extend `validate_api_base(api_base: str | None)` in `src/docpipe_maestro/embedder.py` (shared by both `embedder.py` and `answer.py`):
  - Keep scheme (`http`, `https`) + non-empty `netloc` validation (`"Invalid api_base URL ..."`).
  - For `http://` URLs, inspect `parsed.hostname`: allow HTTP exclusively when `host == "localhost"` or `ipaddress.ip_address(host).is_loopback` is `True` (covers `127.0.0.1`, `127.0.0.0/8`, and IPv6 `::1` cleanly since `urlparse().hostname` strips IPv6 brackets). Any non-loopback `http://` raises `DocpipeError("Insecure remote api_base URL: must use https:// for external endpoints")`.
- **Rationale**: Uses Python stdlib `ipaddress` to cover all loopback addresses accurately without fragile string-prefix hacks, protecting API keys and document excerpts from cleartext transit (`FR-011`) while maintaining seamless local vLLM/Ollama/LiteLLM proxy workflows.
- **Alternatives considered**:
  - Checking only `hostname in {"localhost", "127.0.0.1", "::1"}`: misses valid loopback CIDR addresses such as `127.0.1.1`.

---

## 4. Dual Secret Redaction & Provider Error Classification

- **Decision**: Harden `src/docpipe_maestro/embedder.py` across three areas:
  1. **Broadened regex (`_SECRET_PATTERN_RE`)**: Match URL basic-auth (`://[^/\s:@]+:[^/\s@]+@`), OpenAI-family keys (`\bsk-[A-Za-z0-9_-]{8,}` covering `sk-ant-` and `sk-...`), Groq keys (`\bgsk_[A-Za-z0-9_-]{8,}`), Google API keys (`\bAIza[0-9A-Za-z-_]{35}`), authorization headers (`\bBearer\s+\S+`), and secret query parameters (`[?&](?:api[_-]?key|key|token)=[^&\s]+`).
  2. **Runtime secret scrubbing (`_active_env_secrets()`)**: Inspect loaded environment variables (`*_API_KEY`, `*_TOKEN`, `*_SECRET` with `len >= 8`) so prefixless keys (such as Together.ai `TOGETHER_API_KEY` / `TOGETHERAI_API_KEY` / `TOGETHER_AI_API_KEY` / `TOGETHER_AI_TOKEN` verified in LiteLLM's provider loader, or Azure keys) are detected in `_contains_secret_data()` and scrubbed from all surfaced `DocpipeError` messages (Clarification Q2 / `FR-012`).
  3. **Auth & HTTP 429 classification + zero implicit retries**: Extend `_is_auth_error()` for `PermissionDeniedError`, HTTP `401`/`403`, and `"permissiondenied"`; detect `RateLimitError` / `"ratelimit"` / `"rate_limit"` / `"429"` in `raise_litellm_error()` to emit `DocpipeError(f"{operation.capitalize()} request failed for model {model!r}: Rate limit or quota exceeded (HTTP 429)")` with `from None` when secrets are present, and pass `num_retries=0` into `litellm.completion()` so rate-limited serverless calls fail fast (Clarification Q3 / `FR-013`).
- **Rationale**: Verified in `.venv` that LiteLLM maps `RateLimitError` cleanly across OpenAI/Groq/Together and checks `TOGETHER_API_KEY`, `TOGETHER_AI_API_KEY`, `TOGETHERAI_API_KEY`, and `TOGETHER_AI_TOKEN`. Passing `num_retries=0` prevents hidden backoff waits inside the `timeout` budget while staying compatible with `tests/conftest.py`'s `**kwargs: Any` test double.
- **Alternatives considered**:
  - Regex-only secret detection: unsafe when Together.ai or Azure emit bare 32–64 char opaque keys in error strings.

---

## 5. Structured Chat Messages, Moderation Safety & Backward Compatibility

- **Decision**:
  - Extract a shared `_format_context_block(sections: Sequence[RetrievedChunk]) -> str` helper in `src/docpipe_maestro/query/prompts.py` reused by both `build_prompt()` and new `build_chat_messages() -> list[dict[str, str]]`. Re-export `build_chat_messages` in `src/docpipe_maestro/__init__.py`.
  - Update `answer()` `prompt` parameter type to `str | Sequence[Mapping[str, str]]` (normalize strings to `[{"role": "user", "content": prompt}]`; validate non-empty structured message sequences).
  - Parse completion responses safely: verify `choices` is non-empty, inspect optional `refusal` via `getattr(msg, "refusal", None)` / mapping lookup (compatible with `tests/conftest.py` `SimpleNamespace` which omits `refusal`), verify trimmed `content` is non-empty (Clarification Q4 / `FR-014`), raising descriptive `DocpipeError` in all moderation/refusal/empty-output cases.
- **Rationale**: Eliminates prompt-formatting duplication, preserves 100% compatibility for existing `build_prompt()` and `answer("...")` callers, improves system/user instruction boundary against prompt injection, and catches blank moderation/token-exhaustion responses before they reach callers.
- **Alternatives considered**:
  - Duplicating section formatting across `build_prompt()` and `build_chat_messages()`: violates code-quality DRY rules.

---

## 6. CLI Flag Parity, TOML Precedence & Air-Gapped Safety

- **Decision**:
  - Extend `src/docpipe_maestro/cli.py` with `_cfg_opt_int()` helper alongside `_cfg_opt_float()`.
  - Parse optional TOML keys `api_base`, `temperature`, `max_tokens`, and `timeout` (falling back to `DEFAULT_REQUEST_TIMEOUT = 120.0`) as `argparse` defaults on `p_ask`.
  - Add `--temperature` (`float`), `--max-tokens` (`int`), and `--timeout` (`float`) to `p_ask` alongside existing `--api-base` and `--model`.
  - Build messages via `build_chat_messages(args.question, sections)` in `ask` execution and pass resolved parameters to `answer()`.
- **Rationale**: Strictly enforces `CLI flags > TOML defaults > built-in defaults` (`FR-009`, `FR-010`) with zero boilerplate and full compatibility with existing `docpipe-maestro ask` tests (`--api-base`, `--model`). `prepare_litellm()` already sets `LITELLM_LOCAL_MODEL_COST_MAP=true` by default, and `.env.example` documents `LITELLM_LOCAL_MODEL_COST_MAP` cleanly for visibility.
