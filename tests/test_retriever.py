"""Unit tests for Phase 2 semantic retrieval, parent expansion, and deduplication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docpipe_maestro import ingest, retrieve


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
