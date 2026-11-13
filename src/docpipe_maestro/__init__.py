"""docpipe-maestro: a minimal, provider-agnostic, structure-aware RAG pipeline.

Public surface organized around two separated execution phases:

- Phase 1 (Offline Ingestion & Corpus Lifecycle): ``ingest``, ``sync``, ``remove``,
  ``status``, and ``reindex``.
- Phase 2 (Online Read-Only Retrieval & Optional Generation): ``retrieve``,
  ``build_prompt``, and lazily loaded ``answer``.
- Shared Data Shapes & Exceptions: ``Chunk``, ``EmbeddedChunk``, ``RetrievedChunk``,
  ``SourceRecord``, ``IngestResult``, ``SyncResult``, ``CollectionStatus``, and
  ``DocpipeError`` subclasses.

Static chunking profiles (``DEFAULT``, ``POLICY``) live in ``docpipe_maestro.config``.
"""

from __future__ import annotations

import importlib
import sys
import types as _stdlib_types
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from docpipe_maestro.query.prompts import build_chat_messages, build_prompt
from docpipe_maestro.types import (
    Chunk,
    CollectionStatus,
    DocpipeError,
    EmbeddedChunk,
    GenerationResult,
    IngestResult,
    MissingCredentialError,
    MissingExtraError,
    ModelMismatchError,
    RegistryError,
    RetrievedChunk,
    SourceRecord,
    SyncResult,
    UnsupportedFormatError,
)

if TYPE_CHECKING:
    from docpipe_maestro.embedder import register_embedder
    from docpipe_maestro.ingest.chunker import register_chunker
    from docpipe_maestro.ingest.clean import register_cleaner
    from docpipe_maestro.ingest.enricher import register_enricher
    from docpipe_maestro.ingest.intake import register_parser
    from docpipe_maestro.ingest.pipeline import ingest, reindex, remove, status, sync
    from docpipe_maestro.query.answer import answer, answer_detailed
    from docpipe_maestro.query.reranker import register_reranker
    from docpipe_maestro.query.retriever import retrieve
    from docpipe_maestro.query.searcher import register_searcher
    from docpipe_maestro.store import register_store

try:
    __version__ = version("docpipe-maestro")
except PackageNotFoundError:
    __version__ = "0.1.0.dev0"

__all__ = [
    "Chunk",
    "CollectionStatus",
    "DocpipeError",
    "EmbeddedChunk",
    "GenerationResult",
    "IngestResult",
    "MissingCredentialError",
    "MissingExtraError",
    "ModelMismatchError",
    "RegistryError",
    "RetrievedChunk",
    "SourceRecord",
    "SyncResult",
    "UnsupportedFormatError",
    "__version__",
    "answer",
    "answer_detailed",
    "build_chat_messages",
    "build_prompt",
    "ingest",
    "register_chunker",
    "register_cleaner",
    "register_embedder",
    "register_enricher",
    "register_parser",
    "register_reranker",
    "register_searcher",
    "register_store",
    "reindex",
    "remove",
    "retrieve",
    "status",
    "sync",
]

_PIPELINE_EXPORTS = frozenset({"ingest", "reindex", "remove", "status", "sync"})
_REGISTER_EXPORTS: dict[str, tuple[str, str]] = {
    "register_parser": ("docpipe_maestro.ingest.intake", "register_parser"),
    "register_cleaner": ("docpipe_maestro.ingest.clean", "register_cleaner"),
    "register_enricher": ("docpipe_maestro.ingest.enricher", "register_enricher"),
    "register_chunker": ("docpipe_maestro.ingest.chunker", "register_chunker"),
    "register_embedder": ("docpipe_maestro.embedder", "register_embedder"),
    "register_store": ("docpipe_maestro.store", "register_store"),
    "register_searcher": ("docpipe_maestro.query.searcher", "register_searcher"),
    "register_reranker": ("docpipe_maestro.query.reranker", "register_reranker"),
}


def __getattr__(name: str) -> Any:
    """Lazily expose heavy vector/LLM pipeline helpers and stage registration entry points."""
    if name in _REGISTER_EXPORTS:
        mod_path, attr = _REGISTER_EXPORTS[name]
        obj = getattr(importlib.import_module(mod_path), attr)
        globals()[name] = obj
        return obj
    if name in {"answer", "answer_detailed"}:
        from docpipe_maestro.query import answer as _answer_mod

        obj = getattr(_answer_mod, name)
        globals()[name] = obj
        return obj
    if name in _PIPELINE_EXPORTS:
        from docpipe_maestro.ingest import pipeline as _pipeline_mod

        obj = getattr(_pipeline_mod, name)
        globals()[name] = obj
        return obj
    if name == "retrieve":
        from docpipe_maestro.query.retriever import retrieve as _retrieve

        globals()[name] = _retrieve
        return _retrieve
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _DocpipeModule(_stdlib_types.ModuleType):
    """Ensure lazy function exports (``ingest``) are never shadowed by subpackages."""

    def __getattribute__(self, name: str) -> Any:
        val = super().__getattribute__(name)
        if name == "ingest" and isinstance(val, _stdlib_types.ModuleType):
            return __getattr__(name)
        return val


sys.modules[__name__].__class__ = _DocpipeModule
