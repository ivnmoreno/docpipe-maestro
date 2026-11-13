"""PDF document parser strategy registered under ``PARSERS['pdf']``."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.intake._common import _sections_from_lines_stateful
from docpipe_maestro.types import (
    MissingExtraError,
    ParsedDocument,
    ParsedSection,
    UnsupportedFormatError,
)


def _parse_pdf(path: Path, source_key: str) -> ParsedDocument:
    """Extract per-page text and heuristic section headings from a PDF via ``pypdf``.

    Raises:
        MissingExtraError: If ``pypdf`` (the ``pdf`` extra) is not installed.
        UnsupportedFormatError: If PDF reading or page extraction fails.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise MissingExtraError(
            "PDF support requires the 'pdf' extra: pip install docpipe-maestro[pdf]"
        ) from exc

    try:
        reader = PdfReader(str(path))
        sections: list[ParsedSection] = []
        active_label = "Introduction"
        active_level = 1
        for idx, page_obj in enumerate(reader.pages):
            text = page_obj.extract_text() or ""
            page_secs, active_label, active_level = _sections_from_lines_stateful(
                text.splitlines(),
                source=source_key,
                page=idx + 1,
                markdown_mode=False,
                initial_label=active_label,
                initial_level=active_level,
            )
            sections.extend(page_secs)
    except MissingExtraError:
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse PDF {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="pdf", sections=sections)


@PARSERS.register("pdf")
class PdfParser:
    """Built-in parser for PDF documents (``.pdf``)."""

    name: str = "pdf"
    extensions: tuple[str, ...] = (".pdf",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Extract paginated sections from a PDF document."""
        return _parse_pdf(path, source_key)
