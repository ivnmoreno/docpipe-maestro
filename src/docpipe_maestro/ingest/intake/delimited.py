"""Core delimited-text parser strategies (``.csv`` and ``.tsv``) using Python stdlib ``csv``."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.intake._common import _format_tabular_sections
from docpipe_maestro.types import ParsedDocument, UnsupportedFormatError


def _parse_delimited(
    path: Path,
    *,
    source_key: str,
    delimiter: str,
    format_name: str,
) -> ParsedDocument:
    """Decode strict UTF-8 / UTF-8-SIG delimited text into bounded 25-row sections.

    Raises:
        UnsupportedFormatError: If file reading fails, bytes contain invalid UTF-8
            or embedded NUL bytes, or CSV tokenization fails.
    """
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise UnsupportedFormatError(f"Failed to read {source_key!r}: {exc}") from exc

    if b"\x00" in raw_bytes:
        raise UnsupportedFormatError(f"Binary NUL byte detected in delimited file {source_key!r}")

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedFormatError(
            f"Invalid UTF-8 encoding in delimited file {source_key!r}"
        ) from exc

    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as exc:
        raise UnsupportedFormatError(
            f"Malformed {format_name.upper()} syntax in {source_key!r}: {exc}"
        ) from exc

    sections = _format_tabular_sections(
        rows,
        source_key=source_key,
        section_prefix=source_key,
    )
    return ParsedDocument(source=source_key, format_name=format_name, sections=sections)


@PARSERS.register("csv")
class CsvParser:
    """Built-in core parser for UTF-8 Comma-Separated Values files (``.csv``)."""

    name: str = "csv"
    extensions: tuple[str, ...] = (".csv",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Parse comma-delimited UTF-8 records into header-paired 25-row sections."""
        return _parse_delimited(
            path,
            source_key=source_key,
            delimiter=",",
            format_name=self.name,
        )


@PARSERS.register("tsv")
class TsvParser:
    """Built-in core parser for UTF-8 Tab-Separated Values files (``.tsv``)."""

    name: str = "tsv"
    extensions: tuple[str, ...] = (".tsv",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Parse tab-delimited UTF-8 records into header-paired 25-row sections."""
        return _parse_delimited(
            path,
            source_key=source_key,
            delimiter="\t",
            format_name=self.name,
        )
