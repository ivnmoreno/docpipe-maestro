"""Self-contained static HTML Document Integrity & Chunk Audit Report exporter."""

from __future__ import annotations

import contextlib
import html
import json
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docpipe_maestro import __version__
from docpipe_maestro._crossrefs import (
    CROSSREF_RE,
    _strip_crossref_annotation_lines,
    extract_section_num,
    parse_crossref_match,
)
from docpipe_maestro.config import DEFAULT_COLLECTION, DEFAULT_PERSIST_DIR
from docpipe_maestro.ingest.chunker.default import estimate_tokens
from docpipe_maestro.log import get_logger, stage_event
from docpipe_maestro.manifest import load_manifest, validate_collection_name
from docpipe_maestro.store import STORES
from docpipe_maestro.types import Chunk, DocpipeError, SourceRecord

logger = get_logger(__name__)

_EXCEPTION_MARKER_RE = re.compile(
    r"\b(except|unless|not entitled|subject to|provided that|until)\b",
    re.IGNORECASE,
)
_PROVENANCE_HEADER_RE = re.compile(r"^\[Source: [^\]]+\]\r?\n")
_TERMINAL_PUNCT_RE = re.compile(r"""[.!?:;"')\]…]$""")
_LEADING_LOWER_RE = re.compile(r"^[a-z]")
_NAMED_UNIT_PREFIX_RE = re.compile(r"^(?:clause|section|article|§)\b", re.IGNORECASE)
_CLAUSE_LABEL_DETECT_RE = re.compile(
    r"^(?:(?:Clause|Article|Section)\s+[0-9]+(?:\.[0-9]+)*|"
    r"§\s*[0-9]+(?:\.[0-9]+)*|[0-9]+(?:\.[0-9]+)+)\b",
    re.IGNORECASE | re.MULTILINE,
)

COMPLIANCE_TAGS: tuple[str, ...] = (
    "EU AI Act Art. 10 Data Governance",
    "GDPR Art. 5 Integrity",
)

__all__ = [
    "COMPLIANCE_TAGS",
    "build_audit_report",
    "export_html_report",
    "render_html_report",
]


def _strip_provenance_header(text: str) -> str:
    """Remove the prepended ``[Source: ... | Section: ...]`` line from a child chunk."""
    return _PROVENANCE_HEADER_RE.sub("", text, count=1)


def _extract_crossref_annotations(text: str) -> list[dict[str, str]]:
    """Extract resolved ``[Crossref <display>: <excerpt>]`` annotations cleanly."""
    annotations: list[dict[str, str]] = []
    in_block = False
    depth = 0
    buf: list[str] = []

    def _flush() -> None:
        raw = "\n".join(buf).strip()
        buf.clear()
        if not raw.startswith("[Crossref ") or not raw.endswith("]"):
            return
        inner = raw[len("[Crossref ") : -1]
        if ":" not in inner:
            return
        target, excerpt = inner.split(":", 1)
        annotations.append({"target": target.strip(), "excerpt": excerpt.strip()})

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not in_block:
            if stripped.startswith("[Crossref "):
                buf.append(stripped)
                depth = stripped.count("[") - stripped.count("]")
                if depth <= 0:
                    _flush()
                else:
                    in_block = True
        else:
            buf.append(stripped)
            depth += stripped.count("[") - stripped.count("]")
            if depth <= 0:
                in_block = False
                _flush()

    if buf:
        _flush()

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in annotations:
        key = (item["target"].lower(), item["excerpt"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _body_without_annotations(text: str) -> str:
    """Return chunk text stripped of provenance headers and appended crossref blocks."""
    stripped_header = _strip_provenance_header(text)
    lines = _strip_crossref_annotation_lines(stripped_header)
    return "\n".join(lines).strip()


def _extract_body_citations(
    body_text: str,
    *,
    section_label: str,
    clause_label: str | None,
) -> list[str]:
    """Find non-self section/clause citations referenced in plain chunk body lines."""
    self_keys: set[str] = set()
    sec_num = extract_section_num(section_label)
    if sec_num is not None:
        self_keys.add(sec_num.lower())
        self_keys.add(f"section {sec_num}".lower())
    if clause_label:
        self_keys.add(clause_label.strip().lower())
        clause_num = extract_section_num(clause_label)
        if clause_num is not None:
            self_keys.add(clause_num.lower())

    citations: list[str] = []
    seen: set[str] = set()
    for match in CROSSREF_RE.finditer(body_text):
        lookup_keys, num, display = parse_crossref_match(match)
        if num.lower() in self_keys or any(k.lower() in self_keys for k in lookup_keys):
            continue
        disp_key = display.lower()
        if disp_key not in seen:
            seen.add(disp_key)
            citations.append(display)
    return citations


def _extract_exception_mentions(body_text: str) -> list[dict[str, str]]:
    """Extract rule-exception marker occurrences paired with their enclosing clause snippet."""
    mentions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for paragraph in body_text.splitlines():
        line = paragraph.strip()
        if not line:
            continue
        for match in _EXCEPTION_MARKER_RE.finditer(line):
            marker = match.group(1).lower()
            snippet = line if len(line) <= 280 else line[:277].rstrip() + "..."
            key = (marker, snippet)
            if key not in seen:
                seen.add(key)
                mentions.append({"marker": marker, "snippet": snippet})
    return mentions


def _build_breadcrumb(
    *,
    source: str,
    section: str,
    clause: str | None,
    page: int | None,
) -> str:
    """Format a deterministic hierarchy breadcrumb from existing ``ChunkMetadata``."""
    parts = [source]
    if page is not None:
        parts.append(f"Page {page}")
    if section:
        parts.append(section)
    if clause:
        clause_part = clause if _NAMED_UNIT_PREFIX_RE.match(clause) else f"Clause {clause}"
        parts.append(clause_part)
    return " > ".join(parts)


def _format_rate(numerator: int, denominator: int) -> float | None:
    """Compute a single-decimal percentage or ``None`` when denominator is zero."""
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 1)


def _analyze_section_crossrefs(
    section_chunks: Sequence[Chunk],
    parent_chunk: Chunk | None,
) -> tuple[int, int, dict[str, dict[str, str]]]:
    """Compute unique section citations, resolved count, and resolution lookup."""
    resolved_lookup: dict[str, dict[str, str]] = {}
    all_citations: list[str] = []
    seen_cites: set[str] = set()

    inspect_pool = ([parent_chunk] if parent_chunk is not None else []) + list(section_chunks)
    for item in inspect_pool:
        for ann in _extract_crossref_annotations(item.text):
            resolved_lookup.setdefault(ann["target"].lower(), ann)
        body = _body_without_annotations(item.text)
        for cite in _extract_body_citations(
            body,
            section_label=item.metadata["section"],
            clause_label=item.metadata["clause"],
        ):
            key = cite.lower()
            if key not in seen_cites:
                seen_cites.add(key)
                all_citations.append(cite)

    resolved_count = sum(1 for cite in all_citations if cite.lower() in resolved_lookup)
    # Include section-level resolved annotations even if citation wording differed slightly.
    resolved_count = max(resolved_count, len(resolved_lookup))
    total_cites = max(len(all_citations), resolved_count)
    return total_cites, resolved_count, resolved_lookup


def _build_chunk_record(
    chunk: Chunk,
    *,
    parent_chunk: Chunk | None,
    parent_body_lower: str,
    sibling_clause_counts: Mapping[str, int],
    max_chunk_idx: int,
    section_resolved_refs: Mapping[str, dict[str, str]],
) -> tuple[dict[str, Any], bool, int, int]:
    """Build one serializable chunk audit entry and its local integrity metrics."""
    meta = chunk.metadata
    clean_body = _body_without_annotations(chunk.text)
    direct_annotations = _extract_crossref_annotations(chunk.text)
    body_citations = _extract_body_citations(
        clean_body,
        section_label=meta["section"],
        clause_label=meta["clause"],
    )

    resolved_refs = list(direct_annotations)
    seen_ref_keys = {r["target"].lower() for r in resolved_refs}
    unresolved_refs: list[str] = []
    for cite in body_citations:
        ckey = cite.lower()
        if ckey in seen_ref_keys:
            continue
        sec_hit = section_resolved_refs.get(ckey)
        if sec_hit is not None:
            resolved_refs.append(sec_hit)
            seen_ref_keys.add(ckey)
        else:
            unresolved_refs.append(cite)

    chunk_exceptions = _extract_exception_mentions(clean_body)
    parent_exceptions = (
        _extract_exception_mentions(_body_without_annotations(parent_chunk.text))
        if parent_chunk is not None
        else []
    )

    bound_exceptions: list[dict[str, Any]] = []
    seen_exc: set[tuple[str, str]] = set()
    exc_total = 0
    exc_preserved = 0

    for item in chunk_exceptions:
        preserved = parent_chunk is not None and item["marker"] in parent_body_lower
        exc_total += 1
        if preserved:
            exc_preserved += 1
        key = (item["marker"], item["snippet"])
        seen_exc.add(key)
        bound_exceptions.append(
            {
                "marker": item["marker"],
                "snippet": item["snippet"],
                "scope": "chunk",
                "preserved_in_parent": preserved,
            }
        )

    # Surface rule-exception bindings carried on the parent for rule-only children.
    for item in parent_exceptions:
        key = (item["marker"], item["snippet"])
        if key in seen_exc:
            continue
        seen_exc.add(key)
        bound_exceptions.append(
            {
                "marker": item["marker"],
                "snippet": item["snippet"],
                "scope": "parent",
                "preserved_in_parent": True,
            }
        )

    warnings: list[str] = []
    is_split = False

    if chunk.parent_id is not None and parent_chunk is None:
        warnings.append("Missing linked parent section in store")
    elif chunk.parent_id is None:
        warnings.append("Unlinked child chunk (no parent_id)")

    clause_key = meta["clause"]
    if clause_key and sibling_clause_counts.get(clause_key, 0) > 1:
        is_split = True
        warnings.append(f"Clause {clause_key!r} spans multiple child chunks")

    if clean_body:
        if meta["chunk_index"] > 0 and _LEADING_LOWER_RE.match(clean_body):
            is_split = True
            warnings.append("Chunk starts mid-sentence (lowercase continuation)")
        if meta["chunk_index"] < max_chunk_idx and not _TERMINAL_PUNCT_RE.search(clean_body):
            is_split = True
            warnings.append("Chunk ends without terminal punctuation before sibling chunk")

    if unresolved_refs:
        warnings.append(f"Unresolved cross-reference(s): {', '.join(unresolved_refs)}")

    has_exception = len(bound_exceptions) > 0
    has_crossref = len(resolved_refs) > 0 or len(unresolved_refs) > 0
    has_warning = len(warnings) > 0 or is_split

    breadcrumb = _build_breadcrumb(
        source=meta["source"],
        section=meta["section"],
        clause=meta["clause"],
        page=meta["page"],
    )

    record: dict[str, Any] = {
        "id": chunk.id,
        "parent_id": chunk.parent_id,
        "source": meta["source"],
        "doc_version": meta["doc_version"],
        "section": meta["section"],
        "clause": meta["clause"],
        "page": meta["page"],
        "chunk_index": meta["chunk_index"],
        "embed_model": meta["embed_model"],
        "breadcrumb": breadcrumb,
        "text": clean_body,
        "parent_text": _body_without_annotations(parent_chunk.text)
        if parent_chunk is not None
        else None,
        "token_count": estimate_tokens(clean_body),
        "char_count": len(clean_body),
        "has_exception": has_exception,
        "has_crossref": has_crossref,
        "has_warning": has_warning,
        "is_split": is_split,
        "warnings": warnings,
        "bound_exceptions": bound_exceptions,
        "resolved_crossrefs": resolved_refs,
        "unresolved_crossrefs": unresolved_refs,
    }
    return record, is_split, exc_total, exc_preserved


def build_audit_report(
    chunks: Sequence[Chunk],
    *,
    collection: str,
    sources: Mapping[str, SourceRecord] | None = None,
    embed_model: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a structured JSON-serializable audit payload from existing ``Chunk`` outputs."""
    children = [c for c in chunks if c.metadata["type"] == "child"]
    parents = [c for c in chunks if c.metadata["type"] == "parent"]
    parents_by_id: dict[str, Chunk] = {p.id: p for p in parents}

    # Group children by enclosing parent/section scope for crossref & split diagnostics.
    children_by_group: dict[tuple[str, str, str], list[Chunk]] = defaultdict(list)
    for ch in children:
        group_key = (
            ch.parent_id or "",
            ch.metadata["source"],
            ch.metadata["section"],
        )
        children_by_group[group_key].append(ch)

    total_crossrefs_cited = 0
    total_crossrefs_resolved = 0
    group_resolved_refs: dict[tuple[str, str, str], dict[str, dict[str, str]]] = {}
    group_max_idx: dict[tuple[str, str, str], int] = {}
    group_clause_counts: dict[tuple[str, str, str], dict[str, int]] = {}

    for group_key, group_children in children_by_group.items():
        parent_obj = parents_by_id.get(group_key[0]) if group_key[0] else None
        cited, resolved, lookup = _analyze_section_crossrefs(group_children, parent_obj)
        total_crossrefs_cited += cited
        total_crossrefs_resolved += resolved
        group_resolved_refs[group_key] = lookup
        group_max_idx[group_key] = max(c.metadata["chunk_index"] for c in group_children)
        clause_counts: dict[str, int] = defaultdict(int)
        for c in group_children:
            if c.metadata["clause"]:
                clause_counts[c.metadata["clause"]] += 1
        group_clause_counts[group_key] = clause_counts

    # Include any parent sections that have zero children in crossref totals.
    seen_parent_ids = {k[0] for k in children_by_group if k[0]}
    for pid, p_chunk in parents_by_id.items():
        if pid not in seen_parent_ids:
            cited, resolved, _ = _analyze_section_crossrefs([], p_chunk)
            total_crossrefs_cited += cited
            total_crossrefs_resolved += resolved

    chunk_records: list[dict[str, Any]] = []
    split_count = 0
    exception_links_total = 0
    exception_links_preserved = 0
    distinct_clauses: set[tuple[str, str, str]] = set()

    source_records = sources or {}
    sorted_children = sorted(
        children,
        key=lambda c: (
            c.metadata["source"],
            c.metadata["page"] if c.metadata["page"] is not None else -1,
            parents_by_id[c.parent_id].metadata["chunk_index"]
            if c.parent_id and c.parent_id in parents_by_id
            else 0,
            c.metadata["chunk_index"],
            c.id,
        ),
    )

    for child in sorted_children:
        group_key = (
            child.parent_id or "",
            child.metadata["source"],
            child.metadata["section"],
        )
        parent_obj = parents_by_id.get(child.parent_id) if child.parent_id else None
        parent_body_lower = (
            _body_without_annotations(parent_obj.text).lower() if parent_obj is not None else ""
        )
        rec, is_split, exc_tot, exc_pres = _build_chunk_record(
            child,
            parent_chunk=parent_obj,
            parent_body_lower=parent_body_lower,
            sibling_clause_counts=group_clause_counts.get(group_key, {}),
            max_chunk_idx=group_max_idx.get(group_key, child.metadata["chunk_index"]),
            section_resolved_refs=group_resolved_refs.get(group_key, {}),
        )
        chunk_records.append(rec)
        if is_split:
            split_count += 1
        exception_links_total += exc_tot
        exception_links_preserved += exc_pres

        if child.metadata["clause"]:
            distinct_clauses.add(
                (child.metadata["source"], child.metadata["section"], child.metadata["clause"])
            )
        else:
            for c_match in _CLAUSE_LABEL_DETECT_RE.finditer(rec["text"]):
                distinct_clauses.add(
                    (child.metadata["source"], child.metadata["section"], c_match.group(0).lower())
                )

    source_entries: list[dict[str, Any]] = []
    if source_records:
        for key in sorted(source_records):
            srec = source_records[key]
            source_entries.append(
                {
                    "source": srec.source,
                    "content_hash": srec.content_hash,
                    "doc_version": srec.doc_version,
                    "profile": srec.profile,
                    "embed_model": srec.embed_model,
                    "ingested_at": srec.ingested_at,
                    "size": srec.size,
                    "child_count": len(srec.chunk_ids),
                    "parent_count": len(srec.parent_ids),
                }
            )
    else:
        seen_src: dict[str, dict[str, Any]] = {}
        for c in chunks:
            src_name = c.metadata["source"]
            if src_name not in seen_src:
                seen_src[src_name] = {
                    "source": src_name,
                    "content_hash": f"doc_version:{c.metadata['doc_version']}",
                    "doc_version": c.metadata["doc_version"],
                    "profile": "UNKNOWN",
                    "embed_model": c.metadata["embed_model"],
                    "ingested_at": None,
                    "size": None,
                    "child_count": 0,
                    "parent_count": 0,
                }
            if c.metadata["type"] == "child":
                seen_src[src_name]["child_count"] += 1
            elif c.metadata["type"] == "parent":
                seen_src[src_name]["parent_count"] += 1
        source_entries = [seen_src[k] for k in sorted(seen_src)]

    total_children = len(chunk_records)
    intact_children = total_children - split_count
    clause_integrity_pct = _format_rate(intact_children, total_children)
    crossref_resolution_pct = _format_rate(total_crossrefs_resolved, total_crossrefs_cited)
    exception_preservation_pct = _format_rate(
        exception_links_preserved,
        exception_links_total,
    )

    resolved_model = embed_model or (
        source_entries[0]["embed_model"] if source_entries else "unknown"
    )
    ts = generated_at or datetime.now(UTC).isoformat()

    if len(source_entries) == 1:
        doc_summary = source_entries[0]["source"]
        doc_hash = source_entries[0]["content_hash"]
    elif len(source_entries) > 1:
        doc_summary = f"{len(source_entries)} source documents"
        doc_hash = ", ".join(f"{e['source']} [{e['doc_version']}]" for e in source_entries[:4])
        if len(source_entries) > 4:
            doc_hash += f" (+{len(source_entries) - 4} more)"
    else:
        doc_summary = "No active documents"
        doc_hash = "N/A"

    return {
        "schema_version": "1.0",
        "tool": "docpipe-maestro",
        "tool_version": __version__,
        "generated_at_utc": ts,
        "collection": collection,
        "embed_model": resolved_model,
        "document_summary": doc_summary,
        "document_hash_summary": doc_hash,
        "compliance_tags": list(COMPLIANCE_TAGS),
        "governance_disclaimer": (
            "Technical structural integrity report for audit inspection; "
            "not a legal compliance or regulatory certification."
        ),
        "kpis": {
            "total_chunks": total_children,
            "total_parents": len(parents_by_id),
            "total_clauses_detected": max(len(distinct_clauses), total_children)
            if total_children
            else 0,
            "distinct_clause_labels": len(distinct_clauses),
            "intact_chunks": intact_children,
            "split_or_broken_chunks": split_count,
            "clause_integrity_rate_pct": clause_integrity_pct,
            "crossrefs_resolved": total_crossrefs_resolved,
            "crossrefs_total": total_crossrefs_cited,
            "crossref_resolution_rate_pct": crossref_resolution_pct,
            "rule_exception_links_preserved": exception_links_preserved,
            "rule_exception_links_total": exception_links_total,
            "rule_exception_preservation_rate_pct": exception_preservation_pct,
        },
        "filter_counts": {
            "ALL": total_children,
            "HAS_EXCEPTION": sum(1 for r in chunk_records if r["has_exception"]),
            "HAS_CROSS_REF": sum(1 for r in chunk_records if r["has_crossref"]),
            "WARNING / SPLIT": sum(1 for r in chunk_records if r["has_warning"]),
        },
        "sources": source_entries,
        "chunks": chunk_records,
    }


def _safe_json_for_script_tag(payload: Mapping[str, Any]) -> str:
    """Serialize JSON safely for inline ``<script type='application/json'>`` blocks."""
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


_CSS_STYLES = """
:root {
  --bg: #f4f6f9;
  --surface: #ffffff;
  --surface-alt: #f8fafc;
  --border: #d8e0ea;
  --text: #0f172a;
  --muted: #475569;
  --accent: #1d4ed8;
  --accent-soft: #eff6ff;
  --ok: #15803d;
  --ok-soft: #f0fdf4;
  --warn: #b45309;
  --warn-soft: #fffbeb;
  --purple: #6d28d9;
  --purple-soft: #f5f3ff;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px;
  font-family: var(--sans);
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
.container { max-width: 1160px; margin: 0 auto; }
.header-banner {
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  color: #f8fafc;
  border-radius: 12px;
  padding: 22px 26px;
  margin-bottom: 20px;
}
.header-top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.title-block h1 { margin: 0 0 4px 0; font-size: 1.45rem; letter-spacing: -0.01em; }
.subtitle { color: #cbd5e1; font-size: 0.9rem; }
.compliance-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.compliance-badge {
  background: rgba(59, 130, 246, 0.22);
  border: 1px solid rgba(147, 197, 253, 0.45);
  color: #e0f2fe;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px 18px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.14);
  font-size: 0.84rem;
}
.meta-label { color: #94a3b8; display: block; font-size: 0.74rem; text-transform: uppercase; }
.meta-val { font-family: var(--mono); word-break: break-word; overflow-wrap: anywhere; }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}
.kpi-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
}
.kpi-title { font-size: 0.78rem; color: var(--muted); text-transform: uppercase; font-weight: 700; }
.kpi-value { font-size: 1.75rem; font-weight: 800; margin: 6px 0 4px 0; }
.kpi-sub { font-size: 0.82rem; color: var(--muted); }
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 20px;
}
.panel h2 { margin: 0 0 12px 0; font-size: 1.05rem; }
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.pills { display: flex; flex-wrap: wrap; gap: 8px; }
.pill {
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text);
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
}
.pill.active { background: var(--accent); color: #ffffff; border-color: var(--accent); }
.search-input {
  min-width: 260px;
  flex: 1 1 280px;
  max-width: 420px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 0.9rem;
}
.source-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}
.source-table th, .source-table td {
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  word-break: break-word;
  overflow-wrap: anywhere;
}
.source-table th { color: var(--muted); font-size: 0.76rem; text-transform: uppercase; }
.chunk-card {
  border: 1px solid var(--border);
  border-radius: 9px;
  margin-bottom: 10px;
  background: var(--surface);
  overflow: hidden;
}
.chunk-card summary {
  list-style: none;
  cursor: pointer;
  padding: 12px 14px;
  background: var(--surface-alt);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.chunk-card summary::-webkit-details-marker { display: none; }
.breadcrumb { font-weight: 600; font-size: 0.9rem; word-break: break-word; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.badge {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
}
.badge-exc { background: var(--ok-soft); color: var(--ok); border-color: #bbf7d0; }
.badge-xref { background: var(--purple-soft); color: var(--purple); border-color: #ddd6fe; }
.badge-warn { background: var(--warn-soft); color: var(--warn); border-color: #fde68a; }
.badge-meta {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: #bfdbfe;
  font-family: var(--mono);
}
.chunk-body { padding: 14px 16px; border-top: 1px solid var(--border); }
.chunk-text {
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  font-family: var(--mono);
  font-size: 0.83rem;
  margin: 0 0 12px 0;
}
.detail-group { margin-top: 10px; font-size: 0.84rem; }
.detail-group h4 {
  margin: 0 0 6px 0;
  font-size: 0.8rem;
  text-transform: uppercase;
  color: var(--muted);
}
.detail-list { margin: 0; padding-left: 18px; }
.detail-list li { margin-bottom: 4px; word-break: break-word; overflow-wrap: anywhere; }
.footer-note { font-size: 0.78rem; color: var(--muted); text-align: center; margin-top: 18px; }
.empty-state { padding: 24px; text-align: center; color: var(--muted); font-size: 0.92rem; }
@media print {
  @page { size: A4 portrait; margin: 12mm; }
  body { background: #ffffff; padding: 0; font-size: 10pt; }
  .header-banner {
    background: #ffffff !important;
    color: #0f172a !important;
    border: 1.5px solid #0f172a;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .subtitle, .meta-label { color: #334155 !important; }
  .compliance-badge {
    background: #f1f5f9 !important;
    color: #0f172a !important;
    border-color: #64748b !important;
  }
  .controls { display: none !important; }
  .panel, .kpi-card, .chunk-card { break-inside: avoid; page-break-inside: avoid; }
  .chunk-card .chunk-body { display: block !important; }
  .source-table { table-layout: fixed; width: 100%; }
}
"""

_CLIENT_SCRIPT = """
(function () {
  const dataEl = document.getElementById("report-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent || "{}");

  const filterOrder = ["ALL", "HAS_EXCEPTION", "HAS_CROSS_REF", "WARNING / SPLIT"];
  let activeFilter = "ALL";
  let searchQuery = "";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatPct(val) {
    return val === null || val === undefined ? "N/A" : val.toFixed(1) + "%";
  }

  function renderKpis() {
    const grid = document.getElementById("kpi-grid");
    if (!grid) return;
    grid.replaceChildren();
    const k = data.kpis || {};
    const cards = [
      {
        title: "Total Clauses / Chunks",
        value: String(k.total_chunks || 0),
        sub: (k.total_parents || 0) + " parent section(s) · "
          + (k.distinct_clause_labels || 0) + " labeled clause(s)",
      },
      {
        title: "Clause Integrity Rate",
        value: formatPct(k.clause_integrity_rate_pct),
        sub: (k.intact_chunks || 0) + " / " + (k.total_chunks || 0)
          + " preserved without split indicators",
      },
      {
        title: "Cross-References Resolved",
        value: String(k.crossrefs_resolved || 0) + " / " + String(k.crossrefs_total || 0),
        sub: "Resolution rate: " + formatPct(k.crossref_resolution_rate_pct),
      },
      {
        title: "Rule-Exception Links Preserved",
        value: String(k.rule_exception_links_preserved || 0)
          + " / " + String(k.rule_exception_links_total || 0),
        sub: "Preservation rate: " + formatPct(k.rule_exception_preservation_rate_pct),
      },
    ];
    for (const c of cards) {
      const card = el("div", "kpi-card");
      card.appendChild(el("div", "kpi-title", c.title));
      card.appendChild(el("div", "kpi-value", c.value));
      card.appendChild(el("div", "kpi-sub", c.sub));
      grid.appendChild(card);
    }
  }

  function renderSources() {
    const tbody = document.getElementById("source-rows");
    if (!tbody) return;
    tbody.replaceChildren();
    const sources = data.sources || [];
    if (!sources.length) {
      const tr = el("tr");
      const td = el("td", "", "No active documents committed in this collection.");
      td.colSpan = 6;
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const s of sources) {
      const tr = el("tr");
      tr.appendChild(el("td", "", s.source));
      tr.appendChild(el("td", "meta-val", s.content_hash || s.doc_version));
      tr.appendChild(el("td", "", s.profile || "N/A"));
      tr.appendChild(
        el("td", "", String(s.child_count || 0) + " / " + String(s.parent_count || 0))
      );
      tr.appendChild(el("td", "", s.embed_model || "N/A"));
      tr.appendChild(el("td", "meta-val", s.ingested_at || "N/A"));
      tbody.appendChild(tr);
    }
  }

  function matchesFilter(chunk) {
    if (activeFilter === "HAS_EXCEPTION" && !chunk.has_exception) return false;
    if (activeFilter === "HAS_CROSS_REF" && !chunk.has_crossref) return false;
    if (activeFilter === "WARNING / SPLIT" && !chunk.has_warning) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const hay = [
        chunk.source,
        chunk.section,
        chunk.clause || "",
        chunk.breadcrumb,
        chunk.text,
      ].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }

  function renderPills() {
    const wrap = document.getElementById("filter-pills");
    if (!wrap) return;
    wrap.replaceChildren();
    const counts = data.filter_counts || {};
    for (const name of filterOrder) {
      const count = counts[name] || 0;
      const cls = "pill" + (activeFilter === name ? " active" : "");
      const btn = el("button", cls, name + " (" + count + ")");
      btn.type = "button";
      btn.addEventListener("click", function () {
        activeFilter = name;
        renderPills();
        renderChunks();
      });
      wrap.appendChild(btn);
    }
  }

  function renderChunks() {
    const container = document.getElementById("chunk-explorer");
    const countLabel = document.getElementById("visible-count");
    if (!container) return;
    container.replaceChildren();

    const chunks = (data.chunks || []).filter(matchesFilter);
    if (countLabel) {
      countLabel.textContent = "Showing " + chunks.length + " of "
        + (data.chunks || []).length + " chunk(s)";
    }

    if (!chunks.length) {
      container.appendChild(
        el("div", "empty-state", "No chunks match the current filter criteria.")
      );
      return;
    }

    for (const ch of chunks) {
      const details = el("details", "chunk-card");
      const summary = el("summary");

      const left = el("div", "breadcrumb", ch.breadcrumb);
      const badges = el("div", "badges");
      if (ch.has_exception) badges.appendChild(el("span", "badge badge-exc", "EXCEPTION BOUND"));
      if (ch.has_crossref) badges.appendChild(el("span", "badge badge-xref", "CROSS-REF"));
      if (ch.has_warning) badges.appendChild(el("span", "badge badge-warn", "WARNING / SPLIT"));
      badges.appendChild(
        el("span", "badge badge-meta", ch.token_count + " tok · " + ch.char_count + " chars")
      );

      summary.appendChild(left);
      summary.appendChild(badges);
      details.appendChild(summary);

      const body = el("div", "chunk-body");
      body.appendChild(
        el(
          "div",
          "subtitle",
          "Chunk ID: " + ch.id
            + " · Parent ID: " + (ch.parent_id || "none")
            + " · Version: " + ch.doc_version
            + " · Index: " + ch.chunk_index
        )
      );
      body.lastChild.style.color = "#475569";
      body.lastChild.style.marginBottom = "8px";
      body.lastChild.style.fontFamily = "var(--mono)";
      body.lastChild.style.fontSize = "0.78rem";

      body.appendChild(el("pre", "chunk-text", ch.text));

      if (ch.bound_exceptions && ch.bound_exceptions.length) {
        const grp = el("div", "detail-group");
        grp.appendChild(el("h4", "", "Bound Rule Exceptions"));
        const ul = el("ul", "detail-list");
        for (const ex of ch.bound_exceptions) {
          const st = ex.preserved_in_parent ? "preserved in parent" : "unbound/missing parent";
          const desc = "[" + ex.marker + "] (" + ex.scope + ", " + st + "): " + ex.snippet;
          ul.appendChild(el("li", "", desc));
        }
        grp.appendChild(ul);
        body.appendChild(grp);
      }

      if (ch.resolved_crossrefs && ch.resolved_crossrefs.length) {
        const grp = el("div", "detail-group");
        grp.appendChild(el("h4", "", "Resolved Cross-References"));
        const ul = el("ul", "detail-list");
        for (const xr of ch.resolved_crossrefs) {
          ul.appendChild(el("li", "", xr.target + " → " + xr.excerpt));
        }
        grp.appendChild(ul);
        body.appendChild(grp);
      }

      if (ch.warnings && ch.warnings.length) {
        const grp = el("div", "detail-group");
        grp.appendChild(el("h4", "", "Integrity Warnings"));
        const ul = el("ul", "detail-list");
        for (const w of ch.warnings) {
          ul.appendChild(el("li", "", w));
        }
        grp.appendChild(ul);
        body.appendChild(grp);
      }

      details.appendChild(body);
      container.appendChild(details);
    }
  }

  const searchInput = document.getElementById("chunk-search");
  if (searchInput) {
    searchInput.addEventListener("input", function (ev) {
      searchQuery = (ev.target && ev.target.value ? ev.target.value : "").trim();
      renderChunks();
    });
  }

  window.addEventListener("beforeprint", function () {
    const allDetails = document.querySelectorAll("details.chunk-card");
    for (const d of allDetails) d.open = true;
  });

  renderKpis();
  renderSources();
  renderPills();
  renderChunks();
})();
"""


def render_html_report(report_data: Mapping[str, Any]) -> str:
    """Render a self-contained static HTML5 integrity audit report."""
    esc = html.escape
    tool_ver = esc(str(report_data.get("tool_version", __version__)), quote=True)
    collection = esc(str(report_data.get("collection", "")), quote=True)
    doc_summary = esc(str(report_data.get("document_summary", "")), quote=True)
    doc_hash = esc(str(report_data.get("document_hash_summary", "")), quote=True)
    generated_at = esc(str(report_data.get("generated_at_utc", "")), quote=True)
    embed_model = esc(str(report_data.get("embed_model", "")), quote=True)
    disclaimer = esc(str(report_data.get("governance_disclaimer", "")), quote=True)

    tags = report_data.get("compliance_tags", COMPLIANCE_TAGS)
    tag_spans = "\n".join(
        f'<span class="compliance-badge">{esc(str(tag), quote=True)}</span>' for tag in tags
    )
    safe_json = _safe_json_for_script_tag(report_data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>docpipe-maestro Document Integrity &amp; Chunk Audit Report — {collection}</title>
  <style>{_CSS_STYLES}</style>
</head>
<body>
  <div class="container">
    <header class="header-banner">
      <div class="header-top">
        <div class="title-block">
          <h1>Document Integrity &amp; Chunk Audit Report</h1>
          <div class="subtitle">docpipe-maestro v{tool_ver} · Offline Static Audit Export</div>
        </div>
        <div class="compliance-tags">
          {tag_spans}
        </div>
      </div>
      <div class="meta-grid">
        <div>
          <span class="meta-label">Collection / Embedding Model</span>
          <span class="meta-val">{collection} · {embed_model}</span>
        </div>
        <div>
          <span class="meta-label">Source Document(s)</span>
          <span class="meta-val">{doc_summary}</span>
        </div>
        <div>
          <span class="meta-label">Source Hash / Digest</span>
          <span class="meta-val">{doc_hash}</span>
        </div>
        <div>
          <span class="meta-label">Audit Run Timestamp (UTC)</span>
          <span class="meta-val">{generated_at}</span>
        </div>
      </div>
    </header>

    <section id="kpi-grid" class="kpi-grid" aria-label="Integrity KPIs"></section>

    <section class="panel" aria-label="Source Document Manifest">
      <h2>Indexed Source Manifest</h2>
      <table class="source-table">
        <thead>
          <tr>
            <th>Source</th>
            <th>Content Hash (sha256)</th>
            <th>Profile</th>
            <th>Children / Parents</th>
            <th>Embed Model</th>
            <th>Ingested At (UTC)</th>
          </tr>
        </thead>
        <tbody id="source-rows"></tbody>
      </table>
    </section>

    <section class="panel" aria-label="Hierarchy &amp; Audit Explorer">
      <h2>Hierarchy &amp; Chunk Audit Explorer</h2>
      <div class="controls">
        <div id="filter-pills" class="pills"></div>
        <input
          id="chunk-search"
          class="search-input"
          type="search"
          placeholder="Filter by section, clause ID, breadcrumb, or keyword..."
          aria-label="Search chunks"
        >
      </div>
      <div id="visible-count" style="font-size:0.82rem;color:#475569;margin-bottom:10px;"></div>
      <div id="chunk-explorer"></div>
    </section>

    <footer class="footer-note">
      {disclaimer} · Generated by docpipe-maestro v{tool_ver}
    </footer>
  </div>

  <script id="report-data" type="application/json">
{safe_json}
  </script>
  <script>{_CLIENT_SCRIPT}</script>
</body>
</html>
"""


def _write_atomic_html(target: Path, content: str) -> Path:
    """Write ``content`` to ``target`` atomically as UTF-8."""
    if target.exists() and target.is_dir():
        raise ValueError(f"--html-report target must be a file path, not a directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return target


def export_html_report(
    output_path: str | Path,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    store: str = "default",
    chunks: Sequence[Chunk] | None = None,
    sources: Mapping[str, SourceRecord] | None = None,
    embed_model: str | None = None,
    generated_at: str | None = None,
) -> Path:
    """Export a single-file HTML Document Integrity & Chunk Audit Report.

    Reads persisted records directly from the collection manifest and store when
    ``chunks`` is omitted, preserving active ``doc_version`` scoping without
    duplicating parsing or chunking logic.
    """
    raw_out = str(output_path).strip()
    if not raw_out:
        raise ValueError("--html-report output path must not be empty")
    target = Path(raw_out)
    if target.exists() and target.is_dir():
        raise ValueError(f"--html-report target must be a file path, not a directory: {target}")

    safe_collection = validate_collection_name(collection)
    persist_path = Path(persist_dir)

    with stage_event(
        logger,
        "report",
        collection=safe_collection,
        store=store,
    ) as report_ev:
        if chunks is None:
            manifest = load_manifest(persist_path, safe_collection)
            active_sources = manifest.sources
            resolved_model = embed_model or manifest.embed_model
            loaded_chunks: list[Chunk] = []

            if active_sources:
                store_cls = STORES.resolve(store)
                store_obj = store_cls(persist_path, safe_collection)
                try:
                    active_versions = {k: v.doc_version for k, v in active_sources.items()}
                    all_children = store_obj.get_all_children()
                    all_parents = store_obj.get_all_parents()
                    loaded_chunks.extend(
                        c
                        for c in all_children
                        if active_versions.get(c.metadata["source"]) == c.metadata["doc_version"]
                    )
                    loaded_chunks.extend(
                        p
                        for p in all_parents
                        if active_versions.get(p.metadata["source"]) == p.metadata["doc_version"]
                    )
                finally:
                    close_fn = getattr(store_obj, "close", None)
                    if callable(close_fn):
                        with contextlib.suppress(Exception):
                            close_fn()
            elif store != "default":
                STORES.resolve(store)

            report_payload = build_audit_report(
                loaded_chunks,
                collection=safe_collection,
                sources=active_sources,
                embed_model=resolved_model,
                generated_at=generated_at,
            )
        else:
            if store != "default":
                STORES.resolve(store)
            report_payload = build_audit_report(
                chunks,
                collection=safe_collection,
                sources=sources,
                embed_model=embed_model,
                generated_at=generated_at,
            )

        rendered_html = render_html_report(report_payload)
        written_path = _write_atomic_html(target, rendered_html)
        kpis = report_payload["kpis"]
        report_ev["chunks"] = kpis["total_chunks"]
        report_ev["parents"] = kpis["total_parents"]
        if not isinstance(written_path, Path):  # pragma: no cover - defensive
            raise DocpipeError("Unexpected non-Path return value when writing HTML report")
        return written_path
