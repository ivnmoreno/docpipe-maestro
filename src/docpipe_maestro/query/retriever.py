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
from docpipe_maestro.manifest import check_model_lock, load_manifest
from docpipe_maestro.store import VectorStore
from docpipe_maestro.types import RetrievedChunk


def retrieve(
    question: str,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    top_k: int = DEFAULT_TOP_K,
    threshold: float | None = None,
    expand_parent: bool = True,
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

    child_matches = store.query_children(
        query_vec,
        top_k=top_k,
        active_versions=active_versions,
    )

    if threshold is not None:
        child_matches = [c for c in child_matches if c.score >= threshold]

    if not child_matches:
        return []

    if not expand_parent:
        return sorted(child_matches, key=lambda c: c.score, reverse=True)

    parent_scores: dict[str, float] = {}
    for child in child_matches:
        if child.parent_id is None:
            continue
        prev = parent_scores.get(child.parent_id)
        if prev is None or child.score > prev:
            parent_scores[child.parent_id] = child.score

    if not parent_scores:
        return []

    parents = store.get_by_ids(list(parent_scores.keys()))
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
    return retrieved_parents
