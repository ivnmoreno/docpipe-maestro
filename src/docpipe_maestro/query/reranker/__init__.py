"""Phase 2 reranker extension registry with lazy built-in declarations."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.query.stages import Reranker

if TYPE_CHECKING:
    from docpipe_maestro.query.reranker.cross_encoder import CrossEncoderReranker

RERANKERS: Registry[Reranker] = Registry("reranker")
register_reranker = RERANKERS.register

RERANKERS.register_lazy(
    "cross_encoder",
    "docpipe_maestro.query.reranker.cross_encoder",
    "CrossEncoderReranker",
)

__all__ = [
    "RERANKERS",
    "CrossEncoderReranker",
    "register_reranker",
    "validate_rerank_options",
]

_LAZY_RERANKER_EXPORTS = {
    "CrossEncoderReranker": "docpipe_maestro.query.reranker.cross_encoder",
}


def validate_rerank_options(
    *,
    rerank: bool,
    reranker: str,
    rerank_top_n: int,
) -> type[Reranker] | None:
    """Validate rerank parameters upfront and resolve the active strategy class.

    Rejects non-integer, boolean, or non-positive ``rerank_top_n`` values
    unconditionally. When ``rerank`` is ``False``, returns ``None`` without
    resolving or importing optional reranking backends.
    """
    if isinstance(rerank_top_n, bool) or not isinstance(rerank_top_n, int) or rerank_top_n <= 0:
        raise ValueError("rerank_top_n must be a positive integer >= 1")
    if not rerank:
        return None
    reranker_cls = RERANKERS.resolve(reranker)
    validate_fn = getattr(reranker_cls, "validate_available", None)
    if callable(validate_fn):
        validate_fn()
    return reranker_cls


def __getattr__(name: str) -> Any:
    """Lazily expose built-in reranker classes without eager backend imports."""
    module_path = _LAZY_RERANKER_EXPORTS.get(name)
    if module_path is not None:
        mod = importlib.import_module(module_path)
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
