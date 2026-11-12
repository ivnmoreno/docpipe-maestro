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
