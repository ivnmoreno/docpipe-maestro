"""Phase 1 text cleaning: artifact removal, whitespace normalization, and boilerplate stripping."""

from __future__ import annotations

import re
from collections import Counter

from docpipe_maestro.ingest.intake import ParsedDocument, ParsedSection

_TAG_START_RE = re.compile(
    r"</?(?:a|abbr|article|aside|b|blockquote|body|br|caption|code|dd|del|details|div|dl|dt|"
    r"em|figcaption|figure|footer|h[1-6]|head|header|hr|html|i|img|ins|li|main|mark|meta|nav|"
    r"noscript|ol|p|pre|script|section|small|span|strong|style|sub|summary|sup|table|tbody|"
    r"td|tfoot|th|thead|title|tr|u|ul)\b",
    re.IGNORECASE,
)
_MULTI_SPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _strip_html_tags(text: str) -> str:
    """Strip recognized HTML tags and comments in linear O(n) worst-case time.

    Avoids backtracking traps on unclosed ``<!--`` or ``<tag`` sequences while
    preserving numeric inequalities (``hours > 15 ... < 20``) and placeholders
    such as ``<collection>.json`` or ``<uuid>``.
    """
    if "<" not in text:
        return text

    parts: list[str] = []
    pos = 0
    length = len(text)
    no_more_comments = False
    no_more_gt = False

    while pos < length:
        lt = text.find("<", pos)
        if lt == -1:
            parts.append(text[pos:])
            break
        parts.append(text[pos:lt])

        if not no_more_comments and text.startswith("<!--", lt):
            end = text.find("-->", lt + 4)
            if end == -1:
                no_more_comments = True
                parts.append("<!--")
                pos = lt + 4
            else:
                parts.append(" ")
                pos = end + 3
            continue

        if not no_more_gt:
            match = _TAG_START_RE.match(text, lt)
            if match is not None:
                gt = text.find(">", match.end())
                if gt == -1:
                    no_more_gt = True
                    parts.append(text[lt : match.end()])
                    pos = match.end()
                else:
                    parts.append(" ")
                    pos = gt + 1
                continue

        parts.append("<")
        pos = lt + 1

    return "".join(parts)


def clean_text(text: str) -> str:
    """Clean raw extracted text while preserving line breaks and clause numbering.

    Only recognized HTML tags and comments are removed in linear time so numeric
    inequalities (``hours > 15 ... < 20``) and angle-bracket placeholders
    (``<collection>.json``) remain intact.
    """
    cleaned = _strip_html_tags(text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in cleaned.splitlines()]
    normalized = "\n".join(lines)
    normalized = _MULTI_NL_RE.sub("\n\n", normalized)
    return normalized.strip()


def clean_document(doc: ParsedDocument) -> ParsedDocument:
    """Clean all sections in a ``ParsedDocument`` and strip multi-page boilerplate.

    Tracks the first and last non-empty normalized line per paginated page; any
    edge line appearing on three or more distinct pages is treated as recurring
    header/footer boilerplate and stripped before emitting cleaned sections.
    """
    page_edges: dict[int, set[str]] = {}
    precleaned: list[tuple[ParsedSection, str]] = []
    for sec in doc.sections:
        norm_text = clean_text(sec.raw_text)
        precleaned.append((sec, norm_text))
        if sec.page is not None and norm_text:
            lines = [ln.strip() for ln in norm_text.splitlines() if ln.strip()]
            if lines:
                bucket = page_edges.setdefault(sec.page, set())
                bucket.add(lines[0])
                if len(lines) > 1:
                    bucket.add(lines[-1])

    boilerplate: set[str] = set()
    if len(page_edges) >= 3:
        edge_counts: Counter[str] = Counter()
        for edges in page_edges.values():
            for line in edges:
                edge_counts[line] += 1
        boilerplate = {line for line, count in edge_counts.items() if count >= 3}

    cleaned_sections: list[ParsedSection] = []
    for sec, text in precleaned:
        if boilerplate and text:
            kept = [ln for ln in text.splitlines() if ln.strip() not in boilerplate]
            text = "\n".join(kept).strip()
        if not text:
            continue
        cleaned_sections.append(
            ParsedSection(
                source=sec.source,
                section_label=clean_text(sec.section_label) or "Introduction",
                heading_level=sec.heading_level,
                raw_text=text,
                page=sec.page,
                clauses=list(sec.clauses),
            )
        )

    return ParsedDocument(
        source=doc.source,
        format_name=doc.format_name,
        sections=cleaned_sections,
    )
