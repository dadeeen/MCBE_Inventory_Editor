"""In-process cooperative presence tracking for browser sessions.

This is intentionally lightweight.  It is not a security boundary and it is not
used to permit or deny writes; optimistic player revisions and per-world locks do
that.  Presence only helps users notice when another browser session has the same
world open so they can coordinate before editing.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
_MAX_LABEL_LEN = 80
_MAX_SESSIONS_PER_SNAPSHOT = 8
LOGGER = logging.getLogger("mcbe_editor")


def _presence_now() -> float:
    """Return a monotonic timestamp for presence TTL calculations."""
    return time.monotonic()


def normalize_world_key(world_path: str) -> str:
    """Return a stable key for a world path, resolving symlinks/aliases."""
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(world_path))))


def normalize_session_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Feld 'session_id' muss ein Textwert sein.")
    session_id = value.strip()
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError("Ungültige Sitzungs-ID.")
    return session_id


def _short_text(value: Any, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    if len(value) > _MAX_LABEL_LEN:
        return value[: _MAX_LABEL_LEN - 1] + "…"
    return value


@dataclass
class PresenceSession:
    session_id: str
    world_key: str
    world_path: str
    player_key: str
    player_label: str
    dirty: bool
    created_at: float
    updated_at: float


class WorldPresenceTracker:
    def __init__(self, ttl_seconds: float = 45.0, logger: Any | None = None):
        self.ttl_seconds = ttl_seconds
        self._logger = LOGGER if logger is None else logger
        self._sessions: dict[str, PresenceSession] = {}
        self._lock = threading.RLock()
        self._cleanup_stop = threading.Event()
        self._cleanup_thread: threading.Thread | None = None

    def _session_player_label(self, session: PresenceSession) -> str:
        return session.player_label or "Spieler nicht gewählt"

    def _log_connected(self, session: PresenceSession) -> None:
        if not self._logger:
            return
        self._logger.info(
            "presence connected session_id=%s world=%s player=%s dirty=%s",
            session.session_id,
            session.world_path,
            self._session_player_label(session),
            bool(session.dirty),
        )

    def _log_disconnected(self, session: PresenceSession, reason: str, now: float) -> None:
        if not self._logger:
            return
        self._logger.info(
            "presence disconnected session_id=%s reason=%s world=%s player=%s dirty=%s idle_seconds=%s",
            session.session_id,
            reason,
            session.world_path,
            self._session_player_label(session),
            bool(session.dirty),
            max(0, int(now - session.updated_at)),
        )

    def _cleanup_locked(self, now: float):
        expired = [sess for sess in self._sessions.values() if now - sess.updated_at > self.ttl_seconds]
        for sess in expired:
            self._sessions.pop(sess.session_id, None)
            self._log_disconnected(sess, "timeout", now)
        return len(expired)

    def cleanup(self, *, now: float | None = None) -> int:
        now = _presence_now() if now is None else float(now)
        with self._lock:
            return self._cleanup_locked(now)

    def start_cleanup_thread(self, interval_seconds: float | None = None) -> None:
        interval = self.ttl_seconds if interval_seconds is None else float(interval_seconds)
        interval = max(1.0, min(interval, self.ttl_seconds))
        with self._lock:
            if self._cleanup_thread and self._cleanup_thread.is_alive():
                return
            self._cleanup_stop.clear()

            def run() -> None:
                while not self._cleanup_stop.wait(interval):
                    try:
                        self.cleanup()
                    except Exception:
                        if self._logger:
                            self._logger.exception("presence cleanup failed")

            self._cleanup_thread = threading.Thread(
                target=run,
                name="mcbe-presence-cleanup",
                daemon=True,
            )
            self._cleanup_thread.start()

    def stop_cleanup_thread(self) -> None:
        self._cleanup_stop.set()
        thread = self._cleanup_thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def touch(
        self,
        session_id: str,
        world_path: str,
        *,
        player_key: Any = "",
        player_label: Any = "",
        dirty: bool = False,
        now: float | None = None,
    ) -> dict:
        now = _presence_now() if now is None else float(now)
        session_id = normalize_session_id(session_id)
        world_key = normalize_world_key(world_path)
        player_key_text = _short_text(player_key)
        player_label_text = _short_text(player_label) or ("Spieler" if player_key_text else "")
        with self._lock:
            self._cleanup_locked(now)
            existing = self._sessions.get(session_id)
            # A browser tab may select another world while keeping its session
            # ID. The presence age belongs to the world visit, not to the tab's
            # lifetime across unrelated worlds.
            created_at = existing.created_at if existing and existing.world_key == world_key else now
            current = PresenceSession(
                session_id=session_id,
                world_key=world_key,
                world_path=world_path,
                player_key=player_key_text,
                player_label=player_label_text,
                dirty=bool(dirty),
                created_at=created_at,
                updated_at=now,
            )
            self._sessions[session_id] = current
            if existing is None:
                self._log_connected(current)
            elif existing.world_key != world_key:
                self._log_disconnected(existing, "world_change", now)
                self._log_connected(current)
            return self.snapshot(session_id, world_path, player_key=player_key_text, now=now)

    def leave(self, session_id: str, *, now: float | None = None) -> dict:
        now = _presence_now() if now is None else float(now)
        session_id = normalize_session_id(session_id)
        with self._lock:
            self._cleanup_locked(now)
            removed = self._sessions.pop(session_id, None)
            if removed is not None:
                self._log_disconnected(removed, "leave", now)
        return {
            "success": True,
            "other_sessions": 0,
            "other_dirty_sessions": 0,
            "same_player_sessions": 0,
            "same_player_dirty_sessions": 0,
            "sessions": [],
            "ttl_seconds": self.ttl_seconds,
        }

    def conflict_summary(
        self,
        session_id: str | None,
        world_path: str,
        *,
        player_key: Any = "",
        same_player_only: bool = False,
        now: float | None = None,
    ) -> dict:
        """Return a write-conflict summary based on other dirty browser sessions.

        This is a cooperative safety rail for small LAN use, not a security
        primitive.  Revision checks and service locks remain the authoritative
        protection against stale writes.
        """
        now = _presence_now() if now is None else float(now)
        world_key = normalize_world_key(world_path)
        player_key_text = _short_text(player_key)
        normalized_session_id = None
        if session_id:
            try:
                normalized_session_id = normalize_session_id(session_id)
            except ValueError:
                normalized_session_id = None
        with self._lock:
            self._cleanup_locked(now)
            others = [sess for sess in self._sessions.values() if sess.world_key == world_key and sess.session_id != normalized_session_id]
            relevant = [sess for sess in others if player_key_text and sess.player_key and sess.player_key == player_key_text] if same_player_only else others
            dirty_relevant = [sess for sess in relevant if sess.dirty]
            return {
                "enabled": True,
                "conflict": bool(dirty_relevant),
                "same_player_only": bool(same_player_only),
                "other_sessions": len(others),
                "relevant_sessions": len(relevant),
                "dirty_relevant_sessions": len(dirty_relevant),
                "ttl_seconds": self.ttl_seconds,
                "sessions": [
                    {
                        "player_label": sess.player_label or "Spieler nicht gewählt",
                        "same_player": bool(player_key_text and sess.player_key == player_key_text),
                        "dirty": bool(sess.dirty),
                        "idle_seconds": max(0, int(now - sess.updated_at)),
                    }
                    for sess in dirty_relevant[:_MAX_SESSIONS_PER_SNAPSHOT]
                ],
            }

    def snapshot(self, session_id: str, world_path: str, *, player_key: Any = "", now: float | None = None) -> dict:
        now = _presence_now() if now is None else float(now)
        session_id = normalize_session_id(session_id)
        world_key = normalize_world_key(world_path)
        player_key_text = _short_text(player_key)
        with self._lock:
            self._cleanup_locked(now)
            others = [sess for sess in self._sessions.values() if sess.session_id != session_id and sess.world_key == world_key]
            same_player = [sess for sess in others if player_key_text and sess.player_key and sess.player_key == player_key_text]
            others.sort(key=lambda sess: sess.updated_at, reverse=True)
            session_summaries = []
            for sess in others[:_MAX_SESSIONS_PER_SNAPSHOT]:
                session_summaries.append(
                    {
                        "player_label": sess.player_label or "Spieler nicht gewählt",
                        "same_player": bool(player_key_text and sess.player_key == player_key_text),
                        "dirty": bool(sess.dirty),
                        "age_seconds": max(0, int(now - sess.created_at)),
                        "idle_seconds": max(0, int(now - sess.updated_at)),
                    }
                )
            return {
                "success": True,
                "other_sessions": len(others),
                "other_dirty_sessions": sum(1 for sess in others if sess.dirty),
                "same_player_sessions": len(same_player),
                "same_player_dirty_sessions": sum(1 for sess in same_player if sess.dirty),
                "sessions": session_summaries,
                "ttl_seconds": self.ttl_seconds,
            }
