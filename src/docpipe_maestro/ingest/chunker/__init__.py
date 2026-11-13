"""Phase 1 chunker registry and compatibility re-exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.ingest.stages import Chunker

if TYPE_CHECKING:
    from docpipe_maestro.ingest.chunker.default import (
        DefaultChunker,
        chunk_document,
        estimate_tokens,
    )

CHUNKERS: Registry[Chunker] = Registry("chunker")
register_chunker = CHUNKERS.register

CHUNKERS.register_lazy("default", "docpipe_maestro.ingest.chunker.default", "DefaultChunker")

__all__ = [
    "CHUNKERS",
    "DefaultChunker",
    "chunk_document",
    "estimate_tokens",
    "register_chunker",
]

_LAZY_CHUNKER_EXPORTS = frozenset({"DefaultChunker", "chunk_document", "estimate_tokens"})


def __getattr__(name: str) -> Any:
    """Lazily expose built-in chunking helpers without eager materialization."""
    if name in _LAZY_CHUNKER_EXPORTS:
        mod = importlib.import_module("docpipe_maestro.ingest.chunker.default")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
