"""Phase 2 optional grounded generation powered by litellm."""

from __future__ import annotations

from typing import Any

from docpipe_maestro.config import DEFAULT_GENERATION_MODEL
from docpipe_maestro.types import DocpipeError, MissingCredentialError

EMPTY_CONTEXT_REFUSAL = "Not found in the provided context."


def _is_auth_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "auth" in name
        or "api_key" in msg
        or "apikey" in msg
        or "credentials" in msg
        or "unauthorized" in msg
    )


def answer(
    prompt: str,
    *,
    model: str = DEFAULT_GENERATION_MODEL,
    api_base: str | None = None,
    has_context: bool = True,
) -> str:
    """Generate a grounded answer from a constructed prompt via provider/model string."""
    if not has_context:
        return EMPTY_CONTEXT_REFUSAL

    import litellm

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if api_base is not None:
        kwargs["api_base"] = api_base

    try:
        response = litellm.completion(**kwargs)
    except Exception as exc:
        if _is_auth_error(exc):
            raise MissingCredentialError(
                f"Missing or invalid provider credentials for model {model!r}. "
                "Set the provider's environment variable and retry."
            ) from None
        raise DocpipeError(
            f"Generation request failed for model {model!r}: {type(exc).__name__}"
        ) from exc

    choices = response["choices"] if isinstance(response, dict) else response.choices
    content = choices[0].message.content
    return str(content).strip() if content is not None else ""
