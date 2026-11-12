"""Embedded ChromaDB vector store adapter for Phase 1 writes and Phase 2 reads."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import chromadb

from docpipe_maestro.types import (
    ChunkMetadata,
    ChunkType,
    DocpipeError,
    EmbeddedChunk,
    RetrievedChunk,
)


def _serialize_metadata(meta: ChunkMetadata, parent_id: str | None) -> dict[str, str | int]:
    """Convert ChunkMetadata into Chroma-compatible flat scalar metadata (no None values)."""
    payload: dict[str, str | int] = {
        "type": meta["type"],
        "source": meta["source"],
        "doc_version": meta["doc_version"],
        "section": meta["section"],
        "chunk_index": int(meta["chunk_index"]),
        "embed_model": meta["embed_model"],
    }
    if meta["clause"] is not None:
        payload["clause"] = meta["clause"]
    if meta["page"] is not None:
        payload["page"] = int(meta["page"])
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return payload


def _deserialize_metadata(raw: dict[str, Any]) -> tuple[ChunkMetadata, str | None]:
    """Restore ChunkMetadata and parent_id from stored Chroma metadata."""
    chunk_type_val = str(raw["type"])
    chunk_type: ChunkType = "child" if chunk_type_val == "child" else "parent"
    meta: ChunkMetadata = {
        "type": chunk_type,
        "source": str(raw["source"]),
        "doc_version": str(raw["doc_version"]),
        "section": str(raw["section"]),
        "clause": str(raw["clause"]) if "clause" in raw and raw["clause"] is not None else None,
        "page": int(raw["page"]) if "page" in raw and raw["page"] is not None else None,
        "chunk_index": int(raw["chunk_index"]),
        "embed_model": str(raw["embed_model"]),
    }
    parent_id = (
        str(raw["parent_id"]) if "parent_id" in raw and raw["parent_id"] is not None else None
    )
    return meta, parent_id


class VectorStore:
    """ChromaDB PersistentClient wrapper enforcing cosine space and child-only search."""

    def __init__(self, persist_dir: Path, collection_name: str) -> None:
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))
        try:
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            raise DocpipeError(
                f"Invalid or unusable collection {self._collection_name!r}: {exc}"
            ) from exc

    def add_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Persist child and parent EmbeddedChunks into ChromaDB."""
        if not chunks:
            return
        ids = [c.id for c in chunks]
        embeddings = [c.vector for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [_serialize_metadata(c.metadata, c.parent_id) for c in chunks]
        self._collection.add(
            ids=ids,
            embeddings=embeddings,  # type: ignore[arg-type]
            documents=documents,
            metadatas=metadatas,  # type: ignore[arg-type]
        )

    def query_children(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        active_versions: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]:
        """Search child chunks exclusively (where={"type": "child"}) and return RetrievedChunks."""
        count = self._collection.count()
        if count == 0:
            return []

        n_results = min(max(top_k * 2, top_k), count) if active_versions else min(top_k, count)
        results = self._collection.query(
            query_embeddings=cast(Any, [query_vector]),
            n_results=n_results,
            where={"type": "child"},
            include=["documents", "metadatas", "distances", "embeddings"],
        )

        ids_list = (results.get("ids") or [[]])[0]
        docs_list = (results.get("documents") or [[]])[0]
        metas_list = (results.get("metadatas") or [[]])[0]
        dists_list = (results.get("distances") or [[]])[0]
        embeds_raw: Any = results.get("embeddings")
        embeds_list: Sequence[Any] = (
            embeds_raw[0] if embeds_raw is not None and len(embeds_raw) > 0 else []
        )

        retrieved: list[RetrievedChunk] = []
        for idx, cid in enumerate(ids_list):
            raw_meta = dict(metas_list[idx])
            meta, parent_id = _deserialize_metadata(raw_meta)
            if active_versions is not None:
                expected_ver = active_versions.get(meta["source"])
                if expected_ver is None or meta["doc_version"] != expected_ver:
                    continue
            distance = float(dists_list[idx])
            score = max(0.0, min(1.0, 1.0 - distance))
            vec = (
                [float(x) for x in embeds_list[idx]]
                if idx < len(embeds_list) and embeds_list[idx] is not None
                else []
            )
            retrieved.append(
                RetrievedChunk(
                    id=str(cid),
                    text=str(docs_list[idx]),
                    parent_id=parent_id,
                    metadata=meta,
                    vector=vec,
                    score=score,
                )
            )
            if len(retrieved) >= top_k:
                break
        return retrieved

    def get_by_ids(self, ids: Sequence[str]) -> list[EmbeddedChunk]:
        """Fetch records by exact IDs (used for parent expansion)."""
        if not ids:
            return []
        results = self._collection.get(
            ids=list(ids),
            include=["documents", "metadatas", "embeddings"],
        )
        return self._hydrate_get_results(results)

    def get_all_children(self) -> list[EmbeddedChunk]:
        """Fetch all child records in the collection (used by reindex)."""
        results = self._collection.get(
            where={"type": "child"},
            include=["documents", "metadatas", "embeddings"],
        )
        return self._hydrate_get_results(results)

    def get_all_parents(self) -> list[EmbeddedChunk]:
        """Fetch all parent records in the collection (used by reindex)."""
        results = self._collection.get(
            where={"type": "parent"},
            include=["documents", "metadatas", "embeddings"],
        )
        return self._hydrate_get_results(results)

    def delete_by_source(self, source: str) -> None:
        """Delete all child and parent records belonging to a source key."""
        self._collection.delete(where=cast(Any, {"source": {"$eq": source}}))

    def delete_stale_versions(self, source: str, active_doc_version: str) -> None:
        """Delete all records for source whose doc_version differs from active_doc_version."""
        self._collection.delete(
            where=cast(
                Any,
                {
                    "$and": [
                        {"source": {"$eq": source}},
                        {"doc_version": {"$ne": active_doc_version}},
                    ]
                },
            )
        )

    def reset_collection(self) -> None:
        """Drop and recreate the collection cleanly (used by reindex)."""
        self._client.delete_collection(name=self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def sweep_uncommitted(self, active_versions: dict[str, str]) -> None:
        """Purge any uncommitted staging records left over from an interrupted Phase 1 write."""
        if self._collection.count() == 0:
            return
        results = self._collection.get(include=["metadatas"])
        ids = results.get("ids") or []
        metas = results.get("metadatas") or []
        stale_ids: list[str] = []
        for cid, raw_meta in zip(ids, metas, strict=False):
            if raw_meta is None:
                continue
            source = str(raw_meta.get("source", ""))
            doc_version = str(raw_meta.get("doc_version", ""))
            if active_versions.get(source) != doc_version:
                stale_ids.append(str(cid))
        if stale_ids:
            self._collection.delete(ids=stale_ids)

    @staticmethod
    def _hydrate_get_results(results: Any) -> list[EmbeddedChunk]:
        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        embeds_raw = results.get("embeddings")
        embeds: Sequence[Any] = embeds_raw if embeds_raw is not None else []
        out: list[EmbeddedChunk] = []
        for idx, cid in enumerate(ids):
            raw_meta = dict(metas[idx])
            meta, parent_id = _deserialize_metadata(raw_meta)
            vec = (
                [float(x) for x in embeds[idx]]
                if idx < len(embeds) and embeds[idx] is not None
                else []
            )
            out.append(
                EmbeddedChunk(
                    id=str(cid),
                    text=str(docs[idx]),
                    parent_id=parent_id,
                    metadata=meta,
                    vector=vec,
                )
            )
        return out
