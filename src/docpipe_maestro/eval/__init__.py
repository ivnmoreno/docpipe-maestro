"""Phase 2 read-only retrieval evaluation subpackage for docpipe-maestro."""

from __future__ import annotations

from docpipe_maestro.eval.harness import (
    DEFAULT_EVAL_K_VALUES,
    EvalConfig,
    EvalFixture,
    EvalMetricsSummary,
    EvalQuery,
    EvalReport,
    PerQueryResult,
    evaluate,
    load_eval_fixture,
)
from docpipe_maestro.eval.metrics import (
    normalize_k_values,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

__all__ = [
    "DEFAULT_EVAL_K_VALUES",
    "EvalConfig",
    "EvalFixture",
    "EvalMetricsSummary",
    "EvalQuery",
    "EvalReport",
    "PerQueryResult",
    "evaluate",
    "load_eval_fixture",
    "normalize_k_values",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
