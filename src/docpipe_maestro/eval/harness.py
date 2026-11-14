"""Deterministic, strictly read-only evaluation runner for docpipe-maestro."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_PERSIST_DIR,
)
from docpipe_maestro.embedder import EMBEDDERS
from docpipe_maestro.eval.metrics import (
    normalize_k_values,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from docpipe_maestro.manifest import (
    check_model_lock,
    load_manifest,
    manifest_path,
    validate_collection_name,
)
from docpipe_maestro.query.retriever import retrieve
from docpipe_maestro.query.searcher import SEARCHERS
from docpipe_maestro.store import STORES
from docpipe_maestro.types import (
    DocpipeError,
    EvalConfig,
    EvalFixture,
    EvalMetricsSummary,
    EvalQuery,
    EvalReport,
    PerQueryResult,
)

DEFAULT_EVAL_K_VALUES: tuple[int, ...] = (1, 3, 5, 10)


def _validate_threshold(threshold: float | None) -> float | None:
    """Validate optional score cutoff within ``[0.0, 1.0]``."""
    if threshold is None:
        return None
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(f"threshold must be a float in [0.0, 1.0] or None, got {threshold!r}")
    value = float(threshold)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(f"threshold must be finite and in [0.0, 1.0], got {threshold!r}")
    return value


def _opt_str_field(mapping: Mapping[str, Any], key: str, *, context: str) -> str:
    """Extract an optional string metadata field, normalizing missing/None to ``""``."""
    raw = mapping.get(key)
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise DocpipeError(f"{context}: field {key!r} must be a string, got {type(raw).__name__}.")
    return raw.strip()


def _parse_query_entry(entry: object, index: int) -> EvalQuery:
    """Validate and normalize one query case inside an evaluation fixture."""
    context = f"Evaluation query #{index}"
    if not isinstance(entry, Mapping):
        raise DocpipeError(f"{context} must be a JSON object.")

    question_raw = entry.get("question")
    if not isinstance(question_raw, str) or not question_raw.strip():
        raise DocpipeError(f"{context}: 'question' must be a non-blank string.")

    rel_raw = entry.get("relevant_ids")
    if not isinstance(rel_raw, list) or not rel_raw:
        raise DocpipeError(f"{context}: 'relevant_ids' must be a non-empty list of IDs.")

    deduped_rel: list[str] = []
    seen: set[str] = set()
    for item in rel_raw:
        if not isinstance(item, str) or not item.strip():
            raise DocpipeError(f"{context}: every item in 'relevant_ids' must be a non-blank ID.")
        cleaned = item.strip()
        if cleaned not in seen:
            seen.add(cleaned)
            deduped_rel.append(cleaned)

    notes = _opt_str_field(entry, "notes", context=context)
    return {
        "question": question_raw.strip(),
        "relevant_ids": deduped_rel,
        "notes": notes,
    }


def load_eval_fixture(fixture: str | Path | EvalFixture) -> EvalFixture:
    """Load, validate, and normalize a JSON evaluation fixture file or in-memory dict.

    Raises:
        DocpipeError: If the file cannot be read/parsed or fails schema validation.
    """
    raw: Any
    if isinstance(fixture, (str, Path)):
        path = Path(fixture)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DocpipeError(f"Unable to read evaluation fixture {path}: {exc}") from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DocpipeError(f"Invalid JSON in evaluation fixture {path}: {exc}") from exc
    elif isinstance(fixture, Mapping):
        raw = fixture
    else:
        raise DocpipeError(
            f"Evaluation fixture must be a file path or mapping, got {type(fixture).__name__}."
        )

    if not isinstance(raw, Mapping):
        raise DocpipeError("Evaluation fixture root must be a JSON object.")

    collection_name = _opt_str_field(raw, "collection", context="Evaluation fixture")
    profile_name = _opt_str_field(raw, "profile", context="Evaluation fixture")

    queries_raw = raw.get("queries")
    if not isinstance(queries_raw, list) or not queries_raw:
        raise DocpipeError("Evaluation fixture must contain a non-empty 'queries' list.")

    parsed_queries = [
        _parse_query_entry(entry, idx) for idx, entry in enumerate(queries_raw, start=1)
    ]
    return {
        "collection": collection_name,
        "profile": profile_name,
        "queries": parsed_queries,
    }


def _resolve_target_collection(collection: str | None, loaded_fixture: EvalFixture) -> str:
    """Resolve effective collection: explicit arg > non-empty fixture > DEFAULT_COLLECTION."""
    if collection is not None:
        raw_name = collection
    elif loaded_fixture.get("collection"):
        raw_name = loaded_fixture["collection"]
    else:
        raw_name = DEFAULT_COLLECTION
    return validate_collection_name(raw_name)


def _preflight_check(
    persist_path: Path,
    effective_collection: str,
    *,
    embed_model: str,
    embedder: str,
    store: str,
    searcher: str,
) -> None:
    """Validate registry selectors and read-only store state without creating directories."""
    if embedder != "default":
        EMBEDDERS.resolve(embedder)
    if store != "default":
        STORES.resolve(store)
    SEARCHERS.resolve(searcher)

    # Check manifest file directly so ChromaStore never auto-creates missing directories.
    m_path = manifest_path(persist_path, effective_collection)
    if not m_path.exists():
        raise DocpipeError(f"Collection {effective_collection!r} does not exist at {persist_path}.")

    manifest = load_manifest(persist_path, effective_collection)
    check_model_lock(manifest, embed_model)
    if not manifest.sources:
        raise DocpipeError(
            f"Collection {effective_collection!r} has no committed documents to evaluate."
        )


def _aggregate_metrics(
    per_query: list[PerQueryResult],
    norm_k: tuple[int, ...],
) -> EvalMetricsSummary:
    """Compute mean Precision@K, Recall@K, and MRR across evaluated queries."""
    num_queries = len(per_query)
    return {
        "num_queries": num_queries,
        "mrr": sum(item["reciprocal_rank"] for item in per_query) / num_queries,
        "precision_at_k": {
            str(k): sum(item["precision_at_k"][str(k)] for item in per_query) / num_queries
            for k in norm_k
        },
        "recall_at_k": {
            str(k): sum(item["recall_at_k"][str(k)] for item in per_query) / num_queries
            for k in norm_k
        },
    }


def evaluate(
    fixture: str | Path | EvalFixture,
    *,
    collection: str | None = None,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    k_values: Sequence[int] = DEFAULT_EVAL_K_VALUES,
    expand_parent: bool = True,
    follow_crossrefs: bool = True,
    threshold: float | None = None,
    embedder: str = "default",
    store: str = "default",
    searcher: str = "default",
    **retrieve_kwargs: Any,
) -> EvalReport:
    """Evaluate Phase 2 retrieval against a curated fixture strictly read-only.

    Args:
        fixture: Path to an evaluation JSON fixture file or in-memory ``EvalFixture``.
        collection: Explicit target collection name (overrides fixture ``collection``).
        persist_dir: Local persistence root directory containing manifests and indexes.
        embed_model: Embedding ``provider/model`` expected to match the collection lock.
        k_values: Positive ranking cutoffs (normalized/deduplicated ascending).
        expand_parent: Passed through to ``retrieve()``; ``True`` evaluates parent sections.
        follow_crossrefs: Passed through to ``retrieve()`` for cross-document context.
        threshold: Optional normalized similarity cutoff in ``[0.0, 1.0]``.
        embedder: Registered ``EMBEDDERS`` key (defaults to ``"default"``).
        store: Registered ``STORES`` key (defaults to ``"default"``).
        searcher: Registered ``SEARCHERS`` key (defaults to ``"default"``).
        **retrieve_kwargs: Forwarded to ``retrieve()`` for downstream extension stages.

    Returns:
        Typed ``EvalReport`` containing resolved config, aggregate metrics, and per-query results.

    Raises:
        ValueError: If ``k_values`` or ``threshold`` fail validation.
        RegistryError: If ``embedder``, ``store``, or ``searcher`` is unregistered.
        ModelMismatchError: If ``embed_model`` mismatches the locked collection model.
        DocpipeError: If the fixture is invalid or the collection is missing or empty.
    """
    norm_k = normalize_k_values(k_values)
    norm_threshold = _validate_threshold(threshold)
    loaded_fixture = load_eval_fixture(fixture)
    effective_collection = _resolve_target_collection(collection, loaded_fixture)

    persist_path = Path(persist_dir)
    _preflight_check(
        persist_path,
        effective_collection,
        embed_model=embed_model,
        embedder=embedder,
        store=store,
        searcher=searcher,
    )

    max_k = norm_k[-1]
    per_query: list[PerQueryResult] = []
    for query in loaded_fixture["queries"]:
        chunks = retrieve(
            query["question"],
            collection=effective_collection,
            persist_dir=persist_path,
            embed_model=embed_model,
            top_k=max_k,
            threshold=norm_threshold,
            expand_parent=expand_parent,
            follow_crossrefs=follow_crossrefs,
            embedder=embedder,
            store=store,
            searcher=searcher,
            **retrieve_kwargs,
        )
        retrieved_ids = [chunk.id for chunk in chunks]
        retrieved_scores = [float(chunk.score) for chunk in chunks]
        relevant_ids = list(query["relevant_ids"])

        per_query.append(
            {
                "question": query["question"],
                "notes": query.get("notes", ""),
                "relevant_ids": relevant_ids,
                "retrieved_ids": retrieved_ids,
                "retrieved_scores": retrieved_scores,
                "precision_at_k": {
                    str(k): precision_at_k(retrieved_ids, relevant_ids, k) for k in norm_k
                },
                "recall_at_k": {
                    str(k): recall_at_k(retrieved_ids, relevant_ids, k) for k in norm_k
                },
                "reciprocal_rank": reciprocal_rank(retrieved_ids, relevant_ids),
            }
        )

    config: EvalConfig = {
        "collection": effective_collection,
        "persist_dir": str(persist_path),
        "embed_model": embed_model,
        "k_values": list(norm_k),
        "expand_parent": expand_parent,
        "follow_crossrefs": follow_crossrefs,
        "searcher": searcher,
        "embedder": embedder,
        "store": store,
        "threshold": norm_threshold,
    }
    return {
        "config": config,
        "aggregate": _aggregate_metrics(per_query, norm_k),
        "per_query": per_query,
    }


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
]
