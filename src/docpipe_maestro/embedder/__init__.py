"""Shared embedder registry and lazy compatibility exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro._stages import Embedder

if TYPE_CHECKING:
    from docpipe_maestro.embedder.default import (
        LiteLLMEmbedder,
        _is_loopback_host,
        _item_field,
        embed_query,
        embed_texts,
        prepare_litellm,
        raise_litellm_error,
        validate_api_base,
    )

DEFAULT_REQUEST_TIMEOUT = 120.0

EMBEDDERS: Registry[Embedder] = Registry("embedder")
register_embedder = EMBEDDERS.register

EMBEDDERS.register_lazy("default", "docpipe_maestro.embedder.default", "LiteLLMEmbedder")

__all__ = [
    "DEFAULT_REQUEST_TIMEOUT",
    "EMBEDDERS",
    "LiteLLMEmbedder",
    "_is_loopback_host",
    "_item_field",
    "embed_query",
    "embed_texts",
    "prepare_litellm",
    "raise_litellm_error",
    "register_embedder",
    "validate_api_base",
]

_LAZY_EMBEDDER_EXPORTS = frozenset(
    {
        "LiteLLMEmbedder",
        "_is_loopback_host",
        "_item_field",
        "embed_query",
        "embed_texts",
        "prepare_litellm",
        "raise_litellm_error",
        "validate_api_base",
    }
)


def __getattr__(name: str) -> Any:
    """Lazily expose embedder implementation and helpers without loading ``litellm``."""
    if name in _LAZY_EMBEDDER_EXPORTS:
        mod = importlib.import_module("docpipe_maestro.embedder.default")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
