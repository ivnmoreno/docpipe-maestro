"""Pure, zero-I/O ranking quality metrics for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet


def _validate_cutoff(k: int) -> int:
    """Validate that a ranking cutoff is a strictly positive non-boolean integer."""
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError(f"Cutoff k must be a positive integer greater than zero, got {k!r}")
    return k


def _hits_at_k(
    retrieved_ids: Sequence[str],
    relevant_set: frozenset[str],
    k: int,
) -> int:
    """Count unique relevant identifiers present within the top-k retrieved IDs."""
    return len(set(retrieved_ids[:k]) & relevant_set)


def normalize_k_values(k_values: Sequence[int]) -> tuple[int, ...]:
    """Validate, deduplicate, and sort positive cutoff values in ascending order.

    Args:
        k_values: Sequence of integer ranking cutoffs.

    Returns:
        Sorted tuple of unique positive cutoffs (e.g., ``[10, 3, 3]`` -> ``(3, 10)``).

    Raises:
        ValueError: If ``k_values`` is empty or contains any boolean or non-positive value.
    """
    if not k_values:
        raise ValueError("k_values must contain at least one positive integer cutoff.")
    return tuple(sorted({_validate_cutoff(k) for k in k_values}))


def precision_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: AbstractSet[str] | Sequence[str],
    k: int,
) -> float:
    """Compute fixed-cutoff ``Precision@K`` in ``[0.0, 1.0]``.

    Returns ``0.0`` safely when either ``retrieved_ids`` or ``relevant_ids`` is empty.
    """
    cutoff = _validate_cutoff(k)
    relevant_set = frozenset(relevant_ids)
    if not retrieved_ids or not relevant_set:
        return 0.0
    hits = _hits_at_k(retrieved_ids, relevant_set, cutoff)
    return min(1.0, max(0.0, hits / cutoff))


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: AbstractSet[str] | Sequence[str],
    k: int,
) -> float:
    """Compute standard IR ``Recall@K`` (unique top-K hits / total unique relevant IDs).

    Returns ``0.0`` safely when either ``retrieved_ids`` or ``relevant_ids`` is empty.
    """
    cutoff = _validate_cutoff(k)
    relevant_set = frozenset(relevant_ids)
    if not retrieved_ids or not relevant_set:
        return 0.0
    hits = _hits_at_k(retrieved_ids, relevant_set, cutoff)
    return min(1.0, max(0.0, hits / len(relevant_set)))


def reciprocal_rank(
    retrieved_ids: Sequence[str],
    relevant_ids: AbstractSet[str] | Sequence[str],
) -> float:
    """Compute Reciprocal Rank (``1 / rank`` of first relevant item, else ``0.0``)."""
    relevant_set = frozenset(relevant_ids)
    if not retrieved_ids or not relevant_set:
        return 0.0
    for rank, item_id in enumerate(retrieved_ids, start=1):
        if item_id in relevant_set:
            return 1.0 / rank
    return 0.0


__all__ = [
    "normalize_k_values",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
