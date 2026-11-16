"""Phase 1 ingestion pipeline orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docpipe_maestro._resolve import resolve_parser
from docpipe_maestro._stages import Embedder, Store
from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_PERSIST_DIR,
    resolve_profile,
)
from docpipe_maestro.embedder import EMBEDDERS
from docpipe_maestro.ingest.chunker import CHUNKERS
from docpipe_maestro.ingest.clean import CLEANERS
from docpipe_maestro.ingest.enricher import ENRICHERS
from docpipe_maestro.ingest.stages import Chunker, Cleaner, Enricher
from docpipe_maestro.log import _emit_stage_end, correlation_id, get_logger, stage_event
from docpipe_maestro.manifest import (
    append_audit_record,
    check_model_lock,
    classify_file,
    load_manifest,
    save_manifest,
)
from docpipe_maestro.store import STORES, LexicalIndex
from docpipe_maestro.types import (
    Chunk,
    ChunkingProfile,
    ChunkMetadata,
    CollectionStatus,
    DocpipeError,
    EmbeddedChunk,
    IngestContext,
    IngestResult,
    ParsedDocument,
    PiiAuditRecord,
    PiiBlockedError,
    PiiPolicy,
    SourceRecord,
    SyncResult,
    UnsupportedFormatError,
)

logger = get_logger(__name__)


@dataclass
class _BatchStageMetrics:
    """Cumulative batch timing (ms) and safe counts for Phase 1 stage summaries."""

    intake_ms: float = 0.0
    clean_ms: float = 0.0
    enrich_ms: float = 0.0
    chunk_ms: float = 0.0
    embed_ms: float = 0.0
    docs_processed: int = 0
    sections_parsed: int = 0
    children_chunked: int = 0
    parents_chunked: int = 0
    chunks_embedded: int = 0
    entities_detected: int = 0


def _emit_phase1_prep_summaries(
    *,
    collection: str,
    profile_name: str,
    embed_model: str,
    skipped_count: int,
    metrics: _BatchStageMetrics,
    pii_active: bool,
) -> None:
    """Emit aggregated INFO ``stage.end`` events for Phase 1 batch preparation."""
    shared = {"collection": collection, "docs": metrics.docs_processed, "skipped": skipped_count}
    _emit_stage_end(
        logger,
        "intake",
        level=logging.INFO,
        duration_ms=metrics.intake_ms,
        status="ok",
        fields={**shared, "sections": metrics.sections_parsed},
    )
    _emit_stage_end(
        logger,
        "clean",
        level=logging.INFO,
        duration_ms=metrics.clean_ms,
        status="ok",
        fields=shared,
    )
    enrich_fields: dict[str, Any] = {
        **shared,
        "profile": profile_name,
        "pii_active": pii_active,
    }
    if pii_active:
        enrich_fields["entities_detected"] = metrics.entities_detected
    _emit_stage_end(
        logger,
        "enrich",
        level=logging.INFO,
        duration_ms=metrics.enrich_ms,
        status="ok",
        fields=enrich_fields,
    )
    _emit_stage_end(
        logger,
        "chunk",
        level=logging.INFO,
        duration_ms=metrics.chunk_ms,
        status="ok",
        fields={
            **shared,
            "profile": profile_name,
            "children": metrics.children_chunked,
            "parents": metrics.parents_chunked,
        },
    )
    _emit_stage_end(
        logger,
        "embed",
        level=logging.INFO,
        duration_ms=metrics.embed_ms,
        status="ok",
        fields={
            **shared,
            "embed_model": embed_model,
            "chunks": metrics.chunks_embedded,
        },
    )


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


def _effective_enricher_names(
    enricher_names: Sequence[str],
    *,
    pii_policy: PiiPolicy | None,
) -> tuple[str, ...]:
    """Schedule ``'pii'`` ahead of profile enrichers when ``pii_policy`` is active."""
    names = tuple(enricher_names)
    if pii_policy is None or "pii" in names:
        return names
    return ("pii", *names)


def _resolve_enrichers(enricher_names: Sequence[str]) -> list[Enricher]:
    """Resolve and instantiate configured Phase 1 enrichers in declared order."""
    if not enricher_names:
        return []
    return [ENRICHERS.resolve(name)() for name in enricher_names]


def _apply_enrichers(
    doc: ParsedDocument,
    enrichers: Sequence[Enricher],
    ctx: IngestContext,
) -> ParsedDocument:
    """Apply resolved Phase 1 enrichers sequentially between clean and chunk."""
    enriched = doc
    for enricher in enrichers:
        enriched = enricher.enrich(enriched, ctx)
    return enriched


def _build_pii_audit_record(
    *,
    collection: str,
    source_key: str,
    doc_version: str,
    threshold: float,
    entity_counts: Mapping[str, int],
    actions: Mapping[str, str],
    blocked: bool,
    mode: str,
) -> PiiAuditRecord:
    """Build a structured zero-raw-PII audit record for JSONL persistence."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "collection": collection,
        "source": source_key,
        "doc_version": doc_version,
        "threshold": threshold,
        "entity_counts": dict(sorted(entity_counts.items())),
        "actions": dict(sorted(actions.items())),
        "blocked": blocked,
        "mode": mode,
    }


def _extract_audit_fields(
    extra: Mapping[str, Any],
    fallback_threshold: float,
) -> tuple[float, dict[str, int], dict[str, str]]:
    """Read sanitized count/action/threshold metadata written by ``PiiEnricher``."""
    raw = extra.get("pii_audit")
    if not isinstance(raw, Mapping):
        return fallback_threshold, {}, {}
    thresh_raw = raw.get("threshold", fallback_threshold)
    threshold = float(thresh_raw) if isinstance(thresh_raw, int | float) else fallback_threshold
    counts_raw = raw.get("entity_counts")
    counts = (
        {str(k): int(v) for k, v in counts_raw.items()} if isinstance(counts_raw, Mapping) else {}
    )
    actions_raw = raw.get("actions")
    actions = (
        {str(k): str(v) for k, v in actions_raw.items()} if isinstance(actions_raw, Mapping) else {}
    )
    return threshold, counts, actions


def _extract_document_chunks(
    file_path: Path,
    *,
    source_key: str,
    content_hash: str | None,
    collection: str,
    embed_model: str,
    profile: ChunkingProfile,
    cleaner: Cleaner,
    enrichers: Sequence[Enricher],
    chunker: Chunker,
    pii_policy: PiiPolicy | None = None,
    audit_threshold: float | None = None,
    persist_path: Path | None = None,
    audit_mode: str | None = None,
    metrics: _BatchStageMetrics | None = None,
) -> tuple[str, str, list[Chunk], PiiAuditRecord | None]:
    """Parse, clean, enrich, and chunk a changed source document."""
    if content_hash is None:
        raise DocpipeError(f"Missing content hash for non-unchanged file: {source_key}")
    doc_version = content_hash.split(":", 1)[1][:12]

    t_in = time.perf_counter()
    with stage_event(
        logger,
        "intake",
        log_level=logging.DEBUG,
        collection=collection,
        source=source_key,
    ) as intake_ev:
        parsed: ParsedDocument = resolve_parser(file_path).parse(file_path, source_key=source_key)
        intake_ev["sections"] = len(parsed.sections)
    if metrics is not None:
        metrics.intake_ms += (time.perf_counter() - t_in) * 1000.0
        metrics.docs_processed += 1
        metrics.sections_parsed += len(parsed.sections)

    t_cl = time.perf_counter()
    with stage_event(
        logger,
        "clean",
        log_level=logging.DEBUG,
        collection=collection,
        source=source_key,
    ) as clean_ev:
        cleaned = cleaner.clean(parsed)
        clean_ev["sections"] = len(cleaned.sections)
    if metrics is not None:
        metrics.clean_ms += (time.perf_counter() - t_cl) * 1000.0

    extra: dict[str, Any] = {}
    ctx: IngestContext = {
        "collection": collection,
        "source": source_key,
        "content_hash": content_hash,
        "doc_version": doc_version,
        "embed_model": embed_model,
        "profile": profile.name,
        "extra": extra,
    }
    if pii_policy is not None:
        ctx["pii_policy"] = pii_policy

    fallback_thresh = audit_threshold if audit_threshold is not None else 0.5
    t_en = time.perf_counter()
    with stage_event(
        logger,
        "enrich",
        log_level=logging.DEBUG,
        collection=collection,
        source=source_key,
        profile=profile.name,
        pii_active=pii_policy is not None,
    ) as enrich_ev:
        try:
            enriched = _apply_enrichers(cleaned, enrichers, ctx)
        except PiiBlockedError as exc:
            if pii_policy is not None and persist_path is not None and audit_mode is not None:
                resolved_thresh, _, _ = _extract_audit_fields(extra, fallback_thresh)
                blocked_record = _build_pii_audit_record(
                    collection=collection,
                    source_key=source_key,
                    doc_version=doc_version,
                    threshold=resolved_thresh,
                    entity_counts=exc.entity_counts,
                    actions=exc.actions,
                    blocked=True,
                    mode=audit_mode,
                )
                append_audit_record(persist_path, collection, blocked_record)
            raise
        if pii_policy is not None:
            _, pre_counts, _ = _extract_audit_fields(extra, fallback_thresh)
            detected = sum(pre_counts.values())
            enrich_ev["entities_detected"] = detected
            if metrics is not None:
                metrics.entities_detected += detected
    if metrics is not None:
        metrics.enrich_ms += (time.perf_counter() - t_en) * 1000.0

    t_ch = time.perf_counter()
    with stage_event(
        logger,
        "chunk",
        log_level=logging.DEBUG,
        collection=collection,
        source=source_key,
        profile=profile.name,
    ) as chunk_ev:
        chunks = chunker.chunk(
            enriched,
            profile=profile,
            doc_version=doc_version,
            embed_model=embed_model,
        )
        child_cnt = sum(1 for c in chunks if c.metadata["type"] == "child")
        parent_cnt = sum(1 for c in chunks if c.metadata["type"] == "parent")
        chunk_ev["children"] = child_cnt
        chunk_ev["parents"] = parent_cnt
    if metrics is not None:
        metrics.chunk_ms += (time.perf_counter() - t_ch) * 1000.0
        metrics.children_chunked += child_cnt
        metrics.parents_chunked += parent_cnt

    audit_record: PiiAuditRecord | None = None
    if pii_policy is not None and audit_mode is not None:
        resolved_thresh, counts, actions = _extract_audit_fields(extra, fallback_thresh)
        audit_record = _build_pii_audit_record(
            collection=collection,
            source_key=source_key,
            doc_version=doc_version,
            threshold=resolved_thresh,
            entity_counts=counts,
            actions=actions,
            blocked=False,
            mode=audit_mode,
        )
    return content_hash, doc_version, chunks, audit_record


def _embed_document_chunks(
    chunks: list[Chunk],
    *,
    embedder_inst: Embedder,
    embed_model: str,
    collection: str = "",
    metrics: _BatchStageMetrics | None = None,
) -> tuple[list[EmbeddedChunk], int]:
    """Embed all child chunks in memory and attach zero vectors to parent sections."""
    child_chunks = [c for c in chunks if c.metadata["type"] == "child"]
    parent_chunks = [c for c in chunks if c.metadata["type"] == "parent"]

    t_em = time.perf_counter()
    with stage_event(
        logger,
        "embed",
        log_level=logging.DEBUG,
        collection=collection,
        embed_model=embed_model,
        chunks=len(child_chunks),
    ) as embed_ev:
        child_vectors = embedder_inst.embed_texts([c.text for c in child_chunks], model=embed_model)
        if not child_vectors:
            embed_ev["dim"] = 0
            return [], 0
        dim = len(child_vectors[0])
        embed_ev["dim"] = dim
    if metrics is not None:
        metrics.embed_ms += (time.perf_counter() - t_em) * 1000.0
        metrics.chunks_embedded += len(child_chunks)
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
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> IngestResult:
    """Ingest a file or directory atomically into the vector database.

    Validates, parses, cleans, chunks, and embeds all changed files in memory
    *before* initializing or mutating ``Store``. Each changed document is
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
        cleaner: Registered ``CLEANERS`` key (defaults to ``"default"``).
        chunker: Registered ``CHUNKERS`` key (defaults to ``"default"``).
        embedder: Registered ``EMBEDDERS`` key (defaults to ``"default"``).
        store: Registered ``STORES`` key (defaults to ``"default"``).
        pii_policy: Optional programmatic ``PiiPolicy`` enforced pre-chunking.
        local_only: When ``True``, refuse non-local ``embed_model`` targets.

    Returns:
        Summary of ingested/skipped source keys and written child/parent counts.

    Raises:
        UnsupportedFormatError: If ``path`` is missing, empty, or contains an
            unsupported/corrupted file (aborts the entire batch before writes).
        MissingExtraError: If a required format extra (``pdf``, ``docx``,
            ``html``, ``pii``) is not installed.
        ModelMismatchError: If ``collection`` is already locked to another model.
        MissingCredentialError: If provider credentials are missing or invalid.
        PiiBlockedError: If configured ``block`` PII rules match any section.
        RegistryError: If any requested stage key is unregistered.
        DocpipeError: If embedding, ``local_only``, or store initialization fails.
    """
    with correlation_id():
        return _ingest_impl(
            path,
            profile=profile,
            collection=collection,
            persist_dir=persist_dir,
            embed_model=embed_model,
            force=force,
            cleaner=cleaner,
            chunker=chunker,
            embedder=embedder,
            store=store,
            pii_policy=pii_policy,
            local_only=local_only,
        )


def _ingest_impl(
    path: str | Path,
    *,
    profile: str | ChunkingProfile,
    collection: str,
    persist_dir: str | Path,
    embed_model: str,
    force: bool,
    cleaner: str,
    chunker: str,
    embedder: str,
    store: str,
    pii_policy: PiiPolicy | None,
    local_only: bool,
) -> IngestResult:
    """Execute atomic batch ingestion inside an active correlation scope."""
    if local_only:
        from docpipe_maestro.embedder import enforce_local_only

        enforce_local_only(embed_model, operation="ingest")

    audit_threshold: float | None = None
    if pii_policy is not None:
        from docpipe_maestro._pii import validate_pii_policy

        audit_threshold = validate_pii_policy(pii_policy).min_confidence

    target = Path(path)
    persist_path = Path(persist_dir)
    prof = resolve_profile(profile)

    manifest = load_manifest(persist_path, collection)
    check_model_lock(manifest, embed_model)

    discovered = _discover_files(target, persist_path=persist_path)

    cleaner_inst: Cleaner = CLEANERS.resolve(cleaner)()
    enricher_names = _effective_enricher_names(prof.enrichers, pii_policy=pii_policy)
    enricher_insts: list[Enricher] = _resolve_enrichers(enricher_names)
    chunker_inst: Chunker = CHUNKERS.resolve(chunker)()
    embedder_inst: Embedder = EMBEDDERS.resolve(embedder)()
    store_cls: type[Store] = STORES.resolve(store)

    # Atomic batch validation & in-memory parsing/chunking/embedding before touching the DB
    metrics = _BatchStageMetrics()
    staged_docs: list[tuple[str, str, str, int, float, list[EmbeddedChunk], int]] = []
    staged_audits: dict[str, PiiAuditRecord] = {}
    skipped: list[str] = []
    manifest_dirty = False

    for file_path, source_key in discovered:
        status_flag, content_hash, size, mtime = classify_file(
            file_path, source_key, manifest, force=force
        )
        if status_flag == "unchanged":
            skipped.append(source_key)
            existing = manifest.sources[source_key]
            if existing.size != size or existing.mtime != mtime:
                existing.size = size
                existing.mtime = mtime
                manifest_dirty = True
            continue

        content_hash, doc_version, chunks, audit_record = _extract_document_chunks(
            file_path,
            source_key=source_key,
            content_hash=content_hash,
            collection=collection,
            embed_model=embed_model,
            profile=prof,
            cleaner=cleaner_inst,
            enrichers=enricher_insts,
            chunker=chunker_inst,
            pii_policy=pii_policy,
            audit_threshold=audit_threshold,
            persist_path=persist_path,
            audit_mode="ingest",
            metrics=metrics,
        )
        embedded, dim = _embed_document_chunks(
            chunks,
            embedder_inst=embedder_inst,
            embed_model=embed_model,
            collection=collection,
            metrics=metrics,
        )
        staged_docs.append((source_key, content_hash, doc_version, size, mtime, embedded, dim))
        if audit_record is not None:
            staged_audits[source_key] = audit_record

    _emit_phase1_prep_summaries(
        collection=collection,
        profile_name=prof.name,
        embed_model=embed_model,
        skipped_count=len(skipped),
        metrics=metrics,
        pii_active=pii_policy is not None,
    )

    ingested: list[str] = []
    chunks_written = 0
    parents_written = 0

    with stage_event(
        logger,
        "store",
        operation="ingest",
        collection=collection,
        skipped=len(skipped),
    ) as store_ev:
        if manifest_dirty and not staged_docs:
            save_manifest(persist_path, manifest)

        store_obj: Store = store_cls(persist_path, collection)
        lexical = LexicalIndex(persist_path, collection)
        active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
        store_obj.sweep_uncommitted(active_versions)
        lexical.sweep_uncommitted(active_versions)

        for source_key, content_hash, doc_version, size, mtime, embedded, dim in staged_docs:
            store_obj.add_chunks(embedded)
            lexical.add_chunks(embedded)

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
            staged_audit = staged_audits.get(source_key)
            if staged_audit is not None:
                append_audit_record(persist_path, collection, staged_audit)
            store_obj.delete_stale_versions(source_key, doc_version)
            lexical.delete_stale_versions(source_key, doc_version)

            ingested.append(source_key)
            chunks_written += len(child_ids)
            parents_written += len(parent_ids)

        store_ev["ingested"] = len(ingested)
        store_ev["children"] = chunks_written
        store_ev["parents"] = parents_written

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
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
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
        cleaner: Registered ``CLEANERS`` key (defaults to ``"default"``).
        chunker: Registered ``CHUNKERS`` key (defaults to ``"default"``).
        embedder: Registered ``EMBEDDERS`` key (defaults to ``"default"``).
        store: Registered ``STORES`` key (defaults to ``"default"``).
        pii_policy: Optional programmatic ``PiiPolicy`` enforced pre-chunking.
        local_only: When ``True``, refuse non-local ``embed_model`` targets.

    Returns:
        ``SyncResult`` listing ``added``, ``updated``, ``skipped``, and
        ``removed`` canonical source keys.

    Raises:
        UnsupportedFormatError: If ``directory`` is not a directory or contains
            an unsupported/corrupted file.
        MissingExtraError: If a required format parser or ``pii`` extra is missing.
        ModelMismatchError: If ``collection`` is locked to a different model.
        MissingCredentialError: If embedding credentials are missing or invalid.
        PiiBlockedError: If configured ``block`` PII rules match any section.
        RegistryError: If any requested stage key is unregistered.
        DocpipeError: If embedding, ``local_only``, or store operations fail.
    """
    with correlation_id():
        return _sync_impl(
            directory,
            profile=profile,
            collection=collection,
            persist_dir=persist_dir,
            embed_model=embed_model,
            cleaner=cleaner,
            chunker=chunker,
            embedder=embedder,
            store=store,
            pii_policy=pii_policy,
            local_only=local_only,
        )


def _sync_impl(
    directory: str | Path,
    *,
    profile: str | ChunkingProfile,
    collection: str,
    persist_dir: str | Path,
    embed_model: str,
    cleaner: str,
    chunker: str,
    embedder: str,
    store: str,
    pii_policy: PiiPolicy | None,
    local_only: bool,
) -> SyncResult:
    """Execute three-way directory reconciliation inside an active correlation scope."""
    if local_only:
        from docpipe_maestro.embedder import enforce_local_only

        enforce_local_only(embed_model, operation="sync")

    audit_threshold: float | None = None
    if pii_policy is not None:
        from docpipe_maestro._pii import validate_pii_policy

        audit_threshold = validate_pii_policy(pii_policy).min_confidence

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

    cleaner_inst: Cleaner = CLEANERS.resolve(cleaner)()
    enricher_names = _effective_enricher_names(prof.enrichers, pii_policy=pii_policy)
    enricher_insts: list[Enricher] = _resolve_enrichers(enricher_names)
    chunker_inst: Chunker = CHUNKERS.resolve(chunker)()
    embedder_inst: Embedder = EMBEDDERS.resolve(embedder)()
    store_cls: type[Store] = STORES.resolve(store)

    metrics = _BatchStageMetrics()
    staged_docs: list[tuple[str, str, str, str, int, float, list[EmbeddedChunk], int]] = []
    staged_audits: dict[str, PiiAuditRecord] = {}
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

        content_hash, doc_version, chunks, audit_record = _extract_document_chunks(
            file_path,
            source_key=source_key,
            content_hash=content_hash,
            collection=collection,
            embed_model=embed_model,
            profile=prof,
            cleaner=cleaner_inst,
            enrichers=enricher_insts,
            chunker=chunker_inst,
            pii_policy=pii_policy,
            audit_threshold=audit_threshold,
            persist_path=persist_path,
            audit_mode="sync",
            metrics=metrics,
        )
        embedded, dim = _embed_document_chunks(
            chunks,
            embedder_inst=embedder_inst,
            embed_model=embed_model,
            collection=collection,
            metrics=metrics,
        )
        staged_docs.append(
            (status_flag, source_key, content_hash, doc_version, size, mtime, embedded, dim)
        )
        if audit_record is not None:
            staged_audits[source_key] = audit_record

    _emit_phase1_prep_summaries(
        collection=collection,
        profile_name=prof.name,
        embed_model=embed_model,
        skipped_count=len(skipped),
        metrics=metrics,
        pii_active=pii_policy is not None,
    )

    added: list[str] = []
    updated: list[str] = []

    with stage_event(
        logger,
        "store",
        operation="sync",
        collection=collection,
        skipped=len(skipped),
    ) as store_ev:
        store_obj: Store = store_cls(persist_path, collection)
        lexical = LexicalIndex(persist_path, collection)
        active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
        store_obj.sweep_uncommitted(active_versions)
        lexical.sweep_uncommitted(active_versions)

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
            store_obj.add_chunks(embedded)
            lexical.add_chunks(embedded)
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
            staged_audit = staged_audits.get(source_key)
            if staged_audit is not None:
                append_audit_record(persist_path, collection, staged_audit)
            store_obj.delete_stale_versions(source_key, doc_version)
            lexical.delete_stale_versions(source_key, doc_version)

            if doc_status == "new":
                added.append(source_key)
            else:
                updated.append(source_key)

        for source_key in removed_keys:
            store_obj.delete_by_source(source_key)
            if lexical.exists():
                lexical.delete_by_source(source_key)
            manifest.sources.pop(source_key, None)
            manifest_dirty = True

        if manifest_dirty:
            save_manifest(persist_path, manifest)

        store_ev["added"] = len(added)
        store_ev["updated"] = len(updated)
        store_ev["removed"] = len(removed_keys)

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
    store: str = "default",
) -> bool:
    """Remove all vector records and the manifest entry for a single source.

    Args:
        source: Canonical source key tracked in the collection manifest.
        collection: Target collection name.
        persist_dir: Local persistence directory.
        store: Registered ``STORES`` key (defaults to ``"default"``).

    Returns:
        ``True`` if the source existed and was purged, ``False`` otherwise.
    """
    with correlation_id():
        if store != "default":
            STORES.resolve(store)
        source_key = Path(source).as_posix()
        persist_path = Path(persist_dir)
        with stage_event(
            logger,
            "store",
            operation="remove",
            collection=collection,
            source=source_key,
        ) as store_ev:
            manifest = load_manifest(persist_path, collection)
            if source_key not in manifest.sources:
                store_ev["removed"] = False
                return False

            store_obj: Store = STORES.resolve(store)(persist_path, collection)
            store_obj.delete_by_source(source_key)
            lexical = LexicalIndex(persist_path, collection)
            if lexical.exists():
                lexical.delete_by_source(source_key)
            manifest.sources.pop(source_key)
            save_manifest(persist_path, manifest)
            store_ev["removed"] = True
            return True


def status(
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    store: str = "default",
) -> CollectionStatus:
    """Return a read-only summary of the collection's manifest state.

    Args:
        collection: Target collection name.
        persist_dir: Local persistence directory.
        store: Registered ``STORES`` key (defaults to ``"default"``). Non-default
            keys are validated against ``STORES`` while source metrics are read
            from the collection JSON manifest.

    Returns:
        ``CollectionStatus`` containing locked model metadata, aggregate child
        and parent counts, and sorted per-source ``SourceRecord`` entries.
    """
    with correlation_id():
        if store != "default":
            STORES.resolve(store)
        with stage_event(logger, "store", operation="status", collection=collection) as store_ev:
            manifest = load_manifest(Path(persist_dir), collection)
            sources = sorted(manifest.sources.values(), key=lambda s: s.source)
            total_children = sum(len(s.chunk_ids) for s in sources)
            total_parents = sum(len(s.parent_ids) for s in sources)
            store_ev["sources"] = len(sources)
            store_ev["children"] = total_children
            store_ev["parents"] = total_parents
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
    embedder: str = "default",
    store: str = "default",
    local_only: bool = False,
) -> int:
    """Re-embed all existing stored child chunks under a new embedding model.

    Computes all new child vectors in memory first, updates parent zero-vector
    dimensions to match, rebuilds the vector collection cleanly, and updates
    the manifest's model lock and vector dimensionality.

    Args:
        embed_model: New LiteLLM ``provider/model`` identifier for the collection.
        collection: Target collection name.
        persist_dir: Local persistence directory.
        embedder: Registered ``EMBEDDERS`` key (defaults to ``"default"``).
        store: Registered ``STORES`` key (defaults to ``"default"``).
        local_only: When ``True``, refuse non-local ``embed_model`` targets.

    Returns:
        Count of committed child chunks re-embedded.

    Raises:
        MissingCredentialError: If provider credentials for ``embed_model`` fail.
        RegistryError: If ``embedder`` or ``store`` is unregistered.
        DocpipeError: If embedding, ``local_only``, or collection recreation fails.
    """
    with correlation_id():
        return _reindex_impl(
            embed_model=embed_model,
            collection=collection,
            persist_dir=persist_dir,
            embedder=embedder,
            store=store,
            local_only=local_only,
        )


def _reindex_impl(
    *,
    embed_model: str,
    collection: str,
    persist_dir: str | Path,
    embedder: str,
    store: str,
    local_only: bool,
) -> int:
    """Execute full collection re-embedding inside an active correlation scope."""
    if local_only:
        from docpipe_maestro.embedder import enforce_local_only

        enforce_local_only(embed_model, operation="reindex")

    persist_path = Path(persist_dir)
    manifest = load_manifest(persist_path, collection)
    embedder_inst: Embedder = EMBEDDERS.resolve(embedder)()
    store_obj: Store = STORES.resolve(store)(persist_path, collection)

    active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
    children = [
        c
        for c in store_obj.get_all_children()
        if active_versions.get(c.metadata["source"]) == c.metadata["doc_version"]
    ]
    parents = [
        p
        for p in store_obj.get_all_parents()
        if active_versions.get(p.metadata["source"]) == p.metadata["doc_version"]
    ]

    if not children:
        with stage_event(
            logger,
            "store",
            operation="reindex",
            collection=collection,
            chunks=0,
            parents=len(parents),
        ):
            manifest.embed_model = embed_model
            manifest.embed_dim = None
            save_manifest(persist_path, manifest)
        return 0

    # Embed all children in memory before mutating store or manifest
    with stage_event(
        logger,
        "embed",
        operation="reindex",
        collection=collection,
        embed_model=embed_model,
        chunks=len(children),
    ) as embed_ev:
        new_vectors = embedder_inst.embed_texts([c.text for c in children], model=embed_model)
        new_dim = len(new_vectors[0])
        embed_ev["dim"] = new_dim
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

    with stage_event(
        logger,
        "store",
        operation="reindex",
        collection=collection,
        chunks=len(children),
        parents=len(parents),
    ):
        store_obj.reset_collection()
        store_obj.add_chunks(rebuilt)
        lexical = LexicalIndex(persist_path, collection)
        lexical.reset()
        lexical.add_chunks(rebuilt)

        manifest.embed_model = embed_model
        manifest.embed_dim = new_dim
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in manifest.sources.values():
            rec.embed_model = embed_model
            rec.ingested_at = now_iso
        save_manifest(persist_path, manifest)
    return len(children)
