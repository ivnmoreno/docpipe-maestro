"""Shared format detection, ZIP-bomb guards, and line-based section splitting."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from docpipe_maestro.types import ParsedSection, UnsupportedFormatError

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_TEXT_HEADING_RE = re.compile(
    r"^(?:(?:Section|Article|Chapter|Part)\s+[0-9IVXLC]+(?:\.[0-9]+)*\b.*|"
    r"[0-9]+\.\s+[A-Z][A-Za-z0-9 ,:&'\"/()-]{2,80})$"
)

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx"}
_MAX_DOCX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


def _validate_docx_zip(path: Path, *, source_key: str) -> bool:
    """Inspect a ZIP archive for DOCX payload presence while blocking zip bombs."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > _MAX_DOCX_UNCOMPRESSED_BYTES:
                raise UnsupportedFormatError(
                    f"DOCX archive exceeds uncompressed size limit ({total_uncompressed} bytes): "
                    f"{source_key}"
                )
            return any(info.filename == "word/document.xml" for info in infos)
    except zipfile.BadZipFile:
        return False


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
        if _validate_docx_zip(path, source_key=path.name):
            return "docx"
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
