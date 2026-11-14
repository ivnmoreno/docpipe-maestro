"""Phase 1 enricher registry and lazy compatibility re-exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.ingest.stages import Enricher

if TYPE_CHECKING:
    from docpipe_maestro.ingest.enricher.crossrefs import CrossrefsEnricher, resolve_crossrefs

ENRICHERS: Registry[Enricher] = Registry("enricher")
register_enricher = ENRICHERS.register

ENRICHERS.register_lazy(
    "crossrefs", "docpipe_maestro.ingest.enricher.crossrefs", "CrossrefsEnricher"
)

__all__ = [
    "ENRICHERS",
    "CrossrefsEnricher",
    "register_enricher",
    "resolve_crossrefs",
]

_LAZY_ENRICHER_EXPORTS = frozenset({"CrossrefsEnricher", "resolve_crossrefs"})


def __getattr__(name: str) -> Any:
    """Lazily expose built-in enricher helpers without eager materialization."""
    if name in _LAZY_ENRICHER_EXPORTS:
        mod = importlib.import_module("docpipe_maestro.ingest.enricher.crossrefs")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
