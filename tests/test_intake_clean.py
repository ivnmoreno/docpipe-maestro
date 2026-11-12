"""Unit tests for Phase 1 intake parsing and text cleaning."""

from __future__ import annotations

from pathlib import Path

import pytest

from docpipe_maestro.ingest.clean import clean_document
from docpipe_maestro.ingest.intake import parse_file
from docpipe_maestro.types import UnsupportedFormatError

FIXTURES_DOCS = Path(__file__).parent / "fixtures" / "docs"


def test_parse_all_supported_formats() -> None:
    md_doc = parse_file(FIXTURES_DOCS / "sample.md", source_key="sample.md")
    assert len(md_doc.sections) >= 2
    assert any("Annual Leave" in s.section_label for s in md_doc.sections)

    txt_doc = parse_file(FIXTURES_DOCS / "sample.txt", source_key="sample.txt")
    assert any("encrypted" in s.raw_text.lower() for s in txt_doc.sections)

    html_doc = parse_file(FIXTURES_DOCS / "sample.html", source_key="sample.html")
    cleaned_html = clean_document(html_doc)
    joined_html = "\n".join(s.raw_text for s in cleaned_html.sections)
    assert "console.log" not in joined_html
    assert "reimbursed up to $75" in joined_html

    docx_doc = parse_file(FIXTURES_DOCS / "sample.docx", source_key="sample.docx")
    assert any("Medical insurance coverage" in s.raw_text for s in docx_doc.sections)

    pdf_doc = parse_file(FIXTURES_DOCS / "sample.pdf", source_key="sample.pdf")
    assert any(s.page == 1 for s in pdf_doc.sections)
    assert any(
        "Expense Policy" in s.raw_text or "approved portal" in s.raw_text for s in pdf_doc.sections
    )


def test_magic_byte_fallback_without_extension(tmp_path: Path) -> None:
    pdf_bytes = (FIXTURES_DOCS / "sample.pdf").read_bytes()
    no_ext = tmp_path / "ambiguous_file"
    no_ext.write_bytes(pdf_bytes)
    doc = parse_file(no_ext, source_key="ambiguous_file")
    assert any(s.page == 1 for s in doc.sections)


def test_unsupported_and_corrupted_files_fail_loudly(tmp_path: Path) -> None:
    bad_bin = tmp_path / "image.png"
    bad_bin.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    with pytest.raises(UnsupportedFormatError):
        parse_file(bad_bin, source_key="image.png")

    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\ncorrupted-garbage")
    with pytest.raises(UnsupportedFormatError):
        parse_file(bad_pdf, source_key="corrupt.pdf")


def test_clean_preserves_clause_numbering_and_strips_boilerplate(tmp_path: Path) -> None:
    txt = tmp_path / "clauses.txt"
    txt.write_text(
        "Section 1: Leave\n\n\n1.1   Employees get 20 days.\n1.2   Except for new hires.\n",
        encoding="utf-8",
    )
    doc = clean_document(parse_file(txt, source_key="clauses.txt"))
    full = "\n".join(s.raw_text for s in doc.sections)
    assert "1.1 Employees get 20 days." in full
    assert "1.2 Except for new hires." in full


def test_markdown_fenced_code_html_tables_and_docx_tables(tmp_path: Path) -> None:
    from docx import Document

    # 1. Markdown fenced code block with '#' comments must not split sections
    md = tmp_path / "code.md"
    md.write_text(
        "# Setup Guide\n\n```bash\n# Install dependency\npip install docpipe-maestro\n```\n",
        encoding="utf-8",
    )
    md_doc = parse_file(md, source_key="code.md")
    assert [s.section_label for s in md_doc.sections] == ["Setup Guide"]
    assert "# Install dependency" in md_doc.sections[0].raw_text

    # 2. HTML tables, div direct text, and li>p without duplication
    html = tmp_path / "rich.html"
    html.write_text(
        "<html><body>"
        "<h1>Leave Matrix</h1>"
        "<p>Summary rule.</p>"
        "<ul><li><p>Rule inside list p</p></li></ul>"
        "<div>Direct text in div.</div>"
        "<table><tr><th>Tenure</th><th>Days</th></tr><tr><td>0-1 yr</td><td>15</td></tr></table>"
        "</body></html>",
        encoding="utf-8",
    )
    html_doc = clean_document(parse_file(html, source_key="rich.html"))
    html_txt = "\n".join(s.raw_text for s in html_doc.sections)
    assert "0-1 yr | 15" in html_txt
    assert "Direct text in div." in html_txt
    assert html_txt.count("Rule inside list p") == 1

    # 3. DOCX tables preserved in reading order under active section
    docx_path = tmp_path / "limits.docx"
    d = Document()
    d.add_heading("Approval Limits", level=1)
    tbl = d.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "Role"
    tbl.cell(0, 1).text = "Limit"
    tbl.cell(1, 0).text = "VP"
    tbl.cell(1, 1).text = "$5000"
    d.save(str(docx_path))

    docx_doc = parse_file(docx_path, source_key="limits.docx")
    assert docx_doc.sections[0].section_label == "Approval Limits"
    assert "VP | $5000" in docx_doc.sections[0].raw_text


def test_clean_strips_normalized_multipage_boilerplate() -> None:
    from docpipe_maestro.ingest.intake import ParsedDocument, ParsedSection

    raw_doc = ParsedDocument(
        source="multi.pdf",
        format_name="pdf",
        sections=[
            ParsedSection(
                source="multi.pdf",
                section_label="Section 1: Overview",
                heading_level=2,
                raw_text="ACME   CONFIDENTIAL\nClause 1.1 text.\nFooter Line",
                page=1,
            ),
            ParsedSection(
                source="multi.pdf",
                section_label="Section 1: Overview",
                heading_level=2,
                raw_text="ACME CONFIDENTIAL\nClause 1.2 text.\nFooter Line",
                page=2,
            ),
            ParsedSection(
                source="multi.pdf",
                section_label="Section 1: Overview",
                heading_level=2,
                raw_text="ACME  CONFIDENTIAL\nClause 1.3 text.\nFooter Line",
                page=3,
            ),
        ],
    )
    cleaned = clean_document(raw_doc)
    combined = "\n".join(s.raw_text for s in cleaned.sections)
    assert "CONFIDENTIAL" not in combined
    assert "Footer Line" not in combined
    assert "Clause 1.2 text." in combined
