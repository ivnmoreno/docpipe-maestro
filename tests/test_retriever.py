"""Unit tests for Phase 2 semantic retrieval, parent expansion, and deduplication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, retrieve, status
from docpipe_maestro.manifest import load_manifest, save_manifest
from docpipe_maestro.query.searcher.dense import DenseSearcher
from docpipe_maestro.types import DocpipeError


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
