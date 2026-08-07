from __future__ import annotations

import os
import secrets
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700
BUNDLED_ITEM_DB_RELATIVE_PATH = Path("mcbe_editor") / "resources" / "item_db.json"
BUNDLED_ITEM_DB_JSON = Path(__file__).resolve().parents[1] / BUNDLED_ITEM_DB_RELATIVE_PATH
_FCHMOD: Callable[[int, int], None] | None = getattr(os, "fchmod", None)


def _private_open_flags(flags: int) -> int:
    return flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _restrict_private_fd(fd: int) -> None:
    if _FCHMOD is not None:
        _FCHMOD(fd, PRIVATE_FILE_MODE)


def ensure_private_parent(path: Path) -> None:
    """Create a sensitive file's direct parent without broadening existing ACLs."""
    parent = path.parent
    created = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    if created and os.name != "nt":
        parent.chmod(PRIVATE_DIRECTORY_MODE)


def ensure_private_directory(path: Path) -> None:
    """Create or restrict an application-owned directory for sensitive data."""
    path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    if os.name != "nt":
        path.chmod(PRIVATE_DIRECTORY_MODE)


def restrict_private_file(path: Path) -> None:
    """Restrict an existing sensitive file on POSIX.

    Windows has no stdlib API for replacing inherited ACLs safely. There the
    file keeps the ACL of its application data directory; POSIX deployments
    additionally get an explicit owner-only mode.
    """
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != PRIVATE_FILE_MODE:
        path.chmod(PRIVATE_FILE_MODE)


def atomic_write_private_text(path: Path, text: str) -> None:
    """Atomically replace a sensitive UTF-8 text file with owner-only access."""
    ensure_private_parent(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    flags = _private_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    fd = os.open(tmp, flags, PRIVATE_FILE_MODE)
    try:
        _restrict_private_fd(fd)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        restrict_private_file(path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        tmp.unlink(missing_ok=True)
        raise


def append_private_text(path: Path, text: str) -> None:
    """Append UTF-8 text while creating or correcting the file as mode 0600."""
    ensure_private_parent(path)
    flags = _private_open_flags(os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    fd = os.open(path, flags, PRIVATE_FILE_MODE)
    try:
        _restrict_private_fd(fd)
        with os.fdopen(fd, "a", encoding="utf-8", newline="") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_seed_file(source: Path, target: Path) -> None:
    """Publish a bundled file once without exposing a partial target.

    Multiple application processes can reach first-run seeding concurrently.
    Serialize only the final publication and keep the first complete target;
    later seeders discard their private temporary copies instead of replacing
    a file that may already be in use or may already have been updated.
    """
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    flags = _private_open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    fd = os.open(tmp, flags, 0o600)
    try:
        with source.open("rb") as source_handle, os.fdopen(fd, "wb") as target_handle:
            fd = -1
            shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        from mcbe_editor.world_locks import locked_operation

        with locked_operation(f"atomic-seed:{target.name}", root=target.parent):
            if not target.exists():
                os.replace(tmp, target)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    else:
        tmp.unlink(missing_ok=True)


def _resolved_runtime_path(path: str) -> Path:
    r"""Resolve a runtime path with stable Windows spelling.

    Windows can add the ``\\?\`` extended-path prefix when the target starts
    existing between concurrent ``Path.resolve`` calls.  Both spellings address
    the same file, but returning a stable form avoids process-start races in
    callers that compare or serialize the configured path.
    """

    resolved = Path(path).expanduser().resolve()
    if os.name != "nt":
        return resolved
    text = str(resolved)
    if text.startswith("\\\\?\\UNC\\"):
        return Path(f"\\\\{text[8:]}")
    if text.startswith("\\\\?\\"):
        return Path(text[4:])
    return resolved


def prepare_persistent_json_file(target_path: str | None, bundled_json: Path, expected_name: str) -> Path | None:
    """Copy a bundled JSON file into a writable runtime path when missing."""
    if not target_path:
        return None

    target = _resolved_runtime_path(target_path)
    if target.name != expected_name:
        raise ValueError(f"{expected_name} muss auf {expected_name} zeigen.")

    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() and bundled_json.exists():
        atomic_seed_file(bundled_json, target)

    return target


def prepare_persistent_item_db(item_db_path: str | None, bundled_item_db_json: Path) -> Path | None:
    """Prepare a persistent JSON item database.

    Docker images are immutable from an operational point of view: changes inside
    /app disappear when the container is recreated. When MCBE_ITEM_DB_PATH is set,
    keep the user-updated item database as JSON in that writable path. A legacy
    Only JSON is accepted. Older ``item_db.py`` compatibility has been removed so
    no runtime path can accidentally point at generated Python code.
    """
    if not item_db_path:
        return None

    target = prepare_persistent_json_file(item_db_path, bundled_item_db_json, "item_db.json")
    if target is None:
        return None

    os.environ["MCBE_ITEM_DB_PATH"] = str(target)
    return target
