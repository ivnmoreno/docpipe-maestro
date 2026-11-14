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


def test_crossrefs_enricher_protocol_parity_and_warning_equivalence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CrossrefsEnricher satisfies Enricher and matches resolve_crossrefs text and warnings."""
    from docpipe_maestro.config import DEFAULT, POLICY
    from docpipe_maestro.ingest.crossrefs import resolve_crossrefs
    from docpipe_maestro.ingest.enricher import CrossrefsEnricher
    from docpipe_maestro.ingest.stages import Enricher
    from docpipe_maestro.types import IngestContext, ParsedDocument, ParsedSection

    assert DEFAULT.enrichers == ()
    assert POLICY.enrichers == ("crossrefs",)

    enricher = CrossrefsEnricher()
    assert isinstance(enricher, Enricher)
    assert enricher.name == "crossrefs"

    def _build_doc() -> ParsedDocument:
        return ParsedDocument(
            source="policy.md",
            format_name="markdown",
            sections=[
                ParsedSection(
                    source="policy.md",
                    section_label="1.1 Scope",
                    heading_level=2,
                    raw_text=(
                        "1.1 Applies to all staff.\n"
                        "See Section 2.3 for escalation steps\n"
                        "wrapped across multiple lines.\n"
                        "Also check Section 99.9 for missing ref."
                    ),
                ),
                ParsedSection(
                    source="policy.md",
                    section_label="2.3 Escalation",
                    heading_level=2,
                    raw_text="2.3 Notify security within 15 minutes.\nRefer back to Section 1.1.",
                ),
            ],
        )

    ctx: IngestContext = {
        "collection": "parity",
        "source": "policy.md",
        "content_hash": "sha256:" + "a" * 64,
        "doc_version": "a" * 12,
        "embed_model": "mock/embed",
        "profile": "POLICY",
    }

    with caplog.at_level(logging.WARNING):
        baseline_doc = resolve_crossrefs(_build_doc())
    baseline_warnings = [
        rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING
    ]

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        enriched_doc = enricher.enrich(_build_doc(), ctx)
    enriched_warnings = [
        rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING
    ]

    assert enriched_doc == baseline_doc
    assert enriched_warnings == baseline_warnings
    assert any("99.9" in msg or "Section 99.9" in msg for msg in enriched_warnings)

    sec1_text = enriched_doc.sections[0].raw_text
    sec2_text = enriched_doc.sections[1].raw_text
    assert "[Crossref" in sec1_text
    assert "Notify security within 15 minutes." in sec1_text
    assert "[Crossref" in sec2_text
    assert "Applies to all staff." in sec2_text


def test_policy_and_legacy_profile_run_crossrefs_end_to_end(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both profile='POLICY' and legacy resolve_crossrefs=True execute ENRICHERS['crossrefs']."""
    from docpipe_maestro.ingest.enricher import ENRICHERS
    from docpipe_maestro.ingest.pipeline import ingest, sync
    from docpipe_maestro.ingest.stages import Enricher
    from docpipe_maestro.store import VectorStore
    from docpipe_maestro.types import ChunkingProfile

    _ = mock_litellm_offline
    corpus = tmp_path / "policy_corpus"
    corpus.mkdir()
    doc = corpus / "handbook.md"
    doc.write_text(
        "# Handbook\n\n"
        "## 1. Overview\n"
        "See Section 2 for mandatory reporting rules.\n\n"
        "## 2. Reporting\n"
        "All incidents must be logged within one hour.\n",
        encoding="utf-8",
    )

    resolved: list[str] = []
    orig_resolve = ENRICHERS.resolve

    def _spy_resolve(name: str) -> type[Enricher]:
        resolved.append(name)
        return orig_resolve(name)

    monkeypatch.setattr(ENRICHERS, "resolve", _spy_resolve)

    ingest(
        doc,
        persist_dir=tmp_persist_dir,
        collection="policy_ingest",
        embed_model="mock/embed",
        profile="POLICY",
    )
    assert resolved == ["crossrefs"]

    resolved.clear()
    sync(
        corpus,
        persist_dir=tmp_persist_dir,
        collection="policy_sync",
        embed_model="mock/embed",
        profile="POLICY",
    )
    assert resolved == ["crossrefs"]

    resolved.clear()
    legacy_profile = ChunkingProfile(
        name="LEGACY_POLICY",
        chunk_size=1000,
        overlap=80,
        clause_preserving=True,
        parent_child=True,
        resolve_crossrefs=True,
    )
    assert legacy_profile.enrichers == ("crossrefs",)
    ingest(
        doc,
        persist_dir=tmp_persist_dir,
        collection="policy_legacy",
        embed_model="mock/embed",
        profile=legacy_profile,
    )
    assert resolved == ["crossrefs"]

    def _child_texts(col: str) -> list[str]:
        store = VectorStore(tmp_persist_dir, col)
        return sorted(c.text for c in store.get_all_children())

    ingest_texts = _child_texts("policy_ingest")
    sync_texts = _child_texts("policy_sync")
    legacy_texts = _child_texts("policy_legacy")

    assert ingest_texts == sync_texts == legacy_texts
    assert any("[Crossref" in text for text in ingest_texts)
    assert any("All incidents must be logged within one hour." in text for text in ingest_texts)


def test_legacy_crossrefs_module_silent_reexports_and_identity() -> None:
    """Importing and invoking legacy docpipe_maestro.ingest.crossrefs symbols is silent."""
    import importlib
    import warnings

    from docpipe_maestro import _crossrefs
    from docpipe_maestro.ingest.enricher import crossrefs as enricher_crossrefs
    from docpipe_maestro.types import ParsedDocument, ParsedSection

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        legacy_mod = importlib.reload(importlib.import_module("docpipe_maestro.ingest.crossrefs"))
        from docpipe_maestro.ingest.crossrefs import (
            extract_doc_crossrefs as legacy_extract,
        )
        from docpipe_maestro.ingest.crossrefs import (
            index_section_targets as legacy_index,
        )
        from docpipe_maestro.ingest.crossrefs import (
            match_source_key as legacy_match,
        )
        from docpipe_maestro.ingest.crossrefs import (
            resolve_crossrefs as legacy_resolve,
        )
        from docpipe_maestro.ingest.crossrefs import (
            truncate_excerpt as legacy_truncate,
        )

        refs = legacy_extract("See Section 1.2 of Master Services Agreement.")
        targets = legacy_index([("1.2 Notice", "Written notice required.")])
        matched = legacy_match(
            "Master Services Agreement",
            ["master_services_agreement.md", "other.md"],
        )
        truncated = legacy_truncate("word " * 120, 40)
        resolved = legacy_resolve(
            ParsedDocument(
                source="policy.md",
                format_name="markdown",
                sections=[
                    ParsedSection(
                        source="policy.md",
                        section_label="Section 1",
                        heading_level=2,
                        raw_text="See Section 2.",
                    ),
                    ParsedSection(
                        source="policy.md",
                        section_label="Section 2",
                        heading_level=2,
                        raw_text="Target clause.",
                    ),
                ],
            )
        )

    assert caught == []
    assert refs
    assert "1.2" in targets
    assert matched == "master_services_agreement.md"
    assert truncated.endswith("...")
    assert "[Crossref Section 2:" in resolved.sections[0].raw_text

    assert set(legacy_mod.__all__) == {
        "extract_doc_crossrefs",
        "index_section_targets",
        "match_source_key",
        "resolve_crossrefs",
        "truncate_excerpt",
    }
    assert legacy_extract is _crossrefs.extract_doc_crossrefs
    assert legacy_index is _crossrefs.index_section_targets
    assert legacy_match is _crossrefs.match_source_key
    assert legacy_truncate is _crossrefs.truncate_excerpt
    assert legacy_resolve is enricher_crossrefs.resolve_crossrefs


def test_multiline_crossref_annotation_ignored_by_phase2_extraction_and_clause_indexing(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, object],
) -> None:
    """Multi-line Phase 1 [Crossref ...] notes must not leak false clauses or citations."""
    from docpipe_maestro import ingest, retrieve
    from docpipe_maestro._crossrefs import extract_doc_crossrefs, index_section_targets

    _ = mock_litellm_offline
    annotated_text = (
        "1.1 Retention rules follow Section 2 and "
        "Clause 4.2 of the Master Services Agreement.\n\n"
        "[Crossref Section 2: Section 2: Exceptions [v1]: 2.1 Financial ledgers stay online.\n"
        "2.9 External Tax Code guidance applies via Section 9.9 of the External Tax Code.]"
    )
    doc_refs = extract_doc_crossrefs(annotated_text)
    assert [(disp, phrase) for disp, _keys, phrase in doc_refs] == [
        ("Clause 4.2", "Master Services Agreement"),
    ]
    targets = index_section_targets([("Section 1: Retention", annotated_text)])
    assert "2.9" not in targets
    assert "clause 2.9" not in targets

    corpus = tmp_path / "combined_xref_kb"
    corpus.mkdir()
    (corpus / "retention_policy.md").write_text(
        "## Section 1: Retention\n\n"
        "1.1 Isolate archival records under Section 2 and "
        "Clause 4.2 of the Master Services Agreement.\n\n"
        "## Section 2: Exceptions\n\n"
        "2.1 Financial ledgers remain encrypted for 7 years.\n"
        "See Section 9.9 of the External Tax Code for exceptions.\n",
        encoding="utf-8",
    )
    (corpus / "master_services_agreement.md").write_text(
        "## Article 4: Customer Notice\n\n"
        "4.2 Notify Customer within twenty-four (24) hours of any retention breach.\n",
        encoding="utf-8",
    )
    (corpus / "external_tax_code.md").write_text(
        "## Section 9: Tax Audit\n\n"
        "9.9 Preserve tax filings for ten years with external auditor signoff.\n",
        encoding="utf-8",
    )

    ingest(corpus, profile="POLICY", collection="combo_xref", persist_dir=tmp_persist_dir)
    hits = retrieve(
        "isolate archival records under Section 2",
        collection="combo_xref",
        persist_dir=tmp_persist_dir,
        top_k=1,
        expand_parent=True,
        follow_crossrefs=True,
    )
    assert len(hits) == 1
    assert hits[0].metadata["section"] == "Section 1: Retention"
    assert "[Crossref Section 2:" in hits[0].text
    assert "[Crossref Clause 4.2 (master_services_agreement.md):" in hits[0].text
    assert "[Crossref Section 9.9 (external_tax_code.md):" not in hits[0].text


def test_crossrefs_defensive_edge_cases() -> None:
    """Cover defensive boundary helpers in _crossrefs and lazy module __getattr__."""
    from docpipe_maestro._crossrefs import (
        extract_doc_crossrefs,
        match_source_key,
        truncate_excerpt,
    )
    from docpipe_maestro.ingest import enricher as enricher_pkg

    unbroken = "A" * 60
    assert truncate_excerpt(unbroken, 40) == f"{'A' * 40}..."

    deduped = extract_doc_crossrefs(
        "See Section 4.1 of Compliance Policy and again Section 4.1 of Compliance Policy."
    )
    assert len(deduped) == 1

    assert match_source_key("", ["a.md", "b.md"]) is None
    assert match_source_key("Only Doc", ["only_doc.md"], current_source="only_doc.md") is None

    with pytest.raises(AttributeError, match="does_not_exist"):
        _ = enricher_pkg.does_not_exist
