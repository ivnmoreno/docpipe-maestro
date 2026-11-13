"""Phase 1/2 document cross-reference detection and cycle-safe resolution."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from docpipe_maestro.ingest.intake import ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)

_CROSSREF_RE = re.compile(
    r"\b(?:(Section|Article|Clause)\s+([0-9]+(?:\.[0-9]+)*))|"
    r"(§\s*([0-9]+(?:\.[0-9]+)*))",
    re.IGNORECASE,
)
_DOC_SCOPED_CROSSREF_RE = re.compile(
    r"(?:\b(Section|Article|Clause)\s+([0-9]+(?:\.[0-9]+)*)|(§)\s*([0-9]+(?:\.[0-9]+)*))"
    r"\s+(?:of|in)\s+(?:the\s+)?"
    r"([A-Za-z0-9_.-]+\.(?:md|markdown|txt|pdf|docx|html)\b|"
    r"[A-Z][A-Za-z0-9._-]*"
    r"(?:\s+(?!\b(?:Section|Article|Clause)\s+[0-9])"
    r"(?:(?:of|and|&|for)\s+(?!\b(?:Section|Article|Clause)\s+[0-9]))?[A-Z][A-Za-z0-9._-]*){0,5})",
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DOC_PHRASE_STOPWORDS = frozenset({"the", "of", "and", "for", "a", "an", "in", "under"})

_SECTION_NUM_RE = re.compile(
    r"(?:\b(?:Section|Article|Clause)\s+([0-9]+(?:\.[0-9]+)*)\b"
    r"|^([0-9]+(?:\.[0-9]+)+)(?=\.?(?:\s|$|[:\-—]))"
    r"|^([0-9]+)\.(?=\s|$))",
    re.IGNORECASE,
)
_CLAUSE_START_LINE_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)+)\s+(.+)$")


def _extract_section_num(label: str) -> str | None:
    """Extract normalized section identifier from a heading label, if present.

    Prefixed forms (``Section 7``, ``Article 4``) and dotted decimal headings
    (``7.5 Public API``, ``20.2: Rules``) match directly, whereas bare integer
    headings require a trailing period (``1. Title``) to avoid false-positive
    matches on years or measurements (``2026 Roadmap``, ``3.5mm``).
    """
    match = _SECTION_NUM_RE.search(label)
    if not match:
        return None
    return next((group for group in match.groups() if group is not None), None)


def truncate_excerpt(text: str, max_chars: int = 400) -> str:
    """Truncate text cleanly at a word boundary without chopping words mid-token."""
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    cutoff = clean.rfind(" ", 0, max_chars)
    if cutoff <= 0:
        cutoff = max_chars
    return clean[:cutoff].rstrip(" ,;:") + "..."


def _parse_crossref_match(match: re.Match[str]) -> tuple[list[str], str, str]:
    """Extract normalized lookup keys, numeric target, and display label from a match."""
    if match.group(1) and match.group(2):
        kind = match.group(1).lower()
        num = match.group(2)
        return [f"{kind} {num}", num], num, f"{match.group(1)} {num}"
    num = match.group(4)
    return [num, f"clause {num}", f"section {num}"], num, f"§{num}"


def _iter_clause_blocks(raw_text: str) -> list[tuple[str, str]]:
    """Extract numbered clause numbers paired with their full wrapped paragraph text."""
    blocks: list[tuple[str, str]] = []
    cur_num: str | None = None
    cur_lines: list[str] = []

    def flush() -> None:
        if cur_num is not None and cur_lines:
            blocks.append((cur_num, " ".join(cur_lines)))
        cur_lines.clear()

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[Crossref "):
            flush()
            cur_num = None
            continue
        match = _CLAUSE_START_LINE_RE.match(line)
        if match:
            flush()
            cur_num = match.group(1)
            cur_lines.append(line)
        elif cur_num is not None:
            cur_lines.append(line)

    flush()
    return blocks


def index_section_targets(sections: Sequence[tuple[str, str]]) -> dict[str, tuple[str, int]]:
    """Index normalized section and clause numbers to ``(excerpt_text, section_idx)``."""
    targets: dict[str, tuple[str, int]] = {}
    for sec_idx, (section_label, raw_text) in enumerate(sections):
        num = _extract_section_num(section_label)
        if num is not None:
            full = f"{section_label}: {raw_text}"
            targets.setdefault(num, (full, sec_idx))
            targets.setdefault(f"section {num}".lower(), (full, sec_idx))
        for c_num, c_text in _iter_clause_blocks(raw_text):
            targets.setdefault(c_num, (c_text, sec_idx))
            targets.setdefault(f"clause {c_num}".lower(), (c_text, sec_idx))
    return targets


def _build_target_index(doc: ParsedDocument) -> dict[str, str]:
    """Index section numbers and clause numbers within a single document."""
    indexed = index_section_targets([(sec.section_label, sec.raw_text) for sec in doc.sections])
    return {key: val[0] for key, val in indexed.items()}


def extract_doc_crossrefs(text: str) -> list[tuple[str, list[str], str]]:
    """Extract explicit document-scoped cross-references from non-annotation lines."""
    body_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("[Crossref ")]
    cleaned_body = "\n".join(body_lines)
    refs: list[tuple[str, list[str], str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _DOC_SCOPED_CROSSREF_RE.finditer(cleaned_body):
        lookup_keys, _num, display = _parse_crossref_match(match)
        doc_phrase = match.group(5).strip().rstrip(".,;:")
        dedup_key = (display.lower(), doc_phrase.lower())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        refs.append((display, lookup_keys, doc_phrase))
    return refs


def match_source_key(
    doc_phrase: str,
    available_sources: Sequence[str],
    *,
    current_source: str | None = None,
) -> str | None:
    """Resolve a cited document name/filename unambiguously against collection sources."""
    phrase_lower = doc_phrase.strip().lower()
    candidates = [src for src in available_sources if src != current_source]
    if not candidates or not phrase_lower:
        return None

    for src in candidates:
        stem = src.rsplit(".", 1)[0].lower()
        if phrase_lower in {src.lower(), stem}:
            return src

    phrase_tokens = {
        tok for tok in _TOKEN_RE.findall(phrase_lower) if tok not in _DOC_PHRASE_STOPWORDS
    }
    if len(phrase_tokens) < 2:
        return None

    matched: list[str] = []
    for src in candidates:
        src_tokens = set(_TOKEN_RE.findall(src.lower()))
        if phrase_tokens.issubset(src_tokens):
            matched.append(src)
    return matched[0] if len(matched) == 1 else None


def resolve_crossrefs(doc: ParsedDocument) -> ParsedDocument:
    """Resolve intra-document cross-references cleanly and log unresolved targets.

    Operates in a single non-recursive pass over ``_build_target_index(doc)``
    while excluding the current section's own numbers (``self_keys``) to prevent
    self-referential and cyclic expansions. Appends deduplicated ``[Crossref ...]``
    excerpts (up to 400 characters) and emits ``WARNING`` logs for targets absent
    from the current document.
    """
    targets = _build_target_index(doc)
    resolved_sections: list[ParsedSection] = []

    for sec in doc.sections:
        self_keys: set[str] = set()
        self_num = _extract_section_num(sec.section_label)
        if self_num is not None:
            self_keys.add(self_num)
            self_keys.add(f"section {self_num}".lower())

        seen_refs: set[str] = set()
        appended_notes: list[str] = []

        for match in _CROSSREF_RE.finditer(sec.raw_text):
            lookup_keys, num, display = _parse_crossref_match(match)

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
