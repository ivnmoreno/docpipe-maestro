"""Phase 1 text cleaning: artifact removal, whitespace normalization, and boilerplate stripping."""

from __future__ import annotations

import re
from collections import Counter

from docpipe_maestro.ingest.intake import ParsedDocument, ParsedSection

_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Clean raw extracted text while preserving line breaks and clause numbering."""
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in cleaned.splitlines()]
    normalized = "\n".join(lines)
    normalized = _MULTI_NL_RE.sub("\n\n", normalized)
    return normalized.strip()


def clean_document(doc: ParsedDocument) -> ParsedDocument:
    """Clean all sections in a ParsedDocument and strip repeated multi-page boilerplate."""
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
