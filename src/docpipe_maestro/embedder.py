"""Shared provider-agnostic embedding adapter powered by litellm."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from docpipe_maestro.types import DocpipeError, MissingCredentialError


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


def embed_texts(
    texts: Sequence[str],
    *,
    model: str,
    batch_size: int = 64,
    api_base: str | None = None,
) -> list[list[float]]:
    """Embed a sequence of texts in batches using a provider/model string."""
    if not texts:
        return []

    import litellm

    vectors: list[list[float]] = []
    expected_dim: int | None = None

    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        kwargs: dict[str, Any] = {"model": model, "input": batch}
        if api_base is not None:
            kwargs["api_base"] = api_base
        try:
            response = litellm.embedding(**kwargs)
        except Exception as exc:
            if _is_auth_error(exc):
                raise MissingCredentialError(
                    f"Missing or invalid provider credentials for embedding model {model!r}. "
                    "Set the provider's environment variable and retry."
                ) from None
            raise DocpipeError(
                f"Embedding request failed for model {model!r}: {type(exc).__name__}"
            ) from exc

        data = response["data"] if isinstance(response, dict) else response.data
        sorted_items = sorted(data, key=lambda item: int(item["index"]))
        for item in sorted_items:
            vec = [float(x) for x in item["embedding"]]
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
    """Embed a single query string using the specified provider/model."""
    result = embed_texts([text], model=model, batch_size=1, api_base=api_base)
    return result[0]
