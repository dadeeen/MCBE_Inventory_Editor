from __future__ import annotations

import contextlib
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

import mcbe_editor.backup as backup_module
import mcbe_editor.icons as icons_module
import mcbe_editor.players as players_module


class ReusedDescriptorProbe:
    """Force a foreign file onto the descriptor previously owned by fdopen."""

    def __init__(self, victim_path: Path):
        self._real_mkstemp = tempfile.mkstemp
        self.created_fd = -1
        self.victim_fd = -1
        self.victim_path = victim_path

    def capture_mkstemp(self, *args, **kwargs):
        fd, path = self._real_mkstemp(*args, **kwargs)
        assert self.created_fd < 0, "target path unexpectedly created more than one temporary descriptor"
        self.created_fd = fd
        return fd, path

    def reuse_created_descriptor(self) -> None:
        assert self.created_fd >= 0, "mkstemp descriptor was not captured"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        opened_fd = os.open(self.victim_path, flags, 0o600)
        if opened_fd != self.created_fd:
            os.dup2(opened_fd, self.created_fd)
            os.close(opened_fd)
        self.victim_fd = self.created_fd

    def assert_victim_still_open(self) -> None:
        assert self.victim_fd >= 0, "victim descriptor was not installed"
        os.write(self.victim_fd, b"descriptor still owned by victim\n")
        os.fsync(self.victim_fd)

    def close_victim(self) -> None:
        if self.victim_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(self.victim_fd)
            self.victim_fd = -1


def test_player_import_snapshot_cleanup_does_not_close_reused_descriptor(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "player-export.zip"
    source.write_bytes(b"player export snapshot")
    world = tmp_path / "world"
    world.mkdir()
    probe = ReusedDescriptorProbe(tmp_path / "player-victim.bin")
    monkeypatch.setattr(players_module.tempfile, "mkstemp", probe.capture_mkstemp)

    def fail_after_fdopen(*args, **kwargs):
        del args, kwargs
        probe.reuse_created_descriptor()
        raise RuntimeError("player token failure")

    monkeypatch.setattr(players_module, "_player_import_token", fail_after_fdopen)
    try:
        with pytest.raises(RuntimeError, match="player token failure"):
            players_module.snapshot_player_export_for_import(str(source), str(world))
        probe.assert_victim_still_open()
    finally:
        probe.close_victim()


def test_restore_snapshot_cleanup_does_not_close_reused_descriptor(monkeypatch, tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    backups_dir = Path(backup_module.ensure_safe_backup_location(str(world)))
    backups_dir.mkdir(parents=True)
    source = backups_dir / "restore-source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("db/CURRENT", "manifest")

    probe = ReusedDescriptorProbe(tmp_path / "restore-victim.bin")
    monkeypatch.setattr(backup_module.tempfile, "mkstemp", probe.capture_mkstemp)

    def fail_after_fdopen(_snapshot_path):
        probe.reuse_created_descriptor()
        raise RuntimeError("restore integrity failure")

    monkeypatch.setattr(backup_module, "_verify_zip_integrity", fail_after_fdopen)
    try:
        with pytest.raises(RuntimeError, match="restore integrity failure"):
            backup_module.snapshot_backup_for_restore(str(world), str(source))
        probe.assert_victim_still_open()
    finally:
        probe.close_victim()


def test_icon_source_cleanup_does_not_close_reused_descriptor(monkeypatch, tmp_path: Path) -> None:
    settings = tmp_path / "icon-sources.json"
    probe = ReusedDescriptorProbe(tmp_path / "icons-victim.bin")
    monkeypatch.setattr(icons_module.tempfile, "mkstemp", probe.capture_mkstemp)

    def fail_after_fdopen(_source, _target):
        probe.reuse_created_descriptor()
        raise PermissionError("settings target locked")

    monkeypatch.setattr(icons_module.os, "replace", fail_after_fdopen)
    try:
        with pytest.raises(PermissionError, match="settings target locked"):
            icons_module.save_icon_sources(str(settings), [])
        probe.assert_victim_still_open()
    finally:
        probe.close_victim()
