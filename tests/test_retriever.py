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
