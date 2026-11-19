"""Generic named stage registry with deferred built-in declarations."""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from typing import Generic, TypeVar

from docpipe_maestro.types import RegistryError

T = TypeVar("T")

__all__ = ["Registry", "RegistryError"]


class Registry(Generic[T]):
    """Named strategy registry supporting decorators and lazy built-in loading."""

    def __init__(self, name: str) -> None:
        """Create an empty thread-safe registry for a named pipeline stage category."""
        self._name = name
        self._entries: dict[str, type[T]] = {}
        self._lazy_builtins: dict[str, tuple[str, str]] = {}
        self._in_flight: dict[str, tuple[int, threading.Event]] = {}
        self._materializing: set[str] = set()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """Return the logical stage category name (e.g., ``'parser'``)."""
        return self._name

    def _is_declared_builtin_class(self, key: str, cls: type[T]) -> bool:
        """Return ``True`` if ``cls`` matches the declared lazy built-in for ``key``.

        Caller must hold ``self._lock``.
        """
        target = self._lazy_builtins.get(key)
        return target is not None and (cls.__module__, cls.__name__) == target

    def _materialize_key(self, key: str) -> None:
        """Import and bind a single deferred built-in entry thread-safely if declared."""
        while True:
            current_tid = threading.get_ident()
            wait_event: threading.Event | None = None
            module_path = ""
            attr = ""
            with self._lock:
                if key in self._entries or key not in self._lazy_builtins:
                    return
                in_flight = self._in_flight.get(key)
                if in_flight is not None:
                    owner_tid, ev = in_flight
                    if owner_tid == current_tid:
                        # Preserve same-thread reentrancy during @register(key).
                        return
                    wait_event = ev
                else:
                    module_path, attr = self._lazy_builtins[key]
                    ev = threading.Event()
                    self._in_flight[key] = (current_tid, ev)
                    self._materializing.add(key)

            if wait_event is not None:
                wait_event.wait()
                continue

            # Run import outside self._lock to avoid lock-order deadlocks with the import lock.
            obj: type[T] | None = None
            try:
                mod = importlib.import_module(module_path)
                obj = getattr(mod, attr)
            finally:
                try:
                    with self._lock:
                        if obj is not None:
                            self._entries.setdefault(key, obj)
                            self._lazy_builtins.pop(key, None)
                        self._in_flight.pop(key, None)
                        self._materializing.discard(key)
                finally:
                    ev.set()
            return

    def _materialize_all(self) -> None:
        """Import and bind all remaining deferred built-in entries for diagnostics/listing."""
        with self._lock:
            pending_keys = list(self._lazy_builtins)
        for key in pending_keys:
            self._materialize_key(key)

    def register(self, key: str) -> Callable[[type[T]], type[T]]:
        """Return a class decorator registering a stage class under ``key``.

        Raises:
            RegistryError: If ``key`` is already registered or reserved by another
                unmaterialized built-in declaration.
        """
        with self._lock:
            if key in self._entries:
                raise RegistryError(f"registry '{self._name}' already has entry '{key}'")

        def decorator(cls: type[T]) -> type[T]:
            with self._lock:
                if key in self._entries:
                    raise RegistryError(f"registry '{self._name}' already has entry '{key}'")
                in_flight = self._in_flight.get(key)
                same_thread_in_flight = (
                    in_flight is not None and in_flight[0] == threading.get_ident()
                )
                if (
                    key in self._lazy_builtins
                    and not same_thread_in_flight
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
        with self._lock:
            if key in self._entries or key in self._lazy_builtins or key in self._in_flight:
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
            with self._lock:
                return self._entries[key]
        except KeyError as exc:
            self._materialize_all()
            with self._lock:
                if key in self._entries:
                    return self._entries[key]
                available = ", ".join(sorted(self._entries)) or "<empty>"
            raise RegistryError(
                f"registry '{self._name}' has no entry '{key}' (available: {available})"
            ) from exc

    def __contains__(self, key: object) -> bool:
        """Return ``True`` if ``key`` matches a registered or declared built-in stage."""
        if not isinstance(key, str):
            return False
        self._materialize_key(key)
        with self._lock:
            return key in self._entries

    def keys(self) -> list[str]:
        """Return lexicographically sorted keys after materializing lazy built-ins."""
        self._materialize_all()
        with self._lock:
            return sorted(self._entries)

    def clear(self) -> None:
        """Remove all registered and deferred entries (strictly for test isolation)."""
        with self._lock:
            self._entries.clear()
            self._lazy_builtins.clear()
            pending_events = [ev for _, ev in self._in_flight.values()]
            self._in_flight.clear()
            self._materializing.clear()
        for ev in pending_events:
            ev.set()
