"""Phase 1 @runtime_checkable stage Protocol interfaces and shared re-exports."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from docpipe_maestro._stages import Embedder, Store
from docpipe_maestro.types import Chunk, ChunkingProfile, IngestContext, ParsedDocument

__all__ = [
    "Chunker",
    "Cleaner",
    "Embedder",
    "Enricher",
    "Parser",
    "Store",
]


@runtime_checkable
class Parser(Protocol):
    """Contract for Phase 1 format-specific document parsers."""

    name: str
    extensions: tuple[str, ...]

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Parse an on-disk file into a structured ``ParsedDocument``."""


@runtime_checkable
class Cleaner(Protocol):
    """Contract for Phase 1 parsed-document cleaners."""

    name: str

    def clean(self, doc: ParsedDocument) -> ParsedDocument:
        """Normalize text and strip repetitive boilerplate from a ``ParsedDocument``."""


@runtime_checkable
class Enricher(Protocol):
    """Contract for Phase 1 parsed-document enrichers."""

    name: str

    def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
        """Augment a cleaned ``ParsedDocument`` with metadata or cross-references."""


@runtime_checkable
class Chunker(Protocol):
    """Contract for Phase 1 structure-aware chunkers."""

    name: str

    def chunk(
        self,
        doc: ParsedDocument,
        *,
        profile: ChunkingProfile,
        doc_version: str,
        embed_model: str,
    ) -> list[Chunk]:
        """Split a cleaned ``ParsedDocument`` into parent sections and child chunks."""
