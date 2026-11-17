"""Shared format detection, ZIP-bomb guards, tabular grouping, and section splitting."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from docpipe_maestro.types import ParsedSection, UnsupportedFormatError

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_TEXT_HEADING_RE = re.compile(
    r"^(?:(?:Section|Article|Chapter|Part)\s+[0-9IVXLC]+(?:\.[0-9]+)*\b.*|"
    r"[0-9]+\.\s+[A-Z][A-Za-z0-9 ,:&'\"/()-]{2,80})$"
)

SUPPORTED_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
    ".csv",
    ".tsv",
    ".xlsx",
    ".pptx",
    ".epub",
    ".rst",
}
_MAX_ZIP_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_DEFAULT_TABULAR_ROWS_PER_SECTION = 25
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EXTENSION_FORMAT_MAP: dict[str, str] = {
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".docx": "docx",
    ".csv": "csv",
    ".tsv": "tsv",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".epub": "epub",
    ".rst": "rst",
}
_LEGACY_BINARY_EXTENSIONS = frozenset({".xls", ".ppt", ".doc"})
_ZIP_CONTAINER_MARKERS: tuple[tuple[str, str], ...] = (
    ("word/document.xml", "docx"),
    ("xl/workbook.xml", "xlsx"),
    ("ppt/presentation.xml", "pptx"),
    ("META-INF/container.xml", "epub"),
)


def _inspect_zip_container(
    path: Path,
    *,
    source_key: str,
    max_bytes: int = _MAX_ZIP_UNCOMPRESSED_BYTES,
) -> set[str] | None:
    """Enforce uncompressed size ceiling once and return archive member names.

    Returns ``None`` when ``path`` is not a valid ZIP archive, and raises
    ``UnsupportedFormatError`` immediately when uncompressed entries exceed
    ``max_bytes``.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > max_bytes:
                raise UnsupportedFormatError(
                    f"Archive exceeds uncompressed size limit ({total_uncompressed} bytes): "
                    f"{source_key}"
                )
            return {info.filename for info in infos}
    except (zipfile.BadZipFile, OSError):
        return None


def _validate_zip_container(
    path: Path,
    *,
    source_key: str,
    required_entry: str,
    max_bytes: int = _MAX_ZIP_UNCOMPRESSED_BYTES,
) -> bool:
    """Inspect a ZIP archive for ``required_entry`` while blocking zip bombs."""
    names = _inspect_zip_container(path, source_key=source_key, max_bytes=max_bytes)
    return names is not None and required_entry in names


def _stringify_cell(val: Any) -> str:
    """Normalize a tabular cell value into clean single-line text."""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return str(val.isoformat())
    return " ".join(str(val).split())


def _trim_trailing_empty(cells: list[str]) -> list[str]:
    """Drop trailing blank cells so padded spreadsheet columns do not inflate rows."""
    while cells and not cells[-1]:
        cells.pop()
    return cells


def _format_tabular_sections(
    rows: Iterable[Sequence[Any]],
    *,
    source_key: str,
    section_prefix: str,
    rows_per_section: int = _DEFAULT_TABULAR_ROWS_PER_SECTION,
) -> list[ParsedSection]:
    """Convert raw table rows into fixed-window ``Header: Value`` sections.

    Uses the first non-empty row (with trailing blanks trimmed) as column headers
    and pairs each subsequent non-empty data row against those headers. Blank
    files and header-only tables return ``[]`` to match empty plain-text behavior.
    """
    if rows_per_section < 1:
        raise ValueError(f"rows_per_section must be >= 1, got {rows_per_section}")

    headers: list[str] | None = None
    formatted_rows: list[str] = []

    for raw_row in rows:
        cells = _trim_trailing_empty([_stringify_cell(cell) for cell in raw_row])
        if not cells:
            continue
        if headers is None:
            headers = [cell if cell else f"Column {idx + 1}" for idx, cell in enumerate(cells)]
            continue

        pairs: list[str] = []
        for idx, val in enumerate(cells):
            if not val:
                continue
            col_name = headers[idx] if idx < len(headers) else f"Column {idx + 1}"
            pairs.append(f"{col_name}: {val}")
        if pairs:
            formatted_rows.append(" | ".join(pairs))

    if not formatted_rows:
        return []

    sections: list[ParsedSection] = []
    for offset in range(0, len(formatted_rows), rows_per_section):
        batch = formatted_rows[offset : offset + rows_per_section]
        start = offset + 1
        end = offset + len(batch)
        sections.append(
            ParsedSection(
                source=source_key,
                section_label=f"{section_prefix} (Rows {start}-{end})",
                heading_level=1,
                raw_text="\n".join(batch),
                page=None,
            )
        )
    return sections


def detect_format(path: Path) -> str:
    """Detect document format by extension, falling back to content/magic bytes.

    Extension mapping covers built-in core formats (``.md``/``.markdown``,
    ``.txt``, ``.csv``, ``.tsv``) and optional formats (``.html``/``.htm``,
    ``.pdf``, ``.docx``, ``.xlsx``, ``.pptx``, ``.epub``, ``.rst``).
    Extensionless files inspect the leading 4 KiB for ``%PDF-``, legacy OLE2
    binaries, single-pass ZIP archive payloads, HTML tags, Markdown headings,
    or valid UTF-8 plain text.

    Raises:
        UnsupportedFormatError: If ``path`` is unreadable, uses an unknown or
            legacy binary extension, exceeds ZIP size limits, or contains
            unrecognized binary bytes.
    """
    if not path.is_file():
        raise UnsupportedFormatError(f"Path is not a readable file: {path}")

    ext = path.suffix.lower()
    if ext in _EXTENSION_FORMAT_MAP:
        return _EXTENSION_FORMAT_MAP[ext]
    if ext in _LEGACY_BINARY_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported legacy binary format {ext!r} for {path.name}; "
            "convert to '.xlsx', '.pptx', '.docx', or '.csv'"
        )
    if ext:
        raise UnsupportedFormatError(f"Unsupported file extension {ext!r} for {path.name}")

    # Extensionless fallback via leading 4 KiB magic bytes
    with path.open("rb") as fh:
        head = fh.read(4096)
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(_OLE2_MAGIC):
        raise UnsupportedFormatError(
            f"Unsupported legacy binary office file: {path.name}; "
            "convert to '.xlsx', '.pptx', '.docx', or '.csv'"
        )
    if head.startswith(b"PK\x03\x04"):
        names = _inspect_zip_container(path, source_key=path.name)
        if names is not None:
            for marker, fmt in _ZIP_CONTAINER_MARKERS:
                if marker in names:
                    return fmt
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
