# Data Model: Online LLM Answer Customization

**Feature**: `002-online-llm-customization` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

This feature belongs strictly to Phase 2 (Online Read-Only Retrieval & Generation) and `.cli`/environment configuration helpers. Phase 1 storage schemas (`Chunk`, `ChunkMetadata`, `CollectionManifest`, ChromaDB collections) remain unchanged and read-only during query execution.

---

## 1. Entities & Runtime Structures

### 1.1. GenerationSettings (Conceptual Request Parameters)

Resolved parameters governing a single Phase 2 `answer()` call, constructed via CLI precedence (`CLI flags > TOML defaults > built-in defaults`) or passed explicitly in Python.

| Field | Type | Default | Constraints & Validation Rules |
|---|---|---|---|
| `prompt` | `str \| Sequence[Mapping[str, str]]` | *(required)* | String wrapped as single `user` message; sequence validated non-empty with string `"role"` and `"content"` keys |
| `model` | `str` | `"ollama/llama3.2"` | Non-empty `provider/model` string delegated to LiteLLM |
| `api_base` | `str \| None` | `None` | Validated by `validate_api_base()`: HTTPS required for remote hosts; HTTP permitted strictly on local loopback |
| `has_context` | `bool` | `True` | When `False`, short-circuits immediately with `EMPTY_CONTEXT_REFUSAL` before validation/network calls? *(Note: `api_base` / param validation runs consistently or on online calls — validate params upfront for fail-fast safety, or validate before completion call)* |
| `temperature` | `float \| None` | `None` | Finite float `>= 0.0` (not `bool`). Forwarded when `is not None` (preserving `0.0`); omitted completely when `None` |
| `max_tokens` | `int \| None` | `None` | Integer `>= 1` (not `bool`). Forwarded when `is not None`; omitted completely when `None` |
| `timeout` | `float` | `120.0` (`DEFAULT_REQUEST_TIMEOUT`) | Finite positive float `> 0.0` (not `bool`). Always forwarded to completion call |
| `model_kwargs` | `Mapping[str, Any] \| None` | `None` | Arbitrary provider options (e.g., `top_p`, `frequency_penalty`); MUST NOT contain reserved/conflicting keys (`model`, `messages`, `prompt`, `api_base`, `base_url`, `api_key`, `temperature`, `max_tokens`, `timeout`, `num_retries`) |

### 1.2. ChatMessage (`TypedDict` / Mapping Shape)

Standard role-separated ChatML message item returned by `build_chat_messages(question, sections)`.

| Field | Type | Values / Rules |
|---|---|---|
| `role` | `str` | `"system"` (grounding instructions) or `"user"` (context block + question); programmatic callers may supply valid role strings |
| `content` | `str` | Non-empty prompt content (`system`: `_SYSTEM_INSTRUCTIONS`; `user`: `"## Context\n\n{context_block}\n\n## Question\n\n{question}"`) |

### 1.3. ProjectTomlConfig (`docpipe.toml` Ask/Generation Extensions)

Parsed exclusively inside `src/docpipe_maestro/cli.py:_load_toml_config()` (never read by library modules).

| Key | Expected TOML Type | CLI Fallback | Validation Rule |
|---|---|---|---|
| `model` | `str` | `DEFAULT_GENERATION_MODEL` (`"ollama/llama3.2"`) | Reject non-string via `_cfg_str` |
| `api_base` | `str \| None` | `None` | Optional; reject non-string via `_cfg_opt_str` |
| `temperature` | `int \| float \| None` | `None` | Optional finite float `>= 0.0`; reject `bool`/non-number via `_cfg_opt_float` |
| `max_tokens` | `int \| None` | `None` | Optional int `>= 1`; reject `bool`/`float`/non-int via `_cfg_opt_int` |
| `timeout` | `int \| float` | `DEFAULT_REQUEST_TIMEOUT` (`120.0`) | Optional finite float `> 0.0`; reject `bool`/non-number via `_cfg_opt_float` |

### 1.4. LocalCredentialProfile (`.env` / `.env.example`)

Key-value process environment inputs loaded optionally at CLI startup (`override=False`):
- Discovered at `Path(config).parent / ".env"` if `--config` is passed, or `Path.cwd() / ".env"` otherwise (no upward parent traversal).
- Tracked template `.env.example` documents non-secret placeholders (`GROQ_API_KEY`, `TOGETHERAI_API_KEY` / `TOGETHER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`, `LITELLM_LOCAL_MODEL_COST_MAP`).
- Ignored cleanly by `.gitignore` (`*.env`, `*.env.*`, `.env.production`, `.env.development`).

---

## 2. State & Request Validation Flows

### 2.1. Custom Endpoint URL Security Check (`validate_api_base`)

```text
api_base is None ──▶ None (use provider default)
      │
      ▼
scheme not in {"http", "https"} OR empty netloc ──▶ Raise DocpipeError("Invalid api_base URL...")
      │
      ▼
scheme == "https" ──▶ Validated URL (allowed for remote and local hosts)
      │
      ▼ (scheme == "http")
hostname == "localhost" OR ip_address(hostname).is_loopback?
   ├── Yes (127.0.0.0/8, ::1, localhost) ──▶ Validated URL (loopback dev/proxy allowed)
   └── No (remote hostname / public IP) ──▶ Raise DocpipeError("Insecure remote api_base URL: must use https:// for external endpoints")
```

### 2.2. Completion Execution & Response Safety Flow (`answer`)

```text
has_context == False?
   ├── Yes ──▶ Return EMPTY_CONTEXT_REFUSAL immediately (0 LLM calls)
   └── No  ──▶ Validate generation parameters + model_kwargs + api_base
                 │
                 ▼
         Build kwargs (model, messages, timeout, num_retries=0, optional temperature/max_tokens/api_base/model_kwargs)
                 │
                 ▼
         litellm.completion(**kwargs)
           ├── Raises Auth/401/403 ──▶ Raise MissingCredentialError (sanitized, __cause__=None)
           ├── Raises RateLimit/429 ─▶ Fail fast: Raise DocpipeError("... Rate limit or quota exceeded (HTTP 429)", sanitized)
           ├── Raises Other Error ───▶ Raise DocpipeError (scrubbed of regex + active runtime env secrets)
           └── Response returned
                 ├── choices empty/None ──────▶ Raise DocpipeError("... returned an empty response (possible content filter).")
                 ├── message.refusal present ─▶ Raise DocpipeError("Model refused generation: ...")
                 ├── content None/whitespace ─▶ Raise DocpipeError("... returned empty completion text ...")
                 └── Non-empty text ──────────▶ Return stripped answer string
```
