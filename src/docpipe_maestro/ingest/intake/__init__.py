"""Phase 1 document intake registry and compatibility helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.ingest.intake._common import SUPPORTED_EXTENSIONS, detect_format
from docpipe_maestro.ingest.stages import Parser
from docpipe_maestro.types import ParsedClause, ParsedDocument, ParsedSection

if TYPE_CHECKING:
    from docpipe_maestro.ingest.intake.docx import DocxParser
    from docpipe_maestro.ingest.intake.html import HtmlParser
    from docpipe_maestro.ingest.intake.markdown import MarkdownParser
    from docpipe_maestro.ingest.intake.pdf import PdfParser
    from docpipe_maestro.ingest.intake.text import TextParser

PARSERS: Registry[Parser] = Registry("parser")
register_parser = PARSERS.register

PARSERS.register_lazy("docx", "docpipe_maestro.ingest.intake.docx", "DocxParser")
PARSERS.register_lazy("html", "docpipe_maestro.ingest.intake.html", "HtmlParser")
PARSERS.register_lazy("md", "docpipe_maestro.ingest.intake.markdown", "MarkdownParser")
PARSERS.register_lazy("pdf", "docpipe_maestro.ingest.intake.pdf", "PdfParser")
PARSERS.register_lazy("txt", "docpipe_maestro.ingest.intake.text", "TextParser")

__all__ = [
    "PARSERS",
    "SUPPORTED_EXTENSIONS",
    "DocxParser",
    "HtmlParser",
    "MarkdownParser",
    "ParsedClause",
    "ParsedDocument",
    "ParsedSection",
    "PdfParser",
    "TextParser",
    "detect_format",
    "parse_file",
    "register_parser",
]

_LAZY_PARSER_EXPORTS: dict[str, tuple[str, str]] = {
    "DocxParser": ("docpipe_maestro.ingest.intake.docx", "DocxParser"),
    "HtmlParser": ("docpipe_maestro.ingest.intake.html", "HtmlParser"),
    "MarkdownParser": ("docpipe_maestro.ingest.intake.markdown", "MarkdownParser"),
    "PdfParser": ("docpipe_maestro.ingest.intake.pdf", "PdfParser"),
    "TextParser": ("docpipe_maestro.ingest.intake.text", "TextParser"),
}


def __getattr__(name: str) -> Any:
    """Lazily expose concrete built-in parser classes on direct attribute access."""
    if name in _LAZY_PARSER_EXPORTS:
        import importlib

        mod_path, attr = _LAZY_PARSER_EXPORTS[name]
        obj = getattr(importlib.import_module(mod_path), attr)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def parse_file(path: Path, *, source_key: str) -> ParsedDocument:
    """Parse a single supported file via ``resolve_parser`` into a ``ParsedDocument``."""
    from docpipe_maestro._resolve import resolve_parser

    return resolve_parser(path).parse(path, source_key=source_key)
