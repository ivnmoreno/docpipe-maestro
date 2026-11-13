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

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from docpipe_maestro.ingest.pipeline import ingest, reindex, remove, status, sync
from docpipe_maestro.query.prompts import build_chat_messages, build_prompt
from docpipe_maestro.query.retriever import retrieve
from docpipe_maestro.types import (
    Chunk,
    CollectionStatus,
    DocpipeError,
    EmbeddedChunk,
    IngestResult,
    MissingCredentialError,
    MissingExtraError,
    ModelMismatchError,
    RetrievedChunk,
    SourceRecord,
    SyncResult,
    UnsupportedFormatError,
)

if TYPE_CHECKING:
    from docpipe_maestro.query.answer import answer

try:
    __version__ = version("docpipe-maestro")
except PackageNotFoundError:
    __version__ = "0.1.0.dev0"

__all__ = [
    "Chunk",
    "CollectionStatus",
    "DocpipeError",
    "EmbeddedChunk",
    "IngestResult",
    "MissingCredentialError",
    "MissingExtraError",
    "ModelMismatchError",
    "RetrievedChunk",
    "SourceRecord",
    "SyncResult",
    "UnsupportedFormatError",
    "__version__",
    "answer",
    "build_chat_messages",
    "build_prompt",
    "ingest",
    "reindex",
    "remove",
    "retrieve",
    "status",
    "sync",
]


def __getattr__(name: str) -> Any:
    """Lazily expose optional generation helpers such as ``answer``."""
    if name == "answer":
        try:
            from docpipe_maestro.query.answer import answer as _answer

            return _answer
        except ImportError as exc:
            raise MissingExtraError(
                "Generation support requires the 'generation' extra: "
                "pip install docpipe-maestro[generation]"
            ) from exc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
