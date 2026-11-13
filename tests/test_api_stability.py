"""Public API surface and signature stability tests for docpipe-maestro."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import docpipe_maestro as root
from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_PERSIST_DIR,
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
    assert len(root.__all__) == 33
    for name in EXPECTED_ALL:
        assert hasattr(root, name), f"Missing top-level export: {name}"
    assert issubclass(root.RegistryError, root.DocpipeError)


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
    ]
    assert _params_info(root.answer) == expected_answer_params
    assert _params_info(root.answer_detailed) == expected_answer_params


def test_legacy_module_compatibility_reexports_intact() -> None:
    from docpipe_maestro._stages import Embedder, Store
    from docpipe_maestro.embedder import (
        EMBEDDERS,
        _is_loopback_host,
        _item_field,
        embed_query,
        embed_texts,
        prepare_litellm,
        raise_litellm_error,
        validate_api_base,
    )
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

    assert ParsedClause is TypesClause
    assert ParsedSection is TypesSection
    assert ParsedDocument is TypesDocument
    assert Phase1Embedder is Embedder
    assert Phase1Store is Store
    assert VectorStore is ChromaStore
    assert issubclass(RegistryError, root.DocpipeError)
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
