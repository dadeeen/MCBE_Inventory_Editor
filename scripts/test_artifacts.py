"""Shared locations for disposable test-run artifacts."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_ARTIFACT_ROOT_ENV = "MCBE_TEST_ARTIFACT_ROOT"
DEFAULT_TEST_ARTIFACT_ROOT = Path(tempfile.gettempdir()) / "mcbe-inventory-editor-tests"
DEFAULT_TEST_ARTIFACT_RETENTION_SECONDS = 7 * 24 * 60 * 60
_UNIQUE_RUN_DIRECTORY = re.compile(r"^[a-z0-9_-]+-(?P<pid>[1-9][0-9]*)-[0-9a-f]{8}$")
_PLAYWRIGHT_RUN_DIRECTORY = re.compile(r"^playwright-(?P<pid>[1-9][0-9]*)$")


def test_artifact_root() -> Path:
    """Return an external root for test artifacts, rejecting checkout-local paths."""

    configured = os.environ.get(TEST_ARTIFACT_ROOT_ENV)
    candidate = Path(configured).expanduser() if configured else DEFAULT_TEST_ARTIFACT_ROOT
    resolved = candidate.resolve()
    repository = ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise RuntimeError(f"{TEST_ARTIFACT_ROOT_ENV} must point outside the repository: {resolved}")
    return resolved


def unique_test_artifact_path(label: str) -> Path:
    """Return a collision-resistant child path without creating it."""

    if not label or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in label):
        raise ValueError("test artifact labels must use lowercase ASCII letters, digits, '-' or '_'")
    return test_artifact_root() / f"{label}-{os.getpid()}-{secrets.token_hex(4)}"


def _artifact_run_pid(name: str) -> int | None:
    for pattern in (_UNIQUE_RUN_DIRECTORY, _PLAYWRIGHT_RUN_DIRECTORY):
        if match := pattern.fullmatch(name):
            return int(match.group("pid"))
    return None


def _windows_process_is_running(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_invalid_parameter = 87
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    get_exit_code_process = kernel32.GetExitCodeProcess
    get_exit_code_process.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    get_exit_code_process.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        # ERROR_INVALID_PARAMETER is returned for a PID that no longer exists.
        # Other failures are treated conservatively as a live process.
        return ctypes.get_last_error() != error_invalid_parameter
    try:
        exit_code = wintypes.DWORD()
        if not get_exit_code_process(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        close_handle(handle)


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def prune_stale_test_artifacts(
    *,
    protected: Iterable[Path] = (),
    now: float | None = None,
    max_age_seconds: float = DEFAULT_TEST_ARTIFACT_RETENTION_SECONDS,
) -> list[Path]:
    """Best-effort removal of expired, inactive test-run directories."""

    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be greater than zero")

    root = test_artifact_root()
    if not root.is_dir():
        return []
    root = root.resolve()
    protected_paths = {path.resolve() for path in protected}
    cutoff = (time.time() if now is None else now) - max_age_seconds
    removed: list[Path] = []

    try:
        candidates = list(root.iterdir())
    except OSError as exc:
        print(f"Warning: could not inspect stale test artifacts under {root}: {exc}", file=sys.stderr)
        return removed

    for candidate in candidates:
        pid = _artifact_run_pid(candidate.name)
        if pid is None:
            continue
        try:
            if candidate.is_symlink() or candidate.is_junction() or not candidate.is_dir():
                continue
            resolved = candidate.resolve()
            if resolved.parent != root or resolved in protected_paths:
                continue
            if candidate.stat(follow_symlinks=False).st_mtime > cutoff or _process_is_running(pid):
                continue
            shutil.rmtree(resolved)
            removed.append(resolved)
        except OSError as exc:
            print(f"Warning: could not remove stale test artifact directory {candidate}: {exc}", file=sys.stderr)
    return removed
