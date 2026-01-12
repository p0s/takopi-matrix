"""Copied from takopi.engines - DEPRECATED.

This provides list_backends for the matrix plugin onboarding.
"""

from __future__ import annotations

from typing import Iterable

from takopi.api import ConfigError, EngineBackend

from .ids import RESERVED_ENGINE_IDS

# Import plugin loading from takopi directly (these are internal)
try:
    from takopi.plugins import (
        ENGINE_GROUP,
        PluginLoadFailed,
        PluginNotFound,
        load_entrypoint,
        list_ids,
    )
except ImportError:
    # Fallback if internal imports fail
    ENGINE_GROUP = "takopi.engine_backends"

    class PluginNotFound(Exception):
        available: list[str] = []

    class PluginLoadFailed(Exception):
        pass

    def load_entrypoint(group, name, *, allowlist=None, validator=None):
        raise PluginNotFound()

    def list_ids(group, *, allowlist=None, reserved_ids=None):
        return []


def _validate_engine_backend(backend: object, ep) -> None:
    if not isinstance(backend, EngineBackend):
        raise TypeError(f"{ep.value} is not an EngineBackend")
    if backend.id != ep.name:
        raise ValueError(
            f"{ep.value} engine id {backend.id!r} does not match entrypoint {ep.name!r}"
        )


def get_backend(
    engine_id: str, *, allowlist: Iterable[str] | None = None
) -> EngineBackend:
    if engine_id.lower() in RESERVED_ENGINE_IDS:
        raise ConfigError(f"Engine id {engine_id!r} is reserved.")
    try:
        backend = load_entrypoint(
            ENGINE_GROUP,
            engine_id,
            allowlist=allowlist,
            validator=_validate_engine_backend,
        )
    except PluginNotFound as exc:
        if exc.available:
            available = ", ".join(exc.available)
            message = f"Unknown engine {engine_id!r}. Available: {available}."
        else:
            message = f"Unknown engine {engine_id!r}."
        raise ConfigError(message) from exc
    except PluginLoadFailed as exc:
        raise ConfigError(f"Failed to load engine {engine_id!r}: {exc}") from exc
    return backend


def list_backends(*, allowlist: Iterable[str] | None = None) -> list[EngineBackend]:
    backends: list[EngineBackend] = []
    for engine_id in list_backend_ids(allowlist=allowlist):
        try:
            backends.append(get_backend(engine_id, allowlist=allowlist))
        except ConfigError:
            continue
    if not backends:
        raise ConfigError("No engine backends are available.")
    return backends


def list_backend_ids(*, allowlist: Iterable[str] | None = None) -> list[str]:
    return list_ids(
        ENGINE_GROUP,
        allowlist=allowlist,
        reserved_ids=RESERVED_ENGINE_IDS,
    )
