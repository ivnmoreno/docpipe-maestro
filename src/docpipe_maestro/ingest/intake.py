"""Phase 1 document intake: format detection, magic-byte fallback, and structure extraction."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docpipe_maestro.types import MissingExtraError, UnsupportedFormatError

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_TEXT_HEADING_RE = re.compile(
    r"^(?:(?:Section|Article|Chapter|Part)\s+[0-9IVXLC]+(?:\.[0-9]+)*\b.*|"
    r"[0-9]+\.\s+[A-Z][A-Za-z0-9 ,:&'\"/()-]{2,80})$"
)

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx"}


@dataclass(slots=True)
class ParsedClause:
    """Internal Phase 1 representation of a clause or paragraph block."""

    clause_label: str | None
    text: str
    page: int | None = None


@dataclass(slots=True)
class ParsedSection:
    """Internal Phase 1 representation of a document section."""

    source: str
    section_label: str
    heading_level: int
    raw_text: str
    page: int | None = None
    clauses: list[ParsedClause] = field(default_factory=list)


@dataclass(slots=True)
class ParsedDocument:
    """Internal Phase 1 representation of an ingested source file."""

    source: str
    format_name: str
    sections: list[ParsedSection] = field(default_factory=list)


def detect_format(path: Path) -> str:
    """Detect document format by extension, falling back to content/magic bytes.

    Extension mapping covers ``.md``/``.markdown``, ``.txt``, ``.html``/``.htm``,
    ``.pdf``, and ``.docx``. Extensionless files inspect the first 4 KiB for
    ``%PDF-``, DOCX ZIP payloads (``word/document.xml``), HTML root tags,
    Markdown headings, or valid UTF-8 plain text.

    Raises:
        UnsupportedFormatError: If ``path`` is unreadable, uses an unknown
            extension, or contains unrecognized binary bytes.
    """
    if not path.is_file():
        raise UnsupportedFormatError(f"Path is not a readable file: {path}")

    ext = path.suffix.lower()
    if ext in {".md", ".markdown"}:
        return "md"
    if ext == ".txt":
        return "txt"
    if ext in {".html", ".htm"}:
        return "html"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported file extension {ext!r} for {path.name}")

    # Extensionless fallback via magic bytes
    head = path.read_bytes()[:4096]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "word/document.xml" in zf.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
        raise UnsupportedFormatError(f"Unsupported ZIP-based file: {path.name}")

    if b"\x00" in head:
        raise UnsupportedFormatError(f"Unsupported binary file format: {path.name}")

    try:
        text_head = head.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedFormatError(f"Unrecognized binary encoding for {path.name}") from exc

    lowered = text_head.lstrip().lower()
    if lowered.startswith("<!doctype html") or lowered.startswith("<html"):
        return "html"
    if any(_MD_HEADING_RE.match(line) for line in text_head.splitlines()):
        return "md"
    return "txt"


def _sections_from_lines_stateful(
    lines: list[str],
    *,
    source: str,
    page: int | None,
    markdown_mode: bool,
    initial_label: str = "Introduction",
    initial_level: int = 1,
) -> tuple[list[ParsedSection], str, int]:
    """Parse lines into ``ParsedSection`` blocks while carrying heading state forward.

    In Markdown mode, fenced code blocks (```` ``` ```` / ``~~~``) suppress
    heading detection so shell/Python ``# comment`` lines stay inside their
    enclosing section. Empty container headings (e.g., ``## 7. Title`` directly
    followed by ``### 7.1``) are omitted unless an entire block yields zero
    sections, in which case non-empty text falls back to a single section.

    Returns:
        Tuple of ``(sections, last_active_label, last_active_level)`` so
        multi-page formats (such as PDF) can carry active headings across pages.
    """
    sections: list[ParsedSection] = []
    current_label = initial_label
    current_level = initial_level
    buf: list[str] = []
    fence_char: str | None = None
    fence_len = 0

    def flush() -> None:
        """Emit accumulated section lines if non-empty and clear buffer."""
        body = "\n".join(buf).strip()
        if body:
            sections.append(
                ParsedSection(
                    source=source,
                    section_label=current_label,
                    heading_level=current_level,
                    raw_text=body,
                    page=page,
                )
            )
        buf.clear()

    for line in lines:
        stripped = line.strip()
        if markdown_mode:
            fence_match = _FENCE_RE.match(stripped)
            if fence_match:
                marker = fence_match.group(1)
                if fence_char is None:
                    fence_char = marker[0]
                    fence_len = len(marker)
                elif marker[0] == fence_char and len(marker) >= fence_len and stripped == marker:
                    fence_char = None
                    fence_len = 0
                buf.append(line)
                continue

        if fence_char is None:
            md_match = _MD_HEADING_RE.match(stripped) if markdown_mode else None
            if md_match:
                flush()
                current_level = len(md_match.group(1))
                current_label = md_match.group(2).strip()
                continue
            if not markdown_mode and _TEXT_HEADING_RE.match(stripped):
                flush()
                current_level = 2
                current_label = stripped
                continue
        buf.append(line)

    flush()
    if not sections:
        joined = "\n".join(lines).strip()
        if joined:
            sections.append(
                ParsedSection(
                    source=source,
                    section_label=current_label,
                    heading_level=current_level,
                    raw_text=joined,
                    page=page,
                )
            )
    return sections, current_label, current_level


def _sections_from_lines(
    lines: list[str],
    *,
    source: str,
    page: int | None,
    markdown_mode: bool,
) -> list[ParsedSection]:
    """Split lines into sections using default initial heading state."""
    sections, _, _ = _sections_from_lines_stateful(
        lines,
        source=source,
        page=page,
        markdown_mode=markdown_mode,
    )
    return sections


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


def _parse_docx(path: Path, source_key: str) -> ParsedDocument:
    """Extract styled headings, paragraphs, and pipe-formatted tables from DOCX.

    Raises:
        MissingExtraError: If ``python-docx`` (the ``docx`` extra) is not installed.
        UnsupportedFormatError: If DOCX opening or XML traversal fails.
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


_HTML_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_HTML_CONTAINER_TAGS = {
    "body",
    "div",
    "section",
    "article",
    "main",
    "aside",
    "header",
    "ul",
    "ol",
    "dl",
}


def _parse_html(path: Path, source_key: str) -> ParsedDocument:
    """Extract headings, prose, lists, and tables from HTML via BeautifulSoup.

    Decomposes ``<script>``, ``<style>``, ``<nav>``, ``<footer>``, and
    ``<noscript>`` before DOM traversal so navigation/styling noise never
    pollutes sections.

    Raises:
        MissingExtraError: If ``beautifulsoup4`` (the ``html`` extra) is absent.
        UnsupportedFormatError: If reading or HTML parsing fails.
    """
    try:
        from bs4 import BeautifulSoup
        from bs4.element import Comment, NavigableString, Tag
    except ImportError as exc:
        raise MissingExtraError(
            "HTML support requires the 'html' extra: pip install docpipe-maestro[html]"
        ) from exc

    try:
        raw = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "noscript"]):
            tag.decompose()

        sections: list[ParsedSection] = []
        current_label = "Introduction"
        current_level = 1
        buf: list[str] = []

        def flush() -> None:
            """Emit buffered HTML section content and reset buffer."""
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

        def walk(node: Any) -> None:
            """Recursively traverse HTML nodes in document order without duplication."""
            nonlocal current_label, current_level
            if isinstance(node, Comment):
                return
            if isinstance(node, NavigableString):
                text = " ".join(str(node).split())
                if text:
                    buf.append(text)
                return
            if not isinstance(node, Tag):
                return

            name = node.name.lower()
            if name in _HTML_HEADING_TAGS:
                heading_text = node.get_text(" ", strip=True)
                if heading_text:
                    flush()
                    current_level = int(name[1])
                    current_label = heading_text
                return

            if name == "table":
                for row in node.find_all("tr"):
                    cells = [
                        c.get_text(" ", strip=True)
                        for c in row.find_all(["th", "td"], recursive=False)
                    ]
                    if not cells:
                        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
                    if any(cells):
                        buf.append(" | ".join(cells))
                return

            if name in {"p", "blockquote", "pre"}:
                text = node.get_text(" ", strip=True)
                if text:
                    buf.append(text)
                return

            if name == "li":
                if node.find(["ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"]) is None:
                    text = node.get_text(" ", strip=True)
                    if text:
                        buf.append(text)
                    return
                for child in node.children:
                    walk(child)
                return

            if name in _HTML_CONTAINER_TAGS and (
                node.find(
                    [
                        "h1",
                        "h2",
                        "h3",
                        "h4",
                        "h5",
                        "h6",
                        "p",
                        "li",
                        "ul",
                        "ol",
                        "table",
                        "div",
                        "section",
                        "article",
                        "blockquote",
                        "pre",
                    ]
                )
                is None
            ):
                text = node.get_text(" ", strip=True)
                if text:
                    buf.append(text)
                return

            for child in node.children:
                walk(child)

        root: Any = soup.body if soup.body is not None else soup
        walk(root)
        flush()
    except MissingExtraError:
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse HTML {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="html", sections=sections)


def parse_file(path: Path, *, source_key: str) -> ParsedDocument:
    """Parse a single supported file into a structured ``ParsedDocument``.

    Args:
        path: On-disk path to the source document.
        source_key: Canonical relative key recorded on every emitted section.

    Returns:
        Structured ``ParsedDocument`` containing extracted ``ParsedSection`` items.

    Raises:
        UnsupportedFormatError: If format detection or UTF-8/binary parsing fails.
        MissingExtraError: If a required optional parser dependency is missing.
    """
    fmt = detect_format(path)
    if fmt == "pdf":
        return _parse_pdf(path, source_key)
    if fmt == "docx":
        return _parse_docx(path, source_key)
    if fmt == "html":
        return _parse_html(path, source_key)

    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedFormatError(f"Invalid UTF-8 text in {source_key!r}") from exc

    sections = _sections_from_lines(
        raw.splitlines(),
        source=source_key,
        page=None,
        markdown_mode=(fmt == "md"),
    )
    return ParsedDocument(source=source_key, format_name=fmt, sections=sections)
