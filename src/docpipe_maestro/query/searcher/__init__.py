"""Phase 2 searcher extension registry with lazy built-in declarations."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.query.stages import Searcher

if TYPE_CHECKING:
    from docpipe_maestro.query.searcher.dense import DenseSearcher
    from docpipe_maestro.query.searcher.hybrid import Fts5HybridSearcher

SEARCHERS: Registry[Searcher] = Registry("searcher")
register_searcher = SEARCHERS.register

SEARCHERS.register_lazy("default", "docpipe_maestro.query.searcher.dense", "DenseSearcher")
SEARCHERS.register_lazy(
    "fts5_hybrid", "docpipe_maestro.query.searcher.hybrid", "Fts5HybridSearcher"
)

__all__ = [
    "SEARCHERS",
    "DenseSearcher",
    "Fts5HybridSearcher",
    "register_searcher",
]

_LAZY_SEARCHER_EXPORTS = {
    "DenseSearcher": "docpipe_maestro.query.searcher.dense",
    "Fts5HybridSearcher": "docpipe_maestro.query.searcher.hybrid",
}


def __getattr__(name: str) -> Any:
    """Lazily expose built-in searcher classes without eager backend imports."""
    module_path = _LAZY_SEARCHER_EXPORTS.get(name)
    if module_path is not None:
        mod = importlib.import_module(module_path)
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
