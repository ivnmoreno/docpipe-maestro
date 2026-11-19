"""Unit tests for Phase 2 semantic retrieval, parent expansion, and deduplication."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, retrieve, status
from docpipe_maestro.manifest import load_manifest, save_manifest
from docpipe_maestro.query.searcher.dense import DenseSearcher
from docpipe_maestro.types import DocpipeError, EmbeddedChunk, RetrievedChunk


def test_retrieve_parent_expansion_and_deduplication(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    doc = tmp_path / "leave.md"
    doc.write_text(
        "## Section 1: Annual Leave\n\n"
        "1.1 Annual leave allowance is twenty days per calendar year.\n\n"
        "1.2 Annual leave requests require manager approval except emergency leave.\n\n"
        "## Section 2: Parking\n\n"
        "2.1 Bicycle racks are available in the basement garage.\n",
        encoding="utf-8",
    )
    ingest(doc, profile="POLICY", collection="ret", persist_dir=tmp_persist_dir)

    # Both 1.1 and 1.2 match "annual leave", but must deduplicate into one parent section
    results = retrieve(
        "annual leave allowance approval",
        collection="ret",
        persist_dir=tmp_persist_dir,
        top_k=5,
        expand_parent=True,
    )
    assert len(results) >= 1
    parent_ids = [r.id for r in results]
    assert len(parent_ids) == len(set(parent_ids))
    assert results[0].metadata["type"] == "parent"
    assert "except emergency leave" in results[0].text
    # Ordered descending by score
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_no_expand_parent_and_threshold(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    doc = tmp_path / "rules.md"
    doc.write_text(
        "## Section 1: Travel\n\n1.1 Train tickets are reimbursed in full.\n",
        encoding="utf-8",
    )
    ingest(doc, profile="POLICY", collection="ret2", persist_dir=tmp_persist_dir)

    raw_children = retrieve(
        "train tickets reimbursed",
        collection="ret2",
        persist_dir=tmp_persist_dir,
        top_k=5,
        expand_parent=False,
    )
    assert len(raw_children) == 1
    assert raw_children[0].metadata["type"] == "child"
    assert raw_children[0].text.startswith("[Source:")

    # High threshold filters out unrelated query
    empty = retrieve(
        "quantum astrophysics spacecraft propulsion",
        collection="ret2",
        persist_dir=tmp_persist_dir,
        top_k=5,
        threshold=0.95,
    )
    assert empty == []


def test_retrieve_parent_diversity_oversampling(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    doc = tmp_path / "backups.md"
    doc.write_text(
        "## Section 1: Daily Cloud Backup Rules\n\n"
        "1.1 Cloud backup schedules run daily at midnight.\n\n"
        "1.2 Cloud backup retention is 30 days by default.\n\n"
        "1.3 Cloud backup encryption uses AES-256.\n\n"
        "1.4 Cloud backup logs are archived monthly.\n\n"
        "## Section 2: Cloud Backup Exceptions\n\n"
        "2.1 Executive laptops may defer cloud backup synchronization during offline travel.\n\n"
        "## Section 3: Cloud Backup Audits\n\n"
        "3.1 Security audits verify cloud backup integrity quarterly.\n",
        encoding="utf-8",
    )
    ingest(doc, profile="POLICY", collection="ret_div", persist_dir=tmp_persist_dir)

    results = retrieve(
        "cloud backup schedule retention encryption audits",
        collection="ret_div",
        persist_dir=tmp_persist_dir,
        top_k=3,
        expand_parent=True,
    )
    assert len(results) == 3
    sections = {r.metadata["section"] for r in results}
    assert sections == {
        "Section 1: Daily Cloud Backup Rules",
        "Section 2: Cloud Backup Exceptions",
        "Section 3: Cloud Backup Audits",
    }


def test_retrieve_follows_cross_document_citations(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    corpus = tmp_path / "crossdoc_kb"
    corpus.mkdir()
    (corpus / "incident_runbook.md").write_text(
        "## Section 2: Breach Escalation\n\n"
        "2.1 Isolate breached systems immediately and follow Section 4.1 of the "
        "Compliance Policy and Clause 4.2 of the Master Services Agreement.\n",
        encoding="utf-8",
    )
    (corpus / "compliance_policy.md").write_text(
        "## Section 1: Overview\n\n1.1 General guidelines apply to staff.\n\n"
        "## Section 4: Regulatory Reporting\n\n"
        "4.1 Escalate suspected privacy incidents to the DPO within four (4) hours.\n",
        encoding="utf-8",
    )
    (corpus / "master_services_agreement.md").write_text(
        "## Article 4: Customer Notice\n\n"
        "4.2 Notify Customer within twenty-four (24) hours and preserve logs 90 days.\n",
        encoding="utf-8",
    )
    (corpus / "remote_work_policy.md").write_text(
        "## Section 4: Emergency Updates\n\n4.1 Install critical OS patches within 24 hours.\n",
        encoding="utf-8",
    )

    ingest(corpus, profile="POLICY", collection="xref_col", persist_dir=tmp_persist_dir)

    enriched = retrieve(
        "breach escalation isolate breached systems",
        collection="xref_col",
        persist_dir=tmp_persist_dir,
        top_k=1,
        expand_parent=True,
    )
    assert len(enriched) == 1
    assert "[Crossref Section 4.1 (compliance_policy.md):" in enriched[0].text
    assert "DPO within four (4) hours" in enriched[0].text
    assert "Install critical OS patches" not in enriched[0].text
    assert "[Crossref Clause 4.2 (master_services_agreement.md):" in enriched[0].text
    assert "twenty-four (24) hours" in enriched[0].text

    unenriched = retrieve(
        "breach escalation isolate breached systems",
        collection="xref_col",
        persist_dir=tmp_persist_dir,
        top_k=1,
        expand_parent=True,
        follow_crossrefs=False,
    )
    assert "[Crossref" not in unenriched[0].text


def test_retrieve_chunk_attribute_filters_and_empty_dict(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    _ = mock_litellm_offline
    corpus = tmp_path / "docs"
    corpus.mkdir()
    (corpus / "hr_policy.md").write_text(
        "## Section 1: Annual Leave\n\n"
        "1.1 Employees receive twenty days of annual leave except new hires.\n\n"
        "## Section 2: Parking\n\n"
        "2.1 Garage badge access requires facility approval.\n",
        encoding="utf-8",
    )
    (corpus / "travel_guide.md").write_text(
        "## Section 1: Annual Leave Travel\n\n"
        "1.1 Annual leave flight vouchers require manager approval.\n",
        encoding="utf-8",
    )

    ingest(corpus, profile="POLICY", collection="where_chunks", persist_dir=tmp_persist_dir)
    st = status(collection="where_chunks", persist_dir=tmp_persist_dir)
    hr_rec = next(r for r in st.sources if r.source == "hr_policy.md")

    # Empty dict normalizes identically to None.
    unfiltered = retrieve("annual leave", collection="where_chunks", persist_dir=tmp_persist_dir)
    empty_dict = retrieve(
        "annual leave", collection="where_chunks", persist_dir=tmp_persist_dir, where={}
    )
    assert [c.id for c in empty_dict] == [c.id for c in unfiltered]

    # Single & multi-key chunk filters match strictly hr_policy.md.
    by_source = retrieve(
        "annual leave",
        collection="where_chunks",
        persist_dir=tmp_persist_dir,
        where={"source": "hr_policy.md"},
    )
    assert by_source and all(c.metadata["source"] == "hr_policy.md" for c in by_source)

    for key, val in (
        ("section", "Section 1: Annual Leave"),
        ("clause", "1.1"),
        ("doc_version", hr_rec.doc_version),
        ("embed_model", hr_rec.embed_model),
        ("chunk_index", 0),
    ):
        hits = retrieve(
            "annual leave",
            collection="where_chunks",
            persist_dir=tmp_persist_dir,
            expand_parent=False,
            where={"source": "hr_policy.md", key: val},
        )
        assert hits and all(h.metadata["source"] == "hr_policy.md" for h in hits)

    # Filtering empty/nonexistent collection validates syntax cleanly before returning [].
    assert (
        retrieve(
            "anything",
            collection="never_created_col",
            persist_dir=tmp_persist_dir,
            where={"source": "hr_policy.md"},
        )
        == []
    )
    with pytest.raises(DocpipeError, match="Unsupported filter key"):
        retrieve(
            "anything",
            collection="never_created_col",
            persist_dir=tmp_persist_dir,
            where={"secton": "Leave"},
        )


def test_retrieve_manifest_filters_intersection_and_zero_embed_shortcircuit(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    doc_a = tmp_path / "policy_a.md"
    doc_a.write_text(
        "## Section 1: Leave Rules\n\n1.1 Standard leave requires approval.\n",
        encoding="utf-8",
    )
    doc_b = tmp_path / "guide_b.md"
    doc_b.write_text(
        "## Section 1: Guide Notes\n\nNormal leave guide steps for onboarding.\n",
        encoding="utf-8",
    )
    doc_c = tmp_path / "policy_c.md"
    doc_c.write_text(
        "## Section 1: Remote Policy\n\n1.1 Remote leave tracking uses HR portal.\n",
        encoding="utf-8",
    )

    ingest(doc_a, profile="POLICY", collection="man_flt", persist_dir=tmp_persist_dir)
    ingest(doc_b, profile="DEFAULT", collection="man_flt", persist_dir=tmp_persist_dir)
    ingest(doc_c, profile="POLICY", collection="man_flt", persist_dir=tmp_persist_dir)

    manifest = load_manifest(tmp_persist_dir, "man_flt")
    manifest.sources["policy_a.md"].ingested_at = "2026-11-10T08:00:00+00:00"
    manifest.sources["guide_b.md"].ingested_at = "2026-11-15T18:30:00+00:00"
    manifest.sources["policy_c.md"].ingested_at = "2026-11-20T09:00:00+00:00"
    save_manifest(tmp_persist_dir, manifest)

    # Profile filtering is case-insensitive and works across scalar/$in/$ne/$nin.
    pol_hits = retrieve(
        "leave", collection="man_flt", persist_dir=tmp_persist_dir, where={"profile": "policy"}
    )
    assert {h.metadata["source"] for h in pol_hits} <= {"policy_a.md", "policy_c.md"}
    assert {h.metadata["source"] for h in pol_hits}

    def_hits = retrieve(
        "leave",
        collection="man_flt",
        persist_dir=tmp_persist_dir,
        where={"profile": {"$ne": "POLICY"}},
    )
    assert [h.metadata["source"] for h in def_hits] == ["guide_b.md"]

    # Date-only ingested_before uses inclusive UTC end-of-day bound.
    win_hits = retrieve(
        "leave",
        collection="man_flt",
        persist_dir=tmp_persist_dir,
        where={"ingested_after": "2026-11-15", "ingested_before": "2026-11-15"},
    )
    assert [h.metadata["source"] for h in win_hits] == ["guide_b.md"]

    # Z-suffixed, offset-aware, and naive UTC timestamps compare consistently.
    after_hits = retrieve(
        "leave",
        collection="man_flt",
        persist_dir=tmp_persist_dir,
        where={
            "ingested_after": "2026-11-15T19:30:00+01:00",
            "ingested_before": "2026-11-15T18:30:00Z",
        },
    )
    assert [h.metadata["source"] for h in after_hits] == ["guide_b.md"]

    # Intersecting profile + source constraints scopes strictly or short-circuits cleanly.
    inter = retrieve(
        "leave",
        collection="man_flt",
        persist_dir=tmp_persist_dir,
        where={"profile": "POLICY", "source": {"$in": ["policy_a.md", "guide_b.md"]}},
    )
    assert [h.metadata["source"] for h in inter] == ["policy_a.md"]

    # Empty manifest / conflicting source allowlist must issue ZERO embedding requests.
    embeds_before = len(mock_litellm_offline["embedding"])
    empty_cases: tuple[dict[str, object], ...] = (
        {"ingested_after": "2099-01-01T00:00:00Z"},
        {"profile": "UNKNOWN"},
        {"profile": "POLICY", "source": "guide_b.md"},
        {"profile": "DEFAULT", "source": {"$ne": "guide_b.md"}},
        {"profile": "POLICY", "ingested_after": "2026-11-25", "ingested_before": "2026-11-01"},
    )
    for empty_where in empty_cases:
        assert (
            retrieve("leave", collection="man_flt", persist_dir=tmp_persist_dir, where=empty_where)
            == []
        )
        assert (
            DenseSearcher().search(
                "leave",
                top_k=5,
                collection="man_flt",
                persist_dir=str(tmp_persist_dir),
                embed_model="ollama/nomic-embed-text",
                where=empty_where,
            )
            == []
        )
    assert len(mock_litellm_offline["embedding"]) == embeds_before

    # Sibling malformed field still raises even when manifest matches zero sources.
    with pytest.raises(DocpipeError, match="Unsupported filter key"):
        retrieve(
            "leave",
            collection="man_flt",
            persist_dir=tmp_persist_dir,
            where={"profile": "UNKNOWN", "bad_key": "x"},
        )


def test_retrieve_where_validation_reserved_type_and_bad_operands(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    _ = mock_litellm_offline
    doc = tmp_path / "leave.md"
    doc.write_text("## Section 1\n\n1.1 Annual leave rule.\n", encoding="utf-8")
    ingest(doc, profile="POLICY", collection="bad_where_col", persist_dir=tmp_persist_dir)

    invalid_cases: list[Any] = [
        "source=leave.md",
        {"type": "parent"},
        {"type": "child"},
        {"$or": [{"type": "parent"}, {"page": 1}]},
        {"secton": "Section 1"},
        {"page": True},
        {"page": "2"},
        {"chunk_index": False},
        {"page": {"$in": ["2"]}},
        {"page": {"$gt": True}},
        {"source": {"$in": [123]}},
        {"source": {"$in": []}},
        {"$and": []},
        {"$or": []},
        {"source": {"$regex": ".*"}},
        {"clause": {"$gt": "1.1"}},
        {"$or": [{"profile": "POLICY"}, {"source": "leave.md"}]},
        {"$and": [{"ingested_after": "2026-11-01"}, {"source": "leave.md"}]},
        {"profile": {"$gt": "A"}},
        {"ingested_after": {"$gte": "2026-11-01"}},
        {"ingested_before": "not-a-date"},
        {"page": {}},
    ]
    for bad in invalid_cases:
        with pytest.raises(DocpipeError):
            retrieve(
                "leave",
                collection="bad_where_col",
                persist_dir=tmp_persist_dir,
                where=bad,
            )


def test_retrieve_cold_start_concurrent_subprocess(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    _ = mock_litellm_offline
    doc1 = tmp_path / "leave.md"
    doc1.write_text(
        "## Section 1\n\n1.1 Annual leave allowance is twenty days per calendar year.\n",
        encoding="utf-8",
    )
    doc2 = tmp_path / "travel.md"
    doc2.write_text(
        "## Section 2\n\n2.1 Train tickets are reimbursed in full.\n",
        encoding="utf-8",
    )
    ingest(doc1, profile="POLICY", collection="cold_smoke", persist_dir=tmp_persist_dir)
    ingest(doc2, profile="POLICY", collection="cold_smoke", persist_dir=tmp_persist_dir)

    script = f"""
import hashlib
import math
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
import litellm
from docpipe_maestro import retrieve

_DIM = 64
_WORD_RE = re.compile(r"[a-z0-9]+")

def _stub_embed(*, model, input, **kwargs):
    vecs = []
    for text in input:
        v = [0.0] * _DIM
        tokens = _WORD_RE.findall(text.lower())
        if not tokens:
            v[0] = 1.0
        for tok in tokens:
            d = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(d[:4], "little") % _DIM
            v[idx] += 1.0 if (d[4] & 1) == 0 else -1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm > 0.0:
            v = [x / norm for x in v]
        else:
            v[0] = 1.0
        vecs.append(v)
    return {{
        "data": [{{"index": idx, "embedding": vec}} for idx, vec in enumerate(vecs)],
        "model": model,
    }}

litellm.embedding = _stub_embed
assert "chromadb" not in sys.modules, "chromadb loaded eagerly before barrier"

queries = [
    "annual leave allowance",
    "train tickets reimbursed",
    "calendar year leave",
    "reimbursed travel tickets",
]
barrier = threading.Barrier(len(queries))

def _worker(q):
    barrier.wait(timeout=15)
    hits = retrieve(
        q,
        collection="cold_smoke",
        persist_dir={str(tmp_persist_dir)!r},
        top_k=1,
        local_only=True,
    )
    assert len(hits) == 1
    return hits[0].id

with ThreadPoolExecutor(max_workers=len(queries)) as pool:
    results = list(pool.map(_worker, queries))
assert len(results) == len(queries)
"""
    for attempt in range(5):
        proc = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, (
            f"Cold-start concurrent retrieve failed on attempt {attempt + 1}:\n"
            f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        )


def test_retrieve_reuse_no_per_query_close_and_plugin_compat(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieval preserves Store reuse (0 close calls) and supports plugins without close()."""
    from docpipe_maestro.store import STORES, ChromaStore

    _ = mock_litellm_offline
    doc = tmp_path / "reuse.md"
    doc.write_text(
        "## Section 1: Retention\n\n1.1 Audit logs are retained for 365 days.\n",
        encoding="utf-8",
    )

    # (a) Custom Store stage plugin lacking .close() works across ingest() and retrieve().
    memory_records: dict[str, list[EmbeddedChunk]] = {}

    class _NoCloseStore:
        name: str = "no_close_plugin"

        def __init__(self, persist_dir: Path, collection_name: str) -> None:
            self._key = f"{persist_dir}:{collection_name}"
            memory_records.setdefault(self._key, [])

        def add_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
            memory_records[self._key].extend(chunks)

        def query_children(
            self,
            query_vector: list[float],
            *,
            top_k: int = 5,
            active_versions: dict[str, str] | None = None,
            where: dict[str, object] | None = None,
            include_embeddings: bool = False,
        ) -> list[RetrievedChunk]:
            _ = (query_vector, where, include_embeddings)
            out: list[RetrievedChunk] = []
            for ch in memory_records[self._key]:
                if ch.metadata["type"] != "child":
                    continue
                if active_versions is not None:
                    expected = active_versions.get(ch.metadata["source"])
                    if expected != ch.metadata["doc_version"]:
                        continue
                out.append(
                    RetrievedChunk(
                        id=ch.id,
                        text=ch.text,
                        parent_id=ch.parent_id,
                        metadata=ch.metadata,
                        vector=[],
                        score=0.95,
                    )
                )
            return out[:top_k]

        def get_by_ids(
            self,
            ids: Sequence[str],
            *,
            include_embeddings: bool = False,
        ) -> list[EmbeddedChunk]:
            _ = include_embeddings
            wanted = set(ids)
            return [c for c in memory_records[self._key] if c.id in wanted]

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
            memory_records[self._key] = [
                c for c in memory_records[self._key] if c.metadata["source"] != source
            ]

        def delete_stale_versions(self, source: str, active_doc_version: str) -> None:
            memory_records[self._key] = [
                c
                for c in memory_records[self._key]
                if not (
                    c.metadata["source"] == source
                    and c.metadata["doc_version"] != active_doc_version
                )
            ]

        def sweep_uncommitted(self, active_versions: dict[str, str]) -> int:
            before = len(memory_records[self._key])
            memory_records[self._key] = [
                c
                for c in memory_records[self._key]
                if active_versions.get(c.metadata["source"]) == c.metadata["doc_version"]
            ]
            return before - len(memory_records[self._key])

        def get_all_children(self) -> list[EmbeddedChunk]:
            return [c for c in memory_records[self._key] if c.metadata["type"] == "child"]

        def get_all_parents(self) -> list[EmbeddedChunk]:
            return [c for c in memory_records[self._key] if c.metadata["type"] == "parent"]

        def reset_collection(self) -> None:
            memory_records[self._key] = []

    assert not hasattr(_NoCloseStore, "close")
    monkeypatch.setitem(STORES._entries, "no_close_plugin", _NoCloseStore)

    plugin_dir = tmp_path / "plugin_persist"
    ingest(
        doc,
        profile="POLICY",
        collection="plugin_col",
        persist_dir=plugin_dir,
        store="no_close_plugin",
    )
    plugin_hits = retrieve(
        "Audit logs retention",
        collection="plugin_col",
        persist_dir=plugin_dir,
        top_k=1,
        expand_parent=True,
        store="no_close_plugin",
    )
    assert len(plugin_hits) == 1
    assert "365 days" in plugin_hits[0].text

    # (b) Default ChromaStore retrieval performs zero per-query ChromaStore.close() calls.
    ingest(doc, profile="POLICY", collection="default_reuse", persist_dir=tmp_persist_dir)
    close_calls: list[str] = []
    orig_close = ChromaStore.close

    def _spy_close(self: ChromaStore) -> None:
        close_calls.append(self._collection_name)
        orig_close(self)

    monkeypatch.setattr(ChromaStore, "close", _spy_close)
    for searcher_key in ("default", "fts5_hybrid"):
        hits = retrieve(
            "Audit logs 365 days",
            collection="default_reuse",
            persist_dir=tmp_persist_dir,
            top_k=1,
            expand_parent=True,
            searcher=searcher_key,
        )
        assert len(hits) == 1
        assert "365 days" in hits[0].text
    assert close_calls == []
