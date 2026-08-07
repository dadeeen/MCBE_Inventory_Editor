"""Shared server-guard generation for snapshot-to-write integrity checks."""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from .runtime_data import atomic_write_private_text
from .world_locks import locked_operation


@dataclass(frozen=True)
class ServerGuardObservation:
    """Guard tokens immediately before and after one server observation."""

    previous_token: str
    token: str


class ServerGuardStore:
    """Maintain an opaque guard token shared by all application workers.

    Every process rotates the shared token once before its first use. This
    invalidates snapshots held by browser tabs across backend restarts. Later
    reads always use the shared file, so workers converge on the newest token.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._initialized = False
        self._lock = threading.RLock()

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(32)

    def _read_unlocked(self) -> str:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, RecursionError):
            return ""
        token = payload.get("token") if isinstance(payload, dict) else ""
        return token.strip() if isinstance(token, str) else ""

    def _write_unlocked(self, token: str) -> None:
        payload = json.dumps({"version": 1, "token": token}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        atomic_write_private_text(self.path, payload)

    def _initialize_unlocked(self) -> str:
        token = self._new_token()
        self._write_unlocked(token)
        self._initialized = True
        return token

    def current(self) -> str:
        """Return the current shared token, rotating once for this process."""

        with self._lock, locked_operation("server-guard-state", root=self.path.parent):
            if not self._initialized:
                return self._initialize_unlocked()
            token = self._read_unlocked()
            if token:
                return token
            return self._initialize_unlocked()

    def observe(self, *, online: bool) -> ServerGuardObservation:
        """Capture the shared token and rotate it for an online observation."""

        with self._lock, locked_operation("server-guard-state", root=self.path.parent):
            if not self._initialized:
                current = self._initialize_unlocked()
            else:
                current = self._read_unlocked()
                if not current:
                    current = self._initialize_unlocked()
            previous = current
            if online:
                current = self._new_token()
                self._write_unlocked(current)
            return ServerGuardObservation(previous_token=previous, token=current)
