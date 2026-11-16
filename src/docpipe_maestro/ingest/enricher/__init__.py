"""Phase 1 enricher registry and lazy compatibility re-exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.ingest.stages import Enricher

if TYPE_CHECKING:
    from docpipe_maestro.ingest.enricher.crossrefs import CrossrefsEnricher, resolve_crossrefs
    from docpipe_maestro.ingest.enricher.pii import PiiEnricher

ENRICHERS: Registry[Enricher] = Registry("enricher")
register_enricher = ENRICHERS.register

ENRICHERS.register_lazy(
    "crossrefs", "docpipe_maestro.ingest.enricher.crossrefs", "CrossrefsEnricher"
)
ENRICHERS.register_lazy("pii", "docpipe_maestro.ingest.enricher.pii", "PiiEnricher")

__all__ = [
    "ENRICHERS",
    "CrossrefsEnricher",
    "PiiEnricher",
    "register_enricher",
    "resolve_crossrefs",
]

_LAZY_ENRICHER_EXPORTS: dict[str, str] = {
    "CrossrefsEnricher": "docpipe_maestro.ingest.enricher.crossrefs",
    "resolve_crossrefs": "docpipe_maestro.ingest.enricher.crossrefs",
    "PiiEnricher": "docpipe_maestro.ingest.enricher.pii",
}


def __getattr__(name: str) -> Any:
    """Lazily expose built-in enricher helpers without eager materialization."""
    module_path = _LAZY_ENRICHER_EXPORTS.get(name)
    if module_path is not None:
        mod = importlib.import_module(module_path)
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
