"""Extended integration and stress tests for complex documents and large-corpus usage."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from docx import Document

from docpipe_maestro import ingest, reindex, retrieve, status, sync
from docpipe_maestro.config import DEFAULT, POLICY
from docpipe_maestro.ingest.chunker import chunk_document
from docpipe_maestro.ingest.clean import clean_document
from docpipe_maestro.ingest.crossrefs import resolve_crossrefs
from docpipe_maestro.ingest.intake import parse_file
from docpipe_maestro.types import UnsupportedFormatError

REPO_ROOT = Path(__file__).resolve().parent.parent


def _build_pdf_bytes(pages: list[list[str]]) -> bytes:
    """Build a minimal valid multi-page PDF 1.4 document parseable by pypdf."""
    objs: list[tuple[int, bytes]] = []
    page_ids: list[int] = []
    font_id = 3 + len(pages) * 2

    for i, lines in enumerate(pages):
        p_id = 3 + i * 2
        c_id = p_id + 1
        page_ids.append(p_id)
        stream_lines = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
        for ln in lines:
            esc = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream_lines.append(f"({esc}) Tj T*")
        stream_lines.append("ET")
        content = "\n".join(stream_lines).encode("latin-1", "replace")
        objs.append(
            (
                p_id,
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {c_id} 0 R >>"
                ).encode("ascii"),
            )
        )
        header = f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
        objs.append((c_id, header + content + b"\nendstream"))

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    all_objs: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")),
        *objs,
        (font_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    all_objs.sort(key=lambda item: item[0])

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0] * (len(all_objs) + 1)
    for oid, body in all_objs:
        offsets[oid] = len(out)
        out.extend(f"{oid} 0 obj\n".encode("ascii") + body + b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


@pytest.mark.integration
def test_large_corpus_batching_real_docs_and_reindex(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Stress >70 child chunks (multi-batch embedder >64), real README/Product docs, and reindex."""
    corpus = tmp_path / "enterprise_kb"
    corpus.mkdir()

    # Include real project documentation files containing tables, code fences, and <placeholders>
    shutil.copy(REPO_ROOT / "README.md", corpus / "README.md")
    shutil.copy(REPO_ROOT / "Product.md", corpus / "Product.md")

    # Build a large 35-section policy manual exceeding batch_size=64
    manual_parts = ["# Global Enterprise Handbook\n"]
    for i in range(1, 36):
        manual_parts.append(
            f"## Section {i}: Operational Standard {i}\n\n"
            f"{i}.1 Staff members assigned to division {i} must complete compliance module {i} "
            f"when weekly hours > 15 and tenure < 90 days, except certified auditors.\n\n"
            + ("Supplemental operational guidance detailing regional reporting workflows. " * 22)
            + "\n"
        )
    (corpus / "enterprise_handbook.md").write_text("\n".join(manual_parts), encoding="utf-8")

    # Verify README fenced bash comments (# ...) did NOT create fake headings
    readme_parsed = parse_file(corpus / "README.md", source_key="README.md")
    readme_labels = [s.section_label for s in readme_parsed.sections]
    assert "PDF support only" not in readme_labels
    assert any("Installation" in lbl for lbl in readme_labels)

    # Verify math inequalities & <placeholders> stay intact through clean_document
    handbook_cleaned = clean_document(
        parse_file(corpus / "enterprise_handbook.md", source_key="enterprise_handbook.md")
    )
    handbook_txt = "\n".join(s.raw_text for s in handbook_cleaned.sections)
    assert "hours > 15 and tenure < 90 days" in handbook_txt

    readme_cleaned = clean_document(readme_parsed)
    readme_txt = "\n".join(s.raw_text for s in readme_cleaned.sections)
    assert "<collection>.json" in readme_txt
    assert "<uuid>" in readme_txt

    res = ingest(
        corpus,
        profile="POLICY",
        collection="large_kb",
        persist_dir=tmp_persist_dir,
    )
    assert len(res.ingested) == 3
    # Total child chunks exceed embed_texts default batch_size=64
    assert res.chunks_written > 70
    assert res.parents_written >= 35

    hits = retrieve(
        "compliance module 17 certified auditors division 17",
        collection="large_kb",
        persist_dir=tmp_persist_dir,
        top_k=5,
        expand_parent=True,
    )
    assert hits
    # Parents are strictly deduplicated and sorted descending
    assert len({h.id for h in hits}) == len(hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)

    # Full reindex across >70 stored child chunks to a different model/dimension
    reindexed_count = reindex(
        embed_model="openai/text-embedding-3-small",
        collection="large_kb",
        persist_dir=tmp_persist_dir,
    )
    assert reindexed_count == res.chunks_written
    st = status(collection="large_kb", persist_dir=tmp_persist_dir)
    assert st.embed_model == "openai/text-embedding-3-small"
    assert st.embed_dim == 32
    assert st.total_children == res.chunks_written

    post_hits = retrieve(
        "compliance module 17 certified auditors",
        collection="large_kb",
        persist_dir=tmp_persist_dir,
        embed_model="openai/text-embedding-3-small",
        top_k=3,
    )
    assert post_hits


@pytest.mark.integration
def test_multipage_pdf_continuity_boilerplate_and_identical_pages(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Verify multi-page PDF section inheritance, edge boilerplate stripping, and uniqueness."""
    pdf_path = tmp_path / "multipage_policy.pdf"
    pdf_bytes = _build_pdf_bytes(
        [
            [
                "ACME   CONFIDENTIAL",
                "Section 1: Global Benefits",
                "1.1 Employees receive 22 paid vacation days annually.",
                "Internal Distribution Only",
            ],
            [
                "ACME CONFIDENTIAL",
                "1.2 Staff working < 20 hours per week are not entitled to accrual.",
                "Internal Distribution Only",
            ],
            [
                "ACME  CONFIDENTIAL",
                "Section 2: Equipment & Expense",
                "2.1 Hardware purchases require VP approval subject to Section 1.",
                "Internal Distribution Only",
            ],
            [
                "ACME CONFIDENTIAL",
                "Section 3: Notes",
                "Intentionally left blank.",
                "Internal Distribution Only",
            ],
            [
                "ACME CONFIDENTIAL",
                "Section 3: Notes",
                "Intentionally left blank.",
                "Internal Distribution Only",
            ],
        ]
    )
    pdf_path.write_bytes(pdf_bytes)

    parsed = parse_file(pdf_path, source_key="multipage_policy.pdf")
    cleaned = clean_document(parsed)

    # Page 2 must inherit Section 1 label across the page break
    p2_secs = [s for s in cleaned.sections if s.page == 2]
    assert len(p2_secs) == 1
    assert p2_secs[0].section_label == "Section 1: Global Benefits"
    assert "< 20 hours" in p2_secs[0].raw_text

    # Running headers/footers across >=3 pages stripped cleanly despite spacing differences
    combined = "\n".join(s.raw_text for s in cleaned.sections)
    assert "CONFIDENTIAL" not in combined
    assert "Internal Distribution Only" not in combined

    # Ingesting repeated identical Page 4 & Page 5 Sections must succeed without DuplicateIDError
    res = ingest(
        pdf_path,
        profile="POLICY",
        collection="pdf_multi",
        persist_dir=tmp_persist_dir,
    )
    assert res.chunks_written == 5
    hits = retrieve(
        "not entitled accrual vacation",
        collection="pdf_multi",
        persist_dir=tmp_persist_dir,
    )
    assert hits
    assert any("not entitled to accrual" in h.text for h in hits)


@pytest.mark.integration
def test_complex_docx_and_html_tables_hierarchy_and_unicode(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Verify nested DOCX/HTML tables, nested lists, comments, and Unicode ingestion/retrieval."""
    corpus = tmp_path / "office_docs"
    corpus.mkdir()

    # 1. Complex DOCX with multiple heading levels, tables, and € / — Unicode characters
    docx_path = corpus / "reimbursement.docx"
    doc = Document()
    doc.add_heading("Corporate Travel Manual", level=1)
    doc.add_paragraph("Overview of international travel per-diem allowances — effective 2026.")
    doc.add_heading("Lodging & Hotel Caps", level=2)
    doc.add_paragraph("2.1 Hotel caps depend on city tier below:")
    tbl = doc.add_table(rows=3, cols=3)
    headers = ["Tier", "Nightly Cap", "Pre-Approval"]
    rows = [
        ["Tier A (Major Capitals)", "€280", "Manager"],
        ["Tier B (Regional Hubs)", "€180", "Automatic"],
    ]
    for c_idx, val in enumerate(headers):
        tbl.cell(0, c_idx).text = val
    for r_idx, r_vals in enumerate(rows, start=1):
        for c_idx, val in enumerate(r_vals):
            tbl.cell(r_idx, c_idx).text = val
    doc.save(str(docx_path))

    # 2. Complex messy HTML with scripts, nav, comments, nested div/article, lists, and table
    html_path = corpus / "benefits.html"
    html_path.write_text(
        """<!DOCTYPE html>
        <html>
          <head><style>.hide{display:none}</style><script>window.__secret="x";</script></head>
          <body>
            <nav>Home | Careers | Intranet</nav>
            <!-- CONFIDENTIAL_COMMENT_DO_NOT_INDEX -->
            <h1>Employee Benefits Portal</h1>
            <div><article><section>
              <div>Direct announcement inside nested container.</div>
              <h2>Stock Vesting Schedule</h2>
              <ul>
                <li><p>Standard 4-year vesting with 1-year cliff.</p>
                  <ul><li>Accelerated vesting applies on acquisition.</li></ul>
                </li>
              </ul>
              <blockquote>Consult equity counsel before exercising ISO options.</blockquote>
              <table>
                <tr><th>Status</th><th>Eligibility</th></tr>
                <tr><td>Probationary Hire</td><td>0 days equity grant</td></tr>
              </table>
            </section></article></div>
            <footer>Copyright ACME 2026</footer>
          </body>
        </html>""",
        encoding="utf-8",
    )

    res = ingest(corpus, profile="POLICY", collection="office_col", persist_dir=tmp_persist_dir)
    assert len(res.ingested) == 2

    # DOCX table retrieval
    docx_hits = retrieve(
        "Tier B Regional Hubs Nightly Cap",
        collection="office_col",
        persist_dir=tmp_persist_dir,
    )
    assert docx_hits
    assert any("€180" in h.text and "Automatic" in h.text for h in docx_hits)

    # HTML nested structure, table, div, blockquote, and stripped noise verification
    html_parsed = clean_document(parse_file(html_path, source_key="benefits.html"))
    html_all = "\n".join(s.raw_text for s in html_parsed.sections)
    assert "CONFIDENTIAL_COMMENT" not in html_all
    assert "window.__secret" not in html_all
    assert "Intranet" not in html_all
    assert "Direct announcement inside nested container." in html_all
    assert html_all.count("Standard 4-year vesting with 1-year cliff.") == 1
    assert "Accelerated vesting applies on acquisition." in html_all
    assert "Consult equity counsel" in html_all
    assert "Probationary Hire | 0 days equity grant" in html_all


@pytest.mark.integration
def test_complex_crossrefs_and_oversized_clauses(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify multi-ref resolution, word-safe truncation, numeric headers, and long blocks."""
    long_sec2_body = " ".join(f"compliance_word_{i}" for i in range(120))
    doc_path = tmp_path / "complex_policy.md"
    doc_path.write_text(
        "## Section 1: Core Entitlements\n\n"
        "1.1 General leave applies subject to Section 2, §3.1, §3.1, Section 1, "
        "and Section 4, unless excluded under Article 999.\n\n"
        "## Section 2: Detailed Carryover Computation Rules\n\n"
        f"2.1 {long_sec2_body}\n\n"
        "## Section 3: Approvals\n\n"
        "3.1 Written director sign-off is mandatory.\n\n"
        "## 4. Regional Caps\n\n"
        "4.1 Maximum annual carryover is capped at 5 days.\n",
        encoding="utf-8",
    )

    parsed = clean_document(parse_file(doc_path, source_key="complex_policy.md"))
    with caplog.at_level(logging.WARNING):
        resolved = resolve_crossrefs(parsed)

    sec1_text = resolved.sections[0].raw_text
    # Repeated §3.1 resolved once; self-ref Section 1 skipped; numeric heading Section 4 resolved
    assert sec1_text.count("[Crossref §3.1:") == 1
    assert "[Crossref Section 1:" not in sec1_text
    assert "[Crossref Section 4:" in sec1_text
    assert "Maximum annual carryover" in sec1_text
    assert "Article 999" in caplog.text

    # Word-boundary truncation for long Section 2 excerpt (>400 chars ends cleanly with '...')
    sec2_marker = "[Crossref Section 2:"
    assert sec2_marker in sec1_text
    sec2_line = next(ln for ln in sec1_text.splitlines() if ln.startswith(sec2_marker))
    assert sec2_line.endswith("...]")

    # Oversized >1500-token single clause stays indivisible in POLICY, splits in DEFAULT
    huge_path = tmp_path / "huge_clause.md"
    huge_clause = "1.1 " + " ".join(["regulation"] * 1350) + " unless revoked by board."
    huge_path.write_text(f"## Section 1: Massive\n\n{huge_clause}\n", encoding="utf-8")

    huge_doc = clean_document(parse_file(huge_path, source_key="huge_clause.md"))
    policy_chunks = chunk_document(huge_doc, profile=POLICY, doc_version="v1", embed_model="m")
    default_chunks = chunk_document(huge_doc, profile=DEFAULT, doc_version="v1", embed_model="m")

    policy_children = [c for c in policy_chunks if c.metadata["type"] == "child"]
    default_children = [c for c in default_chunks if c.metadata["type"] == "child"]

    assert len(policy_children) == 1
    assert "unless revoked by board." in policy_children[0].text
    assert len(default_children) >= 3


@pytest.mark.integration
def test_nested_sync_renames_empty_truncation_and_batch_atomicity(
    tmp_path: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Test nested subdirs, empty->nonempty->empty lifecycle, file renames, and atomic abort."""
    # 1. Atomic abort on bad directory must NOT create persist_dir DB artifacts
    bad_dir = tmp_path / "bad_corpus"
    bad_dir.mkdir()
    (bad_dir / "good.md").write_text("# Valid\n\nValid text.\n", encoding="utf-8")
    (bad_dir / "binary.bin").write_bytes(b"\x00\x01\x02\x03")
    aborted_persist = tmp_path / "aborted_store"

    with pytest.raises(UnsupportedFormatError):
        ingest(bad_dir, collection="abort_test", persist_dir=aborted_persist)
    assert not (aborted_persist / "chroma.sqlite3").exists()

    # 2. Nested corpus lifecycle with colocated .docpipe store inside root
    root = tmp_path / "nested_docs"
    (root / "hr" / "2026").mkdir(parents=True)
    (root / "it").mkdir(parents=True)
    persist = root / ".docpipe"

    draft = root / "hr" / "2026" / "00_empty_draft.md"
    draft.write_text("", encoding="utf-8")  # Alphabetically first & empty!
    leave = root / "hr" / "2026" / "leave.md"
    leave.write_text("## Leave\n\nOld 15-day leave clause.\n", encoding="utf-8")
    sec = root / "it" / "security.txt"
    sec.write_text("Section 1: Auth\n\n1.1 Hardware tokens are mandatory.\n", encoding="utf-8")

    first = ingest(root, profile="POLICY", collection="nested_col", persist_dir=persist)
    assert len(first.ingested) == 3

    # First file was empty; embed_dim must still be captured from leave.md
    st1 = status(collection="nested_col", persist_dir=persist)
    assert st1.embed_dim == 64
    assert st1.total_sources == 3

    # Touch untouched file (mtime change only), populate empty draft, rename leave.md, truncate sec
    st_leave = sec.stat()
    draft.write_text("## Draft Promoted\n\n1.1 Promoted policy guidance.\n", encoding="utf-8")
    (root / "hr" / "2026" / "leave_v2.md").write_text(
        "## Leave v2\n\nUpdated 25-day leave allowance.\n", encoding="utf-8"
    )
    leave.unlink()
    os.utime(sec, (st_leave.st_atime + 10, st_leave.st_mtime + 10))
    # First sync: security.txt untouched -> skipped
    s1 = sync(root, profile="POLICY", collection="nested_col", persist_dir=persist)
    assert "hr/2026/leave_v2.md" in s1.added
    assert "hr/2026/00_empty_draft.md" in s1.updated
    assert "it/security.txt" in s1.skipped
    assert "hr/2026/leave.md" in s1.removed

    # Truncate it/security.txt to 0 bytes -> old chunks must be purged with zero orphans
    sec.write_text("", encoding="utf-8")
    s2 = sync(root, profile="POLICY", collection="nested_col", persist_dir=persist)
    assert s2.updated == ["it/security.txt"]
    assert (
        retrieve(
            "Hardware tokens mandatory",
            collection="nested_col",
            persist_dir=persist,
            threshold=0.5,
        )
        == []
    )
    assert (
        retrieve(
            "Old 15-day leave clause",
            collection="nested_col",
            persist_dir=persist,
            threshold=0.5,
        )
        == []
    )
