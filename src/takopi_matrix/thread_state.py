"""Per-thread state store for Matrix."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from takopi.api import ResumeToken

from .state_store import JsonStateStore

STATE_VERSION = 1
STATE_FILENAME = "matrix_thread_state.json"


@dataclass
class _ThreadState:
    version: int
    rooms: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)


def resolve_thread_state_path(config_path: Path) -> Path:
    """Get the path for thread state file, adjacent to config."""
    return config_path.with_name(STATE_FILENAME)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _normalize_engine_id(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    return value or None


def _new_thread_entry() -> dict[str, Any]:
    # Keep the full per-thread schema here so future phases can add methods
    # without requiring a state shape migration.
    return {
        "context_project": None,
        "context_branch": None,
        "default_engine": None,
        "trigger_mode": None,
        "engine_overrides": {},
        "sessions": {},
    }


def _new_state() -> _ThreadState:
    return _ThreadState(version=STATE_VERSION, rooms={})


class MatrixThreadStateStore(JsonStateStore[_ThreadState]):
    """Store per-thread state and resume tokens.

    Scope: room_id + thread_root_event_id + engine.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(
            path,
            version=STATE_VERSION,
            state_type=_ThreadState,
            state_factory=_new_state,
            log_prefix="matrix.thread_state",
        )

    async def get_session_resume(
        self, room_id: str, thread_root_event_id: str, engine: str
    ) -> ResumeToken | None:
        thread_key = _normalize_text(thread_root_event_id)
        engine_key = _normalize_engine_id(engine)
        if thread_key is None or engine_key is None:
            return None
        async with self._lock:
            self._reload_locked_if_needed()
            room = self._state.rooms.get(room_id)
            if not isinstance(room, dict):
                return None
            thread_state = room.get(thread_key)
            if not isinstance(thread_state, dict):
                return None
            sessions = thread_state.get("sessions")
            if not isinstance(sessions, dict):
                return None
            resume = sessions.get(engine_key)
            if not isinstance(resume, str) or not resume:
                return None
            return ResumeToken(engine=engine_key, value=resume)

    async def set_session_resume(
        self, room_id: str, thread_root_event_id: str, token: ResumeToken
    ) -> None:
        thread_key = _normalize_text(thread_root_event_id)
        engine_key = _normalize_engine_id(token.engine)
        resume_value = _normalize_text(token.value)
        if thread_key is None or engine_key is None or resume_value is None:
            return
        async with self._lock:
            self._reload_locked_if_needed()
            thread_state = self._ensure_thread_locked(room_id, thread_key)
            sessions = thread_state.get("sessions")
            if not isinstance(sessions, dict):
                sessions = {}
                thread_state["sessions"] = sessions
            sessions[engine_key] = resume_value
            self._save_locked()

    async def clear_sessions(self, room_id: str, thread_root_event_id: str) -> None:
        thread_key = _normalize_text(thread_root_event_id)
        if thread_key is None:
            return
        async with self._lock:
            self._reload_locked_if_needed()
            room = self._state.rooms.get(room_id)
            if not isinstance(room, dict):
                return
            thread_state = room.get(thread_key)
            if not isinstance(thread_state, dict):
                return
            thread_state["sessions"] = {}
            if self._thread_is_empty(thread_state):
                room.pop(thread_key, None)
            if not room:
                self._state.rooms.pop(room_id, None)
            self._save_locked()

    def _ensure_thread_locked(
        self, room_id: str, thread_root_event_id: str
    ) -> dict[str, Any]:
        room = self._state.rooms.get(room_id)
        if not isinstance(room, dict):
            room = {}
            self._state.rooms[room_id] = room
        thread_state = room.get(thread_root_event_id)
        if isinstance(thread_state, dict):
            return thread_state
        thread_state = _new_thread_entry()
        room[thread_root_event_id] = thread_state
        return thread_state

    @staticmethod
    def _thread_is_empty(thread_state: dict[str, Any]) -> bool:
        if _normalize_text(thread_state.get("context_project")) is not None:
            return False
        if _normalize_text(thread_state.get("context_branch")) is not None:
            return False
        if _normalize_text(thread_state.get("default_engine")) is not None:
            return False
        if _normalize_text(thread_state.get("trigger_mode")) is not None:
            return False
        overrides = thread_state.get("engine_overrides")
        if isinstance(overrides, dict) and overrides:
            return False
        sessions = thread_state.get("sessions")
        return not (isinstance(sessions, dict) and sessions)
