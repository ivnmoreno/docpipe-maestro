"""Shared provider-agnostic embedding adapter powered by litellm."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn
from urllib.parse import urlparse

from docpipe_maestro.types import DocpipeError, MissingCredentialError

DEFAULT_REQUEST_TIMEOUT = 120.0
_SECRET_PATTERN_RE = re.compile(
    r"(?:://[^/\s:@]+:[^/\s@]+@|\bsk-[A-Za-z0-9_-]{8,}|\bgsk_[A-Za-z0-9_-]{8,}|\bBearer\s+\S+)",
    re.IGNORECASE,
)


def _item_field(item: Any, key: str) -> Any:
    """Read an embedding item field whether LiteLLM returns a dict or object."""
    return item[key] if isinstance(item, Mapping) else getattr(item, key)


def _is_auth_error(exc: Exception) -> bool:
    """Heuristically classify credential/authentication errors without inspecting secrets."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "auth" in name
        or "api_key" in msg
        or "apikey" in msg
        or "credentials" in msg
        or "unauthorized" in msg
    )


def _contains_secret_data(exc: Exception) -> bool:
    """Detect whether an exception message embeds URL credentials or token substrings."""
    return bool(_SECRET_PATTERN_RE.search(str(exc)))


def validate_api_base(api_base: str | None) -> str | None:
    """Ensure optional custom endpoint URLs use an explicit http or https scheme."""
    if api_base is None:
        return None
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DocpipeError(
            f"Invalid api_base URL {api_base!r}: must start with http:// or https://"
        )
    return api_base


def prepare_litellm() -> Any:
    """Import LiteLLM with bundled local cost map enabled by default for air-gapped safety."""
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    import litellm

    return litellm


def raise_litellm_error(exc: Exception, *, operation: str, model: str) -> NoReturn:
    """Convert LiteLLM failures into typed ``DocpipeError`` without leaking credentials."""
    if _is_auth_error(exc):
        raise MissingCredentialError(
            f"Missing or invalid provider credentials for {operation} model {model!r}. "
            "Set the provider's environment variable and retry."
        ) from None
    if _contains_secret_data(exc):
        raise DocpipeError(
            f"{operation.capitalize()} request failed for model {model!r}: {type(exc).__name__}"
        ) from None
    raise DocpipeError(
        f"{operation.capitalize()} request failed for model {model!r}: {type(exc).__name__}"
    ) from exc


def embed_texts(
    texts: Sequence[str],
    *,
    model: str,
    batch_size: int = 64,
    api_base: str | None = None,
) -> list[list[float]]:
    """Embed a sequence of texts in batches using a ``provider/model`` string.

    Args:
        texts: Ordered input strings to embed. Empty sequence returns ``[]``.
        model: LiteLLM provider/model identifier (e.g., ``"ollama/nomic-embed-text"``).
        batch_size: Maximum inputs sent per ``litellm.embedding`` request.
        api_base: Optional base URL override for self-hosted or proxy endpoints.

    Returns:
        Dense float vectors aligned 1-to-1 with ``texts`` and verified for
        uniform dimensionality across batches.

    Raises:
        MissingCredentialError: If the provider reports missing/invalid credentials.
        DocpipeError: If the provider call fails, returns an empty vector, or
            returns inconsistent vector dimensions across items.
    """
    if not texts:
        return []

    validated_base = validate_api_base(api_base)
    litellm = prepare_litellm()

    vectors: list[list[float]] = []
    expected_dim: int | None = None

    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        kwargs: dict[str, Any] = {
            "model": model,
            "input": batch,
            "timeout": DEFAULT_REQUEST_TIMEOUT,
        }
        if validated_base is not None:
            kwargs["api_base"] = validated_base
        try:
            response = litellm.embedding(**kwargs)
        except Exception as exc:
            raise_litellm_error(exc, operation="embedding", model=model)

        data = response["data"] if isinstance(response, dict) else response.data
        sorted_items = sorted(data, key=lambda item: int(_item_field(item, "index")))
        for item in sorted_items:
            vec = [float(x) for x in _item_field(item, "embedding")]
            if not vec:
                raise DocpipeError(f"Empty embedding vector returned by {model!r}")
            if expected_dim is None:
                expected_dim = len(vec)
            elif len(vec) != expected_dim:
                raise DocpipeError(
                    f"Inconsistent embedding dimension from {model!r}: "
                    f"expected {expected_dim}, got {len(vec)}"
                )
            vectors.append(vec)

    return vectors


def embed_query(
    text: str,
    *,
    model: str,
    api_base: str | None = None,
) -> list[float]:
    """Embed a single search query using the specified ``provider/model`` string.

    Args:
        text: User query text to embed.
        model: LiteLLM provider/model identifier matching the collection lock.
        api_base: Optional OpenAI-compatible or custom endpoint URL.

    Returns:
        Single dense embedding vector for ``text``.
    """
    result = embed_texts([text], model=model, batch_size=1, api_base=api_base)
    return result[0]
