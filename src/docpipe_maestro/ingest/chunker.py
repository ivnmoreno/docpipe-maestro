"""Phase 1 structure-aware hierarchical chunker (parent sections + child chunks)."""

from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from docpipe_maestro.ingest.intake import ParsedDocument, ParsedSection
from docpipe_maestro.types import Chunk, ChunkingProfile, ChunkMetadata, make_chunk_id

_CLAUSE_START_RE = re.compile(
    r"^(?:(?:Clause|Article|Section)\s+([0-9]+(?:\.[0-9]+)*)|"
    r"(§\s*[0-9]+(?:\.[0-9]+)*)|"
    r"([0-9]+\.[0-9]+(?:\.[0-9]+)*)|"
    r"(\([a-z0-9]+\)))\s+(.+)$",
    re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    """Offline-safe deterministic token estimator (zero network calls).

    Approximates BPE token count from whitespace word count (``ceil(words * 4 / 3)``)
    so fresh air-gapped environments never download remote tokenizers.
    """
    words = len(text.split())
    return max(1, (words * 4 + 2) // 3) if words else 0


def _split_into_clauses(raw_text: str) -> list[tuple[str | None, str]]:
    """Split section text into ``(clause_label, clause_text)`` blocks."""
    blocks: list[tuple[str | None, str]] = []
    current_label: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        """Emit accumulated clause lines if non-empty and clear buffer."""
        text = "\n".join(current_lines).strip()
        if text:
            blocks.append((current_label, text))
        current_lines.clear()

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            current_label = None
            continue
        match = _CLAUSE_START_RE.match(stripped)
        if match:
            flush()
            label = next(g for g in match.groups()[:4] if g is not None)
            current_label = label.strip()
            current_lines.append(stripped)
        else:
            current_lines.append(stripped)

    flush()
    return blocks or [(None, raw_text.strip())]


def _tail_overlap_text(text: str, overlap_tokens: int) -> str:
    """Return trailing words from text up to overlap_tokens."""
    if overlap_tokens <= 0 or not text:
        return ""
    words = text.split()
    max_words = max(1, (overlap_tokens * 3) // 4)
    if len(words) <= max_words:
        return text
    return " ".join(words[-max_words:])


def _split_non_preserving(text: str, profile: ChunkingProfile) -> list[str]:
    """Split text using RecursiveCharacterTextSplitter (sentences -> chars fallback)."""
    if estimate_tokens(text) <= profile.chunk_size:
        return [text]
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " ", ""],
        chunk_size=max(64, profile.chunk_size * 4),
        chunk_overlap=max(0, profile.overlap * 4),
        length_function=len,
    )
    parts = [p.strip() for p in splitter.split_text(text) if p.strip()]
    return parts or [text]


def _format_child_text(
    *,
    source: str,
    section: str,
    clause: str | None,
    body: str,
) -> str:
    """Prepend structural provenance header to a child chunk body."""
    if clause:
        header = f"[Source: {source} | Section: {section} | Clause: {clause}]"
    else:
        header = f"[Source: {source} | Section: {section}]"
    return f"{header}\n{body}"


def _pack_units_with_overlap(
    units: list[tuple[str | None, str]],
    *,
    chunk_size: int,
    overlap: int,
) -> list[tuple[str | None, str]]:
    """Pack clause/paragraph units up to chunk_size tokens with section-scoped overlap."""
    packed: list[tuple[str | None, str]] = []
    current_parts: list[str] = []
    current_clause: str | None = None
    current_tokens = 0

    for label, unit_text in units:
        u_tokens = estimate_tokens(unit_text)
        if current_parts and current_tokens + u_tokens > chunk_size:
            combined = "\n\n".join(current_parts)
            packed.append((current_clause, combined))
            overlap_prefix = _tail_overlap_text(combined, overlap)
            if overlap_prefix and estimate_tokens(overlap_prefix) + u_tokens <= chunk_size:
                current_parts = [overlap_prefix, unit_text]
            else:
                current_parts = [unit_text]
            current_clause = label
            current_tokens = estimate_tokens("\n\n".join(current_parts))
        else:
            if not current_parts:
                current_clause = label
            current_parts.append(unit_text)
            current_tokens += u_tokens

    if current_parts:
        packed.append((current_clause, "\n\n".join(current_parts)))
    return packed


def _build_section_children(
    sec: ParsedSection,
    *,
    parent_id: str,
    profile: ChunkingProfile,
    doc_version: str,
    embed_model: str,
) -> list[Chunk]:
    """Split a parent section into linked child ``Chunk`` objects."""
    clauses = _split_into_clauses(sec.raw_text)
    if profile.clause_preserving:
        units = clauses
    else:
        units = [
            (label, piece)
            for label, c_text in clauses
            for piece in _split_non_preserving(c_text, profile)
        ]

    raw_children = _pack_units_with_overlap(
        units,
        chunk_size=profile.chunk_size,
        overlap=profile.overlap,
    )

    children: list[Chunk] = []
    for idx, (clause_label, body) in enumerate(raw_children):
        formatted = _format_child_text(
            source=sec.source,
            section=sec.section_label,
            clause=clause_label,
            body=body,
        )
        cid = make_chunk_id(
            source=sec.source,
            doc_version=doc_version,
            chunk_type="child",
            section=sec.section_label,
            clause=clause_label,
            chunk_index=idx,
            text=formatted,
            parent_id=parent_id,
        )
        meta: ChunkMetadata = {
            "type": "child",
            "source": sec.source,
            "doc_version": doc_version,
            "section": sec.section_label,
            "clause": clause_label,
            "page": sec.page,
            "chunk_index": idx,
            "embed_model": embed_model,
        }
        children.append(Chunk(id=cid, text=formatted, parent_id=parent_id, metadata=meta))
    return children


def chunk_document(
    doc: ParsedDocument,
    *,
    profile: ChunkingProfile,
    doc_version: str,
    embed_model: str,
) -> list[Chunk]:
    """Chunk a cleaned ``ParsedDocument`` into parent sections and linked children.

    Every ``ParsedSection`` becomes one ``"parent"`` chunk (``parent_id=None``)
    paired with one or more ``"child"`` chunks linked via ``parent_id``. When
    ``profile.clause_preserving`` is ``True`` (e.g., ``POLICY``), individual
    clauses remain indivisible even if they exceed ``profile.chunk_size``.
    Overlap resets at each parent section boundary.
    """
    all_chunks: list[Chunk] = []
    for sec_idx, sec in enumerate(doc.sections):
        parent_id = make_chunk_id(
            source=sec.source,
            doc_version=doc_version,
            chunk_type="parent",
            section=sec.section_label,
            clause=None,
            chunk_index=sec_idx,
            text=sec.raw_text,
        )
        parent_meta: ChunkMetadata = {
            "type": "parent",
            "source": sec.source,
            "doc_version": doc_version,
            "section": sec.section_label,
            "clause": None,
            "page": sec.page,
            "chunk_index": sec_idx,
            "embed_model": embed_model,
        }
        parent = Chunk(
            id=parent_id,
            text=sec.raw_text,
            parent_id=None,
            metadata=parent_meta,
        )
        all_chunks.append(parent)
        all_chunks.extend(
            _build_section_children(
                sec,
                parent_id=parent_id,
                profile=profile,
                doc_version=doc_version,
                embed_model=embed_model,
            )
        )
    return all_chunks
