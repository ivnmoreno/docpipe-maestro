"""Built-in hybrid Searcher combining dense vector cosine and SQLite FTS5 BM25 via RRF."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro._stages import Embedder, Store
from docpipe_maestro.embedder import EMBEDDERS
from docpipe_maestro.manifest import check_model_lock, load_manifest
from docpipe_maestro.query.searcher import SEARCHERS
from docpipe_maestro.store import STORES, LexicalIndex
from docpipe_maestro.types import DocpipeError, RetrievedChunk

RRF_K = 60
DENSE_WEIGHT = 0.5
LEXICAL_WEIGHT = 0.5
MAX_RRF_SCORE = (DENSE_WEIGHT + LEXICAL_WEIGHT) / (RRF_K + 1)


@SEARCHERS.register("fts5_hybrid")
class Fts5HybridSearcher:
    """Hybrid searcher blending dense embeddings and SQLite FTS5 BM25 via RRF."""

    name = "fts5_hybrid"
    _supports_backend_selectors = True

    def __init__(self, *, embedder: str = "default", store: str = "default") -> None:
        self._embedder_key = embedder
        self._store_key = store

    def search(
        self,
        question: str,
        *,
        top_k: int,
        collection: str,
        persist_dir: str,
        embed_model: str,
        where: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        """Fuse dense vector and read-only SQLite FTS5 BM25 rankings using RRF."""
        persist_path = Path(persist_dir)
        manifest = load_manifest(persist_path, collection)
        check_model_lock(manifest, embed_model)
        if not manifest.sources or top_k <= 0:
            return []

        committed_children = sum(len(rec.chunk_ids) for rec in manifest.sources.values())
        lexical = LexicalIndex(persist_path, collection)
        if committed_children > 0 and (not lexical.exists() or not lexical.has_indexed_rows()):
            target_model = manifest.embed_model or embed_model
            raise DocpipeError(
                f"Collection {collection!r} does not have a lexical index yet. "
                f"Run 'docpipe-maestro reindex --model {target_model} "
                f"--collection {collection}' or re-ingest with --force to build it."
            )

        if not question.strip() or not any(ch.isalnum() for ch in question):
            return []

        candidate_k = max(top_k * 2, 20)
        active_versions = {k: v.doc_version for k, v in manifest.sources.items()}

        embedder_inst: Embedder = EMBEDDERS.resolve(self._embedder_key)()
        store_cls: type[Store] = STORES.resolve(self._store_key)
        query_vec = embedder_inst.embed_query(question, model=embed_model)
        store_obj: Store = store_cls(persist_path, collection)

        dense_hits = store_obj.query_children(
            query_vec,
            top_k=candidate_k,
            active_versions=active_versions,
            where=where,
            include_embeddings=False,
        )
        lexical_hits = lexical.search(
            question,
            top_k=candidate_k,
            active_versions=active_versions,
        )

        rrf_scores: dict[str, float] = {}
        chunks_by_id: dict[str, RetrievedChunk] = {}

        for rank, chunk in enumerate(dense_hits, start=1):
            rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + DENSE_WEIGHT / (RRF_K + rank)
            chunks_by_id.setdefault(chunk.id, chunk)

        for rank, chunk in enumerate(lexical_hits, start=1):
            rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + LEXICAL_WEIGHT / (RRF_K + rank)
            chunks_by_id.setdefault(chunk.id, chunk)

        fused: list[RetrievedChunk] = []
        for cid, raw_rrf in rrf_scores.items():
            base = chunks_by_id[cid]
            norm_score = max(0.0, min(1.0, raw_rrf / MAX_RRF_SCORE))
            fused.append(
                RetrievedChunk(
                    id=base.id,
                    text=base.text,
                    parent_id=base.parent_id,
                    metadata=base.metadata,
                    vector=[],
                    score=norm_score,
                )
            )
        fused.sort(key=lambda item: (-item.score, item.id))
        return fused[:top_k]
