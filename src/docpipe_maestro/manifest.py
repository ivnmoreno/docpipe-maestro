"""Database-collocated manifest management with sha256 tracking and model locking."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from docpipe_maestro.types import Manifest, ModelMismatchError

ChangeStatus = Literal["new", "unchanged", "changed"]


def manifest_path(persist_dir: Path, collection: str) -> Path:
    """Return the path to the collection's collocated manifest JSON file."""
    return persist_dir / "manifests" / f"{collection}.json"


def load_manifest(persist_dir: Path, collection: str) -> Manifest:
    """Load the collection manifest, or return a fresh empty Manifest if absent."""
    path = manifest_path(persist_dir, collection)
    if not path.exists():
        return Manifest(collection=collection)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Manifest.from_dict(raw)


def save_manifest(persist_dir: Path, manifest: Manifest) -> None:
    """Atomically write the manifest via temp file, ``fsync``, and ``os.replace``.

    Crash-safe: an interrupted write either cleans up its temporary file or
    leaves the prior committed JSON untouched.
    """
    target = manifest_path(persist_dir, manifest.collection)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{manifest.collection}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def compute_file_hash(path: Path) -> str:
    """Compute a prefixed sha256 digest of the file contents."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def classify_file(
    path: Path,
    source_key: str,
    manifest: Manifest,
    *,
    force: bool = False,
) -> tuple[ChangeStatus, str | None, int, float]:
    """Classify a file using an ``mtime``/``size`` fast-path and ``sha256`` check.

    When ``force`` is ``False`` and both ``size`` and ``mtime`` match the
    manifest, file hashing is skipped altogether. When filesystem metadata
    differs (for example after ``touch``), the full ``sha256`` digest determines
    whether content actually changed.

    Args:
        path: On-disk path to the candidate document.
        source_key: Canonical manifest key for ``path``.
        manifest: Loaded collection manifest.
        force: Bypass fast-path and hash equality checks when ``True``.

    Returns:
        A 4-tuple ``(status, content_hash_or_None, size, mtime)``.
    """
    stat = path.stat()
    size = stat.st_size
    mtime = stat.st_mtime
    existing = manifest.sources.get(source_key)

    if existing is None:
        return "new", compute_file_hash(path), size, mtime

    if not force and existing.size == size and existing.mtime == mtime:
        return "unchanged", None, size, mtime

    content_hash = compute_file_hash(path)
    if not force and existing.content_hash == content_hash:
        return "unchanged", content_hash, size, mtime

    return "changed", content_hash, size, mtime


def check_model_lock(manifest: Manifest, embed_model: str) -> None:
    """Verify that ``embed_model`` matches the collection's locked model.

    Raises:
        ModelMismatchError: If the collection is already locked to a different
            embedding model than ``embed_model``.
    """
    if manifest.embed_model is not None and manifest.embed_model != embed_model:
        raise ModelMismatchError(
            f"Collection {manifest.collection!r} is locked to embedding model "
            f"{manifest.embed_model!r}, but {embed_model!r} was requested. "
            f"Run 'docpipe reindex --model {embed_model} --collection {manifest.collection}' "
            "to migrate the collection."
        )
