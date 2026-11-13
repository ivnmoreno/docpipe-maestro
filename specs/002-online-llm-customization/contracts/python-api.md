# Python Library API Contract Extensions

**Feature**: `002-online-llm-customization` | **Package**: `docpipe_maestro`

All new and extended capabilities remain reachable through the public API surface exported from `docpipe_maestro.__init__`, preserving Constitution Principles I, II, III, and VI. Phase 1 functions (`ingest`, `sync`, `remove`, `status`, `reindex`) and `retrieve()` remain unchanged.

---

## 1. Public Exports (`docpipe_maestro.__init__`)

- Re-export `build_chat_messages` directly alongside `build_prompt` (`__all__` updated monotonically).
- Keep `answer` lazily loaded via `__getattr__` so optional generation import errors still raise `MissingExtraError`.

---

## 2. Prompt Construction (`docpipe_maestro.query.prompts`)

### `build_chat_messages(...) -> list[dict[str, str]]`

```python
def build_chat_messages(
    question: str,
    sections: Sequence[RetrievedChunk],
) -> list[dict[str, str]]: ...
```

- Pure, deterministic function (zero disk I/O, zero network calls).
- Reuses shared internal `_format_context_block(sections)` with `build_prompt()` so source headers (`Source`, `Section`, optional `Clause`, optional `Page`), section ordering, and `---` separators match identically.
- Returns a 2-message list:
  1. `{"role": "system", "content": _SYSTEM_INSTRUCTIONS}`
  2. `{"role": "user", "content": f"## Context\n\n{context_block}\n\n## Question\n\n{question}"}`
- `build_prompt(question, sections) -> str` remains 100% backward-compatible.

---

## 3. Extended Answer Generation (`docpipe_maestro.query.answer`)

### `answer(...) -> str`

```python
def answer(
    prompt: str | Sequence[Mapping[str, str]],
    *,
    model: str = DEFAULT_GENERATION_MODEL,
    api_base: str | None = None,
    has_context: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    model_kwargs: Mapping[str, Any] | None = None,
) -> str: ...
```

- **Empty Context Short-Circuit**: When `has_context=False`, returns `EMPTY_CONTEXT_REFUSAL` (`"Not found in the provided context."`) immediately with zero outbound LLM requests.
- **Prompt Normalization**:
  - `str` input → normalized to `[{"role": "user", "content": prompt}]` (backward compatible).
  - Sequence of mappings → validated non-empty, each element carrying non-empty string `"role"` and string `"content"`. Invalid message shapes raise `DocpipeError`.
- **Parameter Validation & Omission Safety**:
  - `timeout`: must be finite numeric `> 0.0` (bool rejected). Defaults to `120.0` (`DEFAULT_REQUEST_TIMEOUT`).
  - `temperature`: when `None`, `"temperature"` is **omitted** from provider completion kwargs (OpenAI o1/o3 compatibility). When non-`None`, must be finite numeric `>= 0.0` (bool rejected) and is explicitly forwarded (including `0.0`).
  - `max_tokens`: when `None`, `"max_tokens"` is **omitted**. When non-`None`, must be `int >= 1` (bool rejected) and is forwarded.
  - `model_kwargs`: optional provider pass-through options (`top_p`, `frequency_penalty`, etc.). Any reserved or conflicting key in `{"model", "messages", "prompt", "api_base", "base_url", "api_key", "temperature", "max_tokens", "timeout", "num_retries"}` raises `DocpipeError` immediately.
  - Calls `litellm.completion(..., num_retries=0)` so rate-limited calls fail fast without hidden backoff delays.
- **Response Guardrails**:
  - Empty/missing `choices` → `DocpipeError(f"Generation provider {model!r} returned an empty response (possible content filter).")`.
  - Non-empty `message.refusal` → `DocpipeError(f"Model refused generation: ...")` (with secret scrubbing).
  - `message.content` is `None` or whitespace-only → `DocpipeError(f"Generation provider {model!r} returned empty completion text (possible content filter or token exhaustion).")`.
  - Otherwise returns `str(content).strip()`.

---

## 4. Transport Security & Error Sanitization (`docpipe_maestro.embedder`)

### `validate_api_base(api_base: str | None) -> str | None`

- `None` → returns `None`.
- Invalid scheme (`not in {"http", "https"}`) or empty `netloc` → raises `DocpipeError(f"Invalid api_base URL ...")`.
- Plaintext `http://` targeting non-loopback host → raises `DocpipeError("Insecure remote api_base URL: must use https:// for external endpoints")`.
- Loopback hosts (`localhost`, `127.0.0.0/8`, `::1`) permitted over `http://`; all external endpoints require `https://`.

### Secret Redaction & Failure Classification

- `_SECRET_PATTERN_RE` matches URL basic-auth (`://user:pass@`), OpenAI/Anthropic (`sk-...`), Groq (`gsk_...`), Google (`AIza...`), authorization tokens (`Bearer ...`), and URL query secrets (`?api_key=`, `?key=`, `?token=`).
- Active environment secrets (`*_API_KEY`, `*_TOKEN`, `*_SECRET` of length `>= 8`) are additionally detected in exception strings and scrubbed/suppressed (`from None`) so prefixless keys (Together.ai, Azure) cannot leak.
- HTTP `401` / `403` / `AuthenticationError` / `PermissionDeniedError` → raises `MissingCredentialError` (`from None`).
- HTTP `429` / `RateLimitError` → raises `DocpipeError(f"{operation.capitalize()} request failed for model {model!r}: Rate limit or quota exceeded (HTTP 429)")` (`from None` when secrets detected).
