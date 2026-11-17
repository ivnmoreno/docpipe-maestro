"""Unit tests for the ChromaDB VectorStore adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro.store import LexicalIndex, VectorStore
from docpipe_maestro.types import DocpipeError, EmbeddedChunk
from tests.conftest import EMBED_DIM, deterministic_embed


def _make_pair(
    source: str,
    doc_version: str,
    text: str,
    *,
    clause: str | None = "1.1",
    page: int | None = 2,
    chunk_index: int = 0,
) -> tuple[EmbeddedChunk, EmbeddedChunk]:
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
            "clause": clause,
            "page": page,
            "chunk_index": chunk_index,
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

    all_children_default = store.get_all_children()
    all_parents_default = store.get_all_parents()
    assert len(all_children_default) == 1 and all_children_default[0].vector == []
    assert len(all_parents_default) == 1 and all_parents_default[0].vector == []

    all_children_vecs = store.get_all_children(include_embeddings=True)
    all_parents_vecs = store.get_all_parents(include_embeddings=True)
    assert len(all_children_vecs[0].vector) == EMBED_DIM
    assert len(all_parents_vecs[0].vector) == EMBED_DIM


def test_store_where_defense_in_depth_and_optional_nulls(tmp_persist_dir: Path) -> None:
    store = VectorStore(tmp_persist_dir, "store_where")
    lexical = LexicalIndex(tmp_persist_dir, "store_where")
    p1, c1 = _make_pair(
        "a.md",
        "v1",
        "Leave requests require notice and manager approval.",
        clause="1.1",
        page=2,
        chunk_index=0,
    )
    p2, c2 = _make_pair(
        "b.md",
        "v2",
        "Emergency leave requests waive advance notice.",
        clause=None,
        page=None,
        chunk_index=5,
    )
    store.add_chunks([p1, c1, p2, c2])
    lexical.add_chunks([c1, c2])
    active = {"a.md": "v1", "b.md": "v2"}

    qvec = deterministic_embed(["leave notice approval"])[0]

    # Defense-in-depth: direct store or lexical lookup with type='parent' never returns parents.
    assert (
        store.query_children(qvec, top_k=5, active_versions=active, where={"type": "parent"}) == []
    )
    assert lexical.search("leave", top_k=5, active_versions=active, where={"type": "parent"}) == []
    assert (
        lexical.search(
            "leave", top_k=5, active_versions=active, where={"type": {"$in": ["parent"]}}
        )
        == []
    )

    # Direct store accepts type='child' safely.
    assert [
        m.id
        for m in store.query_children(
            qvec, top_k=5, active_versions=active, where={"type": "child"}
        )
    ]

    # Multi-operator dict and missing-attribute $ne/$nin behave identically across stores.
    for expr in (
        {"page": {"$gte": 1, "$lte": 3}},
        {"chunk_index": {"$gte": 5}},
        {"$or": [{"source": "a.md"}, {"chunk_index": 5}]},
    ):
        v_ids = {
            m.id for m in store.query_children(qvec, top_k=5, active_versions=active, where=expr)
        }
        l_ids = {m.id for m in lexical.search("leave", top_k=5, active_versions=active, where=expr)}
        assert v_ids == l_ids and v_ids

    # Absent page (None) and absent clause (None in Chroma, '' in FTS5) match $ne and $nin.
    for neg_expr in ({"page": {"$ne": 2}}, {"page": {"$nin": [2]}}, {"clause": {"$ne": "1.1"}}):
        v_ids = {
            m.id
            for m in store.query_children(qvec, top_k=5, active_versions=active, where=neg_expr)
        }
        l_ids = {
            m.id for m in lexical.search("leave", top_k=5, active_versions=active, where=neg_expr)
        }
        assert v_ids == {c2.id}
        assert l_ids == {c2.id}

    # Unknown keys fail cleanly in direct store & lexical lookup.
    with pytest.raises(DocpipeError, match="Unsupported filter key"):
        store.query_children(qvec, top_k=5, where={"author": "alice"})
    with pytest.raises(DocpipeError, match="Unsupported filter key"):
        lexical.search("leave", top_k=5, where={"author": "alice"})


def _active_systems_for(persist_dir: Path) -> list[str]:
    """Return active ChromaDB SharedSystemClient keys targeting ``persist_dir``."""
    from chromadb.api.shared_system_client import SharedSystemClient

    target = persist_dir.resolve()
    return [
        key for key in SharedSystemClient._identifier_to_system if Path(key).resolve() == target
    ]


def test_store_lifecycle_close_and_context_manager(
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with VectorStore(tmp_persist_dir, "ctx_col") as store:
        assert _active_systems_for(tmp_persist_dir)
        parent, child = _make_pair("ctx.md", "v1", "Context managers release Chroma handles.")
        store.add_chunks([parent, child])
        hits = store.query_children(deterministic_embed(["release Chroma handles"])[0], top_k=2)
        assert [h.id for h in hits] == [child.id]

    assert _active_systems_for(tmp_persist_dir) == []
    store.close()  # Idempotent second close

    # Multiple concurrent handles keep the shared system alive until the last close().
    s1 = VectorStore(tmp_persist_dir, "shared_a")
    s2 = VectorStore(tmp_persist_dir, "shared_b")
    assert _active_systems_for(tmp_persist_dir)
    s1.close()
    assert _active_systems_for(tmp_persist_dir)
    s2.close()
    assert _active_systems_for(tmp_persist_dir) == []

    # Failed collection initialization closes the underlying PersistentClient as well.
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("corrupt metadata")

    with (
        monkeypatch.context() as mp,
        pytest.raises(DocpipeError, match="Invalid or unusable collection"),
    ):
        import chromadb.api.client

        mp.setattr(chromadb.api.client.Client, "get_or_create_collection", _boom)
        VectorStore(tmp_persist_dir, "broken_col")
    assert _active_systems_for(tmp_persist_dir) == []


def test_store_survives_forced_low_hnsw_cache_eviction(
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure small collections (<1000 chunks) survive Chroma HNSW LRU cache eviction."""
    from chromadb.api.rust import RustBindingsAPI

    orig_start = RustBindingsAPI.start

    def _small_cache_start(self: Any) -> None:
        self.hnsw_cache_size = 1
        orig_start(self)

    monkeypatch.setattr(RustBindingsAPI, "start", _small_cache_start)

    stores: list[VectorStore] = []
    try:
        for col_name in ("col_alpha", "col_beta", "col_gamma", "col_delta"):
            store = VectorStore(tmp_persist_dir, col_name)
            p, c = _make_pair(f"{col_name}.md", "v1", f"{col_name} KMS-401 retention rule.")
            if col_name == "col_gamma":
                _, c_extra = _make_pair(
                    f"{col_name}.md",
                    "v1",
                    f"{col_name} extra clause.",
                    chunk_index=1,
                )
                c_extra = EmbeddedChunk(
                    id=f"c_extra_{col_name}",
                    text=c_extra.text,
                    parent_id=p.id,
                    metadata=c_extra.metadata,
                    vector=c_extra.vector,
                )
                store.add_chunks([p, c, c_extra])
            else:
                store.add_chunks([p, c])
            stores.append(store)

        # Force eviction under hnsw_cache_size=1, then query 2-chunk & 3-chunk collections.
        _ = stores[-1].query_children(deterministic_embed(["col_delta KMS-401"])[0], top_k=1)
        alpha_hits = stores[0].query_children(
            deterministic_embed(["col_alpha KMS-401"])[0],
            top_k=1,
        )
        assert len(alpha_hits) == 1
        assert alpha_hits[0].metadata["source"] == "col_alpha.md"
        gamma_hits = stores[2].query_children(
            deterministic_embed(["col_gamma extra clause"])[0],
            top_k=2,
        )
        assert any(h.id == "c_extra_col_gamma" for h in gamma_hits)

        # reset_collection() must preserve eager HNSW persistence too.
        stores[0].reset_collection()
        p2, c2 = _make_pair("col_alpha.md", "v2", "col_alpha updated KMS-401 rule.")
        stores[0].add_chunks([p2, c2])
        _ = stores[1].query_children(deterministic_embed(["col_beta KMS-401"])[0], top_k=1)
        alpha_rebuilt_hits = stores[0].query_children(
            deterministic_embed(["col_alpha updated"])[0],
            top_k=1,
        )
        assert [h.id for h in alpha_rebuilt_hits] == [c2.id]
    finally:
        for store in stores:
            store.close()
