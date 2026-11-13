"""Phase 2 @runtime_checkable retrieval and reranking stage Protocol interfaces."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from docpipe_maestro.types import RetrievedChunk

__all__ = ["Reranker", "Searcher"]


@runtime_checkable
class Searcher(Protocol):
    """Contract for Phase 2 retrieval search strategies."""

    name: str

    def search(
        self,
        question: str,
        *,
        top_k: int,
        collection: str,
        persist_dir: str,
        embed_model: str,
        where: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        """Execute a search query against a collection and return scored chunks."""


@runtime_checkable
class Reranker(Protocol):
    """Contract for Phase 2 post-retrieval reranking strategies."""

    name: str

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Reorder or filter retrieved chunks against ``query`` up to ``top_k``."""
