"""Lazy stdlib-only SQLite reader for zero-byte read-only ChromaDB previews."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_PREVIEW_QUERY = """
SELECT
    MAX(CASE WHEN em.key = 'source' THEN em.string_value END) AS source,
    MAX(CASE WHEN em.key = 'doc_version' THEN em.string_value END) AS doc_version,
    MAX(CASE WHEN em.key = 'type' THEN em.string_value END) AS chunk_type,
    MAX(CASE WHEN em.key = 'chroma:document' THEN em.string_value END) AS document_text
FROM collections c
JOIN segments s ON s.collection = c.id AND s.scope = 'METADATA'
JOIN embeddings e ON e.segment_id = s.id
JOIN embedding_metadata em ON em.id = e.id
WHERE c.name = ?
GROUP BY e.id
ORDER BY e.id
"""


def _execute_preview_query(uri: str, collection_name: str) -> list[tuple[Any, ...]]:
    """Open a read-only SQLite URI connection and fetch grouped metadata rows."""
    conn = sqlite3.connect(uri, uri=True)
    try:
        return conn.execute(_PREVIEW_QUERY, (collection_name,)).fetchall()
    finally:
        conn.close()


def read_chroma_active_preview_rows(
    persist_dir: Path,
    collection_name: str,
    active_versions: Mapping[str, str],
) -> tuple[list[str], int]:
    """Read active committed child texts and parent count from ``chroma.sqlite3``.

    Opens the database using a strict read-only SQLite URI (``?mode=ro``),
    falling back to ``?mode=ro&immutable=1`` only if a read-only persistence
    directory prevents lock/WAL sidecar creation. Never creates or modifies
    files on disk. Returns ``([], 0)`` when ``chroma.sqlite3`` or the target
    collection is absent.
    """
    db_path = Path(persist_dir) / "chroma.sqlite3"
    if not db_path.exists() or not active_versions:
        return [], 0

    resolved_uri = db_path.resolve().as_uri()
    try:
        rows = _execute_preview_query(f"{resolved_uri}?mode=ro", collection_name)
    except sqlite3.OperationalError:
        rows = _execute_preview_query(f"{resolved_uri}?mode=ro&immutable=1", collection_name)

    child_texts: list[str] = []
    parent_count = 0
    for source, doc_version, chunk_type, document_text in rows:
        if not isinstance(source, str) or not isinstance(doc_version, str):
            continue
        if active_versions.get(source) != doc_version:
            continue
        if chunk_type == "child":
            child_texts.append(document_text if isinstance(document_text, str) else "")
        elif chunk_type == "parent":
            parent_count += 1
    return child_texts, parent_count
