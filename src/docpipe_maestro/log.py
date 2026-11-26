"""Structured JSON telemetry, stage timing, and correlation ID helpers."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

LOGGER_NAME = "docpipe_maestro"
RESERVED_ENVELOPE_KEYS = frozenset({"ts", "level", "logger", "msg", "correlation_id"})

__all__ = [
    "LOGGER_NAME",
    "RESERVED_ENVELOPE_KEYS",
    "JsonFormatter",
    "TextFormatter",
    "correlation_id",
    "get_correlation_id",
    "get_logger",
    "stage_event",
]

_CORRELATION_ID: ContextVar[str | None] = ContextVar("docpipe_correlation_id", default=None)


def _json_default(obj: Any) -> Any:
    """Deterministically coerce common non-JSON helper objects for telemetry payloads."""
    if isinstance(obj, os.PathLike):
        return os.fspath(obj)
    if isinstance(obj, (set, frozenset, tuple)):
        return list(obj)
    return str(obj)


def _extract_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Return nested stage/event attributes without touching top-level envelope keys."""
    raw_fields = getattr(record, "docpipe_fields", None)
    return dict(raw_fields) if isinstance(raw_fields, Mapping) else {}


def _extract_correlation_id(record: logging.LogRecord) -> str | None:
    """Return correlation ID attached to ``record`` or active in ``ContextVar``."""
    rec_cid = getattr(record, "correlation_id", None)
    if isinstance(rec_cid, str) and rec_cid:
        return rec_cid
    return get_correlation_id()


def _format_text_value(value: Any) -> str:
    """Format a scalar/helper field cleanly for single-line stderr text logs."""
    if isinstance(value, os.PathLike):
        return json.dumps(os.fspath(value))
    if isinstance(value, str):
        return json.dumps(value) if (" " in value or "=" in value or not value) else value
    if isinstance(value, (bool, int, float)) or value is None:
        return str(value)
    return json.dumps(value, default=_json_default)


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON with fixed envelope keys and nested ``fields``.

    Raw ``exc_info`` / ``exc_text`` tracebacks are intentionally omitted so
    exception messages and local stack variables cannot leak secrets or PII.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as a single-line JSON object string."""
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": _extract_correlation_id(record),
            "fields": _extract_fields(record),
        }
        return json.dumps(payload, default=_json_default)


class TextFormatter(logging.Formatter):
    """Render concise human-readable diagnostic lines to stderr without tracebacks.

    Raw ``exc_info`` / ``exc_text`` tracebacks are excluded identically to
    ``JsonFormatter`` so standalone ``--log-level`` mode cannot leak secrets.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as a single-line human-readable stderr string."""
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        cid = _extract_correlation_id(record) or "-"
        base = f"{ts} {record.levelname} [{cid}] {record.name}: {record.getMessage()}"
        fields = _extract_fields(record)
        if not fields:
            return base
        pairs = " ".join(f"{k}={_format_text_value(v)}" for k, v in fields.items())
        return f"{base} {pairs}"


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """Return a logger under ``docpipe_maestro`` with a passive ``NullHandler`` on root pkg.

    Never attaches output stream handlers, alters ``logging.getLogger()`` (root),
    or forces logger levels on library loggers.
    """
    pkg_logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(handler, logging.NullHandler) for handler in pkg_logger.handlers):
        pkg_logger.addHandler(logging.NullHandler())

    if not name or name == LOGGER_NAME:
        return pkg_logger
    resolved = name if name.startswith(f"{LOGGER_NAME}.") else f"{LOGGER_NAME}.{name}"
    return logging.getLogger(resolved)


def get_correlation_id() -> str | None:
    """Return the active execution-context correlation ID, or ``None`` when unset."""
    return _CORRELATION_ID.get()


@contextmanager
def correlation_id(value: str | None = None) -> Iterator[str]:
    """Bind an async-safe, thread-safe UUID correlation ID for the active scope.

    When ``value`` is ``None`` and an outer correlation ID is already active,
    reuses that active identifier so nested pipeline operations share one trace.
    """
    if value is not None:
        stripped = value.strip()
        if not stripped:
            raise ValueError("correlation_id value must not be empty.")
        resolved = stripped
    else:
        current = _CORRELATION_ID.get()
        resolved = current if current is not None else str(uuid.uuid4())

    token = _CORRELATION_ID.set(resolved)
    try:
        yield resolved
    finally:
        _CORRELATION_ID.reset(token)


def _emit_stage_end(
    logger: logging.Logger,
    stage: str,
    *,
    level: int,
    duration_ms: float,
    status: str,
    fields: Mapping[str, Any] | None = None,
    error_type: str | None = None,
) -> None:
    """Emit a ``stage.end`` record only when ``logger`` is enabled for ``level``."""
    if not logger.isEnabledFor(level):
        return
    payload_fields: dict[str, Any] = dict(fields) if fields is not None else {}
    payload_fields["stage"] = stage
    payload_fields["status"] = status
    payload_fields["duration_ms"] = round(max(0.0, duration_ms), 3)
    if error_type is not None:
        payload_fields["error_type"] = error_type
    logger.log(
        level,
        "stage.end",
        extra={
            "docpipe_fields": payload_fields,
            "correlation_id": get_correlation_id(),
        },
    )


@contextmanager
def stage_event(
    logger: logging.Logger,
    stage: str,
    *,
    log_level: int = logging.INFO,
    **fields: Any,
) -> Iterator[dict[str, Any]]:
    """Measure elapsed milliseconds and emit a correlated ``stage.end`` log event.

    Yields a mutable ``fields`` dictionary so callers can populate safe output
    counts discovered during execution before exit. Short-circuits ``LogRecord``
    creation cleanly when ``logger`` is not enabled for the target severity.
    """
    event_fields: dict[str, Any] = dict(fields)
    t0 = time.perf_counter()
    try:
        yield event_fields
    except Exception as exc:
        _emit_stage_end(
            logger,
            stage,
            level=logging.ERROR,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            status="error",
            fields=event_fields,
            error_type=type(exc).__name__,
        )
        raise
    _emit_stage_end(
        logger,
        stage,
        level=log_level,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        status="ok",
        fields=event_fields,
    )
