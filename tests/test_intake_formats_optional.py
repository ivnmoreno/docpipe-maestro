"""Tests for optional intake extras (.xlsx, .pptx, .epub, .rst): guards, extraction, lifecycle."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, retrieve, sync
from docpipe_maestro.config import POLICY
from docpipe_maestro.ingest.clean import clean_document
from docpipe_maestro.ingest.intake import (
    EpubParser,
    PptxParser,
    RstParser,
    XlsxParser,
    detect_format,
    parse_file,
)
from docpipe_maestro.types import MissingExtraError, PiiPolicy, UnsupportedFormatError


@pytest.mark.parametrize(
    ("filename", "payload", "module_name", "extra_name"),
    [
        ("book.xlsx", b"PK\x03\x04dummy", "openpyxl", "xlsx"),
        ("deck.pptx", b"PK\x03\x04dummy", "pptx", "pptx"),
        ("manual.epub", b"PK\x03\x04dummy", "ebooklib", "epub"),
        ("guide.rst", b"Title\n=====\n\nBody.\n", "docutils", "rst"),
    ],
)
def test_optional_format_missing_extra_fails_loudly_without_store_writes(
    tmp_path: Path,
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_litellm_offline: dict[str, Any],
    filename: str,
    payload: bytes,
    module_name: str,
    extra_name: str,
) -> None:
    _ = mock_litellm_offline
    sample = tmp_path / filename
    sample.write_bytes(payload)

    for key in list(sys.modules):
        if key == module_name or key.startswith(f"{module_name}."):
            monkeypatch.setitem(sys.modules, key, None)
    monkeypatch.setitem(sys.modules, module_name, None)

    with pytest.raises(MissingExtraError, match=rf"docpipe-maestro\[{extra_name}\]"):
        parse_file(sample, source_key=filename)

    with pytest.raises(MissingExtraError, match=rf"docpipe-maestro\[{extra_name}\]"):
        ingest(sample, collection=f"missing_{extra_name}", persist_dir=tmp_persist_dir)

    with pytest.raises(MissingExtraError, match=rf"docpipe-maestro\[{extra_name}\]"):
        sync(tmp_path, collection=f"missing_{extra_name}", persist_dir=tmp_persist_dir)

    from docpipe_maestro import status

    st = status(collection=f"missing_{extra_name}", persist_dir=tmp_persist_dir)
    assert st.total_sources == 0
    assert st.total_children == 0
    assert not (tmp_persist_dir / "chroma.sqlite3").exists()


def _build_sample_xlsx(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws_vis = wb.active
    assert ws_vis is not None
    ws_vis.title = "Leave Matrix"
    # Leading blank row, trailing blank columns, and >25 rows for windowing check
    ws_vis.append([None, None, None])
    ws_vis.append(["Role", "Days", "Condition", None, None])
    for idx in range(1, 29):
        ws_vis.append([f"Role{idx}", 20, f"Except probation rule {idx}", None, None])

    ws_hidden = wb.create_sheet("HiddenDraft")
    ws_hidden.sheet_state = "hidden"
    ws_hidden.append(["SecretCol"])
    ws_hidden.append(["HIDDEN_TAB_SHOULD_NOT_APPEAR"])

    ws_very_hidden = wb.create_sheet("VeryHiddenAudit")
    ws_very_hidden.sheet_state = "veryHidden"
    ws_very_hidden.append(["Internal"])
    ws_very_hidden.append(["VERY_HIDDEN_SHOULD_NOT_APPEAR"])

    ws_empty = wb.create_sheet("EmptySheet")
    ws_empty.append([None, "   "])

    wb.save(str(path))
    wb.close()


def _build_xlsx_with_cached_formula(path: Path) -> None:
    """Create a valid minimal XLSX containing a cached numeric formula value (<f> + <v>)."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Budgets"
    ws.append(["Base", "Bonus", "Total"])
    ws.append([100, 50, "=A2+B2"])
    wb.save(str(path))
    wb.close()

    # Inject cached <v>150</v> next to <f>A2+B2</f> so data_only=True reads 150 cleanly
    buf_entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path, "r") as zf:
        for name in zf.namelist():
            data = zf.read(name)
            if name == "xl/worksheets/sheet1.xml":
                xml_txt = data.decode("utf-8").replace(
                    "<f>A2+B2</f>",
                    "<f>A2+B2</f><v>150</v>",
                )
                data = xml_txt.encode("utf-8")
            buf_entries[name] = data
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in buf_entries.items():
            zf.writestr(name, data)


def _build_sample_pptx(path: Path) -> None:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    blank_layout = prs.slide_layouts[1]

    # Slide 1: title + body + table + speaker notes
    s1 = prs.slides.add_slide(blank_layout)
    assert s1.shapes.title is not None
    s1.shapes.title.text = "Travel Reimbursement Cap"
    s1.placeholders[1].text = "Economy airfare applies except medical accommodation."
    tbl_shape = s1.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(5), Inches(1))
    tbl_shape.table.cell(0, 0).text = "Category"
    tbl_shape.table.cell(0, 1).text = "Limit"
    tbl_shape.table.cell(1, 0).text = "Hotel"
    tbl_shape.table.cell(1, 1).text = "$250 per night"
    s1.notes_slide.notes_text_frame.text = "Clause 2.1 VP pre-approval required unless emergency."

    # Slide 2: grouped shape + fallback Slide 2 title
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    grp = s2.shapes.add_group_shape()
    tb = grp.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    tb.text_frame.text = "Grouped shape security checklist"

    # Slide 3: empty slide skipped
    prs.slides.add_slide(prs.slide_layouts[6])

    prs.save(str(path))


def _build_sample_epub(path: Path) -> None:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("docpipe-epub-014")
    book.set_title("Corporate Compliance Handbook")
    book.set_language("en")

    c1 = epub.EpubHtml(title="Leave Rules", file_name="chap_01.xhtml", lang="en")
    c1.content = (
        "<html><body>"
        "<h1>Section 1: Annual Leave</h1>"
        "<p>Employees receive 20 days except during probation.</p>"
        "<script>alert('xss')</script>"
        "<div hidden>HIDDEN_EPUB_SECRET</div>"
        '<p style="display: none">INJECTED_HIDDEN_TEXT</p>'
        '<span aria-hidden="true">ARIA_HIDDEN_SECRET</span>'
        "</body></html>"
    )
    c2 = epub.EpubHtml(title="Remote Security", file_name="chap_02.xhtml", lang="en")
    c2.content = (
        "<html><body>"
        "<h2>Section 2: Equipment Stipend</h2>"
        "<p>Setup stipend up to $800 USD provided that receipts arrive in 60 days.</p>"
        "</body></html>"
    )
    book.add_item(c1)
    book.add_item(c2)
    book.add_item(
        epub.EpubItem(uid="css", file_name="style.css", media_type="text/css", content=b"body{}")
    )
    book.spine = ["nav", c1, c2]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def test_optional_xlsx_visible_sheets_windowing_and_formulas(tmp_path: Path) -> None:
    assert XlsxParser.extensions == (".xlsx",)
    xlsx_path = tmp_path / "leave.xlsx"
    _build_sample_xlsx(xlsx_path)

    doc = parse_file(xlsx_path, source_key="leave.xlsx")
    assert doc.format_name == "xlsx"
    assert [s.section_label for s in doc.sections] == [
        "Leave Matrix (Rows 1-25)",
        "Leave Matrix (Rows 26-28)",
    ]
    joined = "\n".join(s.raw_text for s in doc.sections)
    assert "Role: Role1 | Days: 20 | Condition: Except probation rule 1" in joined
    assert "Column 4" not in joined
    assert "HIDDEN_TAB_SHOULD_NOT_APPEAR" not in joined
    assert "VERY_HIDDEN_SHOULD_NOT_APPEAR" not in joined

    # Cached formula value read + uncached formula tolerance
    formula_xlsx = tmp_path / "budgets.xlsx"
    _build_xlsx_with_cached_formula(formula_xlsx)
    f_doc = parse_file(formula_xlsx, source_key="budgets.xlsx")
    assert len(f_doc.sections) == 1
    assert "Total: 150" in f_doc.sections[0].raw_text

    # Blank workbook returns sections=[]
    import openpyxl

    empty_xlsx = tmp_path / "empty.xlsx"
    wb = openpyxl.Workbook()
    wb.save(str(empty_xlsx))
    wb.close()
    assert parse_file(empty_xlsx, source_key="empty.xlsx").sections == []


def test_optional_pptx_slides_tables_groups_and_notes(tmp_path: Path) -> None:
    assert PptxParser.extensions == (".pptx",)
    pptx_path = tmp_path / "policy_deck.pptx"
    _build_sample_pptx(pptx_path)

    doc = parse_file(pptx_path, source_key="policy_deck.pptx")
    assert doc.format_name == "pptx"
    assert len(doc.sections) == 2
    assert doc.sections[0].page == 1
    assert doc.sections[0].section_label == "Travel Reimbursement Cap"
    assert "Hotel | $250 per night" in doc.sections[0].raw_text
    assert "Speaker Notes:" in doc.sections[0].raw_text
    assert "Clause 2.1 VP pre-approval required unless emergency." in doc.sections[0].raw_text
    assert doc.sections[1].page == 2
    assert doc.sections[1].section_label == "Slide 2"
    assert "Grouped shape security checklist" in doc.sections[1].raw_text

    from pptx import Presentation

    empty_pptx = tmp_path / "empty.pptx"
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(str(empty_pptx))
    assert parse_file(empty_pptx, source_key="empty.pptx").sections == []


def test_optional_epub_spine_chapters_and_hidden_html_stripping(tmp_path: Path) -> None:
    assert EpubParser.extensions == (".epub",)
    epub_path = tmp_path / "handbook.epub"
    _build_sample_epub(epub_path)

    doc = clean_document(parse_file(epub_path, source_key="handbook.epub"))
    assert doc.format_name == "epub"
    labels = [s.section_label for s in doc.sections]
    assert "Section 1: Annual Leave" in labels
    assert "Section 2: Equipment Stipend" in labels
    combined = "\n".join(s.raw_text for s in doc.sections)
    assert "20 days except during probation" in combined
    assert "up to $800 USD" in combined
    assert "HIDDEN_EPUB_SECRET" not in combined
    assert "INJECTED_HIDDEN_TEXT" not in combined
    assert "ARIA_HIDDEN_SECRET" not in combined
    assert "alert('xss')" not in combined


def test_optional_rst_sections_headings_tables_and_fallbacks(tmp_path: Path) -> None:
    assert RstParser.extensions == (".rst",)

    # 1. Single promoted top-level title + nested section + list + note + table
    rst_path = tmp_path / "policy.rst"
    rst_path.write_text(
        "Employee Standards\n"
        "==================\n\n"
        "Core overview paragraph.\n\n"
        "Remote Work\n"
        "-----------\n\n"
        ".. note::\n"
        "   VPN required on public networks.\n\n"
        "- Laptops enrolled in MDM\n\n"
        "+-------+--------+\n"
        "| Item  | Cap    |\n"
        "+=======+========+\n"
        "| Desk  | $800   |\n"
        "+-------+--------+\n",
        encoding="utf-8",
    )
    doc = parse_file(rst_path, source_key="policy.rst")
    assert doc.format_name == "rst"
    assert [s.section_label for s in doc.sections] == ["Employee Standards", "Remote Work"]
    assert doc.sections[0].heading_level == 1
    assert "Core overview paragraph." in doc.sections[0].raw_text
    assert doc.sections[1].heading_level == 2
    assert "VPN required on public networks." in doc.sections[1].raw_text
    assert "Desk | $800" in doc.sections[1].raw_text

    # 2. Headingless RST falls back to Introduction
    no_head = tmp_path / "plain.rst"
    no_head.write_text("Simple paragraph without heading.\n", encoding="utf-8")
    no_head_doc = parse_file(no_head, source_key="plain.rst")
    assert len(no_head_doc.sections) == 1
    assert no_head_doc.sections[0].section_label == "Introduction"
    assert no_head_doc.sections[0].heading_level == 1

    # 3. Empty RST returns sections=[]
    empty_rst = tmp_path / "empty.rst"
    empty_rst.write_text("   \n", encoding="utf-8")
    assert parse_file(empty_rst, source_key="empty.rst").sections == []


def test_optional_extensionless_zip_detection_and_full_lifecycle(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    _ = mock_litellm_offline

    # Extensionless ZIP container routing across XLSX, PPTX, EPUB
    xlsx_src = tmp_path / "src.xlsx"
    _build_sample_xlsx(xlsx_src)
    extless_xlsx = tmp_path / "blob_xlsx"
    extless_xlsx.write_bytes(xlsx_src.read_bytes())
    assert detect_format(extless_xlsx) == "xlsx"
    assert parse_file(extless_xlsx, source_key="blob_xlsx").format_name == "xlsx"

    pptx_src = tmp_path / "src.pptx"
    _build_sample_pptx(pptx_src)
    extless_pptx = tmp_path / "blob_pptx"
    extless_pptx.write_bytes(pptx_src.read_bytes())
    assert detect_format(extless_pptx) == "pptx"
    assert parse_file(extless_pptx, source_key="blob_pptx").format_name == "pptx"

    epub_src = tmp_path / "src.epub"
    _build_sample_epub(epub_src)
    extless_epub = tmp_path / "blob_epub"
    extless_epub.write_bytes(epub_src.read_bytes())
    assert detect_format(extless_epub) == "epub"
    assert parse_file(extless_epub, source_key="blob_epub").format_name == "epub"

    # Full corpus lifecycle across all 4 rich formats + PII redaction
    corpus = tmp_path / "rich_corpus"
    corpus.mkdir()
    _build_sample_xlsx(corpus / "leave.xlsx")
    _build_sample_pptx(corpus / "travel.pptx")
    _build_sample_epub(corpus / "handbook.epub")
    (corpus / "contact.rst").write_text(
        "Escalation Contact\n==================\n\nReach admin@example.com for overrides.\n",
        encoding="utf-8",
    )

    pii_policy: PiiPolicy = {"types": {"EMAIL_ADDRESS": "redact"}}
    res = ingest(
        corpus,
        profile=POLICY,
        collection="rich_all",
        persist_dir=tmp_persist_dir,
        pii_policy=pii_policy,
    )
    assert sorted(res.ingested) == ["contact.rst", "handbook.epub", "leave.xlsx", "travel.pptx"]

    dry = sync(
        corpus, profile=POLICY, collection="rich_all", persist_dir=tmp_persist_dir, dry_run=True
    )
    assert sorted(dry.skipped) == ["contact.rst", "handbook.epub", "leave.xlsx", "travel.pptx"]
    assert dry.added == []

    hits = retrieve("medical accommodation", collection="rich_all", persist_dir=tmp_persist_dir)
    assert hits and any(h.metadata["source"] == "travel.pptx" for h in hits)

    email_hits = retrieve("Escalation Contact", collection="rich_all", persist_dir=tmp_persist_dir)
    assert email_hits
    assert "admin@example.com" not in email_hits[0].text
    assert "[EMAIL_ADDRESS]" in email_hits[0].text

    # Corrupt archives raise UnsupportedFormatError cleanly
    corrupt_xlsx = tmp_path / "corrupt.xlsx"
    corrupt_xlsx.write_bytes(b"not-a-zip")
    with pytest.raises(UnsupportedFormatError):
        parse_file(corrupt_xlsx, source_key="corrupt.xlsx")
