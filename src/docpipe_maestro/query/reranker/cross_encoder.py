"""Local cross-encoder reranking strategy backed by sentence-transformers."""

from __future__ import annotations

import dataclasses
import importlib.util
import math
import sys
import threading
from typing import Any

from docpipe_maestro.config import DEFAULT_RERANK_MODEL
from docpipe_maestro.query.reranker import RERANKERS
from docpipe_maestro.types import DocpipeError, MissingExtraError, RetrievedChunk

_MISSING_RERANK_MSG = (
    "Cross-encoder reranking requires the 'rerank' extra: pip install 'docpipe-maestro[rerank]'"
)

_MODEL_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def _has_sentence_transformers() -> bool:
    """Check optional dependency visibility without importing ``torch`` eagerly."""
    if "sentence_transformers" in sys.modules:
        return sys.modules["sentence_transformers"] is not None
    return importlib.util.find_spec("sentence_transformers") is not None


def _instantiate_cross_encoder(model_name: str) -> Any:
    """Lazily import ``CrossEncoder`` and construct an instance for ``model_name``."""
    CrossEncoderReranker.validate_available()
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise MissingExtraError(_MISSING_RERANK_MSG) from exc
    return CrossEncoder(model_name)


def _load_cross_encoder(model_name: str) -> Any:
    """Return a cached ``CrossEncoder`` instance for ``model_name`` thread-safely."""
    with _CACHE_LOCK:
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
        model = _instantiate_cross_encoder(model_name)
        _MODEL_CACHE[model_name] = model
        return model


def _sigmoid(raw_score: float) -> float:
    """Map a finite raw cross-encoder logit monotonically onto ``[0.0, 1.0]``."""
    if not math.isfinite(raw_score):
        raise DocpipeError(f"Cross-encoder emitted non-finite score: {raw_score!r}")
    if raw_score >= 0.0:
        prob = 1.0 / (1.0 + math.exp(-raw_score))
    else:
        exp_x = math.exp(raw_score)
        prob = exp_x / (1.0 + exp_x)
    return min(1.0, max(0.0, prob))


@RERANKERS.register("cross_encoder")
class CrossEncoderReranker:
    """Phase 2 child-chunk reranker using a local ``CrossEncoder`` model."""

    name: str = "cross_encoder"

    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL) -> None:
        """Configure a cross-encoder strategy for ``model_name`` (loaded lazily on use)."""
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name must be a non-empty string")
        self._model_name = model_name.strip()

    @property
    def model_name(self) -> str:
        """Return the configured cross-encoder model identifier."""
        return self._model_name

    @classmethod
    def validate_available(cls) -> None:
        """Verify the optional ``[rerank]`` dependency is available without importing it."""
        if not _has_sentence_transformers():
            raise MissingExtraError(_MISSING_RERANK_MSG)

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Rescore candidate chunks against ``query`` and return top ``top_k`` descending."""
        if not chunks or top_k <= 0:
            return []

        model = _load_cross_encoder(self._model_name)
        pairs = [(query, chunk.text) for chunk in chunks]
        raw_preds = model.predict(pairs)
        if isinstance(raw_preds, (int, float)) or getattr(raw_preds, "ndim", None) == 0:
            raw_scores = [float(raw_preds)]
        else:
            raw_scores = [float(val) for val in raw_preds]

        if len(raw_scores) != len(chunks):
            raise DocpipeError(
                f"Cross-encoder prediction count mismatch: expected {len(chunks)}, "
                f"got {len(raw_scores)}"
            )

        scored = [
            dataclasses.replace(chunk, score=_sigmoid(raw_score))
            for chunk, raw_score in zip(chunks, raw_scores, strict=True)
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]


__all__ = ["CrossEncoderReranker"]
