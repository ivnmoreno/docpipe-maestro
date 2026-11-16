"""Phase-neutral metadata filter validation, manifest resolution, and query compilation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, TypeGuard

from docpipe_maestro.types import DocpipeError, Manifest

CHUNK_STR_FIELDS: frozenset[str] = frozenset(
    {"source", "doc_version", "section", "clause", "embed_model"}
)
CHUNK_INT_FIELDS: frozenset[str] = frozenset({"page", "chunk_index"})
CHUNK_FILTER_FIELDS: frozenset[str] = CHUNK_STR_FIELDS | CHUNK_INT_FIELDS

MANIFEST_FILTER_FIELDS: frozenset[str] = frozenset({"profile", "ingested_after", "ingested_before"})
RESERVED_FILTER_FIELDS: frozenset[str] = frozenset({"type"})
ALL_PUBLIC_FILTER_FIELDS: frozenset[str] = CHUNK_FILTER_FIELDS | MANIFEST_FILTER_FIELDS

COMPARISON_OPS: frozenset[str] = frozenset(
    {"$eq", "$ne", "$in", "$nin", "$gt", "$gte", "$lt", "$lte"}
)
LOGICAL_OPS: frozenset[str] = frozenset({"$and", "$or"})
PROFILE_OPS: frozenset[str] = frozenset({"$eq", "$ne", "$in", "$nin"})

SUPPORTED_FILTER_KEYS_DISPLAY = ", ".join(sorted(ALL_PUBLIC_FILTER_FIELDS))

_SQL_OP_MAP: dict[str, str] = {
    "$eq": "=",
    "$ne": "!=",
    "$gt": ">",
    "$gte": ">=",
    "$lt": "<",
    "$lte": "<=",
}
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STRICT_INT_RE = re.compile(r"^[+-]?\d+$")
_RESERVED_TYPES: frozenset[str] = frozenset({"child", "parent"})


@dataclass(frozen=True, slots=True)
class ResolvedWhere:
    """Resolved phase-2 filter state separating chunk predicates from empty short-circuits."""

    chunk_where: dict[str, object] | None
    short_circuit_empty: bool = False


def _is_strict_int(value: object) -> TypeGuard[int]:
    """Return ``True`` for true integers, explicitly rejecting ``bool`` values."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_list_sequence(value: object) -> TypeGuard[Sequence[object]]:
    """Return ``True`` for sequence containers other than string/bytes/mapping."""
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, Mapping))


def _parse_iso_timestamp(raw: object, *, end_of_day_if_date: bool = False, field: str) -> datetime:
    """Parse ISO-8601 date or timestamp into UTC-aware ``datetime`` (Python 3.10+ safe)."""
    if not isinstance(raw, str) or not raw.strip():
        raise DocpipeError(
            f"Filter {field!r} must be a non-empty ISO-8601 date or timestamp string."
        )
    text = raw.strip()
    if _DATE_ONLY_RE.match(text):
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError as exc:
            raise DocpipeError(f"Invalid ISO-8601 date for {field!r}: {raw!r} ({exc}).") from exc
        if end_of_day_if_date:
            return datetime(
                parsed_date.year,
                parsed_date.month,
                parsed_date.day,
                23,
                59,
                59,
                999999,
                tzinfo=timezone.utc,
            )
        return datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            0,
            0,
            0,
            0,
            tzinfo=timezone.utc,
        )

    normalized = f"{text[:-1]}+00:00" if text[-1] in {"Z", "z"} else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DocpipeError(f"Invalid ISO-8601 timestamp for {field!r}: {raw!r} ({exc}).") from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_chunk_scalar(field: str, value: object, *, context: str) -> str | int:
    """Validate one scalar value against its stored chunk field schema type."""
    if field in CHUNK_INT_FIELDS:
        if not _is_strict_int(value):
            raise DocpipeError(
                f"{context}: filter {field!r} requires an integer value (not bool/str), "
                f"got {type(value).__name__}: {value!r}."
            )
        return value
    if field == "type":
        if not isinstance(value, str) or value not in _RESERVED_TYPES:
            raise DocpipeError(
                f"{context}: filter 'type' requires 'child' or 'parent', got {value!r}."
            )
        return value
    if not isinstance(value, str):
        raise DocpipeError(
            f"{context}: filter {field!r} requires a string value, "
            f"got {type(value).__name__}: {value!r}."
        )
    return value


def _combine_and(clauses: Sequence[dict[str, object]]) -> dict[str, object] | None:
    """Flatten nested ``$and`` nodes into a canonical Chroma-compatible predicate dict."""
    if not clauses:
        return None
    flattened: list[dict[str, object]] = []
    for clause in clauses:
        if len(clause) == 1 and "$and" in clause:
            nested = clause["$and"]
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        flattened.append(item)
                continue
        flattened.append(clause)
    if not flattened:
        return None
    if len(flattened) == 1:
        return flattened[0]
    return {"$and": flattened}


_NUMERIC_RANGE_OPS: frozenset[str] = frozenset({"$gt", "$gte", "$lt", "$lte"})


def _normalize_chunk_field_pred(field: str, raw_pred: object) -> list[dict[str, object]]:
    """Validate and expand a chunk-field scalar or operator dict into single-op dicts."""
    if isinstance(raw_pred, Mapping):
        if not raw_pred:
            raise DocpipeError(f"Filter operator mapping for {field!r} cannot be empty.")
        clauses: list[dict[str, object]] = []
        for op, operand in raw_pred.items():
            if not isinstance(op, str) or op not in COMPARISON_OPS:
                supported_ops = ", ".join(sorted(COMPARISON_OPS))
                raise DocpipeError(
                    f"Unsupported operator {op!r} on filter {field!r}. "
                    f"Supported operators: {supported_ops}."
                )
            if op in _NUMERIC_RANGE_OPS and field not in CHUNK_INT_FIELDS:
                raise DocpipeError(
                    f"Range operator {op!r} requires an integer field ('chunk_index' or 'page'), "
                    f"cannot apply to {field!r}."
                )
            if op in {"$in", "$nin"}:
                if not _is_list_sequence(operand) or len(operand) == 0:
                    raise DocpipeError(
                        f"Filter operator {op!r} on {field!r} requires a non-empty list."
                    )
                norm_items = [
                    _validate_chunk_scalar(field, item, context=f"Operator {op}")
                    for item in operand
                ]
                clauses.append({field: {op: norm_items}})
            else:
                norm_scalar = _validate_chunk_scalar(field, operand, context=f"Operator {op}")
                clauses.append({field: {op: norm_scalar}})
        return clauses

    norm_scalar = _validate_chunk_scalar(field, raw_pred, context="Filter")
    return [{field: {"$eq": norm_scalar}}]


def _normalize_profile_pred(raw_pred: object) -> tuple[str, object]:
    """Validate a top-level manifest ``profile`` scalar or operator predicate."""
    if isinstance(raw_pred, Mapping):
        if len(raw_pred) != 1:
            raise DocpipeError(
                "Manifest filter 'profile' accepts either a string or a single "
                "$eq/$ne/$in/$nin operator mapping."
            )
        op, operand = next(iter(raw_pred.items()))
        if not isinstance(op, str) or op not in PROFILE_OPS:
            allowed = ", ".join(sorted(PROFILE_OPS))
            raise DocpipeError(
                f"Unsupported operator {op!r} on manifest filter 'profile'. "
                f"Supported operators: {allowed}."
            )
        if op in {"$in", "$nin"}:
            if not _is_list_sequence(operand) or len(operand) == 0:
                raise DocpipeError(
                    f"Operator {op!r} on 'profile' requires a non-empty list of strings."
                )
            cleaned_list: list[str] = []
            for item in operand:
                if not isinstance(item, str) or not item.strip():
                    raise DocpipeError(
                        f"Operator {op!r} elements for 'profile' must be non-empty strings."
                    )
                cleaned_list.append(item.strip().casefold())
            return op, cleaned_list
        if not isinstance(operand, str) or not operand.strip():
            raise DocpipeError(f"Operator {op!r} value for 'profile' must be a non-empty string.")
        return op, operand.strip().casefold()

    if not isinstance(raw_pred, str) or not raw_pred.strip():
        raise DocpipeError("Manifest filter 'profile' must be a non-empty string.")
    return "$eq", raw_pred.strip().casefold()


def _normalize_where_node(
    node: object,
    *,
    allow_manifest: bool,
    reject_reserved_type: bool,
    is_root: bool,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Validate and split a ``where`` mapping into normalized chunk clauses + manifest spec."""
    if not isinstance(node, Mapping):
        raise DocpipeError(f"Metadata filter 'where' must be a mapping, got {type(node).__name__}.")
    if len(node) == 0:
        if is_root:
            return [], {}
        raise DocpipeError("Logical operator sub-expressions cannot be empty mappings.")

    chunk_clauses: list[dict[str, object]] = []
    manifest_spec: dict[str, object] = {}

    for key, raw_val in node.items():
        if not isinstance(key, str) or not key:
            raise DocpipeError(f"Filter keys must be non-empty strings, got {key!r}.")

        if key in RESERVED_FILTER_FIELDS:
            if reject_reserved_type:
                raise DocpipeError(
                    "Filter key 'type' is reserved internally and cannot be overridden "
                    "(retrieval always searches child records)."
                )
            chunk_clauses.extend(_normalize_chunk_field_pred(key, raw_val))
            continue

        if key in LOGICAL_OPS:
            if not _is_list_sequence(raw_val) or len(raw_val) == 0:
                raise DocpipeError(
                    f"Logical operator {key!r} requires a non-empty list of filter mappings."
                )
            sub_clauses: list[dict[str, object]] = []
            for item in raw_val:
                item_clauses, _ = _normalize_where_node(
                    item,
                    allow_manifest=False,
                    reject_reserved_type=reject_reserved_type,
                    is_root=False,
                )
                combined_item = _combine_and(item_clauses)
                if combined_item is None:
                    raise DocpipeError("Logical operator sub-expressions cannot be empty.")
                sub_clauses.append(combined_item)
            if len(sub_clauses) == 1:
                chunk_clauses.append(sub_clauses[0])
            else:
                chunk_clauses.append({key: sub_clauses})
            continue

        if key in MANIFEST_FILTER_FIELDS:
            if not allow_manifest:
                raise DocpipeError(
                    f"Manifest filter key {key!r} is only supported at top level and cannot "
                    "be nested inside '$and' or '$or'."
                )
            if key == "profile":
                manifest_spec["profile"] = _normalize_profile_pred(raw_val)
            else:
                manifest_spec[key] = _parse_iso_timestamp(
                    raw_val,
                    end_of_day_if_date=(key == "ingested_before"),
                    field=key,
                )
            continue

        if key in CHUNK_FILTER_FIELDS:
            chunk_clauses.extend(_normalize_chunk_field_pred(key, raw_val))
            continue

        raise DocpipeError(
            f"Unsupported filter key {key!r}. "
            f"Supported filter keys: {SUPPORTED_FILTER_KEYS_DISPLAY}."
        )

    return chunk_clauses, manifest_spec


def validate_where(
    where: Mapping[str, Any] | None,
    *,
    reject_reserved_type: bool = True,
) -> None:
    """Validate ``where`` filter syntax, allowed keys, operators, and field types upfront."""
    if where is None:
        return
    _normalize_where_node(
        where,
        allow_manifest=True,
        reject_reserved_type=reject_reserved_type,
        is_root=True,
    )


def _match_profile(source_profile: str, op_spec: object) -> bool:
    """Evaluate a normalized ``profile`` operator against a manifest source profile."""
    if not isinstance(op_spec, tuple) or len(op_spec) != 2:
        raise DocpipeError("Internal error: invalid normalized profile predicate.")
    op, target = op_spec
    norm = source_profile.strip().casefold()
    if op == "$eq":
        return isinstance(target, str) and norm == target
    if op == "$ne":
        return isinstance(target, str) and norm != target
    if op == "$in":
        return isinstance(target, list) and norm in target
    return isinstance(target, list) and norm not in target


def _filter_manifest_sources(
    manifest: Manifest,
    manifest_spec: dict[str, object],
) -> set[str]:
    """Return all committed source keys satisfying top-level manifest predicates."""
    prof_spec = manifest_spec.get("profile")
    after_dt = manifest_spec.get("ingested_after")
    before_dt = manifest_spec.get("ingested_before")

    matched: set[str] = set()
    for src_key, rec in manifest.sources.items():
        if prof_spec is not None and not _match_profile(rec.profile, prof_spec):
            continue
        if after_dt is not None or before_dt is not None:
            rec_dt = _parse_iso_timestamp(rec.ingested_at, field="ingested_at")
            if isinstance(after_dt, datetime) and rec_dt < after_dt:
                continue
            if isinstance(before_dt, datetime) and rec_dt > before_dt:
                continue
        matched.add(src_key)
    return matched


def resolve_retrieve_where(
    where: Mapping[str, Any] | None,
    manifest: Manifest,
    *,
    reject_reserved_type: bool = True,
) -> ResolvedWhere:
    """Validate ``where``, resolve top-level manifest attributes, and return chunk filter state."""
    if where is None:
        return ResolvedWhere(chunk_where=None, short_circuit_empty=False)

    chunk_clauses, manifest_spec = _normalize_where_node(
        where,
        allow_manifest=True,
        reject_reserved_type=reject_reserved_type,
        is_root=True,
    )
    if not chunk_clauses and not manifest_spec:
        return ResolvedWhere(chunk_where=None, short_circuit_empty=False)

    if not manifest_spec:
        return ResolvedWhere(chunk_where=_combine_and(chunk_clauses), short_circuit_empty=False)

    allowed_sources = _filter_manifest_sources(manifest, manifest_spec)
    remaining_clauses: list[dict[str, object]] = []
    for clause in chunk_clauses:
        if len(clause) == 1 and "source" in clause:
            source_op_dict = clause["source"]
            if isinstance(source_op_dict, dict) and len(source_op_dict) == 1:
                op, operand = next(iter(source_op_dict.items()))
                if op == "$eq" and isinstance(operand, str):
                    allowed_sources &= {operand}
                    continue
                if op == "$in" and isinstance(operand, list):
                    allowed_sources &= {str(x) for x in operand}
                    continue
                if op == "$ne" and isinstance(operand, str):
                    allowed_sources.discard(operand)
                    continue
                if op == "$nin" and isinstance(operand, list):
                    allowed_sources -= {str(x) for x in operand}
                    continue
        remaining_clauses.append(clause)

    if not allowed_sources:
        return ResolvedWhere(chunk_where=None, short_circuit_empty=True)

    sorted_sources = sorted(allowed_sources)
    source_clause: dict[str, object] = (
        {"source": {"$eq": sorted_sources[0]}}
        if len(sorted_sources) == 1
        else {"source": {"$in": sorted_sources}}
    )
    combined = _combine_and([source_clause, *remaining_clauses])
    return ResolvedWhere(chunk_where=combined, short_circuit_empty=False)


def build_chroma_child_where(where: Mapping[str, Any] | None) -> dict[str, object]:
    """Validate chunk predicates and bind them conjunctively with ``type='child'``."""
    if where is None:
        return {"type": "child"}
    chunk_clauses, manifest_spec = _normalize_where_node(
        where,
        allow_manifest=False,
        reject_reserved_type=False,
        is_root=True,
    )
    _ = manifest_spec
    if not chunk_clauses:
        return {"type": "child"}
    normalized = _combine_and(chunk_clauses)
    if normalized is None:
        return {"type": "child"}
    return {"$and": [{"type": "child"}, normalized]}


def _compile_column_op(col: str, op: str, operand: object) -> tuple[str, list[object]]:
    """Compile one allowlisted column comparison into parameterized SQL matching ChromaDB."""
    if col == "type":
        if op in {"$in", "$nin"}:
            if not isinstance(operand, list):
                raise DocpipeError(f"Operator {op!r} requires a list operand.")
            matched = "child" in operand
            keep = matched if op == "$in" else not matched
            return ("(1 = 1)" if keep else "(1 = 0)"), []
        val = str(operand)
        if op == "$eq":
            return ("(1 = 1)" if val == "child" else "(1 = 0)"), []
        if op == "$ne":
            return ("(1 = 1)" if val != "child" else "(1 = 0)"), []
        sql_op = _SQL_OP_MAP[op]
        return f"('child' {sql_op} ?)", [val]

    if col == "clause":
        if op == "$eq":
            if operand == "":
                return "(1 = 0)", []
            return "(clause IS NOT NULL AND clause != '' AND clause = ?)", [operand]
        if op == "$ne":
            return "(clause IS NULL OR clause = '' OR clause != ?)", [operand]
        if op == "$in":
            if not isinstance(operand, list):
                raise DocpipeError("Operator '$in' requires a list operand.")
            nonempty = [x for x in operand if x != ""]
            if not nonempty:
                return "(1 = 0)", []
            placeholders = ", ".join("?" for _ in nonempty)
            return f"(clause IS NOT NULL AND clause != '' AND clause IN ({placeholders}))", nonempty
        if op == "$nin":
            if not isinstance(operand, list):
                raise DocpipeError("Operator '$nin' requires a list operand.")
            nonempty = [x for x in operand if x != ""]
            if not nonempty:
                return "(1 = 1)", []
            placeholders = ", ".join("?" for _ in nonempty)
            return (
                f"(clause IS NULL OR clause = '' OR clause NOT IN ({placeholders}))",
                nonempty,
            )
        sql_op = _SQL_OP_MAP[op]
        return f"(clause IS NOT NULL AND clause != '' AND clause {sql_op} ?)", [operand]

    # Nullable (page) or required columns: absent NULL matches $ne / $nin identically to ChromaDB.
    if op == "$ne":
        return f"({col} IS NULL OR {col} != ?)", [operand]
    if op == "$nin":
        if not isinstance(operand, list):
            raise DocpipeError("Operator '$nin' requires a list operand.")
        placeholders = ", ".join("?" for _ in operand)
        return f"({col} IS NULL OR {col} NOT IN ({placeholders}))", list(operand)
    if op == "$in":
        if not isinstance(operand, list):
            raise DocpipeError("Operator '$in' requires a list operand.")
        placeholders = ", ".join("?" for _ in operand)
        return f"({col} IN ({placeholders}))", list(operand)
    sql_op = _SQL_OP_MAP[op]
    return f"({col} {sql_op} ?)", [operand]


def _compile_sql_node(node: Mapping[str, object]) -> tuple[str, list[object]]:
    """Compile a normalized chunk predicate dictionary into SQL ``WHERE`` fragment + params."""
    parts: list[str] = []
    params: list[object] = []

    for key, val in node.items():
        if key in {"$and", "$or"}:
            joiner = " AND " if key == "$and" else " OR "
            if not isinstance(val, list):
                raise DocpipeError(f"Logical operator {key!r} requires a list of predicates.")
            sub_sqls: list[str] = []
            for sub in val:
                if not isinstance(sub, Mapping):
                    raise DocpipeError(f"Logical operator {key!r} items must be mappings.")
                s_sql, s_params = _compile_sql_node(sub)
                sub_sqls.append(s_sql)
                params.extend(s_params)
            parts.append(f"({joiner.join(sub_sqls)})")
        else:
            if key not in CHUNK_FILTER_FIELDS and key != "type":
                raise DocpipeError(f"Unsupported lexical filter column {key!r}.")
            if not isinstance(val, Mapping):
                raise DocpipeError(f"Normalized predicate for {key!r} must be a mapping.")
            op, operand = next(iter(val.items()))
            col_sql, col_params = _compile_column_op(key, str(op), operand)
            parts.append(col_sql)
            params.extend(col_params)

    if len(parts) == 1:
        return parts[0], params
    return f"({' AND '.join(parts)})", params


def compile_lexical_where(where: Mapping[str, Any] | None) -> tuple[str, list[object]] | None:
    """Validate chunk predicates and compile a parameterized SQLite ``WHERE`` fragment."""
    if where is None:
        return None
    chunk_clauses, manifest_spec = _normalize_where_node(
        where,
        allow_manifest=False,
        reject_reserved_type=False,
        is_root=True,
    )
    _ = manifest_spec
    if not chunk_clauses:
        return None
    normalized = _combine_and(chunk_clauses)
    if normalized is None:
        return None
    return _compile_sql_node(normalized)


def _parse_strict_cli_int(key: str, raw_val: str) -> int:
    """Parse strict ASCII integer CLI values (rejecting floats, booleans, and text)."""
    if not _STRICT_INT_RE.match(raw_val):
        raise DocpipeError(f"Filter {key!r} requires a valid integer value, got {raw_val!r}.")
    return int(raw_val)


def parse_cli_where(raw_items: Sequence[str] | None) -> dict[str, object] | None:
    """Parse repeatable CLI ``--where KEY=VALUE`` options into a structured filter dict."""
    if not raw_items:
        return None

    aggregated: dict[str, list[str | int]] = {}
    seen_bounds: set[str] = set()

    for raw in raw_items:
        if "=" not in raw:
            raise DocpipeError(f"Malformed --where expression {raw!r}: expected KEY=VALUE format.")
        key, value = raw.split("=", 1)
        if not key or key != key.strip():
            raise DocpipeError(
                f"Malformed --where expression {raw!r}: filter key must be a non-empty identifier."
            )
        if key in RESERVED_FILTER_FIELDS:
            raise DocpipeError(
                "Filter key 'type' is reserved internally and cannot be overridden "
                "(retrieval always searches child records)."
            )
        if key not in ALL_PUBLIC_FILTER_FIELDS:
            raise DocpipeError(
                f"Unsupported filter key {key!r}. "
                f"Supported filter keys: {SUPPORTED_FILTER_KEYS_DISPLAY}."
            )
        if value == "" or not value.strip():
            raise DocpipeError(
                f"Malformed --where expression {raw!r}: value for {key!r} cannot be empty."
            )

        if key in {"ingested_after", "ingested_before"}:
            if key in seen_bounds:
                raise DocpipeError(f"Duplicate --where {key}=... filter cannot be specified twice.")
            _parse_iso_timestamp(
                value,
                end_of_day_if_date=(key == "ingested_before"),
                field=key,
            )
            seen_bounds.add(key)
            aggregated[key] = [value]
            continue

        typed_val: str | int = (
            _parse_strict_cli_int(key, value) if key in CHUNK_INT_FIELDS else value
        )
        bucket = aggregated.setdefault(key, [])
        if typed_val not in bucket:
            bucket.append(typed_val)

    result: dict[str, object] = {}
    for key, values in aggregated.items():
        if len(values) == 1:
            result[key] = values[0]
        else:
            result[key] = {"$in": list(values)}
    return result or None


__all__ = [
    "ALL_PUBLIC_FILTER_FIELDS",
    "CHUNK_FILTER_FIELDS",
    "CHUNK_INT_FIELDS",
    "CHUNK_STR_FIELDS",
    "COMPARISON_OPS",
    "LOGICAL_OPS",
    "MANIFEST_FILTER_FIELDS",
    "PROFILE_OPS",
    "RESERVED_FILTER_FIELDS",
    "ResolvedWhere",
    "build_chroma_child_where",
    "compile_lexical_where",
    "parse_cli_where",
    "resolve_retrieve_where",
    "validate_where",
]
