"""Unit tests for the database-collocated manifest manager."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docpipe_maestro.manifest import (
    check_model_lock,
    classify_file,
    compute_file_hash,
    load_manifest,
    save_manifest,
)
from docpipe_maestro.types import Manifest, ModelMismatchError, SourceRecord


def test_manifest_atomic_roundtrip_and_model_lock(tmp_persist_dir: Path) -> None:
    manifest = load_manifest(tmp_persist_dir, "handbook")
    assert manifest.embed_model is None
    assert manifest.sources == {}

    manifest.embed_model = "ollama/nomic-embed-text"
    manifest.embed_dim = 64
    manifest.sources["a.md"] = SourceRecord(
        source="a.md",
        content_hash="sha256:abc",
        doc_version="abc",
        size=10,
        mtime=100.0,
        ingested_at="2026-11-12T00:00:00Z",
        embed_model="ollama/nomic-embed-text",
        profile="POLICY",
        chunk_ids=["c1"],
        parent_ids=["p1"],
    )
    save_manifest(tmp_persist_dir, manifest)

    reloaded = load_manifest(tmp_persist_dir, "handbook")
    assert reloaded.embed_model == "ollama/nomic-embed-text"
    assert reloaded.sources["a.md"].chunk_ids == ["c1"]

    check_model_lock(reloaded, "ollama/nomic-embed-text")
    with pytest.raises(ModelMismatchError, match="docpipe reindex"):
        check_model_lock(reloaded, "openai/text-embedding-3-small")


def test_classify_file_mtime_fast_path_and_hash_verification(tmp_path: Path) -> None:
    target = tmp_path / "policy.txt"
    target.write_text("Leave policy v1", encoding="utf-8")
    stat = target.stat()
    chash = compute_file_hash(target)

    manifest = Manifest(collection="c")
    status, new_hash, _, _ = classify_file(target, "policy.txt", manifest)
    assert status == "new"
    assert new_hash == chash

    manifest.sources["policy.txt"] = SourceRecord(
        source="policy.txt",
        content_hash=chash,
        doc_version=chash.split(":", 1)[1][:12],
        size=stat.st_size,
        mtime=stat.st_mtime,
        ingested_at="2026-11-12T00:00:00Z",
        embed_model="ollama/nomic-embed-text",
        profile="DEFAULT",
    )

    # Unchanged mtime+size -> fast-path skip (content_hash is None)
    status, fast_hash, _, _ = classify_file(target, "policy.txt", manifest)
    assert status == "unchanged"
    assert fast_hash is None

    # Touch file (mtime changes, content identical) -> still unchanged after hash check
    os.utime(target, (stat.st_atime + 10, stat.st_mtime + 10))
    status, verified_hash, _, _ = classify_file(target, "policy.txt", manifest)
    assert status == "unchanged"
    assert verified_hash == chash

    # Edit content -> changed
    target.write_text("Leave policy v2", encoding="utf-8")
    status, changed_hash, _, _ = classify_file(target, "policy.txt", manifest)
    assert status == "changed"
    assert changed_hash != chash
