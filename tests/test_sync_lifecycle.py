"""Unit and integration tests for sync, shrinking-file orphan removal, rollback, and reindex."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from docpipe_maestro import ingest, reindex, remove, retrieve, status, sync
from docpipe_maestro.embedder import estimate_embedding_cost
from docpipe_maestro.ingest import ReindexPreview
from docpipe_maestro.manifest import audit_log_path, load_manifest, save_manifest
from docpipe_maestro.store import STORES, ChromaStore, register_store
from docpipe_maestro.types import (
    ChunkMetadata,
    DocpipeError,
    EmbeddedChunk,
    ModelMismatchError,
    PiiBlockedError,
    PiiPolicy,
    RegistryError,
    SourceRecord,
)


def test_sync_three_way_and_shrinking_document_no_orphans(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc_a = corpus / "a.md"
    doc_b = corpus / "b.md"
    doc_c = corpus / "c.md"

    doc_a.write_text(
        "## Section 1: Leave\n\n"
        "1.1 Standard leave is 20 days.\n\n"
        "## Section 2: Sabbatical\n\n"
        "2.1 Sabbatical bonus leave is 30 extra days for tenured staff.\n",
        encoding="utf-8",
    )
    doc_b.write_text("## Section 1: Remote\n\n1.1 Remote work is allowed.\n", encoding="utf-8")
    doc_c.write_text("## Section 1: Parking\n\n1.1 Garage badge required.\n", encoding="utf-8")

    sync(corpus, profile="POLICY", collection="life", persist_dir=tmp_persist_dir)

    # Touch doc_b (mtime changed, content identical)
    st_b = doc_b.stat()
    os.utime(doc_b, (st_b.st_atime + 20, st_b.st_mtime + 20))

    # Shrink doc_a (delete Section 2 completely)
    doc_a.write_text("## Section 1: Leave\n\n1.1 Standard leave is 20 days.\n", encoding="utf-8")

    # Delete doc_c, add doc_d
    doc_c.unlink()
    doc_d = corpus / "d.md"
    doc_d.write_text("## Section 1: Meals\n\n1.1 Travel meals are $75 per day.\n", encoding="utf-8")

    calls_before = len(mock_litellm_offline["embedding"])
    sres = sync(corpus, profile="POLICY", collection="life", persist_dir=tmp_persist_dir)

    assert sres.added == ["d.md"]
    assert sres.updated == ["a.md"]
    assert sres.skipped == ["b.md"]
    assert sres.removed == ["c.md"]

    # Only a.md and d.md were embedded (b.md skipped, c.md deleted)
    embedded_calls = mock_litellm_offline["embedding"][calls_before:]
    assert len(embedded_calls) == 2

    # Deleted Section 2 from shrinking doc_a must have zero orphans
    sabbatical_hits = retrieve(
        "sabbatical bonus leave tenured staff",
        collection="life",
        persist_dir=tmp_persist_dir,
        threshold=0.5,
    )
    assert all("Sabbatical bonus leave" not in r.text for r in sabbatical_hits)

    # Deleted doc_c must not be returned
    garage_hits = retrieve(
        "garage badge required",
        collection="life",
        persist_dir=tmp_persist_dir,
        threshold=0.5,
    )
    assert all("Garage badge" not in r.text for r in garage_hits)


def test_failed_reingestion_preserves_prior_version(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = tmp_path / "policy.md"
    doc.write_text("## Section 1: Leave\n\n1.1 Original 20 days annual leave.\n", encoding="utf-8")
    ingest(doc, profile="POLICY", collection="rollback", persist_dir=tmp_persist_dir)

    # Edit doc and simulate provider failure during re-ingestion
    doc.write_text("## Section 1: Leave\n\n1.1 Updated 25 days annual leave.\n", encoding="utf-8")

    import litellm

    def fail_embed(*, model: str, input: list[str], **kwargs: Any) -> Any:
        raise RuntimeError("Simulated API outage")

    monkeypatch.setattr(litellm, "embedding", fail_embed)
    with pytest.raises(DocpipeError):
        ingest(doc, profile="POLICY", collection="rollback", persist_dir=tmp_persist_dir)

    # Restore mock embedder and verify original version is still intact and queryable
    monkeypatch.undo()
    # Re-apply offline mock manually for query
    from tests.conftest import deterministic_embed

    monkeypatch.setattr(
        litellm,
        "embedding",
        lambda *, model, input, **kwargs: {
            "data": [{"index": i, "embedding": v} for i, v in enumerate(deterministic_embed(input))]
        },
    )
    results = retrieve("annual leave days", collection="rollback", persist_dir=tmp_persist_dir)
    assert len(results) == 1
    assert "Original 20 days" in results[0].text


def test_status_remove_and_reindex_model_migration(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    d1 = tmp_path / "one.md"
    d2 = tmp_path / "two.md"
    d1.write_text("## Section 1: One\n\n1.1 First document rule.\n", encoding="utf-8")
    d2.write_text("## Section 1: Two\n\n1.1 Second document rule.\n", encoding="utf-8")

    ingest(tmp_path, profile="POLICY", collection="mig", persist_dir=tmp_persist_dir)
    st = status(collection="mig", persist_dir=tmp_persist_dir)
    assert st.total_sources == 2
    assert st.embed_model == "ollama/nomic-embed-text"

    # Model mismatch refused until reindex
    with pytest.raises(ModelMismatchError):
        retrieve(
            "first document",
            collection="mig",
            persist_dir=tmp_persist_dir,
            embed_model="openai/text-embedding-3-small",
        )

    assert remove("two.md", collection="mig", persist_dir=tmp_persist_dir) is True
    assert remove("missing.md", collection="mig", persist_dir=tmp_persist_dir) is False

    count = reindex(
        embed_model="openai/text-embedding-3-small",
        collection="mig",
        persist_dir=tmp_persist_dir,
    )
    assert count == 1

    st_after = status(collection="mig", persist_dir=tmp_persist_dir)
    assert st_after.embed_model == "openai/text-embedding-3-small"
    assert st_after.embed_dim == 32

    res = retrieve(
        "first document rule",
        collection="mig",
        persist_dir=tmp_persist_dir,
        embed_model="openai/text-embedding-3-small",
    )
    assert len(res) == 1
    assert "First document rule" in res[0].text


def _tree_sha256(root_dir: Path) -> dict[str, str]:
    """Snapshot relative paths and SHA-256 digests under ``root_dir``."""
    return {
        path.relative_to(root_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root_dir.rglob("*"))
        if path.is_file()
    }


def test_sync_dry_run_and_live_metric_parity_zero_mutation(
    tmp_path: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    corpus = tmp_path / "dry_corpus"
    corpus.mkdir()
    doc_a = corpus / "a.md"
    doc_b = corpus / "b.md"
    doc_c = corpus / "c.md"

    doc_a.write_text("## Section 1: Leave\n\n1.1 Annual leave is 20 days.\n", encoding="utf-8")
    doc_b.write_text(
        "## Section 1: Remote\n\n1.1 Remote days require approval.\n", encoding="utf-8"
    )
    doc_c.write_text("## Section 1: Parking\n\n1.1 Garage badge required.\n", encoding="utf-8")

    missing_persist = tmp_path / "missing_persist"
    calls_before = len(mock_litellm_offline["embedding"])

    dry_first = sync(
        corpus,
        profile="POLICY",
        collection="dry_sync_col",
        persist_dir=missing_persist,
        dry_run=True,
    )
    assert dry_first.dry_run is True
    assert dry_first.added == ["a.md", "b.md", "c.md"]
    assert dry_first.updated == []
    assert dry_first.skipped == []
    assert dry_first.removed == []
    assert dry_first.estimated_children > 0
    assert dry_first.estimated_parents > 0
    assert dry_first.estimated_tokens > 0
    assert dry_first.estimated_cost_usd == 0.0
    assert len(mock_litellm_offline["embedding"]) == calls_before
    assert not missing_persist.exists()

    live_first = sync(
        corpus,
        profile="POLICY",
        collection="dry_sync_col",
        persist_dir=missing_persist,
    )
    assert live_first.dry_run is False
    assert live_first.added == dry_first.added
    assert live_first.estimated_children == dry_first.estimated_children
    assert live_first.estimated_parents == dry_first.estimated_parents
    assert live_first.estimated_tokens == dry_first.estimated_tokens
    assert live_first.estimated_cost_usd == dry_first.estimated_cost_usd
    assert live_first.to_dict()["dry_run"] is False

    # Prepare 3-way diff + mtime drift on unchanged doc_a
    st_a = doc_a.stat()
    os.utime(doc_a, (st_a.st_atime + 25, st_a.st_mtime + 25))
    doc_b.write_text(
        "## Section 1: Remote\n\n1.1 Remote work up to 3 days weekly with manager sign-off.\n",
        encoding="utf-8",
    )
    doc_c.unlink()
    (corpus / "d.md").write_text(
        "## Section 1: Meals\n\n1.1 Travel meals are $75 per day.\n",
        encoding="utf-8",
    )

    manifest_file = missing_persist / "manifests" / "dry_sync_col.json"
    manifest_bytes_before = manifest_file.read_bytes()
    tree_before = _tree_sha256(missing_persist)
    calls_before_diff = len(mock_litellm_offline["embedding"])

    dry_diff = sync(
        corpus,
        profile="POLICY",
        collection="dry_sync_col",
        persist_dir=missing_persist,
        dry_run=True,
    )
    assert dry_diff.dry_run is True
    assert dry_diff.added == ["d.md"]
    assert dry_diff.updated == ["b.md"]
    assert dry_diff.skipped == ["a.md"]
    assert dry_diff.removed == ["c.md"]
    assert dry_diff.estimated_children > 0
    assert dry_diff.estimated_parents > 0
    assert dry_diff.estimated_tokens > 0
    assert dry_diff.estimated_cost_usd == 0.0
    assert len(mock_litellm_offline["embedding"]) == calls_before_diff
    assert manifest_file.read_bytes() == manifest_bytes_before
    assert _tree_sha256(missing_persist) == tree_before

    live_diff = sync(
        corpus,
        profile="POLICY",
        collection="dry_sync_col",
        persist_dir=missing_persist,
    )
    assert live_diff.dry_run is False
    assert live_diff.added == dry_diff.added
    assert live_diff.updated == dry_diff.updated
    assert live_diff.skipped == dry_diff.skipped
    assert live_diff.removed == dry_diff.removed
    assert live_diff.estimated_children == dry_diff.estimated_children
    assert live_diff.estimated_parents == dry_diff.estimated_parents
    assert live_diff.estimated_tokens == dry_diff.estimated_tokens
    assert live_diff.estimated_cost_usd == dry_diff.estimated_cost_usd


def test_sync_dry_run_preflight_validation_and_pii_no_audit(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    corpus = tmp_path / "preflight_corpus"
    corpus.mkdir()
    doc = corpus / "clean.md"
    doc.write_text("# Policy\n\nAll employees receive onboarding.\n", encoding="utf-8")

    sync(corpus, collection="lock_col", persist_dir=tmp_persist_dir)

    with pytest.raises(ModelMismatchError):
        sync(
            corpus,
            collection="lock_col",
            persist_dir=tmp_persist_dir,
            embed_model="openai/text-embedding-3-small",
            dry_run=True,
        )

    ro_persist = tmp_path / "never_created"
    with pytest.raises(DocpipeError, match="local_only"):
        sync(
            corpus,
            collection="local_col",
            persist_dir=ro_persist,
            embed_model="openai/text-embedding-3-small",
            local_only=True,
            dry_run=True,
        )
    assert not ro_persist.exists()

    with pytest.raises(RegistryError):
        sync(
            corpus,
            collection="lock_col",
            persist_dir=tmp_persist_dir,
            store="missing_store_key",
            dry_run=True,
        )

    with pytest.raises(RegistryError):
        sync(
            corpus,
            collection="lock_col",
            persist_dir=tmp_persist_dir,
            embedder="missing_embedder_key",
            dry_run=True,
        )

    pii_corpus = tmp_path / "pii_corpus"
    pii_corpus.mkdir()
    (pii_corpus / "secret.md").write_text(
        "# HR\n\nEmployee SSN is 123-45-6789.\n", encoding="utf-8"
    )
    calls_before = len(mock_litellm_offline["embedding"])
    block_policy: PiiPolicy = {"types": {"US_SSN": "block"}}

    with pytest.raises(PiiBlockedError) as exc_info:
        sync(
            pii_corpus,
            collection="pii_dry",
            persist_dir=tmp_persist_dir,
            pii_policy=block_policy,
            dry_run=True,
        )
    assert "123-45-6789" not in str(exc_info.value)
    assert not audit_log_path(tmp_persist_dir, "pii_dry").exists()
    assert len(mock_litellm_offline["embedding"]) == calls_before


def test_estimate_embedding_cost_offline_pricing_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert estimate_embedding_cost("ollama/nomic-embed-text", 500) == 0.0
    assert estimate_embedding_cost("ollama_chat/llama3.2", 500) == 0.0
    assert estimate_embedding_cost("local/all-MiniLM", 500) == 0.0
    assert estimate_embedding_cost("openai/text-embedding-3-small", 0) == 0.0
    assert estimate_embedding_cost("openai/text-embedding-3-small", -10) == 0.0

    cloud_cost = estimate_embedding_cost("openai/text-embedding-3-small", 1000)
    assert isinstance(cloud_cost, float) and cloud_cost > 0.0
    assert estimate_embedding_cost("unknown-provider/nonexistent-embed-v99", 1000) is None

    empty_dir = tmp_path / "empty_corpus"
    empty_dir.mkdir()
    empty_res = sync(
        empty_dir,
        collection="empty_cloud",
        persist_dir=tmp_path / "empty_persist",
        embed_model="openai/text-embedding-3-small",
        dry_run=True,
    )
    assert empty_res.estimated_tokens == 0
    assert empty_res.estimated_cost_usd == 0.0

    fake_litellm = SimpleNamespace(
        model_cost={
            "openai/bool-rate": {"input_cost_per_token": True},
            "openai/nan-rate": {"input_cost_per_token": float("nan")},
            "openai/neg-rate": {"input_cost_per_token": -0.01},
            "openai/valid-rate": {"input_cost_per_token": 0.0000001},
        }
    )
    monkeypatch.setattr("docpipe_maestro.embedder.default.prepare_litellm", lambda: fake_litellm)
    assert estimate_embedding_cost("openai/bool-rate", 100) is None
    assert estimate_embedding_cost("openai/nan-rate", 100) is None
    assert estimate_embedding_cost("openai/neg-rate", 100) is None
    assert estimate_embedding_cost("openai/valid-rate", 100) == 1e-05


def test_reindex_dry_run_missing_empty_and_validation_parity(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    absent_persist = tmp_path / "absent_reindex_persist"
    absent_preview = reindex(
        embed_model="openai/text-embedding-3-small",
        collection="absent_col",
        persist_dir=absent_persist,
        dry_run=True,
    )
    assert isinstance(absent_preview, ReindexPreview)
    assert absent_preview.collection == "absent_col"
    assert absent_preview.embed_model == "openai/text-embedding-3-small"
    assert absent_preview.previous_embed_model is None
    assert absent_preview.total_sources == 0
    assert absent_preview.total_children == 0
    assert absent_preview.total_parents == 0
    assert absent_preview.estimated_tokens == 0
    assert absent_preview.estimated_cost_usd == 0.0
    assert absent_preview.dry_run is True
    assert not absent_persist.exists()

    # Empty manifest after removing sole document returns zero-work preview with locked prior model
    doc = tmp_path / "temp.md"
    doc.write_text("# Policy\n\nTemporary clause.\n", encoding="utf-8")
    ingest(doc, collection="empty_rx", persist_dir=tmp_persist_dir)
    assert remove("temp.md", collection="empty_rx", persist_dir=tmp_persist_dir) is True

    empty_preview = reindex(
        embed_model="openai/text-embedding-3-small",
        collection="empty_rx",
        persist_dir=tmp_persist_dir,
        dry_run=True,
    )
    assert empty_preview.previous_embed_model == "ollama/nomic-embed-text"
    assert empty_preview.total_sources == 0
    assert empty_preview.total_children == 0
    assert empty_preview.total_parents == 0
    assert empty_preview.estimated_tokens == 0
    assert empty_preview.estimated_cost_usd == 0.0

    # Validation parity on missing and populated manifests
    with pytest.raises(DocpipeError, match="local_only"):
        reindex(
            embed_model="openai/text-embedding-3-small",
            collection="absent_col",
            persist_dir=absent_persist,
            local_only=True,
            dry_run=True,
        )
    assert not absent_persist.exists()

    with pytest.raises(RegistryError):
        reindex(
            embed_model="ollama/nomic-embed-text",
            collection="absent_col",
            persist_dir=absent_persist,
            embedder="unknown_embedder",
            dry_run=True,
        )

    with pytest.raises(RegistryError):
        reindex(
            embed_model="ollama/nomic-embed-text",
            collection="empty_rx",
            persist_dir=tmp_persist_dir,
            store="unknown_store",
            dry_run=True,
        )
    assert not mock_litellm_offline["embedding"] or len(mock_litellm_offline["embedding"]) == 1


def test_reindex_dry_run_active_collection_subprocess_ro_and_parity(
    tmp_path: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    corpus = tmp_path / "rx_corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text(
        "## Section 1: Leave\n\n1.1 Standard leave is 20 days except new hires.\n",
        encoding="utf-8",
    )
    (corpus / "b.md").write_text(
        "## Section 1: Travel\n\n1.1 Economy rail tickets are reimbursed.\n",
        encoding="utf-8",
    )
    persist = tmp_path / "rx_persist"
    ingest(corpus, profile="POLICY", collection="rx_dry", persist_dir=persist)

    # Inject uncommitted staging records that MUST be excluded from active reindex preview
    staged_meta: ChunkMetadata = {
        "type": "child",
        "source": "a.md",
        "doc_version": "uncommitted999",
        "section": "Staged",
        "clause": None,
        "page": None,
        "chunk_index": 99,
        "embed_model": "ollama/nomic-embed-text",
    }
    store_obj = ChromaStore(persist, "rx_dry")
    store_obj.add_chunks(
        [
            EmbeddedChunk(
                id="orphan-child-id",
                text="Orphan uncommitted text that should never count toward reindex preview",
                parent_id="orphan-parent-id",
                metadata=staged_meta,
                vector=[0.1] * 64,
            )
        ]
    )

    st = status(collection="rx_dry", persist_dir=persist)
    calls_before = len(mock_litellm_offline["embedding"])
    tree_before = _tree_sha256(persist)

    local_preview = reindex(
        embed_model="ollama/nomic-embed-text",
        collection="rx_dry",
        persist_dir=persist,
        dry_run=True,
    )
    assert local_preview.estimated_cost_usd == 0.0

    cloud_preview = reindex(
        embed_model="openai/text-embedding-3-small",
        collection="rx_dry",
        persist_dir=persist,
        dry_run=True,
    )
    assert cloud_preview.collection == "rx_dry"
    assert cloud_preview.embed_model == "openai/text-embedding-3-small"
    assert cloud_preview.previous_embed_model == "ollama/nomic-embed-text"
    assert cloud_preview.total_sources == 2
    assert cloud_preview.total_children == st.total_children
    assert cloud_preview.total_parents == st.total_parents
    assert cloud_preview.estimated_tokens > 0
    assert isinstance(cloud_preview.estimated_cost_usd, float)
    assert cloud_preview.estimated_cost_usd > 0.0
    assert cloud_preview.dry_run is True
    assert len(mock_litellm_offline["embedding"]) == calls_before
    assert _tree_sha256(persist) == tree_before

    # Cold subprocess guarantees 0-byte SQLite header drift on chroma.sqlite3
    sub_code = (
        "import json; "
        "from docpipe_maestro import reindex; "
        "p = reindex("
        "embed_model='openai/text-embedding-3-small', "
        "collection='rx_dry', "
        f"persist_dir={str(persist)!r}, "
        "dry_run=True); "
        "print(json.dumps(p.to_dict()))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", sub_code], check=False, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == cloud_preview.to_dict()
    assert _tree_sha256(persist) == tree_before

    # Read-only directory (chmod 0555) verification on POSIX non-root
    if os.name == "posix" and os.geteuid() != 0:
        dirs = [persist, *(p for p in persist.rglob("*") if p.is_dir())]
        files = [p for p in persist.rglob("*") if p.is_file()]
        try:
            for fpath in files:
                os.chmod(fpath, 0o444)
            for dpath in reversed(dirs):
                os.chmod(dpath, 0o555)
            ro_proc = subprocess.run(
                [sys.executable, "-c", sub_code],
                check=False,
                capture_output=True,
                text=True,
            )
            assert ro_proc.returncode == 0, ro_proc.stderr
            assert json.loads(ro_proc.stdout) == cloud_preview.to_dict()
        finally:
            for dpath in dirs:
                os.chmod(dpath, 0o700)
            for fpath in files:
                os.chmod(fpath, 0o600)

    live_count = reindex(
        embed_model="openai/text-embedding-3-small",
        collection="rx_dry",
        persist_dir=persist,
    )
    assert live_count == cloud_preview.total_children


def test_reindex_dry_run_custom_store_delegation(tmp_path: Path) -> None:
    calls: list[str] = []
    committed_child = EmbeddedChunk(
        id="c1",
        text="One two three four five six",
        parent_id="p1",
        metadata={
            "type": "child",
            "source": "doc.md",
            "doc_version": "ver_active",
            "section": "S1",
            "clause": None,
            "page": 1,
            "chunk_index": 0,
            "embed_model": "ollama/nomic-embed-text",
        },
        vector=[0.0],
    )
    staged_child = EmbeddedChunk(
        id="c_stale",
        text="Should not be counted",
        parent_id="p_stale",
        metadata={
            "type": "child",
            "source": "doc.md",
            "doc_version": "ver_uncommitted",
            "section": "S1",
            "clause": None,
            "page": 1,
            "chunk_index": 1,
            "embed_model": "ollama/nomic-embed-text",
        },
        vector=[0.0],
    )
    committed_parent = EmbeddedChunk(
        id="p1",
        text="Parent section text",
        parent_id=None,
        metadata={
            "type": "parent",
            "source": "doc.md",
            "doc_version": "ver_active",
            "section": "S1",
            "clause": None,
            "page": 1,
            "chunk_index": 0,
            "embed_model": "ollama/nomic-embed-text",
        },
        vector=[0.0],
    )

    store_key = "spy_custom_dry_store"
    saved_entries = dict(STORES._entries)
    try:

        @register_store(store_key)
        class _SpyStore:
            name = store_key

            def __init__(self, persist_dir: Path, collection: str) -> None:
                calls.append("init")

            def add_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
                calls.append("add_chunks")
                raise AssertionError("add_chunks must not run during dry_run")

            def delete_by_source(self, source: str) -> None:
                calls.append("delete_by_source")

            def delete_stale_versions(self, source: str, active_version: str) -> None:
                calls.append("delete_stale_versions")

            def sweep_uncommitted(self, active_versions: dict[str, str]) -> int:
                calls.append("sweep_uncommitted")
                return 0

            def reset_collection(self) -> None:
                calls.append("reset_collection")
                raise AssertionError("reset_collection must not run during dry_run")

            def query_children(
                self,
                query_vector: list[float],
                *,
                top_k: int = 5,
                active_versions: dict[str, str] | None = None,
                where: dict[str, object] | None = None,
                include_embeddings: bool = False,
            ) -> list[Any]:
                return []

            def get_by_ids(
                self,
                ids: Sequence[str],
                *,
                include_embeddings: bool = False,
            ) -> list[EmbeddedChunk]:
                return []

            def get_parents_by_source(
                self,
                source: str,
                *,
                active_doc_version: str | None = None,
                include_embeddings: bool = False,
            ) -> list[EmbeddedChunk]:
                return []

            def get_all_children(self) -> list[EmbeddedChunk]:
                calls.append("get_all_children")
                return [committed_child, staged_child]

            def get_all_parents(self) -> list[EmbeddedChunk]:
                calls.append("get_all_parents")
                return [committed_parent]

        persist = tmp_path / "custom_store_persist"
        manifest = load_manifest(persist, "custom_col")
        manifest.embed_model = "ollama/nomic-embed-text"
        manifest.sources["doc.md"] = SourceRecord(
            source="doc.md",
            content_hash="sha256:abc",
            doc_version="ver_active",
            size=10,
            mtime=1.0,
            ingested_at="2026-11-17T00:00:00+00:00",
            embed_model="ollama/nomic-embed-text",
            profile="DEFAULT",
            chunk_ids=["c1"],
            parent_ids=["p1"],
        )
        save_manifest(persist, manifest)

        preview = reindex(
            embed_model="openai/text-embedding-3-small",
            collection="custom_col",
            persist_dir=persist,
            store=store_key,
            dry_run=True,
        )
        assert calls == ["init", "get_all_children", "get_all_parents"]
        assert preview.total_sources == 1
        assert preview.total_children == 1
        assert preview.total_parents == 1
        assert preview.estimated_tokens == 8  # ceil(6 * 4 / 3)
        assert isinstance(preview.estimated_cost_usd, float) and preview.estimated_cost_usd > 0.0
    finally:
        STORES._entries.clear()
        STORES._entries.update(saved_entries)
