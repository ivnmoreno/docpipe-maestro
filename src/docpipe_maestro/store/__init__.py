"""Shared vector store registry and lazy compatibility exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from docpipe_maestro._registry import Registry
from docpipe_maestro._stages import Store

if TYPE_CHECKING:
    from docpipe_maestro.store.chroma import ChromaStore, VectorStore
    from docpipe_maestro.store.lexical import LexicalIndex

STORES: Registry[Store] = Registry("store")
register_store = STORES.register

STORES.register_lazy("default", "docpipe_maestro.store.chroma", "ChromaStore")

__all__ = [
    "STORES",
    "ChromaStore",
    "LexicalIndex",
    "VectorStore",
    "register_store",
]

_LAZY_CHROMA_EXPORTS = frozenset({"ChromaStore", "VectorStore"})


def __getattr__(name: str) -> Any:
    """Lazily expose store exports without eager ``chromadb`` or ``sqlite3`` import."""
    if name in _LAZY_CHROMA_EXPORTS:
        mod = importlib.import_module("docpipe_maestro.store.chroma")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    if name == "LexicalIndex":
        mod = importlib.import_module("docpipe_maestro.store.lexical")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
