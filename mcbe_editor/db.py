import logging
import sys
from collections.abc import Callable
from typing import Protocol

from .leveldb_readonly import ReadonlyLevelDbAdapter
from .leveldb_writer import LevelDbWriter
from .service_errors import LevelDbPermissionError

__all__ = [
    "BedrockDb",
    "LevelDbAdapter",
    "LevelDbPermissionError",
    "ReadonlyLevelDbAdapter",
    "close_db_preserving_active_exception",
]

LOGGER = logging.getLogger(__name__)


def _raise_translated_permission_error(exc: Exception, *, operation: str, db_path: str) -> None:
    """Raise a stable service error for operating-system access-denied failures."""

    if isinstance(exc, PermissionError) and not isinstance(exc, LevelDbPermissionError):
        raise LevelDbPermissionError(operation=operation, db_path=db_path) from exc


class BedrockDb(Protocol):
    def get(self, key: bytes) -> bytes: ...

    def put(self, key: bytes, value: bytes) -> None: ...

    def put_batch(self, data: dict[bytes, bytes | None]) -> None: ...

    def close(self) -> None: ...

    def iter_items(self): ...


def close_db_preserving_active_exception(db: BedrockDb | None, *, context: str) -> None:
    """Close ``db`` without replacing an exception already being propagated.

    A cleanup failure is still raised when the surrounding operation otherwise
    completed normally.  During exception unwinding, however, the original
    exception carries the useful failure reason and must remain the one exposed
    to callers; the close failure is logged as secondary diagnostic context.
    """

    if db is None:
        return
    active_exception = sys.exc_info()[1]
    try:
        db.close()
    except Exception:
        if active_exception is None:
            raise
        LOGGER.exception("Datenbank konnte beim Aufräumen nicht geschlossen werden (%s).", context)


class LevelDbAdapter:
    """Write session with an optional explicitly bound application write gate.

    Storage is handled by the pure-Python ``LevelDbWriter``: it locks the
    database like Mojang's engine and appends each batch atomically to a new
    write-ahead log that Minecraft integrates on its next open.
    ``write_guard=None`` is the offline-tool default; it applies no web policy.
    Web composition must supply its own guard, which stays bound to this session.
    """

    def __init__(self, db_path: str, *, write_guard: Callable[[str], None] | None = None):
        self._write_guard = write_guard
        self._check_write_allowed("LevelDB-Öffnen")
        self._db_path = str(db_path)
        try:
            self._db = LevelDbWriter(self._db_path)
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Öffnen", db_path=self._db_path)
            raise

    def _check_write_allowed(self, action_label: str) -> None:
        if self._write_guard is not None:
            self._write_guard(action_label)

    def get(self, key: bytes) -> bytes:
        try:
            return self._db.get(key)
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Lesen", db_path=self._db_path)
            raise

    def put(self, key: bytes, value: bytes) -> None:
        self._check_write_allowed("LevelDB-Schreiben")
        try:
            self._db.put(key, value)
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Schreiben", db_path=self._db_path)
            raise

    def put_batch(self, data: dict[bytes, bytes | None]) -> None:
        self._check_write_allowed("LevelDB-Batch-Schreiben")
        try:
            self._db.put_batch(data)
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Batch-Schreiben", db_path=self._db_path)
            raise

    def close(self) -> None:
        try:
            self._db.close()
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Schließen", db_path=self._db_path)
            raise

    def iter_items(self):
        return self._db.iter_items()

    def committed_change(self):
        return self._db.committed_change()

    def last_write_reached_log(self) -> bool:
        # A gate rejection returns before the writer runs; its flag is then the
        # previous call's, which is either correct (False) or conservative.
        return self._db.last_write_reached_log()
