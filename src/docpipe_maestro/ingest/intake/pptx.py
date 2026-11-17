"""PPTX presentation parser strategy registered under ``PARSERS['pptx']``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.intake._common import _validate_zip_container
from docpipe_maestro.types import (
    MissingExtraError,
    ParsedDocument,
    ParsedSection,
    UnsupportedFormatError,
)


def _require_pptx() -> Any:
    """Lazily import ``pptx`` or fail loudly with ``MissingExtraError``."""
    try:
        import pptx
    except ImportError as exc:
        raise MissingExtraError(
            "PPTX support requires the 'pptx' extra: pip install 'docpipe-maestro[pptx]'"
        ) from exc
    return pptx


def _collect_shape_lines(shape: Any, *, title_element: Any, out: list[str]) -> None:
    """Collect text paragraphs, tables, and grouped shapes in slide order."""
    if title_element is not None and getattr(shape, "_element", None) is title_element:
        return
    if hasattr(shape, "shapes"):
        for child in shape.shapes:
            _collect_shape_lines(child, title_element=title_element, out=out)
        return
    if getattr(shape, "has_text_frame", False):
        for para in shape.text_frame.paragraphs:
            text = " ".join(para.text.split())
            if text:
                out.append(text)
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            cells = [" ".join(cell.text.split()) for cell in row.cells]
            if any(cells):
                out.append(" | ".join(cells))


def _extract_notes_lines(slide: Any) -> list[str]:
    """Extract normalized non-empty lines from slide speaker notes if present."""
    if not getattr(slide, "has_notes_slide", False):
        return []
    notes_frame = getattr(slide.notes_slide, "notes_text_frame", None)
    if notes_frame is None:
        return []
    lines: list[str] = []
    for line in str(notes_frame.text).splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            lines.append(cleaned)
    return lines


def _parse_pptx(path: Path, source_key: str) -> ParsedDocument:
    """Extract per-slide titles, body/table text, and speaker notes from PPTX.

    Raises:
        MissingExtraError: If ``python-pptx`` (the ``pptx`` extra) is not installed.
        UnsupportedFormatError: If ZIP container validation or slide extraction fails.
    """
    pptx = _require_pptx()

    if not _validate_zip_container(
        path, source_key=source_key, required_entry="ppt/presentation.xml"
    ):
        raise UnsupportedFormatError(f"Invalid PPTX archive structure: {source_key}")

    try:
        prs = pptx.Presentation(str(path))
        sections: list[ParsedSection] = []
        for idx, slide in enumerate(prs.slides, start=1):
            title_shape = getattr(slide.shapes, "title", None)
            title_element = getattr(title_shape, "_element", None) if title_shape else None
            raw_title = (
                " ".join(str(title_shape.text).split())
                if title_shape is not None and getattr(title_shape, "text", None)
                else ""
            )

            parts: list[str] = []
            for shape in slide.shapes:
                _collect_shape_lines(shape, title_element=title_element, out=parts)

            notes_lines = _extract_notes_lines(slide)
            if notes_lines:
                parts.append("Speaker Notes:\n" + "\n".join(notes_lines))

            if not parts and not raw_title:
                continue

            sections.append(
                ParsedSection(
                    source=source_key,
                    section_label=raw_title or f"Slide {idx}",
                    heading_level=1,
                    raw_text="\n".join(parts) if parts else raw_title,
                    page=idx,
                )
            )
    except (MissingExtraError, UnsupportedFormatError):
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse PPTX {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="pptx", sections=sections)


@PARSERS.register("pptx")
class PptxParser:
    """Optional parser for Microsoft PowerPoint presentations (``.pptx``)."""

    name: str = "pptx"
    extensions: tuple[str, ...] = (".pptx",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Extract slides, tables, grouped shapes, and speaker notes from PPTX."""
        return _parse_pptx(path, source_key)
