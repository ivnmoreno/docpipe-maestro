"""Plain-text document parser strategy registered under ``PARSERS['txt']``."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.intake._common import _sections_from_lines
from docpipe_maestro.types import ParsedDocument, UnsupportedFormatError


@PARSERS.register("txt")
class TextParser:
    """Built-in parser for UTF-8 plain-text documents (``.txt``)."""

    name: str = "txt"
    extensions: tuple[str, ...] = (".txt",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Read UTF-8 text content and split using heuristic section headings."""
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedFormatError(f"Invalid UTF-8 text in {source_key!r}") from exc
        sections = _sections_from_lines(
            raw.splitlines(),
            source=source_key,
            page=None,
            markdown_mode=False,
        )
        return ParsedDocument(source=source_key, format_name=self.name, sections=sections)
