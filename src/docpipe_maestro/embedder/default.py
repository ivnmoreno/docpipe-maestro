"""Default provider-agnostic LiteLLM embedder strategy under ``EMBEDDERS['default']``."""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn
from urllib.parse import urlparse

from docpipe_maestro.embedder import DEFAULT_REQUEST_TIMEOUT, EMBEDDERS
from docpipe_maestro.types import DocpipeError, MissingCredentialError

_DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434"
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


def _validate_embedding_batch(
    raw_vectors: Sequence[Sequence[Any]],
    *,
    model: str,
    expected_dim: int | None,
) -> tuple[list[list[float]], int | None]:
    """Convert raw embedding arrays to floats and verify uniform dimensionality."""
    batch_vectors: list[list[float]] = []
    for raw_vec in raw_vectors:
        vec = [float(x) for x in raw_vec]
        if not vec:
            raise DocpipeError(f"Empty embedding vector returned by {model!r}")
        if expected_dim is None:
            expected_dim = len(vec)
        elif len(vec) != expected_dim:
            raise DocpipeError(
                f"Inconsistent embedding dimension from {model!r}: "
                f"expected {expected_dim}, got {len(vec)}"
            )
        batch_vectors.append(vec)
    return batch_vectors, expected_dim


def _embed_ollama_direct(
    texts: Sequence[str],
    *,
    model: str,
    batch_size: int,
    api_base: str | None,
) -> list[list[float]]:
    """Call Ollama ``/api/embed`` directly over HTTP(S), skipping heavy LiteLLM imports."""
    raw_base = (
        api_base
        if api_base is not None
        else (os.environ.get("OLLAMA_API_BASE") or _DEFAULT_OLLAMA_BASE)
    )
    validated_base = validate_api_base(raw_base.strip()) or _DEFAULT_OLLAMA_BASE
    parsed = urlparse(validated_base)
    host = parsed.hostname or "127.0.0.1"
    conn_cls = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    endpoint = f"{parsed.path.rstrip('/')}/api/embed"
    ollama_model = model.removeprefix("ollama/")

    vectors: list[list[float]] = []
    expected_dim: int | None = None
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        payload = json.dumps({"model": ollama_model, "input": batch}).encode("utf-8")
        conn = conn_cls(host, parsed.port, timeout=DEFAULT_REQUEST_TIMEOUT)
        try:
            conn.request(
                "POST", endpoint, body=payload, headers={"Content-Type": "application/json"}
            )
            resp = conn.getresponse()
            raw_body = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                if resp.status == 404 and "page not found" in raw_body.lower():
                    raise LookupError("legacy_ollama_fallback")
                raise RuntimeError(f"HTTP {resp.status}: {raw_body}")
            data = json.loads(raw_body)
        except LookupError:
            raise
        except Exception as exc:
            raise_litellm_error(exc, operation="embedding", model=model)
        finally:
            conn.close()

        raw_embeddings = data.get("embeddings") if isinstance(data, Mapping) else None
        if not isinstance(raw_embeddings, Sequence) or len(raw_embeddings) != len(batch):
            raise DocpipeError(f"Unexpected embedding response shape from {model!r}")
        batch_vecs, expected_dim = _validate_embedding_batch(
            raw_embeddings, model=model, expected_dim=expected_dim
        )
        vectors.extend(batch_vecs)

    return vectors


def embed_texts(
    texts: Sequence[str],
    *,
    model: str,
    batch_size: int = 64,
    api_base: str | None = None,
) -> list[list[float]]:
    """Embed a sequence of texts in batches using a ``provider/model`` string."""
    if not texts:
        return []

    validated_base = validate_api_base(api_base)
    if model.startswith("ollama/") and "litellm" not in sys.modules:
        try:
            return _embed_ollama_direct(
                texts,
                model=model,
                batch_size=batch_size,
                api_base=validated_base,
            )
        except LookupError:
            pass

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
        raw_vecs = [_item_field(item, "embedding") for item in sorted_items]
        batch_vecs, expected_dim = _validate_embedding_batch(
            raw_vecs, model=model, expected_dim=expected_dim
        )
        vectors.extend(batch_vecs)

    return vectors


def embed_query(
    text: str,
    *,
    model: str,
    api_base: str | None = None,
) -> list[float]:
    """Embed a single search query using the specified ``provider/model`` string."""
    result = embed_texts([text], model=model, batch_size=1, api_base=api_base)
    return result[0]


@EMBEDDERS.register("default")
class LiteLLMEmbedder:
    """Built-in LiteLLM + Ollama-direct embedding backend."""

    name: str = "default"

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        api_base: str | None = None,
    ) -> list[list[float]]:
        """Embed a sequence of child chunk texts aligned 1-to-1 with inputs."""
        return embed_texts(texts, model=model, api_base=api_base)

    def embed_query(
        self,
        text: str,
        *,
        model: str,
        api_base: str | None = None,
    ) -> list[float]:
        """Embed a single retrieval query string."""
        return embed_query(text, model=model, api_base=api_base)
