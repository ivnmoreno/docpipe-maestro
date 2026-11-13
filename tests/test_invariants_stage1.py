"""Regression tests guarding previously unguarded Stage 0/Stage 1 invariants."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from docpipe_maestro._resolve import resolve_parser
from docpipe_maestro.cli import main
from docpipe_maestro.ingest.pipeline import ingest, sync
from docpipe_maestro.manifest import load_manifest
from docpipe_maestro.store import STORES, VectorStore
from docpipe_maestro.types import (
    ChunkMetadata,
    DocpipeError,
    EmbeddedChunk,
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
