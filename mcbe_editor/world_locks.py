"""Per-world locks shared across threads and application processes."""

from __future__ import annotations

import errno
import hashlib
import os
import tempfile
import threading
import time
import weakref
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from types import ModuleType
from typing import BinaryIO

from .config import load_config

fcntl: ModuleType | None
try:  # pragma: no cover - platform-dependent import
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
else:  # pragma: no cover - POSIX
    fcntl = _fcntl

msvcrt: ModuleType | None
try:  # pragma: no cover - platform-dependent import
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None
else:  # pragma: no cover - Windows
    msvcrt = _msvcrt

_WORLD_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_OPERATION_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_WORLD_LOCKS_GUARD = threading.Lock()


@dataclass
class _FileLockState:
    handle: BinaryIO
    pid: int
    depth: int = 1


_FILE_LOCK_STATES: dict[str, _FileLockState] = {}


def lock_key(world_path: str) -> str:
    """Return a canonical key so textual aliases share one world lock."""

    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(world_path))))


def get_world_lock(world_path: str) -> threading.RLock:
    key = lock_key(world_path)
    with _WORLD_LOCKS_GUARD:
        lock = _WORLD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _WORLD_LOCKS[key] = lock
        return lock


def _get_operation_lock(key: str) -> threading.RLock:
    with _WORLD_LOCKS_GUARD:
        lock = _OPERATION_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _OPERATION_LOCKS[key] = lock
        return lock


def interprocess_lock_path(world_path: str) -> str:
    """Return the shared lock file used by all processes for one world.

    The lock lives in app-owned storage rather than inside the world directory,
    because restore replaces that directory atomically.  Deployments that share
    a world must share ``MCBE_BACKUP_ROOT`` (or, when unset,
    ``MCBE_DATA_ROOT``) and use the same normalized world path.
    """

    config = load_config()
    root = config.backup_root or config.data_root or os.path.join(tempfile.gettempdir(), "mcbe_inventory_editor")
    digest = hashlib.sha256(lock_key(world_path).encode("utf-8", errors="surrogatepass")).hexdigest()
    return os.path.join(os.path.abspath(os.path.normpath(root)), ".world_locks", f"{digest}.lock")


def operation_lock_path(name: str, *, root: str | os.PathLike[str] | None = None) -> str:
    """Return a stable lock-file path for an app-wide named operation."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Operationssperre benötigt einen Namen.")
    if root is None:
        config = load_config()
        root = config.data_root or config.backup_root or os.path.join(tempfile.gettempdir(), "mcbe_inventory_editor")
    normalized_root = os.path.realpath(os.path.abspath(os.path.normpath(root)))
    normalized_name = name.strip().casefold()
    digest = hashlib.sha256(f"{normalized_root}\0{normalized_name}".encode("utf-8", errors="surrogatepass")).hexdigest()
    return os.path.join(normalized_root, ".operation_locks", f"{digest}.lock")


def _acquire_os_lock(handle: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    if msvcrt is not None:  # pragma: no branch - only one backend exists per platform
        # Reading byte 0 while another process owns the byte-range lock raises
        # PermissionError on Windows. Inspecting the file size does not touch the
        # locked range and lets the normal LK_NBLCK retry loop do the waiting.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} and getattr(exc, "winerror", None) not in {33, 36}:
                    raise
                time.sleep(0.05)
    raise RuntimeError("Diese Plattform unterstützt keine prozessübergreifende Dateisperre.")


def _release_os_lock(handle: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:  # pragma: no branch - only one backend exists per platform
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    raise RuntimeError("Diese Plattform unterstützt keine prozessübergreifende Dateisperre.")


def _enter_file_lock(key: str, path: str) -> None:
    state = _FILE_LOCK_STATES.get(key)
    current_pid = os.getpid()
    if state is not None and state.pid == current_pid:
        state.depth += 1
        return
    if state is not None:
        # A fork can inherit Python state and an open descriptor from its
        # parent. Treat it as foreign state; the child must acquire its own
        # lock instead of incorrectly considering the section reentrant.
        with suppress(OSError):
            state.handle.close()
        del _FILE_LOCK_STATES[key]

    os.makedirs(os.path.dirname(path), exist_ok=True)
    # The handle intentionally stays open for the complete critical section.
    handle = open(path, "a+b")  # noqa: SIM115
    try:
        _acquire_os_lock(handle)
    except BaseException:
        with suppress(OSError):
            handle.close()
        raise
    _FILE_LOCK_STATES[key] = _FileLockState(handle=handle, pid=current_pid)


def _exit_file_lock(key: str) -> None:
    state = _FILE_LOCK_STATES[key]
    state.depth -= 1
    if state.depth:
        return
    try:
        _release_os_lock(state.handle)
    finally:
        try:
            state.handle.close()
        finally:
            # A close failure must not leave reentrant state behind. Otherwise
            # the next acquisition in this process would increment ``depth``
            # without taking a new operating-system lock.
            del _FILE_LOCK_STATES[key]


@contextmanager
def locked_world(world_path: str) -> Iterator[None]:
    """Serialize one world's reads/writes across threads and processes."""

    key = lock_key(world_path)
    lock = get_world_lock(world_path)
    lock.acquire()
    try:
        _enter_file_lock(key, interprocess_lock_path(world_path))
        try:
            yield
        finally:
            _exit_file_lock(key)
    finally:
        lock.release()


@contextmanager
def locked_operation(name: str, *, root: str | os.PathLike[str] | None = None) -> Iterator[None]:
    """Serialize one app-wide mutation across threads and worker processes."""

    path = operation_lock_path(name, root=root)
    key = f"operation:{lock_key(path)}"
    lock = _get_operation_lock(key)
    lock.acquire()
    try:
        _enter_file_lock(key, path)
        try:
            yield
        finally:
            _exit_file_lock(key)
    finally:
        lock.release()
