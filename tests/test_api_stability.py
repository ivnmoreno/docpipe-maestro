"""Public API surface and signature stability tests for docpipe-maestro."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from typing import Any

import docpipe_maestro as root
from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_PERSIST_DIR,
    DEFAULT_RERANK_TOP_N,
    DEFAULT_TOP_K,
)
from docpipe_maestro.embedder import DEFAULT_REQUEST_TIMEOUT

EXPECTED_ALL = {
    "Chunk",
    "CollectionStatus",
    "DocpipeError",
    "EmbeddedChunk",
    "GenerationResult",
    "IngestResult",
    "MissingCredentialError",
    "MissingExtraError",
    "ModelMismatchError",
    "PiiBlockedError",
    "PiiPolicy",
    "RegistryError",
    "RetrievedChunk",
    "SourceRecord",
    "SyncResult",
    "UnsupportedFormatError",
    "__version__",
    "answer",
    "answer_detailed",
    "build_chat_messages",
    "build_prompt",
    "ingest",
    "register_chunker",
    "register_cleaner",
    "register_embedder",
    "register_enricher",
    "register_parser",
    "register_pii_recognizer",
    "register_reranker",
    "register_searcher",
    "register_store",
    "reindex",
    "remove",
    "retrieve",
    "status",
    "sync",
}


def _params_info(fn: Callable[..., Any]) -> list[tuple[str, inspect._ParameterKind, Any]]:
    sig = inspect.signature(fn)
    return [(name, p.kind, p.default) for name, p in sig.parameters.items()]


def test_top_level_all_exports_and_exception_hierarchy() -> None:
    assert set(root.__all__) == EXPECTED_ALL
    assert len(root.__all__) == 36
    for name in EXPECTED_ALL:
        assert hasattr(root, name), f"Missing top-level export: {name}"
    assert callable(root.register_pii_recognizer)
    assert issubclass(root.RegistryError, root.DocpipeError)
    assert issubclass(root.PiiBlockedError, root.DocpipeError)


def test_public_callable_signatures_and_keyword_only_selectors() -> None:
    pos_kw = inspect.Parameter.POSITIONAL_OR_KEYWORD
    kw_only = inspect.Parameter.KEYWORD_ONLY
    empty = inspect.Parameter.empty

    assert _params_info(root.ingest) == [
        ("path", pos_kw, empty),
        ("profile", kw_only, "DEFAULT"),
        ("collection", kw_only, DEFAULT_COLLECTION),
        ("persist_dir", kw_only, DEFAULT_PERSIST_DIR),
        ("embed_model", kw_only, DEFAULT_EMBED_MODEL),
        ("force", kw_only, False),
        ("cleaner", kw_only, "default"),
        ("chunker", kw_only, "default"),
        ("embedder", kw_only, "default"),
        ("store", kw_only, "default"),
        ("pii_policy", kw_only, None),
        ("local_only", kw_only, False),
    ]
    assert _params_info(root.sync) == [
        ("directory", pos_kw, empty),
        ("profile", kw_only, "DEFAULT"),
        ("collection", kw_only, DEFAULT_COLLECTION),
        ("persist_dir", kw_only, DEFAULT_PERSIST_DIR),
        ("embed_model", kw_only, DEFAULT_EMBED_MODEL),
        ("cleaner", kw_only, "default"),
        ("chunker", kw_only, "default"),
        ("embedder", kw_only, "default"),
        ("store", kw_only, "default"),
        ("pii_policy", kw_only, None),
        ("local_only", kw_only, False),
        ("dry_run", kw_only, False),
    ]
    assert _params_info(root.remove) == [
        ("source", pos_kw, empty),
        ("collection", kw_only, DEFAULT_COLLECTION),
        ("persist_dir", kw_only, DEFAULT_PERSIST_DIR),
        ("store", kw_only, "default"),
    ]
    assert _params_info(root.status) == [
        ("collection", kw_only, DEFAULT_COLLECTION),
        ("persist_dir", kw_only, DEFAULT_PERSIST_DIR),
        ("store", kw_only, "default"),
    ]
    assert _params_info(root.reindex) == [
        ("embed_model", kw_only, empty),
        ("collection", kw_only, DEFAULT_COLLECTION),
        ("persist_dir", kw_only, DEFAULT_PERSIST_DIR),
        ("embedder", kw_only, "default"),
        ("store", kw_only, "default"),
        ("local_only", kw_only, False),
        ("dry_run", kw_only, False),
    ]
    assert _params_info(root.retrieve) == [
        ("question", pos_kw, empty),
        ("collection", kw_only, DEFAULT_COLLECTION),
        ("persist_dir", kw_only, DEFAULT_PERSIST_DIR),
        ("embed_model", kw_only, DEFAULT_EMBED_MODEL),
        ("top_k", kw_only, DEFAULT_TOP_K),
        ("threshold", kw_only, None),
        ("expand_parent", kw_only, True),
        ("follow_crossrefs", kw_only, True),
        ("embedder", kw_only, "default"),
        ("store", kw_only, "default"),
        ("searcher", kw_only, "default"),
        ("rerank", kw_only, False),
        ("reranker", kw_only, "cross_encoder"),
        ("rerank_top_n", kw_only, DEFAULT_RERANK_TOP_N),
        ("local_only", kw_only, False),
        ("where", kw_only, None),
    ]
    assert _params_info(root.build_prompt) == [
        ("question", pos_kw, empty),
        ("sections", pos_kw, empty),
    ]
    assert _params_info(root.build_chat_messages) == [
        ("question", pos_kw, empty),
        ("sections", pos_kw, empty),
    ]
    expected_answer_params = [
        ("prompt", pos_kw, empty),
        ("model", kw_only, DEFAULT_GENERATION_MODEL),
        ("api_base", kw_only, None),
        ("has_context", kw_only, True),
        ("temperature", kw_only, None),
        ("max_tokens", kw_only, None),
        ("timeout", kw_only, DEFAULT_REQUEST_TIMEOUT),
        ("model_kwargs", kw_only, None),
        ("fail_on_truncation", kw_only, False),
        ("pii_policy", kw_only, None),
        ("local_only", kw_only, False),
    ]
    assert _params_info(root.answer_detailed) == expected_answer_params
    assert _params_info(root.answer) == [
        *expected_answer_params,
        ("stream", kw_only, False),
    ]

    from docpipe_maestro.eval import evaluate

    assert _params_info(evaluate) == [
        ("fixture", pos_kw, empty),
        ("collection", kw_only, None),
        ("persist_dir", kw_only, DEFAULT_PERSIST_DIR),
        ("embed_model", kw_only, DEFAULT_EMBED_MODEL),
        ("k_values", kw_only, (1, 3, 5, 10)),
        ("expand_parent", kw_only, True),
        ("follow_crossrefs", kw_only, True),
        ("threshold", kw_only, None),
        ("embedder", kw_only, "default"),
        ("store", kw_only, "default"),
        ("searcher", kw_only, "default"),
        ("rerank", kw_only, False),
        ("reranker", kw_only, "cross_encoder"),
        ("rerank_top_n", kw_only, DEFAULT_RERANK_TOP_N),
        ("local_only", kw_only, False),
        ("where", kw_only, None),
        ("retrieve_kwargs", inspect.Parameter.VAR_KEYWORD, empty),
    ]


def test_legacy_module_compatibility_reexports_intact() -> None:
    from docpipe_maestro._stages import Embedder, Store
    from docpipe_maestro.embedder import (
        EMBEDDERS,
        _is_loopback_host,
        _item_field,
        embed_query,
        embed_texts,
        estimate_embedding_cost,
        prepare_litellm,
        raise_litellm_error,
        validate_api_base,
    )
    from docpipe_maestro.ingest import ReindexPreview
    from docpipe_maestro.ingest.chunker import CHUNKERS, chunk_document, estimate_tokens
    from docpipe_maestro.ingest.clean import CLEANERS, clean_document, clean_text
    from docpipe_maestro.ingest.crossrefs import (
        extract_doc_crossrefs,
        index_section_targets,
        match_source_key,
        resolve_crossrefs,
        truncate_excerpt,
    )
    from docpipe_maestro.ingest.intake import (
        PARSERS,
        SUPPORTED_EXTENSIONS,
        ParsedClause,
        ParsedDocument,
        ParsedSection,
        detect_format,
        parse_file,
    )
    from docpipe_maestro.ingest.stages import (
        Chunker,
        Cleaner,
        Enricher,
        Parser,
    )
    from docpipe_maestro.ingest.stages import (
        Embedder as Phase1Embedder,
    )
    from docpipe_maestro.ingest.stages import (
        Store as Phase1Store,
    )
    from docpipe_maestro.store import STORES, ChromaStore, VectorStore
    from docpipe_maestro.types import (
        IngestContext,
        RegistryError,
        SyncResult,
    )
    from docpipe_maestro.types import (
        ParsedClause as TypesClause,
    )
    from docpipe_maestro.types import (
        ParsedDocument as TypesDocument,
    )
    from docpipe_maestro.types import (
        ParsedSection as TypesSection,
    )
    from docpipe_maestro.types import (
        ReindexPreview as TypesReindexPreview,
    )

    assert ParsedClause is TypesClause
    assert ParsedSection is TypesSection
    assert ParsedDocument is TypesDocument
    assert ReindexPreview is TypesReindexPreview
    assert Phase1Embedder is Embedder
    assert Phase1Store is Store
    assert VectorStore is ChromaStore
    assert issubclass(RegistryError, root.DocpipeError)

    default_sync_res = SyncResult(
        collection="c",
        embed_model="m",
        added=[],
        updated=[],
        skipped=[],
        removed=[],
    )
    assert default_sync_res.dry_run is False
    assert default_sync_res.estimated_children == 0
    assert default_sync_res.estimated_parents == 0
    assert default_sync_res.estimated_tokens == 0
    assert default_sync_res.estimated_cost_usd is None
    assert default_sync_res.to_dict()["dry_run"] is False

    preview_obj = ReindexPreview(
        collection="c",
        embed_model="m2",
        previous_embed_model="m1",
        total_sources=1,
        total_children=2,
        total_parents=1,
        estimated_tokens=10,
        estimated_cost_usd=0.0,
    )
    assert preview_obj.dry_run is True
    assert preview_obj.to_dict()["embed_model"] == "m2"
    from docpipe_maestro.query.answer import _RESERVED_MODEL_KWARGS, EMPTY_CONTEXT_REFUSAL

    assert "stream" in _RESERVED_MODEL_KWARGS
    assert root.answer("Q?", has_context=False) == EMPTY_CONTEXT_REFUSAL
    stream_it = root.answer("Q?", has_context=False, stream=True)
    assert isinstance(stream_it, Iterator)
    assert list(stream_it) == [EMPTY_CONTEXT_REFUSAL]

    assert all(
        obj is not None
        for obj in [
            PARSERS,
            SUPPORTED_EXTENSIONS,
            detect_format,
            parse_file,
            CLEANERS,
            clean_text,
            clean_document,
            CHUNKERS,
            chunk_document,
            estimate_tokens,
            resolve_crossrefs,
            extract_doc_crossrefs,
            index_section_targets,
            match_source_key,
            truncate_excerpt,
            EMBEDDERS,
            embed_texts,
            embed_query,
            estimate_embedding_cost,
            prepare_litellm,
            raise_litellm_error,
            validate_api_base,
            _item_field,
            _is_loopback_host,
            STORES,
            Parser,
            Cleaner,
            Enricher,
            Chunker,
            IngestContext,
        ]
    )
