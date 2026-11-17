"""reStructuredText parser strategy registered under ``PARSERS['rst']``."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.types import (
    MissingExtraError,
    ParsedDocument,
    ParsedSection,
    UnsupportedFormatError,
)


def _require_docutils() -> tuple[Any, Any]:
    """Lazily import ``docutils.core`` and ``docutils.nodes`` or fail loudly."""
    try:
        from docutils import core, nodes
    except ImportError as exc:
        raise MissingExtraError(
            "RST support requires the 'rst' extra: pip install 'docpipe-maestro[rst]'"
        ) from exc
    return core, nodes


def _format_table_lines(table_node: Any, nodes: Any) -> list[str]:
    """Extract RST doctree table rows formatted with pipe delimiters."""
    out: list[str] = []
    for row in table_node.findall(nodes.row):
        cells: list[str] = []
        for entry in row.findall(nodes.entry):
            cells.append(" ".join(entry.astext().split()))
        if any(cells):
            out.append(" | ".join(cells))
    return out


def _collect_block_lines(child: Any, nodes: Any, out: list[str]) -> None:
    """Convert non-section RST doctree nodes into clean text lines."""
    if isinstance(child, (nodes.title, nodes.comment, nodes.system_message, nodes.raw)):
        return
    if isinstance(child, nodes.table):
        out.extend(_format_table_lines(child, nodes))
        return
    if isinstance(child, (nodes.bullet_list, nodes.enumerated_list)):
        for item in child.children:
            item_txt = " ".join(item.astext().split())
            if item_txt:
                out.append(f"- {item_txt}")
        return
    if isinstance(child, nodes.Admonition):
        admon_lines = [
            " ".join(p.astext().split())
            for p in child.children
            if not isinstance(p, (nodes.system_message, nodes.comment, nodes.raw))
        ]
        cleaned = " ".join(line for line in admon_lines if line)
        if cleaned:
            out.append(cleaned)
        return
    text = "\n".join(line.strip() for line in child.astext().splitlines() if line.strip())
    if text:
        out.append(text)


def _walk_rst_container(
    container: Any,
    *,
    nodes: Any,
    source_key: str,
    section_label: str,
    heading_level: int,
    sections: list[ParsedSection],
    child_section_base_level: int,
) -> None:
    """Recursively extract hierarchical sections and body blocks from a doctree node."""
    buf: list[str] = []
    for child in container.children:
        if isinstance(child, nodes.section):
            body = "\n".join(buf).strip()
            if body:
                sections.append(
                    ParsedSection(
                        source=source_key,
                        section_label=section_label,
                        heading_level=heading_level,
                        raw_text=body,
                        page=None,
                    )
                )
            buf.clear()

            title_node = next((c for c in child.children if isinstance(c, nodes.title)), None)
            child_label = (
                " ".join(title_node.astext().split()) if title_node is not None else section_label
            )
            clamped_level = min(6, child_section_base_level)
            _walk_rst_container(
                child,
                nodes=nodes,
                source_key=source_key,
                section_label=child_label or section_label,
                heading_level=clamped_level,
                sections=sections,
                child_section_base_level=clamped_level + 1,
            )
        else:
            _collect_block_lines(child, nodes, buf)

    body = "\n".join(buf).strip()
    if body:
        sections.append(
            ParsedSection(
                source=source_key,
                section_label=section_label,
                heading_level=heading_level,
                raw_text=body,
                page=None,
            )
        )


def _parse_rst(path: Path, source_key: str) -> ParsedDocument:
    """Parse strict UTF-8 reStructuredText with external file/raw directives disabled.

    Raises:
        MissingExtraError: If ``docutils`` (the ``rst`` extra) is not installed.
        UnsupportedFormatError: If file reading fails or bytes contain invalid UTF-8/NUL.
    """
    core, nodes = _require_docutils()

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise UnsupportedFormatError(f"Failed to read RST {source_key!r}: {exc}") from exc

    if b"\x00" in raw_bytes:
        raise UnsupportedFormatError(f"Binary NUL byte detected in RST file {source_key!r}")

    try:
        raw = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedFormatError(f"Invalid UTF-8 encoding in RST file {source_key!r}") from exc

    if not raw.strip():
        return ParsedDocument(source=source_key, format_name="rst", sections=[])

    try:
        doctree = core.publish_doctree(
            raw,
            settings_overrides={
                "file_insertion_enabled": False,
                "raw_enabled": False,
                "report_level": 5,
                "halt_level": 5,
                "warning_stream": io.StringIO(),
            },
        )
        doc_title_node = next((c for c in doctree.children if isinstance(c, nodes.title)), None)
        if doc_title_node is not None:
            top_label = " ".join(doc_title_node.astext().split()) or "Introduction"
            child_base_level = 2
        else:
            top_label = "Introduction"
            child_base_level = 1

        sections: list[ParsedSection] = []
        _walk_rst_container(
            doctree,
            nodes=nodes,
            source_key=source_key,
            section_label=top_label,
            heading_level=1,
            sections=sections,
            child_section_base_level=child_base_level,
        )
    except (MissingExtraError, UnsupportedFormatError):
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse RST {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="rst", sections=sections)


@PARSERS.register("rst")
class RstParser:
    """Optional parser for reStructuredText documents (``.rst``)."""

    name: str = "rst"
    extensions: tuple[str, ...] = (".rst",)

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Extract heading hierarchy and clean blocks safely offline from RST."""
        return _parse_rst(path, source_key)
