"""Built-in dense semantic vector Searcher implementation ("default")."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro._stages import Embedder, Store
from docpipe_maestro.embedder import EMBEDDERS
from docpipe_maestro.manifest import check_model_lock, load_manifest
from docpipe_maestro.query.searcher import SEARCHERS
from docpipe_maestro.store import STORES
from docpipe_maestro.types import RetrievedChunk


@SEARCHERS.register("default")
class DenseSearcher:
    """Default pure dense vector searcher over committed child chunks."""

    name = "default"
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
        """Execute cosine vector search against committed child chunks."""
        persist_path = Path(persist_dir)
        manifest = load_manifest(persist_path, collection)
        check_model_lock(manifest, embed_model)
        if not manifest.sources or top_k <= 0:
            return []

        embedder_inst: Embedder = EMBEDDERS.resolve(self._embedder_key)()
        store_cls: type[Store] = STORES.resolve(self._store_key)
        query_vec = embedder_inst.embed_query(question, model=embed_model)
        store_obj: Store = store_cls(persist_path, collection)
        active_versions = {k: v.doc_version for k, v in manifest.sources.items()}
        return store_obj.query_children(
            query_vec,
            top_k=top_k,
            active_versions=active_versions,
            where=where,
            include_embeddings=False,
        )
