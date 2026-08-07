import logging
import sys
from collections.abc import Callable
from typing import Protocol

from .leveldb_readonly import ReadonlyLevelDbAdapter
from .service_errors import LevelDbPermissionError

__all__ = [
    "BedrockDb",
    "LevelDbAdapter",
    "LevelDbPermissionError",
    "ReadonlyLevelDbAdapter",
    "close_db_preserving_active_exception",
    "register_runtime_leveldb_write_guard",
]

LOGGER = logging.getLogger(__name__)

_registered_write_guard: Callable[[str], None] | None = None
_PERMISSION_ERROR_MARKERS = (
    "permission denied",
    "operation not permitted",
    "access is denied",
    "access denied",
    "zugriff verweigert",
)


def _native_error_text(exc: Exception) -> str:
    """Decode native LevelDB byte messages without leaking their repr syntax."""

    parts = []
    for value in exc.args or (exc,):
        if isinstance(value, bytes):
            parts.append(value.decode("utf-8", errors="replace"))
        else:
            parts.append(str(value))
    return " ".join(parts)


def _raise_translated_permission_error(exc: Exception, *, operation: str, db_path: str) -> None:
    """Raise a stable PermissionError only for native access-denied failures."""

    message = _native_error_text(exc).casefold()
    if isinstance(exc, PermissionError) or any(marker in message for marker in _PERMISSION_ERROR_MARKERS):
        raise LevelDbPermissionError(operation=operation, db_path=db_path) from exc


def register_runtime_leveldb_write_guard(guard: Callable[[str], None] | None) -> None:
    """Register the web app's final write gate explicitly.

    The sys.modules lookup below only finds the guard when the Flask app runs
    as ``main``/``__main__``.  Deployments that import the app under another
    module name (z. B. ein WSGI-Wrapper) must register the guard here so the
    final write gate cannot silently disappear.
    """

    global _registered_write_guard
    _registered_write_guard = guard


def _runtime_app_modules():
    """Yield possible Flask app modules for direct and imported execution."""

    seen = set()
    for module_name in ("main", "__main__"):
        module = sys.modules.get(module_name)
        if module is None or id(module) in seen:
            continue
        seen.add(id(module))
        yield module


def _run_runtime_leveldb_write_guard(action_label: str = "LevelDB-Schreiben") -> None:
    """Run the Flask app's final write gate before mutating LevelDB access.

    Opening amulet-leveldb is not a pure read operation for Bedrock worlds: the
    engine can acquire LOCK and replay/refresh LevelDB metadata.  Therefore the
    web app must run the same final write gate before constructing the mutating
    adapter as it runs before put().  Non-web tools keep the historical behavior
    because no runtime Flask app module with the guard is loaded there.
    """

    # Modul-Lookup zuerst: Tests ersetzen sys.modules["main"] gezielt, und der
    # historische Pfad bleibt so unverändert.  Der registrierte Hook greift,
    # wenn die App unter einem anderen Modulnamen läuft.
    for module in _runtime_app_modules():
        guard = getattr(module, "require_final_world_write_allowed", None)
        if guard is None:
            continue
        guard(action_label)
        return
    if _registered_write_guard is not None:
        _registered_write_guard(action_label)


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
    """Thin wrapper around amulet-leveldb (Mojang's custom LevelDB fork).

    The amulet-leveldb package provides pre-built wheels so no C++ compiler is
    needed at install time, and it supports encrypted Bedrock worlds as well.
    """

    def __init__(self, db_path: str):
        _run_runtime_leveldb_write_guard("LevelDB-Öffnen")
        try:
            import leveldb
        except ImportError as exc:
            raise RuntimeError("Abhängigkeit fehlt: 'amulet-leveldb'. Installiere es mit: pip install amulet-leveldb") from exc

        self._db_path = str(db_path)
        try:
            self._db = leveldb.LevelDB(db_path)
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Öffnen", db_path=self._db_path)
            raise

    def get(self, key: bytes) -> bytes:
        try:
            return self._db.get(key)
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Lesen", db_path=self._db_path)
            raise

    def put(self, key: bytes, value: bytes) -> None:
        _run_runtime_leveldb_write_guard("LevelDB-Schreiben")
        try:
            self._db.put(key, value)
        except Exception as exc:
            _raise_translated_permission_error(exc, operation="Schreiben", db_path=self._db_path)
            raise

    def put_batch(self, data: dict[bytes, bytes | None]) -> None:
        _run_runtime_leveldb_write_guard("LevelDB-Batch-Schreiben")
        try:
            self._db.putBatch(data)
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
        return self._db.items()
