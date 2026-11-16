"""Built-in Phase 1 PII protection enricher strategy under ``ENRICHERS['pii']``."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from docpipe_maestro._pii import evaluate_pii_text, validate_pii_policy
from docpipe_maestro.ingest.enricher import ENRICHERS
from docpipe_maestro.types import (
    IngestContext,
    ParsedClause,
    ParsedDocument,
    ParsedSection,
    PiiBlockedError,
)

__all__ = ["PiiEnricher"]


def _merge_audit_stats(
    total_counts: dict[str, int],
    total_actions: dict[str, str],
    counts: dict[str, int],
    actions: dict[str, str],
) -> None:
    """Merge non-PII per-span entity counts and strictest actions cleanly."""
    for entity, count in counts.items():
        total_counts[entity] = total_counts.get(entity, 0) + count
    for entity, action in actions.items():
        if total_actions.get(entity) != "block":
            total_actions[entity] = action


@ENRICHERS.register("pii")
class PiiEnricher:
    """Pre-chunking Phase 1 enricher for PII redaction, tokenization, or blocking."""

    name: str = "pii"

    def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
        """Scrub section labels, bodies, and clauses in ``doc`` per ``ctx['pii_policy']``."""
        raw_policy = ctx.get("pii_policy")
        if raw_policy is None:
            return doc

        validated = validate_pii_policy(raw_policy)
        source_key = ctx["source"]

        doc_counts: dict[str, int] = {}
        doc_actions: dict[str, str] = {}
        doc_blocked: set[str] = set()
        new_sections: list[ParsedSection] = []

        for sec in doc.sections:
            new_label, label_counts, label_actions, label_blocked = evaluate_pii_text(
                sec.section_label,
                validated,
                source=source_key,
                phase="ingest",
                egress_mode=False,
                raise_on_block=False,
            )
            _merge_audit_stats(doc_counts, doc_actions, label_counts, label_actions)
            doc_blocked.update(label_blocked)

            new_raw_text, body_counts, body_actions, body_blocked = evaluate_pii_text(
                sec.raw_text,
                validated,
                source=source_key,
                phase="ingest",
                egress_mode=False,
                raise_on_block=False,
            )
            _merge_audit_stats(doc_counts, doc_actions, body_counts, body_actions)
            doc_blocked.update(body_blocked)

            new_clauses: list[ParsedClause] = []
            had_raw_text = bool(sec.raw_text)
            for clause in sec.clauses:
                new_clause_label = clause.clause_label
                if clause.clause_label:
                    new_clause_label, cl_counts, cl_actions, cl_blocked = evaluate_pii_text(
                        clause.clause_label,
                        validated,
                        source=source_key,
                        phase="ingest",
                        egress_mode=False,
                        raise_on_block=False,
                    )
                    doc_blocked.update(cl_blocked)
                    if not had_raw_text or cl_blocked:
                        _merge_audit_stats(doc_counts, doc_actions, cl_counts, cl_actions)

                new_clause_text, c_counts, c_actions, c_blocked = evaluate_pii_text(
                    clause.text,
                    validated,
                    source=source_key,
                    phase="ingest",
                    egress_mode=False,
                    raise_on_block=False,
                )
                doc_blocked.update(c_blocked)
                if not had_raw_text or c_blocked:
                    _merge_audit_stats(doc_counts, doc_actions, c_counts, c_actions)

                new_clauses.append(
                    ParsedClause(
                        clause_label=new_clause_label,
                        text=new_clause_text,
                        page=clause.page,
                    )
                )

            new_sections.append(
                ParsedSection(
                    source=sec.source,
                    section_label=new_label,
                    heading_level=sec.heading_level,
                    raw_text=new_raw_text,
                    page=sec.page,
                    clauses=new_clauses,
                )
            )

        sorted_counts = dict(sorted(doc_counts.items()))
        sorted_actions = dict(sorted(doc_actions.items()))

        extra = ctx.get("extra")
        if isinstance(extra, MutableMapping):
            audit_target: dict[str, Any] = {
                "entity_counts": sorted_counts,
                "actions": sorted_actions,
                "threshold": validated.min_confidence,
            }
            extra["pii_audit"] = audit_target

        if doc_blocked:
            blocked_sorted = tuple(sorted(doc_blocked))
            raise PiiBlockedError(
                f"Blocked PII entity type(s) {list(blocked_sorted)!r} "
                f"in source {source_key!r} during ingest.",
                entity_counts=sorted_counts,
                actions=sorted_actions,
                blocked_entities=blocked_sorted,
                source=source_key,
                phase="ingest",
            )

        return ParsedDocument(
            source=doc.source,
            format_name=doc.format_name,
            sections=new_sections,
        )
