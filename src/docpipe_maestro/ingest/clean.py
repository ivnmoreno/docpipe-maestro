"""Phase 1 text cleaning: artifact removal, whitespace normalization, and boilerplate stripping."""

from __future__ import annotations

import re
from collections import Counter

from docpipe_maestro.ingest.intake import ParsedClause, ParsedDocument, ParsedSection

_STANDALONE_PAGE_MARKER_RE = re.compile(
    r"^(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*/\s*\d+|-\s*\d+\s*-)$",
    re.IGNORECASE,
)
_CLAUSE_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)+(?:\s|$)")
_HEADING_PREFIX_RE = re.compile(r"^(?:section|article|chapter|part|clause)\s+\d+\b", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\b\d+\b")
_EDGE_ALPHA_WORD_RE = re.compile(r"[A-Za-z]{2,}")

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


def _edge_template(line: str) -> str | None:
    """Build a digit-normalized boilerplate template for paginated edge lines.

    Matches recurring page markers (e.g., ``Page 1 of 4``) and non-clause
    headers/footers with embedded page counters or years (e.g., copyright
    bylines ending in increasing page numbers) while preserving real numbered
    clauses and headings.
    """
    stripped = line.strip()
    if not stripped or not _DIGITS_RE.search(stripped):
        return None
    if _CLAUSE_PREFIX_RE.match(stripped) or _HEADING_PREFIX_RE.match(stripped):
        return None
    normalized = _DIGITS_RE.sub("<NUM>", stripped).lower()
    if _STANDALONE_PAGE_MARKER_RE.match(stripped):
        return normalized
    if len(_EDGE_ALPHA_WORD_RE.findall(normalized)) >= 3:
        return normalized
    return None


def _strip_lines_from_text(
    text: str,
    *,
    exact_boilerplate: set[str],
    template_boilerplate: set[str],
) -> str:
    """Remove matched boilerplate lines from cleaned text."""
    if not text or (not exact_boilerplate and not template_boilerplate):
        return text
    kept: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line in exact_boilerplate:
            continue
        tmpl = _edge_template(line)
        if tmpl is not None and tmpl in template_boilerplate:
            continue
        kept.append(raw_line)
    return "\n".join(kept).strip()


def clean_document(doc: ParsedDocument) -> ParsedDocument:
    """Clean all sections in a ``ParsedDocument`` and strip multi-page boilerplate.

    Tracks the first and last non-empty normalized line per paginated page; any
    exact edge line appearing on three or more distinct pages, recurring
    standalone page marker on two or more pages, or digit-normalized footer/header
    template on three or more pages is stripped before emitting cleaned sections.
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
                for candidate in (*lines[:2], *lines[-2:]):
                    if _STANDALONE_PAGE_MARKER_RE.match(candidate):
                        bucket.add(candidate)

    exact_boilerplate: set[str] = set()
    template_boilerplate: set[str] = set()
    if len(page_edges) >= 2:
        edge_counts: Counter[str] = Counter()
        template_counts: Counter[str] = Counter()
        for edges in page_edges.values():
            seen_templates: set[str] = set()
            for line in edges:
                edge_counts[line] += 1
                tmpl = _edge_template(line)
                if tmpl is not None:
                    seen_templates.add(tmpl)
            for tmpl in seen_templates:
                template_counts[tmpl] += 1

        if len(page_edges) >= 3:
            exact_boilerplate = {line for line, count in edge_counts.items() if count >= 3}
        for tmpl, count in template_counts.items():
            # Standalone page-number lines ("Page 1 of 2") strip at >= 2 distinct pages;
            # richer text templates require >= 3 distinct pages to avoid accidental loss.
            min_pages = 2 if _STANDALONE_PAGE_MARKER_RE.match(tmpl.replace("<num>", "1")) else 3
            if count >= min_pages:
                template_boilerplate.add(tmpl)

    cleaned_sections: list[ParsedSection] = []
    for sec, raw_section_text in precleaned:
        text = _strip_lines_from_text(
            raw_section_text,
            exact_boilerplate=exact_boilerplate,
            template_boilerplate=template_boilerplate,
        )
        if not text:
            continue
        cleaned_clauses: list[ParsedClause] = []
        for clause in sec.clauses:
            clause_text = _strip_lines_from_text(
                clean_text(clause.text),
                exact_boilerplate=exact_boilerplate,
                template_boilerplate=template_boilerplate,
            )
            if clause_text:
                cleaned_clauses.append(
                    ParsedClause(
                        clause_label=clause.clause_label,
                        text=clause_text,
                        page=clause.page,
                    )
                )
        cleaned_sections.append(
            ParsedSection(
                source=sec.source,
                section_label=clean_text(sec.section_label) or "Introduction",
                heading_level=sec.heading_level,
                raw_text=text,
                page=sec.page,
                clauses=cleaned_clauses,
            )
        )

    return ParsedDocument(
        source=doc.source,
        format_name=doc.format_name,
        sections=cleaned_sections,
    )
