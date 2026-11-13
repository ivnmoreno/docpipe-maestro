"""Unit tests for the ChromaDB VectorStore adapter."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro.store import VectorStore
from docpipe_maestro.types import EmbeddedChunk
from tests.conftest import EMBED_DIM, deterministic_embed


def _make_pair(source: str, doc_version: str, text: str) -> tuple[EmbeddedChunk, EmbeddedChunk]:
    parent_id = f"p_{doc_version}_{source}"
    child_id = f"c_{doc_version}_{source}"
    parent = EmbeddedChunk(
        id=parent_id,
        text=f"Full section: {text}",
        parent_id=None,
        metadata={
            "type": "parent",
            "source": source,
            "doc_version": doc_version,
            "section": "Section 1",
            "clause": None,
            "page": None,
            "chunk_index": 0,
            "embed_model": "ollama/nomic-embed-text",
        },
        vector=[0.0] * EMBED_DIM,
    )
    child = EmbeddedChunk(
        id=child_id,
        text=f"[Source: {source} | Section: Section 1]\n{text}",
        parent_id=parent_id,
        metadata={
            "type": "child",
            "source": source,
            "doc_version": doc_version,
            "section": "Section 1",
            "clause": "1.1",
            "page": 2,
            "chunk_index": 0,
            "embed_model": "ollama/nomic-embed-text",
        },
        vector=deterministic_embed([text])[0],
    )
    return parent, child


def test_store_roundtrip_none_metadata_and_parent_filter(tmp_persist_dir: Path) -> None:
    store = VectorStore(tmp_persist_dir, "test_col")
    parent, child = _make_pair("policy.md", "v1", "Employees receive 20 days of annual leave.")
    store.add_chunks([parent, child])

    qvec = deterministic_embed(["annual leave days"])[0]
    matches = store.query_children(qvec, top_k=5)
    assert len(matches) == 1
    assert matches[0].id == child.id
    assert matches[0].parent_id == parent.id
    assert matches[0].metadata["type"] == "child"
    assert matches[0].metadata["page"] == 2
    assert 0.0 <= matches[0].score <= 1.0

    parents = store.get_by_ids([parent.id])
    assert len(parents) == 1
    assert parents[0].metadata["clause"] is None
    assert parents[0].metadata["page"] is None
    assert parents[0].parent_id is None


def test_store_version_isolation_and_delete(tmp_persist_dir: Path) -> None:
    store = VectorStore(tmp_persist_dir, "test_ver")
    p1, c1 = _make_pair("doc.md", "v1", "Old leave rule 15 days.")
    p2, c2 = _make_pair("doc.md", "v2", "New leave rule 25 days.")
    store.add_chunks([p1, c1, p2, c2])

    qvec = deterministic_embed(["leave rule days"])[0]
    # When active_versions points to v1, v2 staging records are ignored
    matches = store.query_children(qvec, top_k=5, active_versions={"doc.md": "v1"})
    assert [m.id for m in matches] == [c1.id]

    store.delete_stale_versions("doc.md", "v2")
    remaining = store.get_all_children()
    assert [c.id for c in remaining] == [c2.id]

    store.delete_by_source("doc.md")
    assert store.get_all_children() == []
    assert store.get_all_parents() == []


def test_store_query_and_get_skip_embeddings_by_default(tmp_persist_dir: Path) -> None:
    store = VectorStore(tmp_persist_dir, "test_vec_opt")
    parent, child = _make_pair("policy.md", "v1", "Remote VPN policy requires MFA.")
    store.add_chunks([parent, child])

    qvec = deterministic_embed(["Remote VPN MFA"])[0]
    default_matches = store.query_children(qvec, top_k=5)
    assert len(default_matches) == 1
    assert default_matches[0].vector == []

    default_parents = store.get_by_ids([parent.id])
    assert len(default_parents) == 1
    assert default_parents[0].vector == []

    with_vecs = store.query_children(qvec, top_k=5, include_embeddings=True)
    assert len(with_vecs[0].vector) == EMBED_DIM
    parents_with_vecs = store.get_by_ids([parent.id], include_embeddings=True)
    assert len(parents_with_vecs[0].vector) == EMBED_DIM

    by_source = store.get_parents_by_source("policy.md", active_doc_version="v1")
    assert [p.id for p in by_source] == [parent.id]
    assert by_source[0].vector == []
