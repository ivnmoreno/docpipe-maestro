"""Collocated SQLite FTS5 lexical index shared between Phase 1 writes and Phase 2 reads."""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path

from docpipe_maestro.manifest import ensure_private_dir, validate_collection_name
from docpipe_maestro.types import (
    Chunk,
    ChunkMetadata,
    DocpipeError,
    EmbeddedChunk,
    RetrievedChunk,
)

_FTS_TOKEN_RE = re.compile(r"[^\W]+(?:[.\-:/][^\W]+)*")
_MAX_QUERY_TERMS = 64

_CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    parent_id UNINDEXED,
    source UNINDEXED,
    doc_version UNINDEXED,
    section,
    clause,
    page UNINDEXED,
    chunk_index UNINDEXED,
    embed_model UNINDEXED,
    content,
    tokenize='unicode61'
)
"""

_INSERT_FTS_SQL = """
INSERT INTO chunks_fts (
    chunk_id,
    parent_id,
    source,
    doc_version,
    section,
    clause,
    page,
    chunk_index,
    embed_model,
    content
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def sanitize_fts_query(query: str) -> str:
    """Convert raw user query text into a safe, OR-joined FTS5 MATCH expression.

    Preserves compound technical identifiers (e.g., ``SEV-1``, ``AES-256``,
    ``Clause 1.2``, ``HTTP/2``) by quoting extracted tokens individually so
    punctuation, unbalanced quotes, and reserved operators (``AND``, ``OR``,
    ``NOT``) never trigger SQLite FTS5 syntax errors.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for raw_token in _FTS_TOKEN_RE.findall(query):
        normalized = raw_token.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        escaped = raw_token.replace('"', '""')
        terms.append(f'"{escaped}"')
        if len(terms) >= _MAX_QUERY_TERMS:
            break
    return " OR ".join(terms)


def _resolve_lexical_path(persist_dir: Path, collection_name: str) -> Path:
    """Return validated, path-contained SQLite path for a collection's FTS5 DB."""
    safe_name = validate_collection_name(collection_name)
    lexical_dir = persist_dir / "lexical"
    candidate = lexical_dir / f"{safe_name}.db"
    if not candidate.resolve().is_relative_to(lexical_dir.resolve()):
        raise DocpipeError(
            f"Invalid or unusable collection {collection_name!r}: "
            "resolves outside lexical directory"
        )
    return candidate


class LexicalIndex:
    """Per-collection collocated SQLite FTS5 full-text index for committed child chunks."""

    def __init__(self, persist_dir: Path, collection_name: str) -> None:
        self._persist_dir = Path(persist_dir)
        self._collection_name = collection_name
        self._db_path = _resolve_lexical_path(self._persist_dir, collection_name)
        self._lexical_dir = self._db_path.parent

    @property
    def db_path(self) -> Path:
        """Path to the collocated SQLite FTS5 database file."""
        return self._db_path

    def exists(self) -> bool:
        """Return ``True`` if the collocated SQLite database file exists on disk."""
        return self._db_path.is_file()

    @contextlib.contextmanager
    def _open_rw(self) -> Iterator[sqlite3.Connection]:
        """Open a writable SQLite connection, ensuring private permissions and schema."""
        ensure_private_dir(self._persist_dir)
        ensure_private_dir(self._lexical_dir)
        try:
            conn = sqlite3.connect(self._db_path)
        except sqlite3.Error as exc:
            raise DocpipeError(
                f"Failed to open lexical index for {self._collection_name!r}: {exc}"
            ) from exc
        with contextlib.suppress(OSError):
            os.chmod(self._db_path, 0o600)
        try:
            with conn:
                conn.execute(_CREATE_FTS_SQL)
            yield conn
        except sqlite3.Error as exc:
            raise DocpipeError(
                f"Lexical index write error for {self._collection_name!r}: {exc}"
            ) from exc
        finally:
            conn.close()

    @contextlib.contextmanager
    def _open_ro(self) -> Iterator[sqlite3.Connection]:
        """Open a strict SQLite URI read-only connection (never creates files)."""
        uri = f"{self._db_path.resolve().as_uri()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise DocpipeError(
                f"Failed to open lexical index read-only for {self._collection_name!r}: {exc}"
            ) from exc
        try:
            yield conn
        finally:
            conn.close()

    def has_indexed_rows(self) -> bool:
        """Return ``True`` if ``chunks_fts`` exists and contains at least one row."""
        if not self.exists():
            return False
        with self._open_ro() as conn:
            try:
                table_row = conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'chunks_fts' LIMIT 1"
                ).fetchone()
                if table_row is None:
                    return False
                has_row = conn.execute("SELECT 1 FROM chunks_fts LIMIT 1").fetchone()
                return has_row is not None
            except sqlite3.Error as exc:
                raise DocpipeError(
                    f"Corrupted or unreadable lexical index for {self._collection_name!r}: {exc}"
                ) from exc

    def add_chunks(self, chunks: Sequence[Chunk | EmbeddedChunk]) -> None:
        """Idempotently stage committed or uncommitted child chunks into FTS5."""
        children = [c for c in chunks if c.metadata["type"] == "child"]
        with self._open_rw() as conn:
            if not children:
                return
            delete_keys = [(c.id,) for c in children]
            rows = [
                (
                    c.id,
                    str(c.parent_id or ""),
                    c.metadata["source"],
                    c.metadata["doc_version"],
                    c.metadata["section"],
                    c.metadata["clause"] or "",
                    c.metadata["page"],
                    c.metadata["chunk_index"],
                    c.metadata["embed_model"],
                    c.text,
                )
                for c in children
            ]
            with conn:
                conn.executemany("DELETE FROM chunks_fts WHERE chunk_id = ?", delete_keys)
                conn.executemany(_INSERT_FTS_SQL, rows)

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        active_versions: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        """Execute a read-only BM25 lexical search over committed child chunks."""
        if top_k <= 0 or not self.exists():
            return []
        fts_query = sanitize_fts_query(query)
        if not fts_query:
            return []

        fetch_limit = max(top_k * 4, top_k) if active_versions is not None else top_k
        sql = (
            "SELECT chunk_id, parent_id, source, doc_version, section, clause, "
            "page, chunk_index, embed_model, content "
            "FROM chunks_fts "
            "WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts, 1.5, 2.0, 1.0) ASC, chunk_id ASC "
            "LIMIT ?"
        )
        with self._open_ro() as conn:
            try:
                rows = conn.execute(sql, (fts_query, fetch_limit)).fetchall()
            except sqlite3.Error as exc:
                raise DocpipeError(
                    f"Lexical search failed for {self._collection_name!r}: {exc}"
                ) from exc

        results: list[RetrievedChunk] = []
        for row in rows:
            (
                chunk_id,
                parent_id,
                source,
                doc_version,
                section,
                clause,
                page,
                chunk_index,
                embed_model,
                content,
            ) = row
            source_str = str(source)
            doc_version_str = str(doc_version)
            if active_versions is not None:
                expected_ver = active_versions.get(source_str)
                if expected_ver is None or doc_version_str != expected_ver:
                    continue

            clause_val = None if clause in (None, "") else str(clause)
            page_val = None if page is None else int(page)
            meta: ChunkMetadata = {
                "type": "child",
                "source": source_str,
                "doc_version": doc_version_str,
                "section": str(section),
                "clause": clause_val,
                "page": page_val,
                "chunk_index": int(chunk_index),
                "embed_model": str(embed_model),
            }
            rank_score = 1.0 / (len(results) + 1)
            results.append(
                RetrievedChunk(
                    id=str(chunk_id),
                    text=str(content),
                    parent_id=str(parent_id),
                    metadata=meta,
                    vector=[],
                    score=rank_score,
                )
            )
            if len(results) >= top_k:
                break
        return results

    def delete_by_source(self, source: str) -> None:
        """Delete all lexical entries belonging to ``source``."""
        if not self.exists():
            return
        with self._open_rw() as conn, conn:
            conn.execute("DELETE FROM chunks_fts WHERE source = ?", (source,))

    def delete_stale_versions(self, source: str, active_doc_version: str) -> None:
        """Delete prior ``doc_version`` lexical rows for ``source`` after commit."""
        if not self.exists():
            return
        with self._open_rw() as conn, conn:
            conn.execute(
                "DELETE FROM chunks_fts WHERE source = ? AND doc_version != ?",
                (source, active_doc_version),
            )

    def sweep_uncommitted(self, active_versions: dict[str, str]) -> int:
        """Purge uncommitted or orphaned lexical records and return deleted count."""
        if not self.exists():
            return 0
        with self._open_rw() as conn:
            rows = conn.execute("SELECT rowid, source, doc_version FROM chunks_fts").fetchall()
            stale_rowids = [
                (int(rowid),)
                for rowid, source, doc_version in rows
                if active_versions.get(str(source)) != str(doc_version)
            ]
            if stale_rowids:
                with conn:
                    conn.executemany("DELETE FROM chunks_fts WHERE rowid = ?", stale_rowids)
            return len(stale_rowids)

    def reset(self) -> None:
        """Drop and recreate ``chunks_fts`` cleanly (used by reindex)."""
        with self._open_rw() as conn, conn:
            conn.execute("DROP TABLE IF EXISTS chunks_fts")
            conn.execute(_CREATE_FTS_SQL)
