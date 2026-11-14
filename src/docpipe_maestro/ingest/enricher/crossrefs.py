"""Built-in Phase 1 cross-reference enricher strategy under ``ENRICHERS['crossrefs']``."""

from __future__ import annotations

import logging

from docpipe_maestro._crossrefs import (
    CROSSREF_RE,
    extract_section_num,
    index_section_targets,
    parse_crossref_match,
    truncate_excerpt,
)
from docpipe_maestro.ingest.enricher import ENRICHERS
from docpipe_maestro.types import IngestContext, ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)

__all__ = ["CrossrefsEnricher", "resolve_crossrefs"]


def resolve_crossrefs(doc: ParsedDocument) -> ParsedDocument:
    """Resolve intra-document cross-references cleanly and log unresolved targets.

    Operates in a single non-recursive pass over ``index_section_targets``
    while excluding the current section's own numbers (``self_keys``) to prevent
    self-referential and cyclic expansions. Appends deduplicated ``[Crossref ...]``
    excerpts (up to 400 characters) and emits ``WARNING`` logs for targets absent
    from the current document.
    """
    targets = index_section_targets([(sec.section_label, sec.raw_text) for sec in doc.sections])
    resolved_sections: list[ParsedSection] = []

    for sec in doc.sections:
        self_keys: set[str] = set()
        self_num = extract_section_num(sec.section_label)
        if self_num is not None:
            self_keys.add(self_num)
            self_keys.add(f"section {self_num}".lower())

        seen_refs: set[str] = set()
        appended_notes: list[str] = []

        for match in CROSSREF_RE.finditer(sec.raw_text):
            lookup_keys, num, display = parse_crossref_match(match)

            if num in self_keys or any(k in self_keys for k in lookup_keys):
                continue

            if display.lower() in seen_refs:
                continue
            seen_refs.add(display.lower())

            resolved_text: str | None = None
            for key in lookup_keys:
                target_entry = targets.get(key)
                if target_entry is not None:
                    resolved_text = target_entry[0]
                    break

            if resolved_text is not None:
                excerpt = truncate_excerpt(resolved_text, 400)
                appended_notes.append(f"[Crossref {display}: {excerpt}]")
            else:
                logger.warning(
                    "Unresolved cross-reference %r in source %r (%s)",
                    display,
                    doc.source,
                    sec.section_label,
                )

        new_text = sec.raw_text
        if appended_notes:
            new_text = f"{sec.raw_text}\n\n" + "\n".join(appended_notes)

        resolved_sections.append(
            ParsedSection(
                source=sec.source,
                section_label=sec.section_label,
                heading_level=sec.heading_level,
                raw_text=new_text,
                page=sec.page,
                clauses=list(sec.clauses),
            )
        )

    return ParsedDocument(
        source=doc.source,
        format_name=doc.format_name,
        sections=resolved_sections,
    )


@ENRICHERS.register("crossrefs")
class CrossrefsEnricher:
    """Built-in Phase 1 enricher resolving intra-document cross-references."""

    name: str = "crossrefs"

    def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
        """Annotate ``ParsedDocument`` sections with resolved intra-document excerpts."""
        _ = ctx
        return resolve_crossrefs(doc)
