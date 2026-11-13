"""DOCX document parser strategy registered under ``PARSERS['docx']``."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.intake._common import _validate_docx_zip
from docpipe_maestro.types import (
    MissingExtraError,
    ParsedDocument,
    ParsedSection,
    UnsupportedFormatError,
)


def _parse_docx(path: Path, source_key: str) -> ParsedDocument:
    """Extract styled headings, paragraphs, and pipe-formatted tables from DOCX.

    Raises:
        MissingExtraError: If ``python-docx`` (the ``docx`` extra) is not installed.
        UnsupportedFormatError: If DOCX opening, zip validation, or XML traversal fails.
    """
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise MissingExtraError(
            "DOCX support requires the 'docx' extra: pip install docpipe-maestro[docx]"
        ) from exc

    try:
        if not _validate_docx_zip(path, source_key=source_key):
            raise UnsupportedFormatError(f"Invalid DOCX archive structure: {source_key}")
        doc = Document(str(path))
        sections: list[ParsedSection] = []
        current_label = "Introduction"
        current_level = 1
        buf: list[str] = []

        def flush() -> None:
            """Emit buffered DOCX body paragraphs/table rows as a section."""
            body = "\n".join(buf).strip()
            if body:
                sections.append(
                    ParsedSection(
                        source=source_key,
                        section_label=current_label,
                        heading_level=current_level,
                        raw_text=body,
                        page=None,
                    )
                )
            buf.clear()

        for child in doc.element.body:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = Paragraph(child, doc)
                text = para.text.strip()
                if not text:
                    continue
                style_name = para.style.name if para.style is not None else ""
                if style_name.startswith("Heading"):
                    flush()
                    current_label = text
                    parts = style_name.split()
                    current_level = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 2
                else:
                    buf.append(text)
            elif tag == "tbl":
                table = Table(child, doc)
                for row in table.rows:
                    cells = [" ".join(cell.text.split()) for cell in row.cells]
                    if any(cells):
                        buf.append(" | ".join(cells))
        flush()
    except MissingExtraError:
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse DOCX {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="docx", sections=sections)


@PARSERS.register("docx")
class DocxParser:
    """Built-in parser for Microsoft Word DOCX archives (``.docx``)."""

    name: str = "docx"
    extensions: tuple[str, ...] = (".docx",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Extract structured sections from a ZIP-validated DOCX file."""
        return _parse_docx(path, source_key)
