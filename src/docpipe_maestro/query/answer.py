"""Phase 2 optional grounded generation powered by litellm."""

from __future__ import annotations

from typing import Any

from docpipe_maestro.config import DEFAULT_GENERATION_MODEL
from docpipe_maestro.embedder import (
    DEFAULT_REQUEST_TIMEOUT,
    prepare_litellm,
    raise_litellm_error,
    validate_api_base,
)

EMPTY_CONTEXT_REFUSAL = "Not found in the provided context."


def answer(
    prompt: str,
    *,
    model: str = DEFAULT_GENERATION_MODEL,
    api_base: str | None = None,
    has_context: bool = True,
) -> str:
    """Generate a grounded answer from a constructed prompt via LiteLLM.

    Args:
        prompt: Grounded prompt string built by ``build_prompt()``.
        model: LiteLLM ``provider/model`` identifier (e.g., ``"ollama/llama3.2"``
            or ``"openai/gpt-4o-mini"``). Credentials are read from environment
            variables by LiteLLM.
        api_base: Optional custom base URL for OpenAI-compatible endpoints.
        has_context: When ``False``, immediately returns ``EMPTY_CONTEXT_REFUSAL``
            without invoking the language model.

    Returns:
        Stripped LLM response text, or ``EMPTY_CONTEXT_REFUSAL`` if
        ``has_context`` is ``False``.

    Raises:
        MissingCredentialError: If the provider rejects missing/invalid API keys.
        DocpipeError: If the completion request fails for any other reason.
    """
    if not has_context:
        return EMPTY_CONTEXT_REFUSAL

    validated_base = validate_api_base(api_base)
    litellm = prepare_litellm()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": DEFAULT_REQUEST_TIMEOUT,
    }
    if validated_base is not None:
        kwargs["api_base"] = validated_base

    try:
        response = litellm.completion(**kwargs)
    except Exception as exc:
        raise_litellm_error(exc, operation="generation", model=model)

    choices = response["choices"] if isinstance(response, dict) else response.choices
    content = choices[0].message.content
    return str(content).strip() if content is not None else ""
