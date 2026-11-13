"""Phase 2 reranker extension registry (contract-only in Stage 1)."""

from __future__ import annotations

from docpipe_maestro._registry import Registry
from docpipe_maestro.query.stages import Reranker

RERANKERS: Registry[Reranker] = Registry("reranker")
register_reranker = RERANKERS.register

__all__ = ["RERANKERS", "register_reranker"]
