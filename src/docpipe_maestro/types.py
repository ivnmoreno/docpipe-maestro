"""Shared data shapes, constants, and exception hierarchy for docpipe-maestro."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

ChunkType = Literal["child", "parent"]


class DocpipeError(Exception):
    """Base exception for all docpipe-maestro errors."""


class UnsupportedFormatError(DocpipeError):
    """Raised when an input file format is unsupported or corrupted."""


class MissingExtraError(DocpipeError):
    """Raised when an optional parser or generation dependency extra is not installed."""


class ModelMismatchError(DocpipeError):
    """Raised when a query or ingest embedding model mismatches the collection lock."""


class MissingCredentialError(DocpipeError):
    """Raised when a required provider credential environment variable is missing."""


class ChunkMetadata(TypedDict):
    """Structured metadata attached to every child and parent chunk."""

    type: ChunkType
    source: str
    doc_version: str
    section: str
    clause: str | None
    page: int | None
    chunk_index: int
    embed_model: str


def make_chunk_id(
    *,
    source: str,
    doc_version: str,
    chunk_type: ChunkType,
    section: str,
    clause: str | None,
    chunk_index: int,
    text: str,
    parent_id: str | None = None,
) -> str:
    """Compute a deterministic 16-character hex content-addressed chunk ID."""
    payload = (
        f"{source}|{doc_version}|{chunk_type}|{parent_id or ''}|"
        f"{section}|{clause or ''}|{chunk_index}|{text}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class Chunk:
    """Foundational text unit produced by chunking and shared across all modules."""

    id: str
    text: str
    parent_id: str | None
    metadata: ChunkMetadata

    def __post_init__(self) -> None:
        chunk_type = self.metadata["type"]
        if chunk_type not in ("child", "parent"):
            raise ValueError(f"Invalid chunk type: {chunk_type!r}")
        if chunk_type == "child" and not self.parent_id:
            raise ValueError("Child chunks must carry a non-empty parent_id")
        if chunk_type == "parent" and self.parent_id is not None:
            raise ValueError("Parent sections must have parent_id=None")


@dataclass(slots=True)
class EmbeddedChunk(Chunk):
    """A Chunk augmented with a vector representation."""

    vector: list[float] = field(default_factory=list)


@dataclass(slots=True)
class RetrievedChunk(EmbeddedChunk):
    """An EmbeddedChunk returned from retrieval with a normalized similarity score."""

    score: float = 0.0


@dataclass(frozen=True, slots=True)
class ChunkingProfile:
    """Static configuration defining chunking limits and structural behavior."""

    name: str
    chunk_size: int
    overlap: int
    clause_preserving: bool
    parent_child: bool
    resolve_crossrefs: bool


@dataclass(slots=True)
class SourceRecord:
    """Per-document manifest entry stored alongside the vector database."""

    source: str
    content_hash: str
    doc_version: str
    size: int
    mtime: float
    ingested_at: str
    embed_model: str
    profile: str
    chunk_ids: list[str] = field(default_factory=list)
    parent_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "content_hash": self.content_hash,
            "doc_version": self.doc_version,
            "size": self.size,
            "mtime": self.mtime,
            "ingested_at": self.ingested_at,
            "embed_model": self.embed_model,
            "profile": self.profile,
            "chunk_ids": list(self.chunk_ids),
            "parent_ids": list(self.parent_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceRecord:
        return cls(
            source=str(data["source"]),
            content_hash=str(data["content_hash"]),
            doc_version=str(data["doc_version"]),
            size=int(data["size"]),
            mtime=float(data["mtime"]),
            ingested_at=str(data["ingested_at"]),
            embed_model=str(data["embed_model"]),
            profile=str(data["profile"]),
            chunk_ids=[str(x) for x in data.get("chunk_ids", [])],
            parent_ids=[str(x) for x in data.get("parent_ids", [])],
        )


@dataclass(slots=True)
class Manifest:
    """Collection-level manifest tracking the locked embedding model and indexed sources."""

    collection: str
    embed_model: str | None = None
    embed_dim: int | None = None
    sources: dict[str, SourceRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "embed_model": self.embed_model,
            "embed_dim": self.embed_dim,
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        raw_sources = data.get("sources", {})
        return cls(
            collection=str(data["collection"]),
            embed_model=str(data["embed_model"]) if data.get("embed_model") else None,
            embed_dim=int(data["embed_dim"]) if data.get("embed_dim") is not None else None,
            sources={k: SourceRecord.from_dict(v) for k, v in raw_sources.items()},
        )


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Summary returned by ingest()."""

    collection: str
    embed_model: str
    ingested: list[str]
    skipped: list[str]
    chunks_written: int
    parents_written: int


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Summary returned by sync()."""

    collection: str
    embed_model: str
    added: list[str]
    updated: list[str]
    skipped: list[str]
    removed: list[str]


@dataclass(frozen=True, slots=True)
class CollectionStatus:
    """Read-only status summary returned by status()."""

    collection: str
    embed_model: str | None
    embed_dim: int | None
    total_sources: int
    total_children: int
    total_parents: int
    sources: list[SourceRecord]
