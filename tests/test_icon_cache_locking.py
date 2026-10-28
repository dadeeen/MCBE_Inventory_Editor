"""Cache publishers share the existing lock protocol under sustained contention."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import icon_cache, world_locks
from mcbe_editor.block_icon_renderer import encode_rgba_png


def test_cache_lock_retries_long_windows_contention_and_is_reentrant(tmp_path, monkeypatch):
    attempts = 0
    releases = 0

    def locking(_fd, mode, length):
        nonlocal attempts, releases
        assert length == 1
        if mode == 1:
            attempts += 1
            if attempts <= 250:
                raise OSError(errno.EDEADLK, "Another publisher owns the lock")
        else:
            assert mode == 2
            releases += 1

    monkeypatch.setattr(world_locks, "fcntl", None)
    monkeypatch.setattr(world_locks, "msvcrt", SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking))
    sleep = Mock()
    monkeypatch.setattr(world_locks.time, "sleep", sleep)
    with icon_cache._cache_lock(tmp_path / "vanilla"), icon_cache._cache_lock(tmp_path / "nested" / ".." / "vanilla"):
        assert attempts == 251
        assert releases == 0
    assert releases == 1
    assert sleep.call_count == 250
    assert (tmp_path / ".vanilla.lock").is_file()


def test_cache_lock_propagates_real_lock_failure_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(world_locks, "fcntl", None)
    locking = Mock(side_effect=OSError(errno.EBADF, "Invalid lock handle"))
    monkeypatch.setattr(world_locks, "msvcrt", SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking))
    sleep = Mock()
    monkeypatch.setattr(world_locks.time, "sleep", sleep)
    with pytest.raises(OSError, match="Invalid lock handle"), icon_cache._cache_lock(tmp_path / "vanilla"):
        pytest.fail("A failed lock must never enter the critical section")
    sleep.assert_not_called()
    locking.side_effect = None
    with icon_cache._cache_lock(tmp_path / "vanilla"):
        pass
    assert locking.call_count == 3


def test_publication_waits_for_existing_process_lock_beyond_windows_retry_limit(tmp_path):
    target = tmp_path / "vanilla"
    staging = tmp_path / "staging"
    image = encode_rgba_png(1, 1, bytes((30, 40, 50, 255)))
    for directory in (target, staging):
        (directory / "textures/items").mkdir(parents=True)
        (directory / "textures/items/apple.png").write_bytes(image)
        (directory / "manifest.json").write_text(json.dumps({"items": {"minecraft:apple": "items/apple"}, "marker": directory.name}))
    started = tmp_path / "started"
    script = (
        "from pathlib import Path\n"
        "import sys\n"
        "from mcbe_editor.icon_cache import publish_icon_cache\n"
        "target, staging, started = map(Path, sys.argv[1:])\n"
        "started.write_text('ready')\n"
        "assert publish_icon_cache(staging, target)\n"
    )
    process = None
    try:
        # Take the original protocol directly, as an older process would.
        with (tmp_path / ".vanilla.lock").open("a+b") as handle:
            handle.write(b"\0")
            handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(target), str(staging), str(started)],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.monotonic() + 10
            while not started.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert started.exists(), "Publisher did not start"
            time.sleep(11.2 if os.name == "nt" else 0.2)
            assert process.poll() is None, "A contending publisher must wait, not time out"
            assert json.loads((target / "manifest.json").read_text())["marker"] == "vanilla"
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, (stdout, stderr)
        assert json.loads((target / "manifest.json").read_text())["marker"] == "staging"
        assert (target / "textures/items/apple.png").read_bytes() == image
        assert not staging.exists()
        assert not list(tmp_path.glob(".vanilla.rollback-*"))
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
