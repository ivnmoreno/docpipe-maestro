"""Core-only unit and integration tests for built-in delimited intake (.csv and .tsv)."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, reindex, retrieve, status, sync
from docpipe_maestro.ingest.clean import clean_document
from docpipe_maestro.ingest.intake import (
    PARSERS,
    SUPPORTED_EXTENSIONS,
    CsvParser,
    TsvParser,
    detect_format,
    parse_file,
    register_parser,
)
from docpipe_maestro.types import ParsedDocument, ParsedSection, UnsupportedFormatError


@contextlib.contextmanager
def _clean_parser_registry() -> Iterator[None]:
    entries = dict(PARSERS._entries)
    lazy = dict(PARSERS._lazy_builtins)
    try:
        yield
    finally:
        PARSERS._entries = entries
        PARSERS._lazy_builtins = lazy


def test_delimited_csv_tsv_bom_crlf_ragged_and_trailing_blank_trimming(tmp_path: Path) -> None:
    assert {".csv", ".tsv"}.issubset(SUPPORTED_EXTENSIONS)

    csv_file = tmp_path / "policies.CSV"
    csv_file.write_bytes(
        b"\xef\xbb\xbfRole,,Days,,\r\n"
        b"Full-Time,Policy Notes,20,Except 90-day probation,\r\n"
        b"Intern\r\n"
        b",,,\r\n"
        b"Contractor,Hourly,0,Not eligible,ExtraField,\r\n"
    )
    assert detect_format(csv_file) == "csv"
    csv_doc = parse_file(csv_file, source_key="policies.CSV")
    assert csv_doc.format_name == "csv"
    assert len(csv_doc.sections) == 1
    sec = csv_doc.sections[0]
    assert sec.section_label == "policies.CSV (Rows 1-3)"
    assert sec.heading_level == 1
    assert sec.page is None
    lines = sec.raw_text.splitlines()
    assert lines == [
        ("Role: Full-Time | Column 2: Policy Notes | Days: 20 | Column 4: Except 90-day probation"),
        "Role: Intern",
        (
            "Role: Contractor | Column 2: Hourly | Days: 0 | "
            "Column 4: Not eligible | Column 5: ExtraField"
        ),
    ]
    assert "\ufeff" not in sec.raw_text

    tsv_file = tmp_path / "travel.tsv"
    tsv_file.write_text(
        "Item\tCap\tRule\n"
        "Airfare\tEconomy\tExcept medical approval\n"
        "Hotel\t$250\tUnless VP approved\n",
        encoding="utf-8",
    )
    assert detect_format(tsv_file) == "tsv"
    tsv_doc = clean_document(parse_file(tsv_file, source_key="travel.tsv"))
    assert tsv_doc.format_name == "tsv"
    assert len(tsv_doc.sections) == 1
    assert tsv_doc.sections[0].section_label == "travel.tsv (Rows 1-2)"
    assert "Item: Hotel | Cap: $250 | Rule: Unless VP approved" in tsv_doc.sections[0].raw_text


def test_delimited_25_row_windowing_and_empty_or_header_only(tmp_path: Path) -> None:
    rows = ["Employee,Department,LeaveDays"]
    rows.extend(f"User{i},Engineering,{15 + (i % 5)}" for i in range(1, 31))
    wide_csv = tmp_path / "roster.csv"
    wide_csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    doc = parse_file(wide_csv, source_key="roster.csv")
    assert [sec.section_label for sec in doc.sections] == [
        "roster.csv (Rows 1-25)",
        "roster.csv (Rows 26-30)",
    ]
    assert len(doc.sections[0].raw_text.splitlines()) == 25
    assert len(doc.sections[1].raw_text.splitlines()) == 5
    assert "Employee: User26 | Department: Engineering | LeaveDays: 16" in doc.sections[1].raw_text

    # Empty, whitespace-only, and header-only inputs return sections=[] consistently
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("", encoding="utf-8")
    assert parse_file(empty_csv, source_key="empty.csv").sections == []

    blank_tsv = tmp_path / "blank.tsv"
    blank_tsv.write_text("   \n\t\t\n", encoding="utf-8")
    assert parse_file(blank_tsv, source_key="blank.tsv").sections == []

    header_only = tmp_path / "headers_only.csv"
    header_only.write_bytes(b"\xef\xbb\xbfColA,ColB\n")
    assert parse_file(header_only, source_key="headers_only.csv").sections == []


def test_delimited_rejects_non_utf8_and_nul_bytes(tmp_path: Path) -> None:
    cp1252_csv = tmp_path / "latin1_cp1252.csv"
    cp1252_csv.write_bytes(b"Name,City,Allowance\nJos\xe9,M\xfcnich,\x80120\n")
    with pytest.raises(UnsupportedFormatError, match="UTF-8"):
        parse_file(cp1252_csv, source_key="latin1_cp1252.csv")

    nul_tsv = tmp_path / "binary_nul.tsv"
    nul_tsv.write_bytes(b"A\tB\nval\x00\t123\n")
    with pytest.raises(UnsupportedFormatError, match=r"NUL|binary|UTF-8"):
        parse_file(nul_tsv, source_key="binary_nul.tsv")


def test_delimited_custom_override_end_to_end(tmp_path: Path) -> None:
    assert CsvParser.extensions == (".csv",)
    assert TsvParser.extensions == (".tsv",)
    sample_csv = tmp_path / "data.csv"
    sample_csv.write_text("A,B\n1,2\n", encoding="utf-8")

    with _clean_parser_registry():

        @register_parser("custom_csv_override")
        class CustomCsv:
            name: str = "custom_csv_override"
            extensions: tuple[str, ...] = (".csv",)

            def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
                return ParsedDocument(
                    source=source_key,
                    format_name="custom_csv",
                    sections=[
                        ParsedSection(
                            source=source_key,
                            section_label="Custom",
                            heading_level=1,
                            raw_text="custom",
                        )
                    ],
                )

        doc = parse_file(sample_csv, source_key="data.csv")
        assert doc.format_name == "custom_csv"
        assert doc.sections[0].raw_text == "custom"


def test_delimited_full_phase1_phase2_lifecycle_core_only(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    _ = mock_litellm_offline
    corpus = tmp_path / "tabular_corpus"
    corpus.mkdir()

    (corpus / "leave.csv").write_text(
        "Category,Entitlement,Exception\n"
        "Full-Time,20 days,Except initial 90-day probationary period\n",
        encoding="utf-8-sig",
    )
    (corpus / "expenses.tsv").write_text(
        "Type\tLimit\tCondition\nLodging\t$250/night\tUnless pre-approved by VP under Clause 2.1\n",
        encoding="utf-8",
    )
    (corpus / "empty.csv").write_text("", encoding="utf-8")

    res = ingest(corpus, profile="POLICY", collection="delimited_col", persist_dir=tmp_persist_dir)
    assert sorted(res.ingested) == ["empty.csv", "expenses.tsv", "leave.csv"]
    assert res.chunks_written >= 2

    dry = sync(
        corpus,
        profile="POLICY",
        collection="delimited_col",
        persist_dir=tmp_persist_dir,
        dry_run=True,
    )
    assert dry.added == []
    assert dry.updated == []
    assert sorted(dry.skipped) == ["empty.csv", "expenses.tsv", "leave.csv"]

    st = status(collection="delimited_col", persist_dir=tmp_persist_dir)
    assert st.total_sources == 3

    hits = retrieve("probationary period", collection="delimited_col", persist_dir=tmp_persist_dir)
    assert hits and any("90-day probationary period" in h.text for h in hits)

    reindexed = reindex(
        collection="delimited_col",
        persist_dir=tmp_persist_dir,
        embed_model="mock/small-embed",
    )
    assert reindexed == res.chunks_written
