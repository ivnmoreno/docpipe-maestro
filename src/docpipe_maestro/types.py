"""Shared data shapes, constants, and exception hierarchy for docpipe-maestro.

All cross-module schemas (chunks, profiles, manifest state, operation summaries,
and error types) are defined exclusively here to prevent drift between Phase 1
(ingestion) and Phase 2 (query) modules.
"""

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


class RegistryError(DocpipeError):
    """Raised when stage registration collides on a key or lookup misses a key."""


@dataclass(slots=True)
class ParsedClause:
    """Internal Phase 1 representation of a clause or paragraph block."""

    clause_label: str | None
    text: str
    page: int | None = None


@dataclass(slots=True)
class ParsedSection:
    """Internal Phase 1 representation of a document section."""

    source: str
    section_label: str
    heading_level: int
    raw_text: str
    page: int | None = None
    clauses: list[ParsedClause] = field(default_factory=list)


@dataclass(slots=True)
class ParsedDocument:
    """Internal Phase 1 representation of an ingested source file."""

    source: str
    format_name: str
    sections: list[ParsedSection] = field(default_factory=list)


class _IngestContextBase(TypedDict):
    """Required execution context fields passed to Phase 1 enricher stages."""

    collection: str
    source: str
    content_hash: str
    doc_version: str
    embed_model: str
    profile: str


class IngestContext(_IngestContextBase, total=False):
    """Execution context passed to Phase 1 ``Enricher`` stage extensions."""

    extra: dict[str, Any]


class ChunkMetadata(TypedDict):
    """Structured metadata attached to every child and parent chunk.

    Attributes:
        type: Distinguishes searchable ``"child"`` chunks from ``"parent"`` sections.
        source: Normalized source key (relative POSIX path or filename).
        doc_version: 12-character ``sha256`` content hash prefix of the source file.
        section: Section heading label containing this chunk.
        clause: Detected clause label (e.g., ``"4.2"``), or ``None`` when absent.
        page: 1-based page number for paginated documents (PDF), or ``None``.
        chunk_index: 0-based ordinal position within the parent section (or section index).
        embed_model: ``provider/model`` identifier used to embed the collection.
    """

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
    """Compute a deterministic 16-character hex content-addressed chunk ID.

    Including ``source``, ``doc_version``, ``parent_id``, structural location,
    and text guarantees reproducible IDs for identical inputs while isolating
    sequential versions during transactional updates.
    """
    payload = (
        f"{source}|{doc_version}|{chunk_type}|{parent_id or ''}|"
        f"{section}|{clause or ''}|{chunk_index}|{text}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class Chunk:
    """Foundational text unit produced by chunking and shared across all modules.

    Enforces parent-child structural invariants: ``"child"`` chunks must carry a
    non-empty ``parent_id``, whereas ``"parent"`` sections must have ``parent_id=None``.

    Attributes:
        id: Deterministic content-addressed 16-character hex identifier.
        text: Chunk content (children carry a prepended ``[Source: ...]`` header).
        parent_id: Identifier of the enclosing parent section, or ``None`` for parents.
        metadata: Typed structural and provenance metadata.
    """

    id: str
    text: str
    parent_id: str | None
    metadata: ChunkMetadata

    def __post_init__(self) -> None:
        """Validate child/parent linkage invariants against ``metadata['type']``."""
        chunk_type = self.metadata["type"]
        if chunk_type not in ("child", "parent"):
            raise ValueError(f"Invalid chunk type: {chunk_type!r}")
        if chunk_type == "child" and not self.parent_id:
            raise ValueError("Child chunks must carry a non-empty parent_id")
        if chunk_type == "parent" and self.parent_id is not None:
            raise ValueError("Parent sections must have parent_id=None")


@dataclass(slots=True)
class EmbeddedChunk(Chunk):
    """A Chunk augmented with a dense embedding vector (or zero vector for parents).

    Attributes:
        vector: Embedding coordinates for children; ``[0.0] * dim`` for parents.
    """

    vector: list[float] = field(default_factory=list)


@dataclass(slots=True)
class RetrievedChunk(EmbeddedChunk):
    """An EmbeddedChunk returned from retrieval with a normalized similarity score.

    Attributes:
        score: Normalized cosine similarity clamped to ``[0.0, 1.0]``.
    """

    score: float = 0.0


@dataclass(frozen=True, slots=True)
class ChunkingProfile:
    """Static configuration defining chunking limits and structural behavior.

    Attributes:
        name: Canonical uppercase profile identifier (e.g., ``"DEFAULT"``, ``"POLICY"``).
        chunk_size: Target maximum child chunk budget in estimated tokens.
        overlap: Trailing word-token overlap carried within the same parent section.
        clause_preserving: If ``True``, numbered/labeled clauses are never split mid-clause.
        parent_child: Whether parent sections are emitted alongside linked child chunks.
        resolve_crossrefs: Whether intra-document cross-references are appended to sections.
    """

    name: str
    chunk_size: int
    overlap: int
    clause_preserving: bool
    parent_child: bool
    resolve_crossrefs: bool


@dataclass(slots=True)
class SourceRecord:
    """Per-document manifest entry stored alongside the vector database.

    Attributes:
        source: Canonical relative POSIX path or filename for the indexed document.
        content_hash: Full ``"sha256:<hex>"`` digest of the raw file bytes.
        doc_version: Active 12-character hex version prefix stored in chunk metadata.
        size: Raw file size in bytes recorded at commit time.
        mtime: Filesystem modification timestamp used strictly as a fast-path hint.
        ingested_at: ISO-8601 UTC timestamp of the last commit or reindex.
        embed_model: ``provider/model`` string used to embed the document's children.
        profile: Name of the ``ChunkingProfile`` used when chunking the document.
        chunk_ids: Committed child chunk IDs owned by this source.
        parent_ids: Committed parent section IDs owned by this source.
    """

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
        """Serialize this source record into a JSON-compatible dictionary."""
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
        """Deserialize a ``SourceRecord`` from parsed manifest JSON data."""
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
    """Collection-level manifest tracking the locked embedding model and indexed sources.

    Attributes:
        collection: Target ChromaDB collection name.
        embed_model: Collection-locked embedding model, or ``None`` before first write.
        embed_dim: Vector dimensionality recorded on first non-empty write, or ``None``.
        sources: Mapping from canonical source key to committed ``SourceRecord``.
    """

    collection: str
    embed_model: str | None = None
    embed_dim: int | None = None
    sources: dict[str, SourceRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the collection manifest into a JSON-compatible dictionary."""
        return {
            "collection": self.collection,
            "embed_model": self.embed_model,
            "embed_dim": self.embed_dim,
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        """Deserialize a ``Manifest`` from parsed JSON data."""
        raw_sources = data.get("sources", {})
        return cls(
            collection=str(data["collection"]),
            embed_model=str(data["embed_model"]) if data.get("embed_model") else None,
            embed_dim=int(data["embed_dim"]) if data.get("embed_dim") is not None else None,
            sources={k: SourceRecord.from_dict(v) for k, v in raw_sources.items()},
        )


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Summary returned by ``ingest()``.

    Attributes:
        collection: Target collection name.
        embed_model: Embedding ``provider/model`` string used for the run.
        ingested: Source keys newly indexed or re-indexed during this call.
        skipped: Unchanged source keys skipped via the manifest fast-path or hash check.
        chunks_written: Number of child chunks written to the vector store.
        parents_written: Number of parent sections written to the vector store.
    """

    collection: str
    embed_model: str
    ingested: list[str]
    skipped: list[str]
    chunks_written: int
    parents_written: int


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Summary returned by ``sync()``.

    Attributes:
        collection: Target collection name.
        embed_model: Embedding ``provider/model`` string used for the run.
        added: New source keys added to the collection.
        updated: Modified source keys replaced via staged delete-then-reinsert.
        skipped: Unchanged source keys skipped during reconciliation.
        removed: Missing source keys purged from both the vector store and manifest.
    """

    collection: str
    embed_model: str
    added: list[str]
    updated: list[str]
    skipped: list[str]
    removed: list[str]


@dataclass(frozen=True, slots=True)
class CollectionStatus:
    """Read-only status summary returned by ``status()``.

    Attributes:
        collection: Target collection name.
        embed_model: Locked collection embedding model, or ``None`` if empty.
        embed_dim: Vector dimensionality recorded for the collection, or ``None``.
        total_sources: Count of tracked documents in the manifest.
        total_children: Sum of committed child chunks across all tracked sources.
        total_parents: Sum of committed parent sections across all tracked sources.
        sources: Tracked ``SourceRecord`` entries sorted lexicographically by source key.
    """

    collection: str
    embed_model: str | None
    embed_dim: int | None
    total_sources: int
    total_children: int
    total_parents: int
    sources: list[SourceRecord]


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Structured response and telemetry returned by ``answer_detailed()``.

    Attributes:
        text: Stripped LLM answer text, or ``EMPTY_CONTEXT_REFUSAL`` if empty context.
        model: Target LiteLLM ``provider/model`` identifier used for generation.
        finish_reason: Provider stop reason (e.g., ``"stop"``, ``"length"``), or ``None``.
        truncated: ``True`` when ``finish_reason == "length"``.
        prompt_tokens: Reported input prompt tokens, or ``None`` when unavailable.
        completion_tokens: Reported output tokens, or ``None`` when unavailable.
        reasoning_tokens: Reported internal reasoning tokens, or ``None`` when unavailable.
        total_tokens: Reported total tokens billed, or ``None`` when unavailable.
        elapsed_seconds: Wall-clock duration of the completion call in seconds.
    """

    text: str
    model: str
    finish_reason: str | None = None
    truncated: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    elapsed_seconds: float = 0.0


class _EvalQueryRequired(TypedDict):
    """Required fields for a single labeled benchmark query."""

    question: str
    relevant_ids: list[str]


class EvalQuery(_EvalQueryRequired, total=False):
    """Canonical schema for one evaluation query entry inside a fixture."""

    notes: str


class _EvalFixtureRequired(TypedDict):
    """Required fields for a structured retrieval evaluation fixture."""

    queries: list[EvalQuery]


class EvalFixture(_EvalFixtureRequired, total=False):
    """Canonical schema for a retrieval evaluation benchmark fixture."""

    collection: str
    profile: str


class EvalConfig(TypedDict):
    """Resolved evaluation run configuration captured in every ``EvalReport``."""

    collection: str
    persist_dir: str
    embed_model: str
    k_values: list[int]
    expand_parent: bool
    follow_crossrefs: bool
    searcher: str
    embedder: str
    store: str
    threshold: float | None


class PerQueryResult(TypedDict):
    """Diagnostic retrieval metrics and hits for a single evaluation query."""

    question: str
    notes: str
    relevant_ids: list[str]
    retrieved_ids: list[str]
    retrieved_scores: list[float]
    precision_at_k: dict[str, float]
    recall_at_k: dict[str, float]
    reciprocal_rank: float


class EvalMetricsSummary(TypedDict):
    """Aggregate ranking metrics averaged across all fixture queries."""

    num_queries: int
    mrr: float
    precision_at_k: dict[str, float]
    recall_at_k: dict[str, float]


class EvalReport(TypedDict):
    """Structured output returned by ``evaluate()`` and ``docpipe-maestro eval --json``."""

    config: EvalConfig
    aggregate: EvalMetricsSummary
    per_query: list[PerQueryResult]
