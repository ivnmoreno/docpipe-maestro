"""Unit and integration tests for sync, shrinking-file orphan removal, rollback, and reindex."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, reindex, remove, retrieve, status, sync
from docpipe_maestro.types import DocpipeError, ModelMismatchError


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
