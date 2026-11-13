"""Phase 2 searcher extension registry (contract-only in Stage 1)."""

from __future__ import annotations

from docpipe_maestro._registry import Registry
from docpipe_maestro.query.stages import Searcher

SEARCHERS: Registry[Searcher] = Registry("searcher")
register_searcher = SEARCHERS.register

__all__ = ["SEARCHERS", "register_searcher"]
