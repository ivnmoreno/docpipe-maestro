"""Backward-compatible re-exports for legacy ``docpipe_maestro.ingest.crossrefs`` imports."""

from __future__ import annotations

from docpipe_maestro._crossrefs import (
    extract_doc_crossrefs,
    index_section_targets,
    match_source_key,
    truncate_excerpt,
)
from docpipe_maestro.ingest.enricher.crossrefs import resolve_crossrefs

__all__ = [
    "extract_doc_crossrefs",
    "index_section_targets",
    "match_source_key",
    "resolve_crossrefs",
    "truncate_excerpt",
]
