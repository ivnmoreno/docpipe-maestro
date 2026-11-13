"""Unit tests for intra-document cross-reference detection and resolution."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from docpipe_maestro.ingest.clean import clean_document
from docpipe_maestro.ingest.crossrefs import resolve_crossrefs
from docpipe_maestro.ingest.intake import parse_file


def test_crossref_resolves_intra_document_and_prevents_cycles(tmp_path: Path) -> None:
    md = tmp_path / "policy.md"
    md.write_text(
        "## Section 1: Leave\n\n"
        "1.1 Annual leave is 20 days, subject to Section 2.\n\n"
        "## Section 2: Probation\n\n"
        "2.1 Probationary employees are not entitled to full leave under §1.1.\n",
        encoding="utf-8",
    )
    doc = clean_document(parse_file(md, source_key="policy.md"))
    resolved = resolve_crossrefs(doc)

    sec1 = resolved.sections[0].raw_text
    sec2 = resolved.sections[1].raw_text
    assert "[Crossref Section 2:" in sec1
    assert "Probationary employees" in sec1
    assert "[Crossref §1.1:" in sec2
    assert "Annual leave is 20 days" in sec2


def test_unresolved_crossref_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    md = tmp_path / "external_ref.md"
    md.write_text(
        "## Section 1: Overview\n\n1.1 Refer to Article 99 in the external regulatory code.\n",
        encoding="utf-8",
    )
    doc = clean_document(parse_file(md, source_key="external_ref.md"))
    with caplog.at_level(logging.WARNING):
        resolved = resolve_crossrefs(doc)

    assert "Article 99" in caplog.text
    assert len(resolved.sections) == 1


def test_crossref_resolves_dotted_headings_and_avoids_numeric_false_positives(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    md = tmp_path / "spec.md"
    md.write_text(
        "### 7.5 Public API\n\n"
        "Expose ingest, sync, and retrieve functions.\n\n"
        "### 20.2: Compliance Rules\n\n"
        "Verify Section 7.5 signatures; also check Article 2026 and §3.5.\n\n"
        "### 20.3 Self Reference\n\n"
        "Under §20.3 and Section 20.2, audit logs remain immutable.\n\n"
        "### 2026 Roadmap\n\n"
        "Future plans only.\n\n"
        "### 3.5mm Audio Hardware\n\n"
        "Analog jack specs.\n",
        encoding="utf-8",
    )
    doc = clean_document(parse_file(md, source_key="spec.md"))
    with caplog.at_level(logging.WARNING):
        resolved = resolve_crossrefs(doc)

    sec_20_2 = resolved.sections[1].raw_text
    sec_20_3 = resolved.sections[2].raw_text
    assert "[Crossref Section 7.5: 7.5 Public API: Expose ingest" in sec_20_2
    assert "[Crossref Article 2026:" not in sec_20_2
    assert "[Crossref §3.5:" not in sec_20_2
    assert "[Crossref Section 20.2: 20.2: Compliance Rules:" in sec_20_3
    assert "[Crossref §20.3:" not in sec_20_3
    assert "Article 2026" in caplog.text
    assert "§3.5" in caplog.text


def test_crossref_wrapped_clauses_and_doc_scoped_extraction(tmp_path: Path) -> None:
    from docpipe_maestro.ingest.crossrefs import extract_doc_crossrefs, match_source_key

    md = tmp_path / "wrapped.md"
    md.write_text(
        "## Article 4: Security\n\n"
        "4.2 Provider must notify Customer within\n"
        "twenty-four (24) hours of confirmed incident.\n\n"
        "## Article 5: Liability\n\n"
        "5.1 Except for Clause 4.2, liability is capped.\n",
        encoding="utf-8",
    )
    resolved = resolve_crossrefs(clean_document(parse_file(md, source_key="wrapped.md")))
    sec5 = resolved.sections[1].raw_text
    assert "[Crossref Clause 4.2:" in sec5
    assert "twenty-four (24) hours" in sec5

    refs = extract_doc_crossrefs(
        "Cross-reference Section 4.1 of the Compliance Policy and "
        "Clause 4.2 of the Master Services Agreement.\n"
        "[Crossref Section 9.9 of the External Spec: ignore annotation]"
    )
    assert [(disp, phrase) for disp, _keys, phrase in refs] == [
        ("Section 4.1", "Compliance Policy"),
        ("Clause 4.2", "Master Services Agreement"),
    ]
    sources = [
        "company_compliance_policy.html",
        "master_services_agreement.pdf",
        "remote_work_policy.md",
        "incident_response_runbook.md",
    ]
    assert (
        match_source_key(
            "Compliance Policy",
            sources,
            current_source="incident_response_runbook.md",
        )
        == "company_compliance_policy.html"
    )
    assert (
        match_source_key(
            "Master Services Agreement",
            sources,
            current_source="incident_response_runbook.md",
        )
        == "master_services_agreement.pdf"
    )
    assert match_source_key("Policy", sources) is None
