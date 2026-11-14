"""Tests for Registry[T], custom parser routing, stage protocols, and end-to-end plugins."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import (
    ingest,
    register_chunker,
    register_cleaner,
    register_embedder,
    register_enricher,
    register_parser,
    register_reranker,
    register_searcher,
    register_store,
    reindex,
    remove,
    retrieve,
    status,
    sync,
)
from docpipe_maestro._registry import Registry, RegistryError
from docpipe_maestro._resolve import resolve_parser
from docpipe_maestro._stages import Embedder, Store
from docpipe_maestro.embedder import EMBEDDERS
from docpipe_maestro.ingest.chunker import CHUNKERS
from docpipe_maestro.ingest.clean import CLEANERS
from docpipe_maestro.ingest.enricher import ENRICHERS
from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.stages import Chunker, Cleaner, Enricher, Parser
from docpipe_maestro.query.reranker import RERANKERS
from docpipe_maestro.query.searcher import SEARCHERS
from docpipe_maestro.query.stages import Reranker, Searcher
from docpipe_maestro.store import STORES, VectorStore
from docpipe_maestro.types import (
    Chunk,
    ChunkingProfile,
    ChunkMetadata,
    DocpipeError,
    EmbeddedChunk,
    IngestContext,
    ParsedDocument,
    ParsedSection,
    RetrievedChunk,
    UnsupportedFormatError,
    make_chunk_id,
)


@contextmanager
def _restore_registry(registry: Registry[Any]) -> Iterator[Registry[Any]]:
    """Snapshot and restore internal registry mappings for leak-free test isolation."""
    entries = dict(registry._entries)
    lazy = dict(registry._lazy_builtins)
    materializing = set(registry._materializing)
    try:
        yield registry
    finally:
        registry._entries.clear()
        registry._entries.update(entries)
        registry._lazy_builtins.clear()
        registry._lazy_builtins.update(lazy)
        registry._materializing.clear()
        registry._materializing.update(materializing)


def test_registry_register_resolve_sorted_keys_and_clear() -> None:
    reg: Registry[Any] = Registry("demo")
    assert reg.name == "demo"
    assert reg.keys() == []
    assert "missing" not in reg

    with pytest.raises(
        RegistryError, match=r"has no entry 'missing' \(available: <empty>\)"
    ) as exc:
        reg.resolve("missing")
    assert isinstance(exc.value, DocpipeError)
    assert isinstance(exc.value.__cause__, KeyError)

    @reg.register("zeta")
    class Zeta:
        pass

    @reg.register("alpha")
    class Alpha:
        pass

    assert reg.keys() == ["alpha", "zeta"]
    assert "alpha" in reg
    assert "zeta" in reg
    assert reg.resolve("alpha") is Alpha
    assert reg.resolve("zeta") is Zeta

    with pytest.raises(
        RegistryError,
        match=r"registry 'demo' has no entry 'unknown' \(available: alpha, zeta\)",
    ):
        reg.resolve("unknown")

    reg.clear()
    assert reg.keys() == []
    assert "alpha" not in reg


def test_registry_duplicate_rejection_and_lazy_builtin_guard() -> None:
    reg: Registry[Any] = Registry("parser")
    reg.register_lazy("fake_lazy", "nonexistent_mod_that_must_not_import", "MissingCls")

    with pytest.raises(RegistryError, match="already has entry 'fake_lazy'") as exc:

        @reg.register("fake_lazy")
        class OverrideAttempt:
            pass

    assert isinstance(exc.value, DocpipeError)

    @reg.register("custom")
    class First:
        pass

    with pytest.raises(RegistryError, match="already has entry 'custom'"):

        @reg.register("custom")
        class Second:
            pass

    with pytest.raises(RegistryError, match="already has entry 'custom'"):
        reg.register_lazy("custom", "some.mod", "SomeCls")

    with pytest.raises(RegistryError, match="already has entry 'fake_lazy'"):
        reg.register_lazy("fake_lazy", "other.mod", "OtherCls")

    # Package-level active registries also reject duplicates against deferred built-ins
    with _restore_registry(CLEANERS):
        CLEANERS.clear()
        CLEANERS.register_lazy("default", "nonexistent.clean.mod", "DefaultCleaner")
        with pytest.raises(RegistryError, match="already has entry 'default'"):

            @register_cleaner("default")
            class DupCleaner:
                name = "default"

                def clean(self, doc: ParsedDocument) -> ParsedDocument:
                    return doc


def test_resolve_parser_custom_precedence_preferred_and_errors(tmp_path: Path) -> None:
    missing_file = tmp_path / "does_not_exist.txt"
    with pytest.raises(UnsupportedFormatError):
        resolve_parser(missing_file)

    weird_file = tmp_path / "data.weird"
    weird_file.write_text("abc", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match="Unsupported file extension"):
        resolve_parser(weird_file)

    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("hello world", encoding="utf-8")

    with _restore_registry(PARSERS):

        @register_parser("z_txt")
        class ZTxtParser:
            name: str = "z_txt"
            extensions: tuple[str, ...] = (".txt",)

            def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
                return ParsedDocument(source=source_key, format_name=self.name, sections=[])

        @register_parser("a_txt")
        class ATxtParser:
            name: str = "a_txt"
            extensions: tuple[str, ...] = (".TXT",)

            def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
                return ParsedDocument(source=source_key, format_name=self.name, sections=[])

        # Custom parsers take precedence over built-in "txt" and resolve ties in sorted key order
        chosen = resolve_parser(txt_file)
        assert isinstance(chosen, ATxtParser)

        explicit = resolve_parser(txt_file, preferred="z_txt")
        assert isinstance(explicit, ZTxtParser)


def test_orchestrators_validate_non_default_stage_keys(
    tmp_path: Path,
    tmp_persist_dir: Path,
) -> None:
    doc = tmp_path / "note.txt"
    doc.write_text("Sample text for validation.", encoding="utf-8")

    with pytest.raises(RegistryError, match="registry 'store' has no entry 'missing'"):
        status(collection="c", persist_dir=tmp_persist_dir, store="missing")

    with pytest.raises(RegistryError, match="registry 'store' has no entry 'missing'"):
        remove("note.txt", collection="c", persist_dir=tmp_persist_dir, store="missing")

    with pytest.raises(RegistryError, match="registry 'embedder' has no entry 'missing'"):
        retrieve("question", collection="c", persist_dir=tmp_persist_dir, embedder="missing")

    with pytest.raises(RegistryError, match="registry 'store' has no entry 'missing'"):
        retrieve("question", collection="c", persist_dir=tmp_persist_dir, store="missing")

    with pytest.raises(RegistryError, match="registry 'cleaner' has no entry 'missing'"):
        ingest(doc, collection="c", persist_dir=tmp_persist_dir, cleaner="missing")

    with pytest.raises(RegistryError, match="registry 'chunker' has no entry 'missing'"):
        ingest(doc, collection="c", persist_dir=tmp_persist_dir, chunker="missing")


def test_end_to_end_custom_stages_via_ingest_and_retrieve(
    tmp_path: Path,
    tmp_persist_dir: Path,
) -> None:
    corpus_dir = tmp_path / "custom_corpus"
    corpus_dir.mkdir()
    rst_doc = corpus_dir / "guide.rst"
    rst_doc.write_text(
        "RST Custom Title\n================\n\ncustom body sentence\n", encoding="utf-8"
    )

    in_memory_records: dict[str, dict[str, EmbeddedChunk]] = {}

    with (
        _restore_registry(PARSERS),
        _restore_registry(CLEANERS),
        _restore_registry(CHUNKERS),
        _restore_registry(EMBEDDERS),
        _restore_registry(STORES),
    ):

        @register_parser("rst")
        class RstParser:
            name: str = "rst"
            extensions: tuple[str, ...] = (".rst",)

            def parse(self, path: Path, *, source_key: str) -> ParsedDocument:
                raw = path.read_text(encoding="utf-8").strip()
                return ParsedDocument(
                    source=source_key,
                    format_name="rst",
                    sections=[
                        ParsedSection(
                            source=source_key,
                            section_label="RST Guide",
                            heading_level=1,
                            raw_text=raw,
                        )
                    ],
                )

        @register_cleaner("upper")
        class UpperCleaner:
            name = "upper"

            def clean(self, doc: ParsedDocument) -> ParsedDocument:
                return ParsedDocument(
                    source=doc.source,
                    format_name=doc.format_name,
                    sections=[
                        ParsedSection(
                            source=s.source,
                            section_label=s.section_label,
                            heading_level=s.heading_level,
                            raw_text=s.raw_text.upper(),
                            page=s.page,
                        )
                        for s in doc.sections
                    ],
                )

        @register_chunker("single")
        class SingleChunker:
            name = "single"

            def chunk(
                self,
                doc: ParsedDocument,
                *,
                profile: ChunkingProfile,
                doc_version: str,
                embed_model: str,
            ) -> list[Chunk]:
                out: list[Chunk] = []
                for idx, sec in enumerate(doc.sections):
                    pid = make_chunk_id(
                        source=sec.source,
                        doc_version=doc_version,
                        chunk_type="parent",
                        section=sec.section_label,
                        clause=None,
                        chunk_index=idx,
                        text=sec.raw_text,
                    )
                    pmeta: ChunkMetadata = {
                        "type": "parent",
                        "source": sec.source,
                        "doc_version": doc_version,
                        "section": sec.section_label,
                        "clause": None,
                        "page": sec.page,
                        "chunk_index": idx,
                        "embed_model": embed_model,
                    }
                    cmeta: ChunkMetadata = {
                        "type": "child",
                        "source": sec.source,
                        "doc_version": doc_version,
                        "section": sec.section_label,
                        "clause": None,
                        "page": sec.page,
                        "chunk_index": 0,
                        "embed_model": embed_model,
                    }
                    cid = make_chunk_id(
                        source=sec.source,
                        doc_version=doc_version,
                        chunk_type="child",
                        section=sec.section_label,
                        clause=None,
                        chunk_index=0,
                        text=sec.raw_text,
                        parent_id=pid,
                    )
                    out.append(Chunk(id=pid, text=sec.raw_text, parent_id=None, metadata=pmeta))
                    out.append(Chunk(id=cid, text=sec.raw_text, parent_id=pid, metadata=cmeta))
                return out

        @register_embedder("unit_mem")
        class MemoryEmbedder:
            name = "unit_mem"

            def embed_texts(
                self,
                texts: Sequence[str],
                *,
                model: str,
                api_base: str | None = None,
            ) -> list[list[float]]:
                _ = (model, api_base)
                return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

            def embed_query(
                self,
                text: str,
                *,
                model: str,
                api_base: str | None = None,
            ) -> list[float]:
                _ = (text, model, api_base)
                return [1.0, 0.0, 0.0, 0.0]

        @register_store("unit_mem")
        class MemoryStore:
            name = "unit_mem"

            def __init__(self, persist_dir: Path, collection_name: str) -> None:
                _ = persist_dir
                self._bucket = in_memory_records.setdefault(collection_name, {})

            def add_chunks(self, chunks: Sequence[EmbeddedChunk]) -> None:
                for chunk in chunks:
                    self._bucket[chunk.id] = chunk

            def query_children(
                self,
                query_vector: list[float],
                *,
                top_k: int = 5,
                active_versions: dict[str, str] | None = None,
                where: dict[str, object] | None = None,
                include_embeddings: bool = False,
            ) -> list[RetrievedChunk]:
                _ = (query_vector, where, include_embeddings)
                hits: list[RetrievedChunk] = []
                for item in self._bucket.values():
                    if item.metadata["type"] != "child":
                        continue
                    if active_versions is not None and (
                        active_versions.get(item.metadata["source"]) != item.metadata["doc_version"]
                    ):
                        continue
                    hits.append(
                        RetrievedChunk(
                            id=item.id,
                            text=item.text,
                            parent_id=item.parent_id,
                            metadata=item.metadata,
                            vector=[],
                            score=1.0,
                        )
                    )
                return hits[:top_k]

            def get_by_ids(
                self,
                ids: Sequence[str],
                *,
                include_embeddings: bool = False,
            ) -> list[EmbeddedChunk]:
                _ = include_embeddings
                return [self._bucket[cid] for cid in ids if cid in self._bucket]

            def get_parents_by_source(
                self,
                source: str,
                *,
                active_doc_version: str | None = None,
                include_embeddings: bool = False,
            ) -> list[EmbeddedChunk]:
                _ = include_embeddings
                return [
                    c
                    for c in self._bucket.values()
                    if c.metadata["type"] == "parent"
                    and c.metadata["source"] == source
                    and (
                        active_doc_version is None
                        or c.metadata["doc_version"] == active_doc_version
                    )
                ]

            def delete_by_source(self, source: str) -> None:
                for cid in [k for k, v in self._bucket.items() if v.metadata["source"] == source]:
                    del self._bucket[cid]

            def delete_stale_versions(self, source: str, active_doc_version: str) -> None:
                for cid in [
                    k
                    for k, v in self._bucket.items()
                    if v.metadata["source"] == source
                    and v.metadata["doc_version"] != active_doc_version
                ]:
                    del self._bucket[cid]

            def sweep_uncommitted(self, active_versions: dict[str, str]) -> int:
                stale = [
                    k
                    for k, v in self._bucket.items()
                    if active_versions.get(v.metadata["source"]) != v.metadata["doc_version"]
                ]
                for cid in stale:
                    del self._bucket[cid]
                return len(stale)

            def get_all_children(self) -> list[EmbeddedChunk]:
                return [c for c in self._bucket.values() if c.metadata["type"] == "child"]

            def get_all_parents(self) -> list[EmbeddedChunk]:
                return [c for c in self._bucket.values() if c.metadata["type"] == "parent"]

            def reset_collection(self) -> None:
                self._bucket.clear()

        ingest_res = ingest(
            rst_doc,
            collection="mem_col",
            persist_dir=tmp_persist_dir,
            embed_model="custom/tiny",
            cleaner="upper",
            chunker="single",
            embedder="unit_mem",
            store="unit_mem",
        )
        assert ingest_res.ingested == ["guide.rst"]
        assert ingest_res.chunks_written == 1
        assert ingest_res.parents_written == 1

        st = status(collection="mem_col", persist_dir=tmp_persist_dir, store="unit_mem")
        assert st.total_sources == 1
        assert st.embed_dim == 4

        retrieved = retrieve(
            "custom body sentence",
            collection="mem_col",
            persist_dir=tmp_persist_dir,
            embed_model="custom/tiny",
            embedder="unit_mem",
            store="unit_mem",
        )
        assert len(retrieved) == 1
        assert "CUSTOM BODY SENTENCE" in retrieved[0].text
        assert retrieved[0].metadata["type"] == "parent"

        reindexed_count = reindex(
            embed_model="custom/tiny-v2",
            collection="mem_col",
            persist_dir=tmp_persist_dir,
            embedder="unit_mem",
            store="unit_mem",
        )
        assert reindexed_count == 1

        # Remove via custom store then re-add via sync using custom stage selectors
        assert remove(
            "guide.rst",
            collection="mem_col",
            persist_dir=tmp_persist_dir,
            store="unit_mem",
        )
        sync_res = sync(
            corpus_dir,
            collection="mem_col",
            persist_dir=tmp_persist_dir,
            embed_model="custom/tiny-v2",
            cleaner="upper",
            chunker="single",
            embedder="unit_mem",
            store="unit_mem",
        )
        assert sync_res.added == ["guide.rst"]


def test_top_level_eight_registries_empty_defaults_and_protocol_conformance(
    tmp_persist_dir: Path,
) -> None:
    import docpipe_maestro as root

    # Subpackage imports from test setup must never shadow callable root.ingest
    assert callable(root.ingest)

    assert ENRICHERS.keys() == ["crossrefs"]
    assert callable(register_enricher)
    with pytest.raises(
        root.RegistryError,
        match=r"registry 'enricher' has no entry 'missing' \(available: crossrefs\)",
    ):
        ENRICHERS.resolve("missing")

    assert SEARCHERS.keys() == ["default", "fts5_hybrid"]
    with pytest.raises(
        root.RegistryError,
        match=r"registry 'searcher' has no entry 'missing' \(available: default, fts5_hybrid\)",
    ):
        SEARCHERS.resolve("missing")

    assert RERANKERS.keys() == ["cross_encoder"]
    with pytest.raises(
        root.RegistryError,
        match=r"registry 'reranker' has no entry 'missing' \(available: cross_encoder\)",
    ):
        RERANKERS.resolve("missing")
    assert callable(register_reranker)

    with (
        _restore_registry(ENRICHERS),
        _restore_registry(SEARCHERS),
        _restore_registry(RERANKERS),
    ):

        @register_enricher("tagger")
        class TagEnricher:
            name = "tagger"

            def enrich(self, doc: ParsedDocument, ctx: Any) -> ParsedDocument:
                _ = ctx
                return doc

        @register_searcher("lexical")
        class LexSearcher:
            name = "lexical"

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
                _ = (question, top_k, collection, persist_dir, embed_model, where)
                return []

        @register_reranker("noop")
        class NoopReranker:
            name = "noop"

            def rerank(
                self,
                query: str,
                chunks: list[RetrievedChunk],
                *,
                top_k: int,
            ) -> list[RetrievedChunk]:
                _ = query
                return chunks[:top_k]

        assert isinstance(TagEnricher(), Enricher)
        assert isinstance(LexSearcher(), Searcher)
        assert isinstance(NoopReranker(), Reranker)

    parser_keys = PARSERS.keys()
    for key in parser_keys:
        assert isinstance(PARSERS.resolve(key)(), Parser)
    searcher_keys = SEARCHERS.keys()
    for key in searcher_keys:
        assert isinstance(SEARCHERS.resolve(key)(), Searcher)
    reranker_keys = RERANKERS.keys()
    for key in reranker_keys:
        assert isinstance(RERANKERS.resolve(key)(), Reranker)
    enricher_keys = ENRICHERS.keys()
    for key in enricher_keys:
        assert isinstance(ENRICHERS.resolve(key)(), Enricher)
    assert isinstance(CLEANERS.resolve("default")(), Cleaner)
    assert isinstance(CHUNKERS.resolve("default")(), Chunker)
    assert isinstance(EMBEDDERS.resolve("default")(), Embedder)
    store_cls = STORES.resolve("default")
    assert isinstance(store_cls(tmp_persist_dir, "proto_check"), Store)


def test_lazy_materialization_does_not_load_unrelated_sibling_builtins() -> None:
    import subprocess
    import sys

    code = (
        "import sys; "
        "from docpipe_maestro.ingest.intake import PARSERS; "
        "assert 'md' in PARSERS; "
        "assert 'pdf' in PARSERS._lazy_builtins; "
        "assert 'docx' in PARSERS._lazy_builtins; "
        "assert 'pypdf' not in sys.modules; "
        "assert 'docx' not in sys.modules; "
        "assert 'bs4' not in sys.modules; "
        "assert 'chromadb' not in sys.modules; "
        "assert 'litellm' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_enricher_execution_order_duplicates_context_upfront_lookup_and_default_skip(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify enricher ordering, duplicates, IngestContext, upfront lookup, and DEFAULT skip."""
    _ = mock_litellm_offline
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc_a = corpus / "alpha.md"
    doc_a.write_text("# Alpha\n\nInitial alpha body.\n", encoding="utf-8")

    with _restore_registry(ENRICHERS):
        calls: list[tuple[str, str, dict[str, Any]]] = []

        @register_enricher("first")
        class _FirstEnricher:
            name = "first"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                calls.append(("first", doc.source, dict(ctx)))
                return ParsedDocument(
                    source=doc.source,
                    format_name=doc.format_name,
                    sections=[
                        ParsedSection(
                            source=sec.source,
                            section_label=sec.section_label,
                            heading_level=sec.heading_level,
                            raw_text=f"{sec.raw_text}\n[ENRICHED:first]",
                            page=sec.page,
                            clauses=list(sec.clauses),
                        )
                        for sec in doc.sections
                    ],
                )

        @register_enricher("second")
        class _SecondEnricher:
            name = "second"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                calls.append(("second", doc.source, dict(ctx)))
                return ParsedDocument(
                    source=doc.source,
                    format_name=doc.format_name,
                    sections=[
                        ParsedSection(
                            source=sec.source,
                            section_label=sec.section_label,
                            heading_level=sec.heading_level,
                            raw_text=f"{sec.raw_text}\n[ENRICHED:second]",
                            page=sec.page,
                            clauses=list(sec.clauses),
                        )
                        for sec in doc.sections
                    ],
                )

        def _profile(name: str, enrichers: tuple[str, ...]) -> ChunkingProfile:
            return ChunkingProfile(
                name=name,
                chunk_size=1000,
                overlap=80,
                clause_preserving=False,
                parent_child=False,
                resolve_crossrefs=False,
                enrichers=enrichers,
            )

        order_profile = _profile("CUSTOM_ORDER", ("first", "second"))
        ingest(
            doc_a,
            persist_dir=tmp_persist_dir,
            collection="order_col",
            embed_model="mock/embed",
            profile=order_profile,
        )

        assert [(name, src) for name, src, _ in calls] == [
            ("first", "alpha.md"),
            ("second", "alpha.md"),
        ]
        expected_ctx_keys = {
            "collection",
            "source",
            "content_hash",
            "doc_version",
            "embed_model",
            "profile",
        }
        for _, _, captured_ctx in calls:
            assert expected_ctx_keys.issubset(captured_ctx.keys())
            assert captured_ctx["collection"] == "order_col"
            assert captured_ctx["source"] == "alpha.md"
            assert captured_ctx["content_hash"].startswith("sha256:")
            assert captured_ctx["doc_version"] == captured_ctx["content_hash"].split(":", 1)[1][:12]
            assert len(captured_ctx["doc_version"]) == 12
            assert captured_ctx["embed_model"] == "mock/embed"
            assert captured_ctx["profile"] == "CUSTOM_ORDER"

        order_store = VectorStore(tmp_persist_dir, "order_col")
        combined_text = "\n".join(c.text for c in order_store.get_all_children())
        assert "[ENRICHED:first]\n[ENRICHED:second]" in combined_text

        calls.clear()
        doc_b = corpus / "beta.md"
        doc_b.write_text("# Beta\n\nInitial beta body.\n", encoding="utf-8")
        dup_profile = _profile("CUSTOM_DUP", ("first", "first"))
        sync(
            corpus,
            persist_dir=tmp_persist_dir,
            collection="order_col",
            embed_model="mock/embed",
            profile=dup_profile,
        )
        assert [(name, src) for name, src, _ in calls] == [
            ("first", "beta.md"),
            ("first", "beta.md"),
        ]
        for _, _, captured_ctx in calls:
            assert captured_ctx["collection"] == "order_col"
            assert captured_ctx["source"] == "beta.md"
            assert captured_ctx["profile"] == "CUSTOM_DUP"
            assert len(captured_ctx["doc_version"]) == 12

        beta_text = "\n".join(
            c.text for c in order_store.get_all_children() if c.metadata["source"] == "beta.md"
        )
        assert "[ENRICHED:first]\n[ENRICHED:first]" in beta_text

        missing_profile = _profile("MISSING_ENRICHER", ("does_not_exist",))
        with pytest.raises(RegistryError, match="does_not_exist"):
            ingest(
                doc_a,
                persist_dir=tmp_persist_dir,
                collection="order_col",
                embed_model="mock/embed",
                profile=missing_profile,
            )
        with pytest.raises(RegistryError, match="does_not_exist"):
            sync(
                corpus,
                persist_dir=tmp_persist_dir,
                collection="order_col",
                embed_model="mock/embed",
                profile=missing_profile,
            )

        resolve_calls: list[str] = []
        orig_resolve = ENRICHERS.resolve

        def _spy_resolve(name: str) -> Any:
            resolve_calls.append(name)
            return orig_resolve(name)

        monkeypatch.setattr(ENRICHERS, "resolve", _spy_resolve)

        doc_c = tmp_path / "gamma.md"
        doc_c.write_text("# Gamma\n\nDefault body.\n", encoding="utf-8")
        ingest(
            doc_c,
            persist_dir=tmp_persist_dir,
            collection="default_skip_col",
            embed_model="mock/embed",
            profile="DEFAULT",
        )
        sync_default_dir = tmp_path / "sync_default"
        sync_default_dir.mkdir()
        (sync_default_dir / "delta.md").write_text("# Delta\n\nDefault sync.\n", encoding="utf-8")
        sync(
            sync_default_dir,
            persist_dir=tmp_persist_dir,
            collection="default_skip_sync_col",
            embed_model="mock/embed",
            profile="DEFAULT",
        )
        assert resolve_calls == []
