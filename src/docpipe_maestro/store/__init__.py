"""Shared vector store registry and lazy compatibility exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro._stages import Store

if TYPE_CHECKING:
    from docpipe_maestro.store.chroma import ChromaStore, VectorStore

STORES: Registry[Store] = Registry("store")
register_store = STORES.register

STORES.register_lazy("default", "docpipe_maestro.store.chroma", "ChromaStore")

__all__ = [
    "STORES",
    "ChromaStore",
    "VectorStore",
    "register_store",
]

_LAZY_STORE_EXPORTS = frozenset({"ChromaStore", "VectorStore"})


def __getattr__(name: str) -> Any:
    """Lazily expose ``ChromaStore`` and ``VectorStore`` without eager ``chromadb`` import."""
    if name in _LAZY_STORE_EXPORTS:
        mod = importlib.import_module("docpipe_maestro.store.chroma")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
