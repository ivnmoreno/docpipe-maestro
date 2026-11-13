"""Generic named stage registry with deferred built-in declarations."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Generic, TypeVar

from docpipe_maestro.types import RegistryError

T = TypeVar("T")

__all__ = ["Registry", "RegistryError"]


class Registry(Generic[T]):
    """Named strategy registry supporting decorators and lazy built-in loading."""

    def __init__(self, name: str) -> None:
        """Create an empty registry for a named pipeline stage category."""
        self._name = name
        self._entries: dict[str, type[T]] = {}
        self._lazy_builtins: dict[str, tuple[str, str]] = {}
        self._materializing: set[str] = set()

    @property
    def name(self) -> str:
        """Return the logical stage category name (e.g., ``'parser'``)."""
        return self._name

    def _is_declared_builtin_class(self, key: str, cls: type[T]) -> bool:
        """Return ``True`` if ``cls`` matches the declared lazy built-in for ``key``."""
        target = self._lazy_builtins.get(key)
        return target is not None and (cls.__module__, cls.__name__) == target

    def _materialize_key(self, key: str) -> None:
        """Import and bind a single deferred built-in entry if declared for ``key``."""
        if key in self._entries or key not in self._lazy_builtins or key in self._materializing:
            return
        module_path, attr = self._lazy_builtins[key]
        self._materializing.add(key)
        try:
            mod = importlib.import_module(module_path)
            obj: type[T] = getattr(mod, attr)
            if key not in self._entries:
                self._entries[key] = obj
            self._lazy_builtins.pop(key, None)
        finally:
            self._materializing.discard(key)

    def _materialize_all(self) -> None:
        """Import and bind all remaining deferred built-in entries for diagnostics/listing."""
        for key in list(self._lazy_builtins):
            self._materialize_key(key)

    def register(self, key: str) -> Callable[[type[T]], type[T]]:
        """Return a class decorator registering a stage class under ``key``.

        Raises:
            RegistryError: If ``key`` is already registered or reserved by another
                unmaterialized built-in declaration.
        """
        if key in self._entries:
            raise RegistryError(f"registry '{self._name}' already has entry '{key}'")

        def decorator(cls: type[T]) -> type[T]:
            if key in self._entries:
                raise RegistryError(f"registry '{self._name}' already has entry '{key}'")
            if (
                key in self._lazy_builtins
                and key not in self._materializing
                and not self._is_declared_builtin_class(key, cls)
            ):
                raise RegistryError(f"registry '{self._name}' already has entry '{key}'")
            self._lazy_builtins.pop(key, None)
            self._entries[key] = cls
            return cls

        return decorator

    def register_lazy(self, key: str, module_path: str, attr: str) -> None:
        """Declare a deferred built-in stage class without importing ``module_path``.

        Raises:
            RegistryError: If ``key`` already has a live entry or lazy declaration.
        """
        if key in self._entries or key in self._lazy_builtins:
            raise RegistryError(f"registry '{self._name}' already has entry '{key}'")
        self._lazy_builtins[key] = (module_path, attr)

    def resolve(self, key: str) -> type[T]:
        """Resolve and return the concrete stage class registered under ``key``.

        Raises:
            RegistryError: If ``key`` is not registered (listing sorted available keys
                or ``<empty>``).
        """
        self._materialize_key(key)
        try:
            return self._entries[key]
        except KeyError as exc:
            self._materialize_all()
            available = ", ".join(sorted(self._entries)) or "<empty>"
            raise RegistryError(
                f"registry '{self._name}' has no entry '{key}' (available: {available})"
            ) from exc

    def __contains__(self, key: object) -> bool:
        """Return ``True`` if ``key`` matches a registered or declared built-in stage."""
        if not isinstance(key, str):
            return False
        self._materialize_key(key)
        return key in self._entries

    def keys(self) -> list[str]:
        """Return lexicographically sorted keys after materializing lazy built-ins."""
        self._materialize_all()
        return sorted(self._entries)

    def clear(self) -> None:
        """Remove all registered and deferred entries (strictly for test isolation)."""
        self._entries.clear()
        self._lazy_builtins.clear()
        self._materializing.clear()
