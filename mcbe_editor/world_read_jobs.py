"""Bounded, resumable read jobs with private cross-process result storage.

Only the two world/player read routes opt in. A client-generated identifier
deduplicates retries even when the initial HTTP response is lost. Short polls
renew a lease; abandoned reads stop at cooperative checkpoints. Results expire
and are scoped to the requesting CSRF session, never a persistent world cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from .read_operation import ReadStoppedError, observe
from .runtime_data import atomic_write_private_text, ensure_private_directory
from .world_locks import locked_operation

LOGGER = logging.getLogger(__name__)
READ_ID_HEADER = "X-MCBE-Read-ID"
_ID = re.compile(r"[0-9a-f]{32}")
_MAX_CANCELLED_READS = 64
JsonObject = dict[str, Any]


class ReadJobError(ValueError):
    def __init__(self, message: str, status: int, code: str):
        super().__init__(message)
        self.status = status
        self.code = code


class WorldReadJobs:
    def __init__(self, directory: Path, *, limit: int = 2, timeout: float = 300, lease: float = 45, retention: float = 60):
        self.directory = directory
        self.limit = limit
        self.timeout = timeout
        self.lease = lease
        self.retention = retention
        self._slots = threading.BoundedSemaphore(limit)

    def _path(self, identifier: str) -> Path:
        if not _ID.fullmatch(identifier):
            raise ReadJobError("Ungültige Lade-ID.", 400, "invalid_read_id")
        return self.directory / f"{identifier}.json"

    @staticmethod
    def _owner(owner: str) -> str:
        return hashlib.sha256(owner.encode()).hexdigest()

    def _load(self, path: Path, owner: str) -> JsonObject:
        try:
            data: JsonObject = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ReadJobError("Der Ladevorgang ist abgelaufen. Lade die Welt erneut.", 404, "read_job_expired") from exc
        if data["owner"] != self._owner(owner):
            raise ReadJobError("Der Ladevorgang ist abgelaufen. Lade die Welt erneut.", 404, "read_job_expired")
        return data

    def _write(self, path: Path, data: JsonObject) -> None:
        atomic_write_private_text(path, json.dumps(data, ensure_ascii=False))

    def _lock(self) -> AbstractContextManager[None]:
        return locked_operation("world-read-jobs", root=self.directory)

    def _expire(self, data: JsonObject, now: float) -> bool:
        """Apply the same terminal transition during polling, work and admission."""
        if data["state"] != "running":
            return False
        deadline, code = min(
            (data["created"] + self.timeout, "read_timeout"),
            (data["updated"] + self.lease, "read_timeout"),
            (data["observed"] + self.lease, "read_cancelled"),
        )
        if now > deadline:
            self._stop(data, code, finished=deadline)
            return True
        return False

    def _expired_result(self, data: JsonObject, now: float) -> bool:
        return bool(data["state"] == "done" and now > data.get("cancel_until", data["finished"] + self.retention))

    def _sweep(self, now: float) -> tuple[int, int]:
        active = 0
        cancelled = 0
        completed = []
        for path in self.directory.glob("*.json"):
            if not _ID.fullmatch(path.stem):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            changed = self._expire(data, now)
            if self._expired_result(data, now):
                path.unlink(missing_ok=True)
                continue
            if changed:
                self._write(path, data)
            if data["state"] == "running":
                active += 1
            elif "cancel_until" in data:
                cancelled += 1
            else:
                completed.append((data["finished"], path))
        # Bound retained payloads as well as active threads. A missing result is
        # an explicit expiry, never a successful empty world.
        for _finished, path in sorted(completed)[:-64]:
            path.unlink(missing_ok=True)
        return active, cancelled

    def start(self, identifier: str, owner: str, identity: str, work: Callable[[], tuple[JsonObject, int]]) -> tuple[JsonObject, int]:
        path = self._path(identifier)
        identity_hash = hashlib.sha256(identity.encode()).hexdigest()
        ensure_private_directory(self.directory)
        with self._lock():
            if path.exists():
                data = self._load(path, owner)
                if data["identity"] is not None and data["identity"] != identity_hash:
                    raise ReadJobError("Diese Lade-ID gehört zu einer anderen Anfrage.", 409, "read_id_conflict")
                return self._snapshot(path, data, renew=True)
            active, cancelled = self._sweep(time.time())
            self._check_cancellation_capacity(active, cancelled)
            if active >= self.limit or not self._slots.acquire(blocking=False):
                raise ReadJobError("Es laufen bereits mehrere Ladevorgänge. Versuche es gleich erneut.", 429, "read_jobs_busy")
            now = time.time()
            data = {
                "owner": self._owner(owner),
                "identity": identity_hash,
                "created": now,
                "observed": now,
                "updated": now,
                "state": "running",
                "phase": "waiting",
                "current": 0,
                "generation": secrets.token_hex(16),
            }
            try:
                self._write(path, data)
                thread = threading.Thread(target=self._run, args=(path, data["generation"], work), name="world-read", daemon=True)
                thread.start()
            except BaseException:
                path.unlink(missing_ok=True)
                self._slots.release()
                raise
            return self._public(path, data)

    def poll(self, identifier: str, owner: str, *, cancel: bool = False) -> tuple[JsonObject, int]:
        path = self._path(identifier)
        ensure_private_directory(self.directory)
        with self._lock():
            if cancel:
                return self._cancel(path, owner)
            data = self._load(path, owner)
            return self._snapshot(path, data, renew=True)

    def _cancel(self, path: Path, owner: str) -> tuple[JsonObject, int]:
        """Reserve an explicit cancellation under the shared lock, in any state."""
        # Authenticate before cleanup, including for expired results. A foreign
        # session must not remove an existing job or take over its identifier.
        data = self._load(path, owner) if path.exists() else None
        now = time.time()
        if data is not None and "cancel_until" in data and not self._expired_result(data, now):
            return self._public(path, data)  # Repeated DELETE must not extend retention.
        # A running job already owns a reservation slot. Missing and completed
        # jobs need admission before they can promise to block a delayed POST.
        if data is None or data["state"] != "running":
            self._check_cancellation_capacity(*self._sweep(now))
        if data is None:
            data = {"owner": self._owner(owner), "identity": None, "created": now, "generation": secrets.token_hex(16)}
        self._stop(data, "read_cancelled", finished=now)
        data["cancel_until"] = now + self.timeout + self.retention
        self._write(path, data)
        return self._public(path, data)

    def _snapshot(self, path: Path, data: JsonObject, *, renew: bool) -> tuple[JsonObject, int]:
        now = time.time()
        changed = self._expire(data, now)
        if self._expired_result(data, now):
            path.unlink(missing_ok=True)
            raise ReadJobError("Der Ladevorgang ist abgelaufen. Lade die Welt erneut.", 404, "read_job_expired")
        if data["state"] == "running" and renew:
            data["observed"] = now
            changed = True
        if changed:
            self._write(path, data)
        return self._public(path, data)

    @staticmethod
    def _check_cancellation_capacity(active: int, cancelled: int) -> None:
        # Every admitted worker must still be cancellable even at this bound.
        # Never evict a promised cancellation to make room for another request.
        if active + cancelled >= _MAX_CANCELLED_READS:
            raise ReadJobError("Es sind zu viele Leseaufträge vorgemerkt. Versuche es später erneut.", 429, "read_jobs_busy")

    @staticmethod
    def _stop(data: JsonObject, code: str, *, finished: float) -> None:
        data.update(state="done", finished=finished, status=408, result={"success": False, "code": code})

    @staticmethod
    def _public(path: Path, data: JsonObject) -> tuple[JsonObject, int]:
        if data["state"] == "done":
            return data["result"], data["status"]
        return {
            "success": True,
            "pending": True,
            "read_id": path.stem,
            "progress": {
                "phase": data["phase"],
                "current": data["current"],
                "elapsed_seconds": max(0, int(time.time() - data["created"])),
            },
        }, 202

    def _run(self, path: Path, generation: str, work: Callable[[], tuple[JsonObject, int]]) -> None:
        last_update = 0.0
        latest_current = 0

        def checkpoint(phase: str | None = None, *, current: int | None = None) -> None:
            nonlocal last_update, latest_current
            if current is not None:
                latest_current = current
            now = time.monotonic()
            if phase is None and now - last_update < 0.25:
                return
            with self._lock():
                if not path.exists():
                    raise ReadStoppedError()
                data = json.loads(path.read_text(encoding="utf-8"))
                if data["generation"] != generation or data["state"] != "running":
                    raise ReadStoppedError()
                self._snapshot(path, data, renew=False)
                if data["state"] != "running":
                    raise ReadStoppedError()
                if phase is not None:
                    data["phase"] = phase
                data["current"] = latest_current
                data["updated"] = time.time()
                self._write(path, data)
            last_update = now

        try:
            with observe(checkpoint):
                checkpoint()
                result, status = work()
                checkpoint("finishing")
            with self._lock():
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if data["generation"] == generation and data["state"] == "running":
                        self._snapshot(path, data, renew=False)
                    if data["generation"] == generation and data["state"] == "running":
                        data.update(state="done", finished=time.time(), result=result, status=status)
                        self._write(path, data)
        except ReadStoppedError:
            pass
        except Exception:
            LOGGER.exception("World read job failed")
            with self._lock():
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if data["generation"] == generation and data["state"] == "running":
                        data.update(state="done", finished=time.time(), status=500, result={"success": False, "code": "read_job_failed"})
                        self._write(path, data)
        finally:
            self._slots.release()
