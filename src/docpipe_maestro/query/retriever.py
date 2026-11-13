"""Phase 2 read-only semantic retrieval, parent expansion, and deduplication."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_PERSIST_DIR,
    DEFAULT_TOP_K,
)
from docpipe_maestro.embedder import embed_query
from docpipe_maestro.ingest.crossrefs import (
    extract_doc_crossrefs,
    index_section_targets,
    match_source_key,
    truncate_excerpt,
)
from docpipe_maestro.manifest import check_model_lock, load_manifest
from docpipe_maestro.store import VectorStore
from docpipe_maestro.types import EmbeddedChunk, RetrievedChunk


def _enrich_crossdoc_references(
    sections: list[RetrievedChunk],
    *,
    store: VectorStore,
    active_versions: dict[str, str],
) -> list[RetrievedChunk]:
    """Resolve explicit cross-document section/clause references cleanly in 1 hop."""
    if not sections or len(active_versions) < 2:
        return sections

    available_sources = list(active_versions)
    present_ids = {sec.id for sec in sections}
    target_cache: dict[str, tuple[list[EmbeddedChunk], dict[str, tuple[str, int]]]] = {}

    enriched: list[RetrievedChunk] = []
    for sec in sections:
        refs = extract_doc_crossrefs(sec.text)
        if not refs:
            enriched.append(sec)
            continue

        notes: list[str] = []
        current_source = sec.metadata["source"]
        for display, lookup_keys, doc_phrase in refs:
            target_source = match_source_key(
                doc_phrase,
                available_sources,
                current_source=current_source,
            )
            if target_source is None:
                continue

            cached = target_cache.get(target_source)
            if cached is None:
                target_parents = store.get_parents_by_source(
                    target_source,
                    active_doc_version=active_versions[target_source],
                    include_embeddings=False,
                )
                target_index = index_section_targets(
                    [(p.metadata["section"], p.text) for p in target_parents]
                )
                cached = (target_parents, target_index)
                target_cache[target_source] = cached

            target_parents, target_index = cached
            match_val: tuple[str, int] | None = None
            for key in lookup_keys:
                if key in target_index:
                    match_val = target_index[key]
                    break
            if match_val is None:
                continue

            resolved_text, sec_idx = match_val
            if target_parents[sec_idx].id in present_ids:
                continue
            excerpt = truncate_excerpt(resolved_text, 400)
            note = f"[Crossref {display} ({target_source}): {excerpt}]"
            if note not in notes and note not in sec.text:
                notes.append(note)

        if not notes:
            enriched.append(sec)
        else:
            enriched.append(
                RetrievedChunk(
                    id=sec.id,
                    text=f"{sec.text}\n\n" + "\n".join(notes),
                    parent_id=sec.parent_id,
                    metadata=sec.metadata,
                    vector=sec.vector,
                    score=sec.score,
                )
            )
    return enriched


def retrieve(
    question: str,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    top_k: int = DEFAULT_TOP_K,
    threshold: float | None = None,
    expand_parent: bool = True,
    follow_crossrefs: bool = True,
) -> list[RetrievedChunk]:
    """Retrieve relevant parent sections (or child chunks) for a question.

    Treats both the vector store and manifest as strictly read-only. Searches
    only committed ``"child"`` chunks, optionally filters by normalized cosine
    similarity (``[0.0, 1.0]``), and when ``expand_parent`` is ``True`` fetches
    unique parent sections scored by ``max(child.score)``.

    Args:
        question: Natural-language search query.
        collection: Target collection name.
        persist_dir: Local persistence directory.
        embed_model: Embedding ``provider/model`` matching the collection lock.
        top_k: Maximum matched child chunks queried before parent deduplication.
        threshold: Optional minimum normalized similarity score in ``[0.0, 1.0]``.
        expand_parent: If ``True``, expand matched children to deduplicated
            parent sections; if ``False``, return matched child chunks directly.
        follow_crossrefs: When ``expand_parent`` and ``follow_crossrefs`` are
            ``True``, resolves explicit cross-document section/clause citations
            into non-recursive ``[Crossref ...]`` annotations when the target
            section is absent from top-k results.

    Returns:
        Matched ``RetrievedChunk`` objects ordered by descending ``score``.

    Raises:
        ModelMismatchError: If ``embed_model`` mismatches the collection lock.
        MissingCredentialError: If provider credentials are missing or invalid.
        DocpipeError: If embedding or store lookup fails.
    """
    persist_path = Path(persist_dir)
    manifest = load_manifest(persist_path, collection)
    check_model_lock(manifest, embed_model)

    if not manifest.sources or top_k <= 0:
        return []

    query_vec = embed_query(question, model=embed_model)
    store = VectorStore(persist_path, collection)
    active_versions = {k: v.doc_version for k, v in manifest.sources.items()}

    child_top_k = top_k * 3 if expand_parent else top_k
    child_matches = store.query_children(
        query_vec,
        top_k=child_top_k,
        active_versions=active_versions,
        include_embeddings=False,
    )

    if threshold is not None:
        child_matches = [c for c in child_matches if c.score >= threshold]

    if not child_matches:
        return []

    if not expand_parent:
        return sorted(child_matches, key=lambda c: c.score, reverse=True)[:top_k]

    parent_scores: dict[str, float] = {}
    for child in child_matches:
        if child.parent_id is None:
            continue
        prev = parent_scores.get(child.parent_id)
        if prev is None or child.score > prev:
            parent_scores[child.parent_id] = child.score

    if not parent_scores:
        return []

    top_parent_ids = sorted(
        parent_scores,
        key=lambda pid: parent_scores[pid],
        reverse=True,
    )[:top_k]
    parents = store.get_by_ids(top_parent_ids, include_embeddings=False)
    retrieved_parents = [
        RetrievedChunk(
            id=p.id,
            text=p.text,
            parent_id=p.parent_id,
            metadata=p.metadata,
            vector=p.vector,
            score=parent_scores[p.id],
        )
        for p in parents
        if p.id in parent_scores
    ]
    retrieved_parents.sort(key=lambda r: r.score, reverse=True)
    top_parents = retrieved_parents[:top_k]
    if follow_crossrefs:
        return _enrich_crossdoc_references(
            top_parents,
            store=store,
            active_versions=active_versions,
        )
    return top_parents
