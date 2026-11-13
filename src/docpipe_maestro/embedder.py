"""Shared provider-agnostic embedding adapter powered by litellm."""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn
from urllib.parse import urlparse

from docpipe_maestro.types import DocpipeError, MissingCredentialError

DEFAULT_REQUEST_TIMEOUT = 120.0
_MISSING = object()
_SECRET_PATTERN_RE = re.compile(
    r"(?:://[^/\s:@]+:[^/\s@]+@"
    r"|\bsk-[A-Za-z0-9_-]{8,}"
    r"|\bgsk_[A-Za-z0-9_-]{8,}"
    r"|\bAIza[A-Za-z0-9_-]{8,}"
    r"|\bBearer\s+\S+"
    r"|[?&](?:api[_-]?key|key|token)=[^&\s]+)",
    re.IGNORECASE,
)
_ENV_SECRET_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
_HTTP_AUTH_STATUS_RE = re.compile(r"\b(?:401|403)\b")
_HTTP_RATE_LIMIT_STATUS_RE = re.compile(r"\b429\b")


def _item_field(item: Any, key: str, default: Any = _MISSING) -> Any:
    """Read a response field whether LiteLLM returns a dict or attribute object."""
    if isinstance(item, Mapping):
        if key in item:
            return item[key]
        if default is not _MISSING:
            return default
        raise KeyError(key)
    if default is not _MISSING:
        return getattr(item, key, default)
    return getattr(item, key)


def _active_env_secrets() -> tuple[str, ...]:
    """Collect active non-trivial secret values from environment variables."""
    return tuple(
        val
        for name, val in os.environ.items()
        if name.endswith(_ENV_SECRET_SUFFIXES) and len(val) >= 8
    )


def _is_auth_error(exc: Exception) -> bool:
    """Heuristically classify credential/authentication errors without inspecting secrets."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "auth" in name
        or "permission" in name
        or "api_key" in msg
        or "apikey" in msg
        or "credentials" in msg
        or "unauthorized" in msg
        or bool(_HTTP_AUTH_STATUS_RE.search(msg))
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect HTTP 429 or provider rate-limit exhaustion errors."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "ratelimit" in name
        or "rate_limit" in name
        or "rate limit" in msg
        or "rate_limit" in msg
        or "too many requests" in msg
        or bool(_HTTP_RATE_LIMIT_STATUS_RE.search(msg))
    )


def _contains_secret_data(exc: Exception) -> bool:
    """Detect URL credentials, token patterns, or loaded environment secrets in errors."""
    text = str(exc)
    if _SECRET_PATTERN_RE.search(text):
        return True
    return any(secret in text for secret in _active_env_secrets())


def _is_loopback_host(hostname: str | None) -> bool:
    """Return ``True`` when ``hostname`` targets ``localhost`` or a loopback IP."""
    if not hostname:
        return False
    normalized = hostname.strip().lower().rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_api_base(api_base: str | None) -> str | None:
    """Ensure custom endpoints are valid URLs and restrict plain HTTP to loopback hosts."""
    if api_base is None:
        return None
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DocpipeError(
            f"Invalid api_base URL {api_base!r}: must start with http:// or https://"
        )
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise DocpipeError("Insecure remote api_base URL: must use https:// for external endpoints")
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
    has_secret = _contains_secret_data(exc)
    if _is_rate_limit_error(exc):
        msg = (
            f"Rate limit or quota exceeded (HTTP 429) for {operation} model {model!r}. "
            "Retry later or switch provider."
        )
        if has_secret:
            raise DocpipeError(msg) from None
        raise DocpipeError(msg) from exc
    if has_secret:
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
