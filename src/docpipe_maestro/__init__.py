"""docpipe-maestro: a minimal, provider-agnostic, structure-aware RAG pipeline."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from docpipe_maestro.ingest.pipeline import ingest, reindex, remove, status, sync
from docpipe_maestro.query.prompts import build_prompt
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
    "build_prompt",
    "ingest",
    "reindex",
    "remove",
    "retrieve",
    "status",
    "sync",
]


def __getattr__(name: str) -> Any:
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
