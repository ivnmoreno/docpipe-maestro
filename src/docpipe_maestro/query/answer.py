"""Phase 2 optional grounded generation powered by litellm."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from docpipe_maestro.config import DEFAULT_GENERATION_MODEL
from docpipe_maestro.embedder import (
    DEFAULT_REQUEST_TIMEOUT,
    _item_field,
    prepare_litellm,
    raise_litellm_error,
    validate_api_base,
)
from docpipe_maestro.types import DocpipeError

EMPTY_CONTEXT_REFUSAL = "Not found in the provided context."

_RESERVED_MODEL_KWARGS = frozenset(
    {
        "model",
        "messages",
        "prompt",
        "api_base",
        "base_url",
        "api_key",
        "temperature",
        "max_tokens",
        "timeout",
        "num_retries",
    }
)


def _validate_finite_number(value: Any, *, name: str, minimum: float, inclusive: bool) -> float:
    """Validate that a generation float/int setting is finite and within bounds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DocpipeError(f"Invalid {name} value {value!r}: expected numeric value.")
    num = float(value)
    out_of_bounds = num < minimum if inclusive else num <= minimum
    if not math.isfinite(num) or out_of_bounds:
        op = ">=" if inclusive else ">"
        raise DocpipeError(f"Invalid {name} value {value!r}: must be finite and {op} {minimum}.")
    return num


def _validate_generation_params(
    *,
    temperature: float | None,
    max_tokens: int | None,
    timeout: float,
    model_kwargs: Mapping[str, Any] | None,
) -> tuple[float | None, int | None, float, dict[str, Any]]:
    """Validate generation controls and guard against reserved pass-through overrides."""
    valid_timeout = _validate_finite_number(timeout, name="timeout", minimum=0.0, inclusive=False)
    valid_temp = (
        _validate_finite_number(temperature, name="temperature", minimum=0.0, inclusive=True)
        if temperature is not None
        else None
    )
    valid_max_tokens: int | None = None
    if max_tokens is not None:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise DocpipeError(f"Invalid max_tokens value {max_tokens!r}: must be an integer >= 1.")
        valid_max_tokens = max_tokens

    extra: dict[str, Any] = {}
    if model_kwargs is not None:
        if not isinstance(model_kwargs, Mapping):
            raise DocpipeError("Invalid model_kwargs: expected mapping of option names to values.")
        conflicts = sorted(key for key in model_kwargs if str(key) in _RESERVED_MODEL_KWARGS)
        if conflicts:
            joined = ", ".join(conflicts)
            raise DocpipeError(
                f"Reserved or duplicate parameter(s) not allowed in model_kwargs: {joined}"
            )
        extra = {str(k): v for k, v in model_kwargs.items()}

    return valid_temp, valid_max_tokens, valid_timeout, extra


def _normalize_messages(prompt: str | Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Normalize a string prompt or structured chat sequence into ChatML message dicts."""
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    if isinstance(prompt, (bytes, bytearray)) or not isinstance(prompt, Sequence):
        raise DocpipeError("Invalid prompt: expected a string or a sequence of message mappings.")
    if not prompt:
        raise DocpipeError("Invalid prompt: message sequence must not be empty.")

    normalized: list[dict[str, str]] = []
    for idx, entry in enumerate(prompt):
        if not isinstance(entry, Mapping):
            raise DocpipeError(
                f"Invalid prompt message at index {idx}: expected a dict with 'role' and 'content'."
            )
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(role, str) or not role.strip():
            raise DocpipeError(
                f"Invalid prompt message at index {idx}: 'role' must be a non-empty string."
            )
        if not isinstance(content, str):
            raise DocpipeError(
                f"Invalid prompt message at index {idx}: 'content' must be a string."
            )
        normalized.append({"role": role, "content": content})
    return normalized


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
) -> str:
    """Generate a grounded answer from a prompt string or role-separated messages.

    Args:
        prompt: Grounded prompt string built by ``build_prompt()`` or a
            role-separated message sequence built by ``build_chat_messages()``.
        model: LiteLLM ``provider/model`` identifier (e.g., ``"ollama/llama3.2"``,
            ``"groq/llama-3.3-70b-versatile"``, or ``"together_ai/..."``).
            Credentials are read exclusively from environment variables.
        api_base: Optional custom base URL for OpenAI-compatible endpoints.
        has_context: When ``False``, immediately returns ``EMPTY_CONTEXT_REFUSAL``
            without invoking the language model.
        temperature: Optional sampling temperature (``>= 0.0``). Omitted from
            provider requests when ``None`` for reasoning-model compatibility.
        max_tokens: Optional maximum completion tokens (``>= 1``). Omitted when ``None``.
        timeout: Completion request timeout in seconds (``> 0.0``).
        model_kwargs: Optional extra provider generation parameters (must not
            redefine reserved or first-class controls).

    Returns:
        Stripped LLM response text, or ``EMPTY_CONTEXT_REFUSAL`` if
        ``has_context`` is ``False``.

    Raises:
        MissingCredentialError: If the provider rejects missing/invalid API keys.
        DocpipeError: If validation fails or the completion request fails.
    """
    messages = _normalize_messages(prompt)
    valid_temp, valid_max_tokens, valid_timeout, extra_kwargs = _validate_generation_params(
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        model_kwargs=model_kwargs,
    )

    if not has_context:
        return EMPTY_CONTEXT_REFUSAL

    validated_base = validate_api_base(api_base)
    litellm = prepare_litellm()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "timeout": valid_timeout,
        "num_retries": 0,
    }
    if valid_temp is not None:
        kwargs["temperature"] = valid_temp
    if valid_max_tokens is not None:
        kwargs["max_tokens"] = valid_max_tokens
    if validated_base is not None:
        kwargs["api_base"] = validated_base
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    try:
        response = litellm.completion(**kwargs)
    except Exception as exc:
        raise_litellm_error(exc, operation="generation", model=model)

    return _extract_completion_text(response, model=model)


def _extract_completion_text(response: Any, *, model: str) -> str:
    """Validate and extract non-empty answer text from a LiteLLM completion response."""
    choices = _item_field(response, "choices", None)
    if not choices:
        raise DocpipeError(f"Generation model {model!r} returned no completion choices.")
    message = _item_field(choices[0], "message", None)
    if message is None:
        raise DocpipeError(f"Generation model {model!r} returned an empty choice message.")
    refusal = _item_field(message, "refusal", None)
    if refusal:
        raise DocpipeError(
            f"Generation model {model!r} refused the request: {str(refusal).strip()}"
        )
    content = _item_field(message, "content", None)
    text = str(content).strip() if content is not None else ""
    if not text:
        raise DocpipeError(f"Generation model {model!r} returned an empty response.")
    return text
