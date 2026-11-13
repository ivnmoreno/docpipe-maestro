"""Phase 1 enricher extension registry (contract-only in Stage 1)."""

from __future__ import annotations

from docpipe_maestro._registry import Registry
from docpipe_maestro.ingest.stages import Enricher

ENRICHERS: Registry[Enricher] = Registry("enricher")
register_enricher = ENRICHERS.register

__all__ = ["ENRICHERS", "register_enricher"]
