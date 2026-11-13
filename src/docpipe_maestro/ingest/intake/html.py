"""HTML document parser strategy registered under ``PARSERS['html']``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.types import (
    MissingExtraError,
    ParsedDocument,
    ParsedSection,
    UnsupportedFormatError,
)

_HIDDEN_STYLE_RE = re.compile(
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
    re.IGNORECASE,
)
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

    Decomposes ``<script>``, ``<style>``, ``<nav>``, ``<footer>``,
    ``<noscript>``, ``<template>``, ``<svg>``, and hidden DOM subtrees before
    iterative traversal so navigation noise and hidden prompt-injection elements
    never enter extracted sections.

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
        for tag in soup(["script", "style", "nav", "footer", "noscript", "template", "svg"]):
            tag.decompose()
        for tag in list(soup.find_all(True)):
            if getattr(tag, "attrs", None) is None:
                continue
            has_hidden_attr = tag.has_attr("hidden")
            aria_hidden = str(tag.get("aria-hidden", "")).strip().lower() == "true"
            style_val = str(tag.get("style", ""))
            if has_hidden_attr or aria_hidden or (style_val and _HIDDEN_STYLE_RE.search(style_val)):
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

        def walk_iterative(root_node: Any) -> None:
            """Iteratively traverse HTML nodes in document order without hitting RecursionError."""
            nonlocal current_label, current_level
            stack: list[Any] = [root_node]
            while stack:
                node = stack.pop()
                if isinstance(node, Comment):
                    continue
                if isinstance(node, NavigableString):
                    text = " ".join(str(node).split())
                    if text:
                        buf.append(text)
                    continue
                if not isinstance(node, Tag):
                    continue

                name = node.name.lower()
                if name in _HTML_HEADING_TAGS:
                    heading_text = node.get_text(" ", strip=True)
                    if heading_text:
                        flush()
                        current_level = int(name[1])
                        current_label = heading_text
                    continue

                if name == "table":
                    for row in node.find_all("tr"):
                        cells = [
                            c.get_text(" ", strip=True)
                            for c in row.find_all(["th", "td"], recursive=False)
                        ]
                        if not cells:
                            cells = [
                                c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])
                            ]
                        if any(cells):
                            buf.append(" | ".join(cells))
                    continue

                if name in {"p", "blockquote", "pre"}:
                    text = node.get_text(" ", strip=True)
                    if text:
                        buf.append(text)
                    continue

                if name == "li":
                    if node.find(["ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"]) is None:
                        text = node.get_text(" ", strip=True)
                        if text:
                            buf.append(text)
                        continue
                    stack.extend(reversed(list(node.children)))
                    continue

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
                    continue

                stack.extend(reversed(list(node.children)))

        root: Any = soup.body if soup.body is not None else soup
        walk_iterative(root)
        flush()
    except MissingExtraError:
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"Failed to parse HTML {source_key!r}: {exc}") from exc

    return ParsedDocument(source=source_key, format_name="html", sections=sections)


@PARSERS.register("html")
class HtmlParser:
    """Built-in parser for HTML documents (``.html``, ``.htm``)."""

    name: str = "html"
    extensions: tuple[str, ...] = (".html", ".htm")

    def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
        """Extract structured sections from HTML while filtering hidden elements."""
        return _parse_html(path, source_key)
