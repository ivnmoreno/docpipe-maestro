"""Tests for Hybrid Lexical Search (SQLite FTS5 + RRF) and lifecycle integration."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import (
    ingest,
    register_embedder,
    register_store,
    reindex,
    remove,
    retrieve,
    sync,
)
from docpipe_maestro.cli import main
from docpipe_maestro.embedder import EMBEDDERS
from docpipe_maestro.manifest import load_manifest
from docpipe_maestro.query.searcher import SEARCHERS
from docpipe_maestro.query.stages import Searcher
from docpipe_maestro.store import STORES
from docpipe_maestro.store.lexical import LexicalIndex, sanitize_fts_query
from docpipe_maestro.types import (
    Chunk,
    ChunkMetadata,
    DocpipeError,
    EmbeddedChunk,
    RetrievedChunk,
)


def _make_child_chunk(
    cid: str,
    *,
    source: str,
    doc_version: str,
    section: str,
    clause: str | None,
    text: str,
    chunk_index: int = 0,
    page: int | None = None,
) -> Chunk:
    return Chunk(
        id=cid,
        text=text,
        parent_id="p_" + cid,
        metadata=ChunkMetadata(
            type="child",
            source=source,
            doc_version=doc_version,
            section=section,
            clause=clause,
            page=page,
            chunk_index=chunk_index,
            embed_model="mock/embed",
        ),
    )


def test_sanitize_fts_query_handles_special_syntax_and_operators() -> None:
    """Raw technical codes, unbalanced quotes, wildcards, and SQL operators sanitize safely."""
    assert sanitize_fts_query("What triggers SEV-1 and AES-256?") == (
        '"What" OR "triggers" OR "SEV-1" OR "and" OR "AES-256"'
    )
    assert sanitize_fts_query('Clause 1.2 AND NOT OR "unclosed * ^ : (foo)') == (
        '"Clause" OR "1.2" OR "AND" OR "NOT" OR "OR" OR "unclosed" OR "foo"'
    )
    assert sanitize_fts_query("") == ""
    assert sanitize_fts_query("   \t\n  ") == ""
    assert sanitize_fts_query('!!! ??? """ --- ***') == ""

    # Deduplication (case-insensitive) and safe querying in SQLite FTS5
    assert sanitize_fts_query("SEV-1 sev-1 SEV-1") == '"SEV-1"'


def test_lexical_index_sanitize_and_direct_bm25_search(tmp_persist_dir: Path) -> None:
    """LexicalIndex executes sanitized BM25 queries strictly in read-only mode."""
    idx = LexicalIndex(tmp_persist_dir, "unit_lex")
    assert not idx.exists()
    assert not idx.has_indexed_rows()

    c1 = _make_child_chunk(
        "c_sev1",
        source="runbook.md",
        doc_version="ver111111111",
        section="Section 1: Severity",
        clause="1.1",
        text="[Source: runbook.md | Section 1: Severity]\n1.1 SEV-1 requires immediate escalation.",
        page=2,
    )
    c2 = _make_child_chunk(
        "c_travel",
        source="travel.docx",
        doc_version="ver222222222",
        section="Section 2: Lodging",
        clause="2.2",
        text="[Source: travel.docx | Section 2: Lodging]\n2.2 Hotel cap is $275/night.",
        chunk_index=1,
    )
    idx.add_chunks([c1, c2])
    assert idx.exists()
    assert idx.has_indexed_rows()

    active = {"runbook.md": "ver111111111", "travel.docx": "ver222222222"}
    hits = idx.search('SEV-1 AND "unclosed * :', top_k=5, active_versions=active)
    assert len(hits) == 1
    assert hits[0].id == "c_sev1"
    assert hits[0].metadata["clause"] == "1.1"
    assert hits[0].metadata["page"] == 2
    assert 0.0 < hits[0].score <= 1.0

    # Empty and punctuation-only queries return [] cleanly without error
    assert idx.search("", active_versions=active) == []
    assert idx.search("??? --- !!!", active_versions=active) == []


def test_hybrid_searcher_protocol_and_lazy_registration(tmp_persist_dir: Path) -> None:
    """Built-in 'default' and 'fts5_hybrid' searchers satisfy Searcher protocol."""
    _ = tmp_persist_dir
    keys = SEARCHERS.keys()
    assert "default" in keys
    assert "fts5_hybrid" in keys

    default_inst = SEARCHERS.resolve("default")()
    hybrid_inst = SEARCHERS.resolve("fts5_hybrid")()
    assert isinstance(default_inst, Searcher)
    assert isinstance(hybrid_inst, Searcher)
    assert default_inst.name == "default"
    assert hybrid_inst.name == "fts5_hybrid"


def test_hybrid_search_boosts_exact_identifier_over_dense_only(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """fts5_hybrid elevates exact identifier/clause hits while default stays baseline."""
    _ = mock_litellm_offline
    doc_a = tmp_path / "runbook.md"
    doc_a.write_text(
        "## Section 1: Generic Overview\n\n"
        "1.1 General operational guidance for service availability and health monitoring.\n\n"
        "## Section 2: Incident Codes\n\n"
        "2.1 Code ZXQ-904 triggers mandatory containment except during scheduled drills.\n",
        encoding="utf-8",
    )
    # Seed several distractor chunks sharing words like 'code' or 'service'
    doc_b = tmp_path / "faq.md"
    doc_b.write_text(
        "## Section 1: Code Reviews\n\n"
        "1.1 Standard code review policy applies to all repositories.\n\n"
        "## Section 2: Incident Escalation Codes\n\n"
        "2.1 Standard incident severity codes follow normal triage windows.\n",
        encoding="utf-8",
    )
    ingest(tmp_path, profile="POLICY", collection="hyb_exact", persist_dir=tmp_persist_dir)

    hybrid_results = retrieve(
        "ZXQ-904",
        collection="hyb_exact",
        persist_dir=tmp_persist_dir,
        top_k=2,
        searcher="fts5_hybrid",
    )
    assert len(hybrid_results) >= 1
    assert hybrid_results[0].metadata["section"] == "Section 2: Incident Codes"
    assert "ZXQ-904" in hybrid_results[0].text
    assert "except during scheduled drills" in hybrid_results[0].text
    assert all(0.0 <= r.score <= 1.0 for r in hybrid_results)

    # Conceptual query with zero exact keyword matches degrades gracefully to dense hits
    conceptual = retrieve(
        "unmapped conceptual terminology",
        collection="hyb_exact",
        persist_dir=tmp_persist_dir,
        top_k=2,
        searcher="fts5_hybrid",
    )
    assert len(conceptual) >= 1
    assert all(0.0 <= r.score <= 1.0 for r in conceptual)

    # Empty / whitespace / punctuation-only queries return [] cleanly
    assert (
        retrieve("", collection="hyb_exact", persist_dir=tmp_persist_dir, searcher="fts5_hybrid")
        == []
    )
    assert (
        retrieve("   ", collection="hyb_exact", persist_dir=tmp_persist_dir, searcher="fts5_hybrid")
        == []
    )
    assert (
        retrieve(
            "??? !!! ---",
            collection="hyb_exact",
            persist_dir=tmp_persist_dir,
            searcher="fts5_hybrid",
        )
        == []
    )

    # Default searcher keeps pure dense baseline scores & behavior intact
    default_results = retrieve(
        "ZXQ-904",
        collection="hyb_exact",
        persist_dir=tmp_persist_dir,
        top_k=2,
        searcher="default",
    )
    implicit_default = retrieve(
        "ZXQ-904",
        collection="hyb_exact",
        persist_dir=tmp_persist_dir,
        top_k=2,
    )
    assert [(r.id, r.score) for r in default_results] == [(r.id, r.score) for r in implicit_default]


# ---------------------------------------------------------------------------
# Phase 4 (US2): Synchronized Lexical Lifecycle & Legacy Guard
# ---------------------------------------------------------------------------


def test_lexical_lifecycle_ingest_sync_remove_and_empty_file(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """ingest, sync, and remove keep collocated SQLite FTS5 synchronized cleanly."""
    _ = mock_litellm_offline

    # Empty file ingest initializes schema with 0 rows; hybrid search returns [] cleanly
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")
    ingest(empty_file, collection="empty_lex", persist_dir=tmp_persist_dir)
    empty_idx = LexicalIndex(tmp_persist_dir, "empty_lex")
    assert empty_idx.exists()
    assert not empty_idx.has_indexed_rows()
    assert (
        retrieve(
            "anything", collection="empty_lex", persist_dir=tmp_persist_dir, searcher="fts5_hybrid"
        )
        == []
    )

    # Full corpus lifecycle: ingest -> modify -> sync -> remove
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    keep_doc = corpus / "keep.md"
    drop_doc = corpus / "drop.md"
    keep_doc.write_text(
        "## Section 1: Retention\n\n1.1 Legacy rule uses token OBSOLETE-99.\n",
        encoding="utf-8",
    )
    drop_doc.write_text(
        "## Section 1: Temporary\n\n1.1 Ephemeral notice contains REMOVED-88.\n",
        encoding="utf-8",
    )
    ingest(corpus, profile="POLICY", collection="life_lex", persist_dir=tmp_persist_dir)

    lex = LexicalIndex(tmp_persist_dir, "life_lex")
    assert lex.db_path.is_file()
    mode = stat.S_IMODE(lex.db_path.stat().st_mode)
    assert (mode & 0o077) == 0

    mtime_before = lex.db_path.stat().st_mtime_ns
    hits_before = retrieve(
        "OBSOLETE-99",
        collection="life_lex",
        persist_dir=tmp_persist_dir,
        searcher="fts5_hybrid",
    )
    assert len(hits_before) >= 1 and "OBSOLETE-99" in hits_before[0].text
    # Phase 2 hybrid retrieval never mutates lexical SQLite DB
    assert lex.db_path.stat().st_mtime_ns == mtime_before

    # Modify keep.md and remove drop.md, then sync
    keep_doc.write_text(
        "## Section 1: Retention\n\n1.1 Updated policy uses token FRESH-77.\n",
        encoding="utf-8",
    )
    drop_doc.unlink()
    sync(corpus, profile="POLICY", collection="life_lex", persist_dir=tmp_persist_dir)

    active_versions = {
        k: v.doc_version for k, v in load_manifest(tmp_persist_dir, "life_lex").sources.items()
    }
    assert lex.search("OBSOLETE-99", active_versions=active_versions) == []
    assert lex.search("REMOVED-88", active_versions=active_versions) == []
    fresh_hits = retrieve(
        "FRESH-77",
        collection="life_lex",
        persist_dir=tmp_persist_dir,
        searcher="fts5_hybrid",
    )
    assert len(fresh_hits) >= 1 and "FRESH-77" in fresh_hits[0].text

    # Remove keep.md completely
    assert remove("keep.md", collection="life_lex", persist_dir=tmp_persist_dir) is True
    assert lex.search("FRESH-77") == []


def test_lexical_sweep_uncommitted_and_path_traversal_guard(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Crash recovery sweeps orphan FTS5 records; invalid collection names are rejected."""
    _ = mock_litellm_offline
    with pytest.raises(DocpipeError, match="invalid path characters"):
        LexicalIndex(tmp_persist_dir, "../escape")

    doc = tmp_path / "alpha.md"
    doc.write_text("## Section 1\n\n1.1 Active committed rule.\n", encoding="utf-8")
    ingest(doc, profile="POLICY", collection="sweep_lex", persist_dir=tmp_persist_dir)

    lex = LexicalIndex(tmp_persist_dir, "sweep_lex")
    orphan = _make_child_chunk(
        "orphan_chunk_01",
        source="alpha.md",
        doc_version="orphan999999",
        section="Section 9",
        clause=None,
        text="[Source: alpha.md | Section 9]\nPHANTOM-UNCOMMITTED-XYZ rule.",
    )
    lex.add_chunks([orphan])

    # Phase 2 queries filter out uncommitted versions immediately
    manifest = load_manifest(tmp_persist_dir, "sweep_lex")
    active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
    assert lex.search("PHANTOM-UNCOMMITTED-XYZ", active_versions=active_versions) == []
    assert lex.search("PHANTOM-UNCOMMITTED-XYZ")  # orphan row physically present pre-sweep
    hybrid_hits = retrieve(
        "PHANTOM-UNCOMMITTED-XYZ",
        collection="sweep_lex",
        persist_dir=tmp_persist_dir,
        searcher="fts5_hybrid",
        threshold=0.0,
    )
    assert all("PHANTOM-UNCOMMITTED-XYZ" not in c.text for c in hybrid_hits)

    # Next ingest sweeps the uncommitted orphan record permanently
    doc_b = tmp_path / "beta.md"
    doc_b.write_text("## Section 1\n\n1.1 Beta clause.\n", encoding="utf-8")
    ingest(doc_b, profile="POLICY", collection="sweep_lex", persist_dir=tmp_persist_dir)
    assert lex.search("PHANTOM-UNCOMMITTED-XYZ") == []


def test_legacy_unindexed_collection_errors_until_reindex(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Missing lexical index errors fast with reindex guidance and does not create DB on remove."""
    _ = mock_litellm_offline
    doc_a = tmp_path / "doc_a.md"
    doc_b = tmp_path / "doc_b.md"
    doc_a.write_text("## Section 1\n\n1.1 Token LEGACY-ALPHA rule.\n", encoding="utf-8")
    doc_b.write_text("## Section 1\n\n1.1 Token LEGACY-BETA rule.\n", encoding="utf-8")
    ingest(tmp_path, profile="POLICY", collection="legacy_col", persist_dir=tmp_persist_dir)

    # Simulate legacy collection ingested before 005-hybrid-search
    lex = LexicalIndex(tmp_persist_dir, "legacy_col")
    lex.db_path.unlink()
    assert not lex.exists()

    # remove() on a legacy collection must NOT materialize an empty .db file (F3)
    assert remove("doc_b.md", collection="legacy_col", persist_dir=tmp_persist_dir) is True
    assert not lex.exists()

    with pytest.raises(DocpipeError, match="reindex"):
        retrieve(
            "LEGACY-ALPHA",
            collection="legacy_col",
            persist_dir=tmp_persist_dir,
            searcher="fts5_hybrid",
        )
    # Phase 2 failure left filesystem completely untouched
    assert not lex.exists()

    # Default vector search still works unaffected on unindexed collection
    assert (
        len(
            retrieve(
                "LEGACY-ALPHA",
                collection="legacy_col",
                persist_dir=tmp_persist_dir,
                searcher="default",
            )
        )
        >= 1
    )

    # reindex() rebuilds both vector and lexical indexes cleanly
    count = reindex(
        embed_model="ollama/nomic-embed-text",
        collection="legacy_col",
        persist_dir=tmp_persist_dir,
    )
    assert count >= 1
    assert lex.exists() and lex.has_indexed_rows()
    rebuilt_hits = retrieve(
        "LEGACY-ALPHA",
        collection="legacy_col",
        persist_dir=tmp_persist_dir,
        searcher="fts5_hybrid",
    )
    assert len(rebuilt_hits) >= 1
    assert "LEGACY-ALPHA" in rebuilt_hits[0].text


# ---------------------------------------------------------------------------
# Phase 5 (US3): Score Normalization, Threshold, CLI/TOML, Parity & Latency
# ---------------------------------------------------------------------------


@contextmanager
def _restore_registry(registry: Any) -> Iterator[None]:
    saved_entries = dict(registry._entries)
    saved_lazy = dict(registry._lazy_builtins)
    try:
        yield
    finally:
        registry._entries.clear()
        registry._entries.update(saved_entries)
        registry._lazy_builtins.clear()
        registry._lazy_builtins.update(saved_lazy)


def test_rrf_theoretical_max_normalization_and_threshold_filtering(
    tmp_path: Path,
    tmp_persist_dir: Path,
) -> None:
    """Dual rank-1 match normalizes to 1.0 while single-signal rank-1 normalizes to 0.5."""
    _ = tmp_path
    with _restore_registry(EMBEDDERS), _restore_registry(STORES):
        _mem: dict[str, list[EmbeddedChunk]] = {}

        @register_embedder("rrf_mock")
        class _ConstEmbedder:
            name = "rrf_mock"

            def embed_texts(
                self,
                texts: Sequence[str],
                *,
                model: str,
                api_base: str | None = None,
            ) -> list[list[float]]:
                _ = (model, api_base)
                return [[1.0, 0.0] for _ in texts]

            def embed_query(
                self,
                text: str,
                *,
                model: str,
                api_base: str | None = None,
            ) -> list[float]:
                _ = (text, model, api_base)
                return [1.0, 0.0]

        @register_store("rrf_store")
        class _RrfMockStore:
            name = "rrf_store"

            def __init__(self, persist_dir: Path, collection_name: str) -> None:
                self._key = f"{persist_dir}:{collection_name}"
                _mem.setdefault(self._key, [])

            def add_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
                _mem[self._key].extend(chunks)

            def query_children(
                self,
                query_vector: list[float],
                *,
                top_k: int = 5,
                active_versions: dict[str, str] | None = None,
                where: dict[str, object] | None = None,
                include_embeddings: bool = False,
            ) -> list[RetrievedChunk]:
                _ = (query_vector, active_versions, where, include_embeddings)
                # Return c_dual first, c_dense second; intentionally omit c_lex_only
                ordered_ids = ["c_dual", "c_dense"]
                by_id = {c.id: c for c in _mem[self._key] if c.metadata["type"] == "child"}
                out: list[RetrievedChunk] = []
                for idx, cid in enumerate(ordered_ids[:top_k]):
                    ch = by_id[cid]
                    out.append(
                        RetrievedChunk(
                            id=ch.id,
                            text=ch.text,
                            parent_id=ch.parent_id,
                            metadata=ch.metadata,
                            vector=[],
                            score=1.0 - idx * 0.1,
                        )
                    )
                return out

            def get_by_ids(
                self, ids: Sequence[str], *, include_embeddings: bool = False
            ) -> list[EmbeddedChunk]:
                _ = include_embeddings
                id_set = set(ids)
                return [c for c in _mem[self._key] if c.id in id_set]

            def get_parents_by_source(
                self,
                source: str,
                *,
                active_doc_version: str | None = None,
                include_embeddings: bool = False,
            ) -> list[EmbeddedChunk]:
                _ = (source, active_doc_version, include_embeddings)
                return []

            def delete_by_source(self, source: str) -> None:
                _ = source

            def delete_stale_versions(self, source: str, active_doc_version: str) -> None:
                _ = (source, active_doc_version)

            def sweep_uncommitted(self, active_versions: dict[str, str]) -> int:
                _ = active_versions
                return 0

            def get_all_children(self) -> list[EmbeddedChunk]:
                return []

            def get_all_parents(self) -> list[EmbeddedChunk]:
                return []

            def reset_collection(self) -> None:
                _mem[self._key] = []

        # Populate manifest + store + lexical DB directly for deterministic rank check
        from docpipe_maestro.manifest import save_manifest
        from docpipe_maestro.types import Manifest, SourceRecord

        ver = "ver123456789"
        c_dual = EmbeddedChunk(
            id="c_dual",
            text="RARE_TOKEN alpha item",
            parent_id="p_dual",
            metadata=ChunkMetadata(
                type="child",
                source="d.md",
                doc_version=ver,
                section="S1",
                clause=None,
                page=None,
                chunk_index=0,
                embed_model="rrf/embed",
            ),
            vector=[1.0, 0.0],
        )
        c_dense = EmbeddedChunk(
            id="c_dense",
            text="general unrelated narrative",
            parent_id="p_dense",
            metadata=ChunkMetadata(
                type="child",
                source="d.md",
                doc_version=ver,
                section="S2",
                clause=None,
                page=None,
                chunk_index=1,
                embed_model="rrf/embed",
            ),
            vector=[1.0, 0.0],
        )
        c_lex_only = EmbeddedChunk(
            id="c_lex_only",
            text="RARE_TOKEN appears only lexically",
            parent_id="p_lex",
            metadata=ChunkMetadata(
                type="child",
                source="d.md",
                doc_version=ver,
                section="S3",
                clause=None,
                page=None,
                chunk_index=2,
                embed_model="rrf/embed",
            ),
            vector=[1.0, 0.0],
        )
        store_inst = _RrfMockStore(tmp_persist_dir, "rrf_norm")
        store_inst.add_chunks([c_dual, c_dense, c_lex_only])
        LexicalIndex(tmp_persist_dir, "rrf_norm").add_chunks([c_dual, c_dense, c_lex_only])
        save_manifest(
            tmp_persist_dir,
            Manifest(
                collection="rrf_norm",
                embed_model="rrf/embed",
                embed_dim=2,
                sources={
                    "d.md": SourceRecord(
                        source="d.md",
                        content_hash="sha256:00",
                        doc_version=ver,
                        size=10,
                        mtime=1.0,
                        ingested_at="2026-11-14T00:00:00+00:00",
                        embed_model="rrf/embed",
                        profile="DEFAULT",
                        chunk_ids=["c_dual", "c_dense", "c_lex_only"],
                        parent_ids=[],
                    )
                },
            ),
        )

        fused = retrieve(
            "RARE_TOKEN",
            collection="rrf_norm",
            persist_dir=tmp_persist_dir,
            embed_model="rrf/embed",
            top_k=5,
            expand_parent=False,
            embedder="rrf_mock",
            store="rrf_store",
            searcher="fts5_hybrid",
        )
        by_id = {c.id: c.score for c in fused}
        # c_dual is #1 in both dense and lexical -> 1.0000
        assert by_id["c_dual"] == pytest.approx(1.0)
        # c_lex_only is absent in dense, #2 in lexical -> 0.5 * (61 / 62)
        assert by_id["c_lex_only"] == pytest.approx(0.5 * (61.0 / 62.0))
        # c_dense is #2 in dense, absent in lexical -> 0.5 * (61 / 62)
        assert by_id["c_dense"] == pytest.approx(0.5 * (61.0 / 62.0))

        # Threshold above 0.6 isolates dual-signal matches cleanly
        strict = retrieve(
            "RARE_TOKEN",
            collection="rrf_norm",
            persist_dir=tmp_persist_dir,
            embed_model="rrf/embed",
            top_k=5,
            threshold=0.6,
            expand_parent=False,
            embedder="rrf_mock",
            store="rrf_store",
            searcher="fts5_hybrid",
        )
        assert [c.id for c in strict] == ["c_dual"]


def test_cli_searcher_flags_toml_default_and_invalid_searcher(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI query/ask accept --searcher & TOML defaults and exit 1 on unknown searchers."""
    _ = mock_litellm_offline
    doc = tmp_path / "policy.md"
    doc.write_text("## Section 1\n\n1.1 Error code KLM-404 halts job runs.\n", encoding="utf-8")
    ingest(doc, profile="POLICY", collection="cli_lex", persist_dir=tmp_persist_dir)
    capsys.readouterr()

    rc_q = main(
        [
            "query",
            "KLM-404",
            "--searcher",
            "fts5_hybrid",
            "--collection",
            "cli_lex",
            "--persist-dir",
            str(tmp_persist_dir),
            "--json",
        ]
    )
    out_q = capsys.readouterr().out
    assert rc_q == 0
    payload = json.loads(out_q)
    assert payload["results"] and "KLM-404" in payload["results"][0]["text"]

    rc_ask = main(
        [
            "ask",
            "What does KLM-404 do?",
            "--searcher",
            "fts5_hybrid",
            "--collection",
            "cli_lex",
            "--persist-dir",
            str(tmp_persist_dir),
        ]
    )
    capsys.readouterr()
    assert rc_ask == 0

    cfg_file = tmp_path / "custom.toml"
    cfg_file.write_text('searcher = "fts5_hybrid"\n', encoding="utf-8")
    rc_toml = main(
        [
            "--config",
            str(cfg_file),
            "query",
            "KLM-404",
            "--collection",
            "cli_lex",
            "--persist-dir",
            str(tmp_persist_dir),
            "--json",
        ]
    )
    out_toml = capsys.readouterr().out
    assert rc_toml == 0
    assert json.loads(out_toml)["results"]

    rc_bad = main(
        [
            "query",
            "KLM-404",
            "--searcher",
            "ghost_searcher",
            "--collection",
            "cli_lex",
            "--persist-dir",
            str(tmp_persist_dir),
        ]
    )
    err_bad = capsys.readouterr().err
    assert rc_bad == 1
    assert "Error:" in err_bad
    assert "fts5_hybrid" in err_bad


def test_reverse_safety_exception_preservation_under_hybrid_search(
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Release Gate #1 exception-preservation queries hold under searcher='fts5_hybrid'."""
    _ = mock_litellm_offline
    corpus_dir = Path(__file__).resolve().parent / "fixtures" / "policy_corpus"
    ingest(corpus_dir, profile="POLICY", collection="rev_hyb", persist_dir=tmp_persist_dir)

    checks = [
        ("How many days of paid annual leave do employees receive?", "except"),
        ("What is the business travel hotel cap?", "provided that"),
        ("Who qualifies for bereavement leave?", "unless"),
    ]
    for question, marker in checks:
        sections = retrieve(
            question,
            collection="rev_hyb",
            persist_dir=tmp_persist_dir,
            top_k=3,
            expand_parent=True,
            searcher="fts5_hybrid",
        )
        assert sections, f"No sections retrieved for {question!r}"
        combined = "\n".join(s.text.lower() for s in sections)
        assert marker in combined, f"Exception marker {marker!r} missing for {question!r}"


def test_lazy_imports_defer_sqlite3_chromadb_and_litellm() -> None:
    """Importing root, register_searcher, or CLI build_parser avoids heavy backend imports."""
    code = (
        "import sys; "
        "import docpipe_maestro as root; "
        "from docpipe_maestro.cli import build_parser; "
        "build_parser(); "
        "_ = root.register_searcher; "
        "assert 'chromadb' not in sys.modules; "
        "assert 'litellm' not in sys.modules; "
        "assert 'sqlite3' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_lexical_search_latency_under_20ms_for_5000_chunks(tmp_persist_dir: Path) -> None:
    """LexicalIndex.search finishes in well under 20 ms across 5,000 indexed chunks."""
    idx = LexicalIndex(tmp_persist_dir, "perf_5k")
    ver = "perfver12345"
    batch: list[Chunk] = []
    for i in range(5000):
        extra = " ZXQ-904 escalation" if i == 4321 else ""
        batch.append(
            _make_child_chunk(
                f"c_{i:05d}",
                source="bulk.md",
                doc_version=ver,
                section=f"Section {i // 10}",
                clause=f"{i}.1",
                chunk_index=i,
                text=(
                    f"[Source: bulk.md | Section {i // 10}] "
                    f"Standardized policy clause entry {i}{extra}."
                ),
            )
        )
    idx.add_chunks(batch)
    active = {"bulk.md": ver}

    # Warm filesystem cache once, then measure read-only query time cleanly
    _ = idx.search("Standardized policy", top_k=15, active_versions=active)
    t0 = time.perf_counter()
    hits = idx.search("ZXQ-904 escalation", top_k=15, active_versions=active)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert hits and hits[0].id == "c_04321"
    assert elapsed_ms < 20.0, f"5,000-chunk FTS5 lookup took {elapsed_ms:.2f} ms (>= 20 ms)"
