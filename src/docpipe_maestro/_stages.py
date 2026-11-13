"""Phase-neutral shared @runtime_checkable stage Protocol interfaces."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from docpipe_maestro.types import EmbeddedChunk, RetrievedChunk


@runtime_checkable
class Embedder(Protocol):
    """Contract for dense text embedding backends shared across Phase 1 and Phase 2."""

    name: str

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        api_base: str | None = None,
    ) -> list[list[float]]:
        """Embed a sequence of child chunk texts aligned 1-to-1 with inputs."""

    def embed_query(
        self,
        text: str,
        *,
        model: str,
        api_base: str | None = None,
    ) -> list[float]:
        """Embed a single retrieval query string."""


@runtime_checkable
class Store(Protocol):
    """Contract for vector store backends shared across Phase 1 writes and Phase 2 reads."""

    name: str

    def __init__(self, persist_dir: Path, collection_name: str) -> None:
        """Open or initialize a collection store at ``persist_dir``."""

    def add_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Persist child and parent ``EmbeddedChunk`` items into the collection."""

    def query_children(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        active_versions: dict[str, str] | None = None,
        where: dict[str, object] | None = None,
        include_embeddings: bool = False,
    ) -> list[RetrievedChunk]:
        """Search committed child chunks using cosine similarity."""

    def get_by_ids(
        self,
        ids: Sequence[str],
        *,
        include_embeddings: bool = False,
    ) -> list[EmbeddedChunk]:
        """Fetch stored chunks or parent sections by exact identifier."""

    def get_parents_by_source(
        self,
        source: str,
        *,
        active_doc_version: str | None = None,
        include_embeddings: bool = False,
    ) -> list[EmbeddedChunk]:
        """Fetch parent sections belonging to ``source`` (optionally version-scoped)."""

    def delete_by_source(self, source: str) -> None:
        """Delete all records belonging to ``source``."""

    def delete_stale_versions(self, source: str, active_doc_version: str) -> None:
        """Delete prior ``doc_version`` records for ``source`` after commit."""

    def sweep_uncommitted(self, active_versions: dict[str, str]) -> int:
        """Purge uncommitted staging records and return the removed count."""

    def get_all_children(self) -> list[EmbeddedChunk]:
        """Return all stored child records for full-collection re-indexing."""

    def get_all_parents(self) -> list[EmbeddedChunk]:
        """Return all stored parent records for full-collection re-indexing."""

    def reset_collection(self) -> None:
        """Drop and recreate the collection cleanly before re-indexed writes."""
