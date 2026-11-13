"""Phase 1 cleaner registry and compatibility re-exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.ingest.stages import Cleaner

if TYPE_CHECKING:
    from docpipe_maestro.ingest.clean.default import (
        DefaultCleaner,
        clean_document,
        clean_text,
    )

CLEANERS: Registry[Cleaner] = Registry("cleaner")
register_cleaner = CLEANERS.register

CLEANERS.register_lazy("default", "docpipe_maestro.ingest.clean.default", "DefaultCleaner")

__all__ = [
    "CLEANERS",
    "DefaultCleaner",
    "clean_document",
    "clean_text",
    "register_cleaner",
]

_LAZY_CLEAN_EXPORTS = frozenset({"DefaultCleaner", "clean_document", "clean_text"})


def __getattr__(name: str) -> Any:
    """Lazily expose built-in cleaner helpers and class without eager materialization."""
    if name in _LAZY_CLEAN_EXPORTS:
        mod = importlib.import_module("docpipe_maestro.ingest.clean.default")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
