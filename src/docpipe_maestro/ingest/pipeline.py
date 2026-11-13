"""Phase 1 ingestion pipeline orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_PERSIST_DIR,
    resolve_profile,
)
from docpipe_maestro.embedder import embed_texts
from docpipe_maestro.ingest.chunker import chunk_document
from docpipe_maestro.ingest.clean import clean_document
from docpipe_maestro.ingest.crossrefs import resolve_crossrefs
from docpipe_maestro.ingest.intake import ParsedDocument, parse_file
from docpipe_maestro.manifest import (
    check_model_lock,
    classify_file,
    load_manifest,
    save_manifest,
)
from docpipe_maestro.store import VectorStore
from docpipe_maestro.types import (
    Chunk,
    ChunkingProfile,
    ChunkMetadata,
    CollectionStatus,
    DocpipeError,
    EmbeddedChunk,
    IngestResult,
    SourceRecord,
    SyncResult,
    UnsupportedFormatError,
)

logger = logging.getLogger(__name__)


def _is_within(path: Path, parent: Path) -> bool:
    """Return True if path is equal to or inside parent."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _discover_files(
    target: Path,
    *,
    persist_path: Path | None = None,
    allow_empty: bool = False,
) -> list[tuple[Path, str]]:
    """Return sorted (file_path, source_key) pairs for a single file or directory."""
    if target.is_file():
        return [(target, target.name)]
    if target.is_dir():
        candidates: list[Path] = []
        for p in sorted(target.rglob("*")):
            if p.is_symlink():
                logger.warning("Skipping symlink during directory discovery: %s", p)
                continue
            if not p.is_file():
                continue
            if not _is_within(p, target):
                logger.warning("Skipping path escaping target directory: %s", p)
                continue
            if persist_path is not None and _is_within(p, persist_path):
                continue
            candidates.append(p)
        if not candidates and not allow_empty:
            raise UnsupportedFormatError(f"No files found in directory: {target}")
        return [(p, p.relative_to(target).as_posix()) for p in candidates]
    raise UnsupportedFormatError(f"Path does not exist: {target}")


def _embed_document_chunks(
    chunks: list[Chunk],
    *,
    embed_model: str,
) -> tuple[list[EmbeddedChunk], int]:
    """Embed all child chunks in memory and attach zero vectors to parent sections."""
    child_chunks = [c for c in chunks if c.metadata["type"] == "child"]
    parent_chunks = [c for c in chunks if c.metadata["type"] == "parent"]

    child_vectors = embed_texts([c.text for c in child_chunks], model=embed_model)
    if not child_vectors:
        return [], 0
    dim = len(child_vectors[0])
    zero_vec = [0.0] * dim

    embedded: list[EmbeddedChunk] = []
    for p in parent_chunks:
        embedded.append(
            EmbeddedChunk(
                id=p.id,
                text=p.text,
                parent_id=p.parent_id,
                metadata=p.metadata,
                vector=list(zero_vec),
            )
        )
    for c, vec in zip(child_chunks, child_vectors, strict=True):
        embedded.append(
            EmbeddedChunk(
                id=c.id,
                text=c.text,
                parent_id=c.parent_id,
                metadata=c.metadata,
                vector=vec,
            )
        )
    return embedded, dim


def ingest(
    path: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    force: bool = False,
) -> IngestResult:
    """Ingest a file or directory atomically into the vector database.

    Validates, parses, cleans, chunks, and embeds all changed files in memory
    *before* initializing or mutating ``VectorStore``. Each changed document is
    written under a new ``doc_version``, committed atomically in the manifest,
    and prior versions for that source are purged afterward so failed updates
    leave the previous version intact and queryable.

    Args:
        path: Source file or directory tree to ingest recursively.
        profile: Profile name (``"DEFAULT"`` / ``"POLICY"``) or ``ChunkingProfile``.
        collection: Target ChromaDB collection and manifest name.
        persist_dir: Local persistence directory for ChromaDB and manifests.
        embed_model: LiteLLM ``provider/model`` identifier for child embeddings.
        force: Re-ingest files even when ``mtime``/``size``/``sha256`` match.

    Returns:
        Summary of ingested/skipped source keys and written child/parent counts.

    Raises:
        UnsupportedFormatError: If ``path`` is missing, empty, or contains an
            unsupported/corrupted file (aborts the entire batch before writes).
        MissingExtraError: If a required format extra (``pdf``, ``docx``,
            ``html``) is not installed.
        ModelMismatchError: If ``collection`` is already locked to another model.
        MissingCredentialError: If provider credentials are missing or invalid.
        DocpipeError: If embedding or store initialization fails.
    """
    target = Path(path)
    persist_path = Path(persist_dir)
    prof = resolve_profile(profile)

    manifest = load_manifest(persist_path, collection)
    check_model_lock(manifest, embed_model)

    discovered = _discover_files(target, persist_path=persist_path)

    # Atomic batch validation & in-memory parsing/chunking/embedding before touching the DB
    staged_docs: list[tuple[str, str, str, int, float, list[EmbeddedChunk], int]] = []
    skipped: list[str] = []
    manifest_dirty = False

    for file_path, source_key in discovered:
        status, content_hash, size, mtime = classify_file(
            file_path, source_key, manifest, force=force
        )
        if status == "unchanged":
            skipped.append(source_key)
            existing = manifest.sources[source_key]
            if existing.size != size or existing.mtime != mtime:
                existing.size = size
                existing.mtime = mtime
                manifest_dirty = True
            continue

        if content_hash is None:
            raise DocpipeError(f"Missing content hash for non-unchanged file: {source_key}")
        doc_version = content_hash.split(":", 1)[1][:12]
        parsed: ParsedDocument = parse_file(file_path, source_key=source_key)
        cleaned = clean_document(parsed)
        if prof.resolve_crossrefs:
            cleaned = resolve_crossrefs(cleaned)
        chunks = chunk_document(
            cleaned,
            profile=prof,
            doc_version=doc_version,
            embed_model=embed_model,
        )
        embedded, dim = _embed_document_chunks(chunks, embed_model=embed_model)
        staged_docs.append((source_key, content_hash, doc_version, size, mtime, embedded, dim))

    if manifest_dirty and not staged_docs:
        save_manifest(persist_path, manifest)

    store = VectorStore(persist_path, collection)
    active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
    store.sweep_uncommitted(active_versions)

    ingested: list[str] = []
    chunks_written = 0
    parents_written = 0

    for source_key, content_hash, doc_version, size, mtime, embedded, dim in staged_docs:
        store.add_chunks(embedded)

        child_ids = [c.id for c in embedded if c.metadata["type"] == "child"]
        parent_ids = [c.id for c in embedded if c.metadata["type"] == "parent"]

        if manifest.embed_model is None:
            manifest.embed_model = embed_model
        if manifest.embed_dim is None and dim > 0:
            manifest.embed_dim = dim

        manifest.sources[source_key] = SourceRecord(
            source=source_key,
            content_hash=content_hash,
            doc_version=doc_version,
            size=size,
            mtime=mtime,
            ingested_at=datetime.now(timezone.utc).isoformat(),
            embed_model=embed_model,
            profile=prof.name,
            chunk_ids=child_ids,
            parent_ids=parent_ids,
        )
        save_manifest(persist_path, manifest)
        store.delete_stale_versions(source_key, doc_version)

        ingested.append(source_key)
        chunks_written += len(child_ids)
        parents_written += len(parent_ids)

    return IngestResult(
        collection=collection,
        embed_model=embed_model,
        ingested=ingested,
        skipped=skipped,
        chunks_written=chunks_written,
        parents_written=parents_written,
    )


def sync(
    directory: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
) -> SyncResult:
    """Three-way reconcile ``directory`` against the collection manifest.

    Adds new files, skips unchanged files (refreshing ``mtime``/``size`` when
    only filesystem timestamps changed), replaces modified files via staged
    delete-then-reinsert, and removes records/manifest entries for files
    deleted from ``directory``.

    Args:
        directory: Directory path to synchronize with the manifest.
        profile: Profile name (``"DEFAULT"`` / ``"POLICY"``) or ``ChunkingProfile``.
        collection: Target ChromaDB collection and manifest name.
        persist_dir: Local persistence directory for ChromaDB and manifests.
        embed_model: LiteLLM ``provider/model`` identifier for child embeddings.

    Returns:
        ``SyncResult`` listing ``added``, ``updated``, ``skipped``, and
        ``removed`` canonical source keys.

    Raises:
        UnsupportedFormatError: If ``directory`` is not a directory or contains
            an unsupported/corrupted file.
        MissingExtraError: If a required format parser extra is missing.
        ModelMismatchError: If ``collection`` is locked to a different model.
        MissingCredentialError: If embedding credentials are missing or invalid.
        DocpipeError: If embedding or store operations fail.
    """
    target = Path(directory)
    if not target.is_dir():
        raise UnsupportedFormatError(f"Sync target is not a directory: {target}")

    persist_path = Path(persist_dir)
    prof = resolve_profile(profile)
    manifest = load_manifest(persist_path, collection)
    check_model_lock(manifest, embed_model)

    discovered = _discover_files(target, persist_path=persist_path, allow_empty=True)
    disk_keys = {source_key for _, source_key in discovered}
    removed_keys = sorted(set(manifest.sources.keys()) - disk_keys)

    staged_docs: list[tuple[str, str, str, str, int, float, list[EmbeddedChunk], int]] = []
    skipped: list[str] = []
    manifest_dirty = False

    for file_path, source_key in discovered:
        status_flag, content_hash, size, mtime = classify_file(file_path, source_key, manifest)
        if status_flag == "unchanged":
            skipped.append(source_key)
            existing = manifest.sources[source_key]
            if existing.size != size or existing.mtime != mtime:
                existing.size = size
                existing.mtime = mtime
                manifest_dirty = True
            continue

        if content_hash is None:
            raise DocpipeError(f"Missing content hash for non-unchanged file: {source_key}")
        doc_version = content_hash.split(":", 1)[1][:12]
        parsed = parse_file(file_path, source_key=source_key)
        cleaned = clean_document(parsed)
        if prof.resolve_crossrefs:
            cleaned = resolve_crossrefs(cleaned)
        chunks = chunk_document(
            cleaned,
            profile=prof,
            doc_version=doc_version,
            embed_model=embed_model,
        )
        embedded, dim = _embed_document_chunks(chunks, embed_model=embed_model)
        staged_docs.append(
            (status_flag, source_key, content_hash, doc_version, size, mtime, embedded, dim)
        )

    store = VectorStore(persist_path, collection)
    active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
    store.sweep_uncommitted(active_versions)

    added: list[str] = []
    updated: list[str] = []

    for (
        doc_status,
        source_key,
        content_hash,
        doc_version,
        size,
        mtime,
        embedded,
        dim,
    ) in staged_docs:
        store.add_chunks(embedded)
        child_ids = [c.id for c in embedded if c.metadata["type"] == "child"]
        parent_ids = [c.id for c in embedded if c.metadata["type"] == "parent"]

        if manifest.embed_model is None:
            manifest.embed_model = embed_model
        if manifest.embed_dim is None and dim > 0:
            manifest.embed_dim = dim

        manifest.sources[source_key] = SourceRecord(
            source=source_key,
            content_hash=content_hash,
            doc_version=doc_version,
            size=size,
            mtime=mtime,
            ingested_at=datetime.now(timezone.utc).isoformat(),
            embed_model=embed_model,
            profile=prof.name,
            chunk_ids=child_ids,
            parent_ids=parent_ids,
        )
        save_manifest(persist_path, manifest)
        store.delete_stale_versions(source_key, doc_version)

        if doc_status == "new":
            added.append(source_key)
        else:
            updated.append(source_key)

    for source_key in removed_keys:
        store.delete_by_source(source_key)
        manifest.sources.pop(source_key, None)
        manifest_dirty = True

    if manifest_dirty:
        save_manifest(persist_path, manifest)

    return SyncResult(
        collection=collection,
        embed_model=embed_model,
        added=added,
        updated=updated,
        skipped=skipped,
        removed=removed_keys,
    )


def remove(
    source: str | Path,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
) -> bool:
    """Remove all vector records and the manifest entry for a single source.

    Args:
        source: Canonical source key tracked in the collection manifest.
        collection: Target collection name.
        persist_dir: Local persistence directory.

    Returns:
        ``True`` if the source existed and was purged, ``False`` otherwise.
    """
    source_key = Path(source).as_posix()
    persist_path = Path(persist_dir)
    manifest = load_manifest(persist_path, collection)
    if source_key not in manifest.sources:
        return False

    store = VectorStore(persist_path, collection)
    store.delete_by_source(source_key)
    manifest.sources.pop(source_key)
    save_manifest(persist_path, manifest)
    return True


def status(
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
) -> CollectionStatus:
    """Return a read-only summary of the collection's manifest state.

    Args:
        collection: Target collection name.
        persist_dir: Local persistence directory.

    Returns:
        ``CollectionStatus`` containing locked model metadata, aggregate child
        and parent counts, and sorted per-source ``SourceRecord`` entries.
    """
    manifest = load_manifest(Path(persist_dir), collection)
    sources = sorted(manifest.sources.values(), key=lambda s: s.source)
    total_children = sum(len(s.chunk_ids) for s in sources)
    total_parents = sum(len(s.parent_ids) for s in sources)
    return CollectionStatus(
        collection=manifest.collection,
        embed_model=manifest.embed_model,
        embed_dim=manifest.embed_dim,
        total_sources=len(sources),
        total_children=total_children,
        total_parents=total_parents,
        sources=sources,
    )


def reindex(
    *,
    embed_model: str,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
) -> int:
    """Re-embed all existing stored child chunks under a new embedding model.

    Computes all new child vectors in memory first, updates parent zero-vector
    dimensions to match, rebuilds the ChromaDB collection cleanly, and updates
    the manifest's model lock and vector dimensionality.

    Args:
        embed_model: New LiteLLM ``provider/model`` identifier for the collection.
        collection: Target collection name.
        persist_dir: Local persistence directory.

    Returns:
        Count of committed child chunks re-embedded.

    Raises:
        MissingCredentialError: If provider credentials for ``embed_model`` fail.
        DocpipeError: If embedding or collection recreation fails.
    """
    persist_path = Path(persist_dir)
    manifest = load_manifest(persist_path, collection)
    store = VectorStore(persist_path, collection)

    active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
    children = [
        c
        for c in store.get_all_children()
        if active_versions.get(c.metadata["source"]) == c.metadata["doc_version"]
    ]
    parents = [
        p
        for p in store.get_all_parents()
        if active_versions.get(p.metadata["source"]) == p.metadata["doc_version"]
    ]

    if not children:
        manifest.embed_model = embed_model
        manifest.embed_dim = None
        save_manifest(persist_path, manifest)
        return 0

    # Embed all children in memory before mutating ChromaDB or manifest
    new_vectors = embed_texts([c.text for c in children], model=embed_model)
    new_dim = len(new_vectors[0])
    zero_vec = [0.0] * new_dim

    rebuilt: list[EmbeddedChunk] = []
    for p in parents:
        p_meta: ChunkMetadata = {
            **p.metadata,
            "embed_model": embed_model,
        }
        rebuilt.append(
            EmbeddedChunk(
                id=p.id,
                text=p.text,
                parent_id=p.parent_id,
                metadata=p_meta,
                vector=list(zero_vec),
            )
        )
    for c, vec in zip(children, new_vectors, strict=True):
        c_meta: ChunkMetadata = {
            **c.metadata,
            "embed_model": embed_model,
        }
        rebuilt.append(
            EmbeddedChunk(
                id=c.id,
                text=c.text,
                parent_id=c.parent_id,
                metadata=c_meta,
                vector=vec,
            )
        )

    store.reset_collection()
    store.add_chunks(rebuilt)

    manifest.embed_model = embed_model
    manifest.embed_dim = new_dim
    now_iso = datetime.now(timezone.utc).isoformat()
    for rec in manifest.sources.values():
        rec.embed_model = embed_model
        rec.ingested_at = now_iso
    save_manifest(persist_path, manifest)
    return len(children)
