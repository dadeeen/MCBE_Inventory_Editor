"""Transient, cross-process progress for the existing synchronous update requests.

Only phases and counters are shared. The POST response remains authoritative for
success/failure; losing progress telemetry must never abort a data update.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

from mcbe_editor.runtime_data import atomic_write_private_text, ensure_private_directory

PROGRESS_ENV = "MCBE_UPDATE_PROGRESS_PATH"
PROGRESS_HEADER = "X-MCBE-Progress"
_ID_RE = re.compile(r"[a-f0-9]{32}")
_last_report: tuple[str, str, float] = ("", "", 0.0)


def progress_path(directory: Path, progress_id: str) -> Path:
    if not _ID_RE.fullmatch(progress_id):
        raise ValueError("Ungültige Fortschritts-ID.")
    return directory / f"{progress_id}.json"


def write_progress(path: Path, phase: str, *, current: int | None = None, total: int | None = None, unit: str | None = None) -> None:
    snapshot: dict[str, str | int] = {"phase": phase}
    if current is not None:
        snapshot["current"] = max(0, current)
    if total is not None and total > 0:
        snapshot["total"] = total
    if unit:
        snapshot["unit"] = unit
    with contextlib.suppress(OSError):
        atomic_write_private_text(path, json.dumps(snapshot))


@contextlib.contextmanager
def track_progress(directory: Path, progress_id: str) -> Iterator[Path | None]:
    path = progress_path(directory, progress_id)
    try:
        ensure_private_directory(directory)
        # Completed requests remove their snapshot. Reap leftovers after a crash.
        for old in directory.glob("*.json"):
            if _ID_RE.fullmatch(old.stem):
                with contextlib.suppress(OSError):
                    if old.stat().st_mtime < time.time() - 86400:
                        old.unlink()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    except FileExistsError as exc:
        raise ValueError("Diese Fortschritts-ID wird bereits verwendet.") from exc
    except OSError:
        yield None
        return
    try:
        write_progress(path, "waiting")
        yield path
    finally:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def read_progress(directory: Path, progress_id: str) -> dict | None:
    path = progress_path(directory, progress_id)
    try:
        with path.open(encoding="utf-8") as handle:
            snapshot = json.loads(handle.read(4096))
        return snapshot if isinstance(snapshot, dict) else None
    except (OSError, ValueError):
        return None


def report_progress(phase: str, *, current: int | None = None, total: int | None = None, unit: str | None = None) -> None:
    """Best-effort script callback; CLI runs without a progress path are unchanged."""
    path = os.environ.get(PROGRESS_ENV, "")
    if not path:
        return
    global _last_report
    now = time.monotonic()
    old_path, old_phase, old_time = _last_report
    finished = current is not None and total is not None and current >= total
    if (path, phase) == (old_path, old_phase) and now - old_time < 0.3 and not finished:
        return
    _last_report = (path, phase, now)
    write_progress(Path(path), phase, current=current, total=total, unit=unit)
