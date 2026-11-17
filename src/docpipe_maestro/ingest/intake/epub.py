"""EPUB digital book parser strategy registered under ``PARSERS['epub']``."""

from __future__ import annotations

import re
from html.parser import HTMLParser
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

_SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "noscript", "template", "svg", "head"})
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK_TAGS = frozenset({"p", "div", "section", "article", "li", "blockquote", "pre", "dt", "dd"})
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_HIDDEN_STYLE_RE = re.compile(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", re.IGNORECASE)


def _require_epub() -> tuple[Any, Any]:
    """Lazily import ``ebooklib`` & ``ebooklib.epub`` or raise ``MissingExtraError``."""
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as exc:
        raise MissingExtraError(
            "EPUB support requires the 'epub' extra: pip install 'docpipe-maestro[epub]'"
        ) from exc
    return ebooklib, epub


def _attrs_are_hidden(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
    """Return True if tag or attributes mark non-visible/excluded HTML subtrees."""
    if tag in _SKIP_TAGS:
        return True
    for key, val in attrs:
        k = key.lower()
        if k == "hidden":
            return True
        if k == "aria-hidden" and (val or "").strip().lower() == "true":
            return True
        if k == "style" and val and _HIDDEN_STYLE_RE.search(val):
            return True
    return False


class _EpubHtmlSectionExtractor(HTMLParser):
    """Offline stdlib HTML extractor filtering hidden/noise subtrees into sections."""

    def __init__(self, *, source: str, default_label: str) -> None:
        super().__init__(convert_charrefs=True)
        self._source = source
        self._current_label = default_label
        self._current_level = 1
        self._tag_stack: list[tuple[str, bool]] = []
        self._hidden_depth = 0
        self._heading_tag: str | None = None
        self._heading_buf: list[str] = []
        self._text_buf: list[str] = []
        self._inline_buf: list[str] = []
        self._in_table_row = False
        self._in_cell = False
        self._cell_buf: list[str] = []
        self._row_cells: list[str] = []
        self.sections: list[ParsedSection] = []

    def _flush_inline(self) -> None:
        text = " ".join("".join(self._inline_buf).split())
        if text:
            self._text_buf.append(text)
        self._inline_buf.clear()

    def _flush_section(self) -> None:
        self._flush_inline()
        body = "\n".join(self._text_buf).strip()
        if body:
            self.sections.append(
                ParsedSection(
                    source=self._source,
                    section_label=self._current_label,
                    heading_level=self._current_level,
                    raw_text=body,
                    page=None,
                )
            )
        self._text_buf.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        is_hidden = _attrs_are_hidden(low, attrs)
        if low in _VOID_TAGS:
            if low == "br" and self._hidden_depth == 0:
                self._inline_buf.append("\n")
            return
        self._tag_stack.append((low, is_hidden))
        if is_hidden:
            self._hidden_depth += 1
            return
        if self._hidden_depth > 0:
            return

        if low in _HEADING_TAGS:
            self._flush_inline()
            self._heading_tag = low
            self._heading_buf.clear()
        elif low == "tr":
            self._flush_inline()
            self._in_table_row = True
            self._row_cells.clear()
        elif low in {"td", "th"} and self._in_table_row:
            self._in_cell = True
            self._cell_buf.clear()
        elif low in _BLOCK_TAGS:
            self._flush_inline()

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in _VOID_TAGS:
            return

        # Pop back to nearest matching open tag to stay resilient to malformed XHTML
        for idx in range(len(self._tag_stack) - 1, -1, -1):
            open_tag, was_hidden = self._tag_stack[idx]
            if open_tag == low:
                popped = self._tag_stack[idx:]
                del self._tag_stack[idx:]
                self._hidden_depth -= sum(1 for _, h in popped if h)
                break
        else:
            return

        if self._hidden_depth > 0 or was_hidden:
            return

        if self._heading_tag == low:
            heading = " ".join("".join(self._heading_buf).split())
            self._heading_tag = None
            self._heading_buf.clear()
            if heading:
                self._flush_section()
                self._current_label = heading
                self._current_level = _HEADING_TAGS[low]
        elif low in {"td", "th"} and self._in_cell:
            self._row_cells.append(" ".join("".join(self._cell_buf).split()))
            self._in_cell = False
            self._cell_buf.clear()
        elif low == "tr" and self._in_table_row:
            if any(self._row_cells):
                self._text_buf.append(" | ".join(self._row_cells))
            self._in_table_row = False
            self._row_cells.clear()
        elif low in _BLOCK_TAGS:
            self._flush_inline()

    def handle_data(self, data: str) -> None:
        if self._hidden_depth > 0:
            return
        if self._heading_tag is not None:
            self._heading_buf.append(data)
        elif self._in_cell:
            self._cell_buf.append(data)
        else:
            self._inline_buf.append(data)

    def finalize(self) -> list[ParsedSection]:
        """Flush remaining inline text and return extracted sections."""
        self._flush_section()
        return self.sections


def _parse_epub(path: Path, source_key: str) -> ParsedDocument:
    """Extract ordered spine chapters from an EPUB without BeautifulSoup.

    Raises:
        MissingExtraError: If ``ebooklib`` (the ``epub`` extra) is not installed.
        UnsupportedFormatError: If ZIP container check or EPUB reading fails.
    """
    ebooklib, epub = _require_epub()

    if not _validate_zip_container(
        path, source_key=source_key, required_entry="META-INF/container.xml"
    ):
        raise UnsupportedFormatError(f"Invalid EPUB archive structure: {source_key}")

    try:
        book = epub.read_epub(str(path), {"ignore_ncx": True})
        sections: list[ParsedSection] = []
        chapter_num = 0
        for item_id, _linear in book.spine:
            item = book.get_item_with_id(item_id)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            if isinstance(item, epub.EpubNav):
                continue
            raw_content = item.get_content()
            if not raw_content:
                continue
            try:
                html_text = raw_content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise UnsupportedFormatError(
                    f"Invalid UTF-8 chapter content in EPUB {source_key!r}"
                ) from exc
            chapter_num += 1
            fallback_label = (
                " ".join(str(item.title).split())
                if getattr(item, "title", None)
                else f"Chapter {chapter_num}"
            )
            extractor = _EpubHtmlSectionExtractor(
                source=source_key,
                default_label=fallback_label or f"Chapter {chapter_num}",
            )
            extractor.feed(html_text)
            extractor.close()
            sections.extend(extractor.finalize())
    except (MissingExtraError, UnsupportedFormatError):
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse EPUB {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="epub", sections=sections)


@PARSERS.register("epub")
class EpubParser:
    """Optional parser for EPUB digital books (``.epub``)."""

    name: str = "epub"
    extensions: tuple[str, ...] = (".epub",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Extract spine chapters safely from a ZIP-validated EPUB archive."""
        return _parse_epub(path, source_key)
