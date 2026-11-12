"""Phase 1 intra-document cross-reference detection and cycle-safe resolution."""

from __future__ import annotations

import logging
import re

from docpipe_maestro.ingest.intake import ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)

_CROSSREF_RE = re.compile(
    r"\b(?:(Section|Article|Clause)\s+([0-9]+(?:\.[0-9]+)*))|"
    r"(§\s*([0-9]+(?:\.[0-9]+)*))",
    re.IGNORECASE,
)

_SECTION_NUM_RE = re.compile(
    r"(?:\b(?:Section|Article|Clause)\s+([0-9]+(?:\.[0-9]+)*)\b|^([0-9]+)\.\s+)",
    re.IGNORECASE,
)
_CLAUSE_LINE_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)+)\s+(.+)$", re.MULTILINE)


def _truncate_excerpt(text: str, max_chars: int = 400) -> str:
    """Truncate text cleanly at a word boundary without chopping words mid-token."""
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    cutoff = clean.rfind(" ", 0, max_chars)
    if cutoff <= 0:
        cutoff = max_chars
    return clean[:cutoff].rstrip(" ,;:") + "..."


def _build_target_index(doc: ParsedDocument) -> dict[str, str]:
    """Index section numbers and clause numbers within a single document."""
    targets: dict[str, str] = {}
    for sec in doc.sections:
        sec_match = _SECTION_NUM_RE.search(sec.section_label)
        if sec_match:
            num = sec_match.group(1) or sec_match.group(2)
            assert num is not None
            targets.setdefault(num, f"{sec.section_label}: {sec.raw_text}")
            targets.setdefault(f"section {num}".lower(), f"{sec.section_label}: {sec.raw_text}")
        for c_match in _CLAUSE_LINE_RE.finditer(sec.raw_text):
            c_num = c_match.group(1)
            c_text = c_match.group(0).strip()
            targets.setdefault(c_num, c_text)
            targets.setdefault(f"clause {c_num}".lower(), c_text)
    return targets


def resolve_crossrefs(doc: ParsedDocument) -> ParsedDocument:
    """Resolve intra-document cross-references and log any unresolved targets."""
    targets = _build_target_index(doc)
    resolved_sections: list[ParsedSection] = []

    for sec in doc.sections:
        self_keys: set[str] = set()
        sec_match = _SECTION_NUM_RE.search(sec.section_label)
        if sec_match:
            self_num = sec_match.group(1) or sec_match.group(2)
            assert self_num is not None
            self_keys.add(self_num)
            self_keys.add(f"section {self_num}".lower())

        seen_refs: set[str] = set()
        appended_notes: list[str] = []

        for match in _CROSSREF_RE.finditer(sec.raw_text):
            if match.group(1) and match.group(2):
                kind = match.group(1).lower()
                num = match.group(2)
                lookup_keys = [f"{kind} {num}", num]
                display = f"{match.group(1)} {num}"
            else:
                num = match.group(4)
                lookup_keys = [num, f"clause {num}", f"section {num}"]
                display = f"§{num}"

            if num in self_keys or any(k in self_keys for k in lookup_keys):
                continue

            if display.lower() in seen_refs:
                continue
            seen_refs.add(display.lower())

            resolved_text: str | None = None
            for key in lookup_keys:
                if key in targets:
                    resolved_text = targets[key]
                    break

            if resolved_text is not None:
                excerpt = _truncate_excerpt(resolved_text, 400)
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
