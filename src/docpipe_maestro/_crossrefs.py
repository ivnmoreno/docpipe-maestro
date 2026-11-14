"""Phase-neutral cross-reference matching, target indexing, and bounded excerpt utilities."""

from __future__ import annotations

import re
from collections.abc import Sequence

CROSSREF_RE = re.compile(
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

__all__ = [
    "CROSSREF_RE",
    "extract_doc_crossrefs",
    "extract_section_num",
    "index_section_targets",
    "iter_clause_blocks",
    "match_source_key",
    "parse_crossref_match",
    "truncate_excerpt",
]


def extract_section_num(label: str) -> str | None:
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


def parse_crossref_match(match: re.Match[str]) -> tuple[list[str], str, str]:
    """Extract normalized lookup keys, numeric target, and display label from a match."""
    if match.group(1) and match.group(2):
        kind = match.group(1).lower()
        num = match.group(2)
        return [f"{kind} {num}", num], num, f"{match.group(1)} {num}"
    num = match.group(4)
    return [num, f"clause {num}", f"section {num}"], num, f"§{num}"


def _strip_crossref_annotation_lines(text: str) -> list[str]:
    """Return lines with single- or multi-line ``[Crossref ...]`` blocks blanked out."""
    lines: list[str] = []
    in_crossref_block = False
    bracket_depth = 0
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not in_crossref_block:
            if stripped.startswith("[Crossref "):
                bracket_depth = stripped.count("[") - stripped.count("]")
                in_crossref_block = bracket_depth > 0
                lines.append("")
            else:
                lines.append(raw_line)
        else:
            bracket_depth += stripped.count("[") - stripped.count("]")
            if bracket_depth <= 0:
                in_crossref_block = False
            lines.append("")
    return lines


def iter_clause_blocks(raw_text: str) -> list[tuple[str, str]]:
    """Extract numbered clause numbers paired with their full wrapped paragraph text."""
    blocks: list[tuple[str, str]] = []
    cur_num: str | None = None
    cur_lines: list[str] = []

    def flush() -> None:
        if cur_num is not None and cur_lines:
            blocks.append((cur_num, " ".join(cur_lines)))
        cur_lines.clear()

    for raw_line in _strip_crossref_annotation_lines(raw_text):
        line = raw_line.strip()
        if not line:
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
        num = extract_section_num(section_label)
        if num is not None:
            full = f"{section_label}: {raw_text}"
            targets.setdefault(num, (full, sec_idx))
            targets.setdefault(f"section {num}".lower(), (full, sec_idx))
        for c_num, c_text in iter_clause_blocks(raw_text):
            targets.setdefault(c_num, (c_text, sec_idx))
            targets.setdefault(f"clause {c_num}".lower(), (c_text, sec_idx))
    return targets


def extract_doc_crossrefs(text: str) -> list[tuple[str, list[str], str]]:
    """Extract explicit document-scoped cross-references from non-annotation lines."""
    cleaned_body = "\n".join(_strip_crossref_annotation_lines(text))
    refs: list[tuple[str, list[str], str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _DOC_SCOPED_CROSSREF_RE.finditer(cleaned_body):
        lookup_keys, _num, display = parse_crossref_match(match)
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
