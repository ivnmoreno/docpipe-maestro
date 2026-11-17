"""XLSX spreadsheet parser strategy registered under ``PARSERS['xlsx']``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.intake._common import (
    _format_tabular_sections,
    _validate_zip_container,
)
from docpipe_maestro.types import (
    MissingExtraError,
    ParsedDocument,
    ParsedSection,
    UnsupportedFormatError,
)


def _require_openpyxl() -> Any:
    """Lazily import ``openpyxl`` or fail loudly with ``MissingExtraError``."""
    try:
        import openpyxl
    except ImportError as exc:
        raise MissingExtraError(
            "XLSX support requires the 'xlsx' extra: pip install 'docpipe-maestro[xlsx]'"
        ) from exc
    return openpyxl


def _parse_xlsx(path: Path, source_key: str) -> ParsedDocument:
    """Extract visible worksheets into header-paired 25-row tabular sections.

    Raises:
        MissingExtraError: If ``openpyxl`` (the ``xlsx`` extra) is not installed.
        UnsupportedFormatError: If ZIP container validation or workbook reading fails.
    """
    openpyxl = _require_openpyxl()

    if not _validate_zip_container(path, source_key=source_key, required_entry="xl/workbook.xml"):
        raise UnsupportedFormatError(f"Invalid XLSX archive structure: {source_key}")

    sections: list[ParsedSection] = []
    try:
        with path.open("rb") as fh:
            wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
            try:
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    if getattr(ws, "sheet_state", "visible") != "visible":
                        continue
                    sheet_sections = _format_tabular_sections(
                        ws.iter_rows(values_only=True),
                        source_key=source_key,
                        section_prefix=str(ws.title or sheet_name),
                    )
                    sections.extend(sheet_sections)
            finally:
                wb.close()
    except (MissingExtraError, UnsupportedFormatError):
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse XLSX {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="xlsx", sections=sections)


@PARSERS.register("xlsx")
class XlsxParser:
    """Optional parser for Microsoft Excel spreadsheets (``.xlsx``)."""

    name: str = "xlsx"
    extensions: tuple[str, ...] = (".xlsx",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Extract visible worksheets from a ZIP-validated XLSX workbook."""
        return _parse_xlsx(path, source_key)
