"""Regression tests guarding previously unguarded Stage 0/Stage 1 invariants."""

from __future__ import annotations

import os
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from docpipe_maestro._resolve import resolve_parser
from docpipe_maestro.cli import main
from docpipe_maestro.ingest.enricher import ENRICHERS, register_enricher
from docpipe_maestro.ingest.pipeline import ingest, sync
from docpipe_maestro.manifest import load_manifest
from docpipe_maestro.store import STORES, LexicalIndex, VectorStore
from docpipe_maestro.types import (
    ChunkingProfile,
    ChunkMetadata,
    DocpipeError,
    EmbeddedChunk,
    IngestContext,
    ParsedDocument,
    ParsedSection,
    RegistryError,
    UnsupportedFormatError,
    make_chunk_id,
)


def _make_pair(
    *,
    source: str,
    doc_version: str,
    embed_model: str = "mock/embed",
    text: str = "Clause content.",
    dim: int = 8,
) -> list[EmbeddedChunk]:
    """Build a valid parent + child EmbeddedChunk pair with deterministic IDs."""
    parent_id = make_chunk_id(
        source=source,
        doc_version=doc_version,
        chunk_type="parent",
        section="Section 1",
        clause=None,
        chunk_index=0,
        text=text,
        parent_id=None,
    )
    child_text = f"[Source: {source} | Section 1]\n{text}"
    child_id = make_chunk_id(
        source=source,
        doc_version=doc_version,
        chunk_type="child",
        section="Section 1",
        clause=None,
        chunk_index=0,
        text=child_text,
        parent_id=parent_id,
    )
    parent = EmbeddedChunk(
        id=parent_id,
        text=text,
        parent_id=None,
        metadata=ChunkMetadata(
            type="parent",
            source=source,
            doc_version=doc_version,
            section="Section 1",
            clause=None,
            page=None,
            chunk_index=0,
            embed_model=embed_model,
        ),
        vector=[0.0] * dim,
    )
    child = EmbeddedChunk(
        id=child_id,
        text=child_text,
        parent_id=parent_id,
        metadata=ChunkMetadata(
            type="child",
            source=source,
            doc_version=doc_version,
            section="Section 1",
            clause=None,
            page=None,
            chunk_index=0,
            embed_model=embed_model,
        ),
        vector=[float(i + 1) for i in range(dim)],
    )
    return [parent, child]


def test_sweep_uncommitted_direct_and_on_subsequent_ingest_and_sync(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: None,
) -> None:
    """sweep_uncommitted removes orphan chunks and cleans interrupted writes on ingest/sync."""
    _ = mock_litellm_offline
    store = VectorStore(tmp_persist_dir, "sweep_direct")
    assert store.sweep_uncommitted({}) == 0

    committed = _make_pair(source="committed.md", doc_version="commit000001")
    stale_same_source = _make_pair(source="committed.md", doc_version="orphan999999")
    orphan_other = _make_pair(source="ghost.md", doc_version="ghost0000001")
    store.add_chunks(committed + stale_same_source + orphan_other)

    purged = store.sweep_uncommitted({"committed.md": "commit000001"})
    assert purged == 4

    remaining_children = store.get_all_children()
    remaining_parents = store.get_all_parents()
    assert [c.metadata["doc_version"] for c in remaining_children] == ["commit000001"]
    assert [p.metadata["doc_version"] for p in remaining_parents] == ["commit000001"]
    assert store.sweep_uncommitted({"committed.md": "commit000001"}) == 0

    # Simulate an interrupted crash between store write and manifest commit,
    # then verify both ingest() and sync() sweep the uncommitted orphans away.
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc_a = corpus / "alpha.txt"
    doc_a.write_text("# Alpha\n\nInitial alpha text.\n", encoding="utf-8")

    ingest(doc_a, persist_dir=tmp_persist_dir, collection="crash_col", embed_model="mock/embed")

    crash_store = VectorStore(tmp_persist_dir, "crash_col")
    crash_store.add_chunks(_make_pair(source="alpha.txt", doc_version="crashed00001", dim=64))
    crash_store.add_chunks(_make_pair(source="untracked.txt", doc_version="crashed00002", dim=64))

    doc_b = corpus / "beta.txt"
    doc_b.write_text("# Beta\n\nSecond document text.\n", encoding="utf-8")
    ingest(doc_b, persist_dir=tmp_persist_dir, collection="crash_col", embed_model="mock/embed")

    versions_after_ingest = {c.metadata["doc_version"] for c in crash_store.get_all_children()}
    assert "crashed00001" not in versions_after_ingest
    assert "crashed00002" not in versions_after_ingest

    # Inject another interrupted write and verify sync() cleans it as well.
    crash_store.add_chunks(_make_pair(source="beta.txt", doc_version="crashed00003", dim=64))
    sync(corpus, persist_dir=tmp_persist_dir, collection="crash_col", embed_model="mock/embed")
    versions_after_sync = {c.metadata["doc_version"] for c in crash_store.get_all_children()}
    assert "crashed00003" not in versions_after_sync


def test_empty_only_ingestion_preserves_none_embed_dim(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: None,
) -> None:
    """Ingesting an empty file locks embed_model but leaves embed_dim as None until dim > 0."""
    _ = mock_litellm_offline
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    result = ingest(
        empty_file,
        persist_dir=tmp_persist_dir,
        collection="empty_dim_col",
        embed_model="mock/embed",
    )
    assert result.chunks_written == 0

    manifest = load_manifest(tmp_persist_dir, "empty_dim_col")
    assert manifest.embed_model == "mock/embed"
    assert manifest.embed_dim is None
    assert "empty.txt" in manifest.sources
    assert manifest.sources["empty.txt"].chunk_ids == []

    real_file = tmp_path / "real.txt"
    real_file.write_text("Section 1\nSubstantive sentence for embedding.", encoding="utf-8")
    ingest(
        real_file,
        persist_dir=tmp_persist_dir,
        collection="empty_dim_col",
        embed_model="mock/embed",
    )
    updated_manifest = load_manifest(tmp_persist_dir, "empty_dim_col")
    assert updated_manifest.embed_dim == 64


def test_resolve_parser_extensionless_magic_bytes_and_zip_bomb_guard(
    tmp_path: Path,
) -> None:
    """Extensionless files route by magic bytes/content and reject oversized DOCX archives."""
    pdf_noext = tmp_path / "doc_pdf"
    pdf_noext.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n")
    assert resolve_parser(pdf_noext).name == "pdf"

    docx_noext = tmp_path / "doc_docx"
    with zipfile.ZipFile(docx_noext, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
    assert resolve_parser(docx_noext).name == "docx"

    bomb_info = zipfile.ZipInfo("word/document.xml")
    bomb_info.file_size = 300 * 1024 * 1024
    with (
        patch.object(zipfile.ZipFile, "infolist", return_value=[bomb_info]),
        pytest.raises(UnsupportedFormatError, match="uncompressed size limit"),
    ):
        resolve_parser(docx_noext)

    html_noext = tmp_path / "doc_html"
    html_noext.write_text("<!DOCTYPE html><html><body><h1>Hi</h1></body></html>", encoding="utf-8")
    assert resolve_parser(html_noext).name == "html"

    md_noext = tmp_path / "doc_md"
    md_noext.write_text("# Section Title\n\nParagraph text.\n", encoding="utf-8")
    assert resolve_parser(md_noext).name == "md"

    txt_noext = tmp_path / "doc_txt"
    txt_noext.write_text("Plain UTF-8 document without headings.\n", encoding="utf-8")
    assert resolve_parser(txt_noext).name == "txt"

    bin_noext = tmp_path / "doc_bin"
    bin_noext.write_bytes(b"\x00\x01\x02\xff\xfe")
    with pytest.raises(UnsupportedFormatError):
        resolve_parser(bin_noext)


def test_cli_main_handles_registry_error_with_exit_code_1(
    tmp_path: Path,
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RegistryError propagates cleanly through cli.main as exit code 1 on stderr."""
    doc = tmp_path / "sample.md"
    doc.write_text("# Sample\n\nBody text.", encoding="utf-8")

    def _fail_store(name: str) -> object:
        raise RegistryError(f"Unknown stage {name!r} in registry 'stores'.")

    monkeypatch.setattr(STORES, "resolve", _fail_store)

    rc = main(["ingest", str(doc), "--persist-dir", str(tmp_persist_dir)])
    captured = capsys.readouterr()

    assert issubclass(RegistryError, DocpipeError)
    assert rc == 1
    assert captured.out == ""
    assert "Error:" in captured.err
    assert "Unknown stage" in captured.err


@contextmanager
def _restore_enrichers() -> Iterator[None]:
    """Snapshot and restore ``ENRICHERS`` state around isolated invariant tests."""
    entries = dict(ENRICHERS._entries)
    lazy = dict(ENRICHERS._lazy_builtins)
    materializing = set(ENRICHERS._materializing)
    try:
        yield
    finally:
        ENRICHERS._entries.clear()
        ENRICHERS._entries.update(entries)
        ENRICHERS._lazy_builtins.clear()
        ENRICHERS._lazy_builtins.update(lazy)
        ENRICHERS._materializing.clear()
        ENRICHERS._materializing.update(materializing)


def _collection_snapshot(
    persist_dir: Path,
    collection: str,
    *,
    lexical_query: str = "alpha beta gamma",
) -> tuple[
    list[tuple[str, str, str]],
    list[tuple[str, str, str]],
    list[tuple[str, str, str]],
    dict[str, tuple[str, str, float, list[str]]],
]:
    """Capture persisted store, lexical, and manifest state for atomic rollback checks."""
    store = VectorStore(persist_dir, collection)
    children = sorted(
        ((c.id, c.metadata["doc_version"], c.text) for c in store.get_all_children()),
        key=lambda row: row[0],
    )
    parents = sorted(
        ((p.id, p.metadata["doc_version"], p.text) for p in store.get_all_parents()),
        key=lambda row: row[0],
    )
    lexical_hits = [
        (r.id, r.metadata["doc_version"], r.text)
        for r in LexicalIndex(persist_dir, collection).search(lexical_query, top_k=50)
    ]
    manifest = load_manifest(persist_dir, collection)
    manifest_state = {
        k: (v.content_hash, v.doc_version, v.mtime, list(v.chunk_ids))
        for k, v in sorted(manifest.sources.items())
    }
    return children, parents, lexical_hits, manifest_state


def test_enricher_failure_aborts_atomically_and_profile_override_precedence(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enricher exceptions abort cleanly and explicit enrichers override resolve_crossrefs."""
    _ = mock_litellm_offline

    def _profile(
        name: str,
        *,
        resolve_crossrefs: bool = False,
        enrichers: tuple[str, ...] = (),
    ) -> ChunkingProfile:
        return ChunkingProfile(
            name=name,
            chunk_size=1000,
            overlap=80,
            clause_preserving=False,
            parent_child=False,
            resolve_crossrefs=resolve_crossrefs,
            enrichers=enrichers,
        )

    assert _profile("LEGACY_FLAG", resolve_crossrefs=True).enrichers == ("crossrefs",)
    assert _profile("LEGACY_EMPTY", resolve_crossrefs=True, enrichers=()).enrichers == (
        "crossrefs",
    )

    override_profile = _profile(
        "OVERRIDE",
        resolve_crossrefs=True,
        enrichers=("custom_only",),
    )
    assert override_profile.enrichers == ("custom_only",)

    with _restore_enrichers():
        override_ran: list[str] = []
        resolved_names: list[str] = []
        orig_resolve = ENRICHERS.resolve

        @register_enricher("custom_only")
        class _CustomOnlyEnricher:
            name = "custom_only"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = ctx
                override_ran.append(doc.source)
                return ParsedDocument(
                    source=doc.source,
                    format_name=doc.format_name,
                    sections=[
                        ParsedSection(
                            source=sec.source,
                            section_label=sec.section_label,
                            heading_level=sec.heading_level,
                            raw_text=f"{sec.raw_text}\n[CUSTOM_ONLY]",
                            page=sec.page,
                            clauses=list(sec.clauses),
                        )
                        for sec in doc.sections
                    ],
                )

        def _spy_resolve(name: str) -> Any:
            resolved_names.append(name)
            return orig_resolve(name)

        override_doc = tmp_path / "override.md"
        override_doc.write_text("# Override\n\nSection 1\nSee Section 2.\n", encoding="utf-8")
        with monkeypatch.context() as mp:
            mp.setattr(ENRICHERS, "resolve", _spy_resolve)
            ingest(
                override_doc,
                persist_dir=tmp_persist_dir,
                collection="override_col",
                embed_model="mock/embed",
                profile=override_profile,
            )
        assert override_ran == ["override.md"]
        assert resolved_names == ["custom_only"]

    corpus = tmp_path / "atomic_corpus"
    corpus.mkdir()
    alpha = corpus / "alpha.md"
    alpha.write_text("# Alpha\n\nAlpha baseline stable content.\n", encoding="utf-8")
    ingest(
        corpus,
        persist_dir=tmp_persist_dir,
        collection="atomic_col",
        embed_model="mock/embed",
    )
    baseline = _collection_snapshot(tmp_persist_dir, "atomic_col")

    with _restore_enrichers():

        @register_enricher("touch")
        class _TouchEnricher:
            name = "touch"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = ctx
                return doc

        @register_enricher("boom")
        class _BoomEnricher:
            name = "boom"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = (doc, ctx)
                raise RuntimeError("mid-sequence boom")

        beta_single = tmp_path / "beta_single.md"
        beta_single.write_text("# Beta\n\nBeta volatile token.\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="mid-sequence boom"):
            ingest(
                beta_single,
                persist_dir=tmp_persist_dir,
                collection="atomic_col",
                embed_model="mock/embed",
                profile=_profile("FAIL_SEQ", enrichers=("touch", "boom")),
            )
        assert _collection_snapshot(tmp_persist_dir, "atomic_col") == baseline

        seen_batch: list[str] = []

        @register_enricher("fail_second")
        class _FailSecondEnricher:
            name = "fail_second"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = ctx
                seen_batch.append(doc.source)
                if len(seen_batch) == 2:
                    raise RuntimeError("mid-batch boom")
                return doc

        (corpus / "beta.md").write_text("# Beta\n\nBeta batch file.\n", encoding="utf-8")
        (corpus / "gamma.md").write_text("# Gamma\n\nGamma batch file.\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="mid-batch boom"):
            sync(
                corpus,
                persist_dir=tmp_persist_dir,
                collection="atomic_col",
                embed_model="mock/embed",
                profile=_profile("FAIL_BATCH", enrichers=("fail_second",)),
            )
        assert len(seen_batch) == 2
        assert _collection_snapshot(tmp_persist_dir, "atomic_col") == baseline


def test_chunking_profile_enrichers_normalization_and_immutability() -> None:
    """ChunkingProfile normalizes iterable enrichers to immutable tuples and locks fields."""
    caller_list = ["first", "second"]
    prof = ChunkingProfile(
        name="CUSTOM_NORM",
        chunk_size=512,
        overlap=32,
        clause_preserving=False,
        parent_child=True,
        resolve_crossrefs=True,
        enrichers=cast(tuple[str, ...], caller_list),
    )
    caller_list.append("mutated_after_init")
    assert prof.enrichers == ("first", "second")
    assert isinstance(prof.enrichers, tuple)

    legacy_list_empty = ChunkingProfile(
        name="LEGACY_EMPTY_LIST",
        chunk_size=512,
        overlap=32,
        clause_preserving=False,
        parent_child=True,
        resolve_crossrefs=True,
        enrichers=cast(tuple[str, ...], []),
    )
    assert legacy_list_empty.enrichers == ("crossrefs",)

    mutable_view: Any = prof
    with pytest.raises(FrozenInstanceError):
        mutable_view.enrichers = ("other",)


def test_ingest_batch_force_and_mixed_sync_delete_abort_on_enricher_failure(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: None,
) -> None:
    """Directory ingest(), force=True overwrite, and sync() deletions abort atomically."""
    _ = mock_litellm_offline

    def _custom_profile(name: str, enricher_key: str) -> ChunkingProfile:
        return ChunkingProfile(
            name=name,
            chunk_size=1000,
            overlap=80,
            clause_preserving=False,
            parent_child=False,
            resolve_crossrefs=False,
            enrichers=(enricher_key,),
        )

    ingest_corpus = tmp_path / "ingest_corpus"
    ingest_corpus.mkdir()
    keep_ingest = ingest_corpus / "alpha.md"
    keep_ingest.write_text("# Alpha\n\nAlpha original version.\n", encoding="utf-8")
    ingest(
        ingest_corpus,
        persist_dir=tmp_persist_dir,
        collection="batch_ingest_col",
        embed_model="mock/embed",
    )
    ingest_baseline = _collection_snapshot(
        tmp_persist_dir, "batch_ingest_col", lexical_query="alpha beta gamma delta"
    )

    fail_dir = tmp_path / "fail_dir"
    fail_dir.mkdir()
    (fail_dir / "beta.md").write_text("# Beta\n\nBeta first batch file.\n", encoding="utf-8")
    (fail_dir / "gamma.md").write_text("# Gamma\n\nGamma second batch file.\n", encoding="utf-8")

    with _restore_enrichers():
        seen_ingest: list[str] = []

        @register_enricher("fail_ingest_second")
        class _FailIngestSecond:
            name = "fail_ingest_second"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = ctx
                seen_ingest.append(doc.source)
                if len(seen_ingest) == 2:
                    raise DocpipeError("mid-directory ingest failure")
                return doc

        @register_enricher("always_fail_force")
        class _AlwaysFailForce:
            name = "always_fail_force"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = (doc, ctx)
                raise DocpipeError("forced overwrite failure")

        with pytest.raises(DocpipeError, match="mid-directory ingest failure"):
            ingest(
                fail_dir,
                persist_dir=tmp_persist_dir,
                collection="batch_ingest_col",
                embed_model="mock/embed",
                profile=_custom_profile("FAIL_DIR", "fail_ingest_second"),
            )
        assert len(seen_ingest) == 2
        assert (
            _collection_snapshot(
                tmp_persist_dir, "batch_ingest_col", lexical_query="alpha beta gamma delta"
            )
            == ingest_baseline
        )

        with pytest.raises(DocpipeError, match="forced overwrite failure"):
            ingest(
                keep_ingest,
                persist_dir=tmp_persist_dir,
                collection="batch_ingest_col",
                embed_model="mock/embed",
                force=True,
                profile=_custom_profile("FAIL_FORCE", "always_fail_force"),
            )
        assert (
            _collection_snapshot(
                tmp_persist_dir, "batch_ingest_col", lexical_query="alpha beta gamma delta"
            )
            == ingest_baseline
        )

    sync_corpus = tmp_path / "mixed_sync_corpus"
    sync_corpus.mkdir()
    keep_doc = sync_corpus / "keep.md"
    doomed_doc = sync_corpus / "doomed.md"
    update_doc = sync_corpus / "update.md"
    keep_doc.write_text("# Keep\n\nKeep content untouched.\n", encoding="utf-8")
    doomed_doc.write_text("# Doomed\n\nDoomed content present before failure.\n", encoding="utf-8")
    update_doc.write_text("# Update\n\nUpdate original version.\n", encoding="utf-8")

    sync(
        sync_corpus,
        persist_dir=tmp_persist_dir,
        collection="mixed_sync_col",
        embed_model="mock/embed",
    )
    sync_baseline = _collection_snapshot(
        tmp_persist_dir, "mixed_sync_col", lexical_query="keep doomed update modified"
    )

    st_keep = keep_doc.stat()
    os.utime(keep_doc, (st_keep.st_atime + 25, st_keep.st_mtime + 25))
    doomed_doc.unlink()
    update_doc.write_text("# Update\n\nUpdate modified content.\n", encoding="utf-8")

    with _restore_enrichers():

        @register_enricher("fail_mixed_sync")
        class _FailMixedSync:
            name = "fail_mixed_sync"

            def enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = (doc, ctx)
                raise DocpipeError("mixed sync boom")

        with pytest.raises(DocpipeError, match="mixed sync boom"):
            sync(
                sync_corpus,
                persist_dir=tmp_persist_dir,
                collection="mixed_sync_col",
                embed_model="mock/embed",
                profile=_custom_profile("FAIL_MIXED", "fail_mixed_sync"),
            )

    assert (
        _collection_snapshot(
            tmp_persist_dir, "mixed_sync_col", lexical_query="keep doomed update modified"
        )
        == sync_baseline
    )
