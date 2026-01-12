"""Copied from takopi.commands - DEPRECATED.

This provides get_command and list_command_ids for the matrix plugin.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, overload

from takopi.api import ConfigError, CommandBackend

from .ids import RESERVED_COMMAND_IDS

# Import plugin loading from takopi directly (these are internal)
try:
    from takopi.plugins import (
        COMMAND_GROUP,
        PluginLoadFailed,
        PluginNotFound,
        load_entrypoint,
        list_ids,
    )
except ImportError:
    # Fallback if internal imports fail
    COMMAND_GROUP = "takopi.command_backends"

    class PluginNotFound(Exception):
        available: list[str] = []

    class PluginLoadFailed(Exception):
        pass

    def load_entrypoint(group, name, *, allowlist=None, validator=None):
        raise PluginNotFound()

    def list_ids(group, *, allowlist=None, reserved_ids=None):
        return []


def _validate_command_backend(backend: object, ep) -> None:
    if not isinstance(backend, CommandBackend):
        raise TypeError(f"{ep.value} is not a CommandBackend")
    if backend.id != ep.name:
        raise ValueError(
            f"{ep.value} command id {backend.id!r} does not match entrypoint {ep.name!r}"
        )


@overload
def get_command(
    command_id: str,
    *,
    allowlist: Iterable[str] | None = None,
    required: Literal[True] = True,
) -> CommandBackend: ...


@overload
def get_command(
    command_id: str,
    *,
    allowlist: Iterable[str] | None = None,
    required: Literal[False],
) -> CommandBackend | None: ...


def get_command(
    command_id: str,
    *,
    allowlist: Iterable[str] | None = None,
    required: bool = True,
) -> CommandBackend | None:
    if command_id.lower() in RESERVED_COMMAND_IDS:
        raise ConfigError(f"Command id {command_id!r} is reserved.")
    try:
        backend = load_entrypoint(
            COMMAND_GROUP,
            command_id,
            allowlist=allowlist,
            validator=_validate_command_backend,
        )
    except PluginNotFound as exc:
        if not required:
            return None
        if exc.available:
            available = ", ".join(exc.available)
            message = f"Unknown command {command_id!r}. Available: {available}."
        else:
            message = f"Unknown command {command_id!r}."
        raise ConfigError(message) from exc
    except PluginLoadFailed as exc:
        raise ConfigError(f"Failed to load command {command_id!r}: {exc}") from exc
    return backend


def list_command_ids(*, allowlist: Iterable[str] | None = None) -> list[str]:
    return list_ids(
        COMMAND_GROUP,
        allowlist=allowlist,
        reserved_ids=RESERVED_COMMAND_IDS,
    )
