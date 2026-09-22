import builtins
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from mcbe_editor import players


def test_oversized_import_source_is_rejected_before_snapshot_creation(tmp_path, monkeypatch):
    source = tmp_path / "source.zip"
    source.write_bytes(b"x" * 33)
    monkeypatch.setattr(players, "MAX_EXPORT_SOURCE_BYTES", 32)
    create = Mock(side_effect=AssertionError("oversized source created a snapshot"))
    monkeypatch.setattr(players.tempfile, "mkstemp", create)
    with pytest.raises(ValueError, match="zu groß"):
        players.snapshot_player_export_for_import(str(source), str(tmp_path / "world"))
    create.assert_not_called()


def test_import_source_growth_hits_copy_limit_and_cleans_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "source.zip"
    source.write_bytes(b"small")
    monkeypatch.setattr(players, "MAX_EXPORT_SOURCE_BYTES", 32)
    monkeypatch.setattr(players, "player_export_dir_for_world", lambda _: str(tmp_path / "exports"))

    def growing_source(path, mode, *args, **kwargs):
        if path == str(source) and mode == "rb":
            source.write_bytes(b"x" * 100)
        return builtins.open(path, mode, *args, **kwargs)

    monkeypatch.setattr(players, "open", growing_source, raising=False)
    with pytest.raises(ValueError, match="zu groß"):
        players.snapshot_player_export_for_import(str(source), str(tmp_path / "world"))
    assert list((tmp_path / "exports" / ".import_sources").iterdir()) == []


def test_import_source_at_limit_is_copied_completely(tmp_path, monkeypatch):
    source = tmp_path / "source.zip"
    source.write_bytes(b"x" * 32)
    monkeypatch.setattr(players, "MAX_EXPORT_SOURCE_BYTES", 32)
    snapshot, token = players.snapshot_player_export_for_import(str(source), str(tmp_path / "world"))
    assert Path(snapshot).read_bytes() == source.read_bytes()
    assert token["size_bytes"] == 32


def test_next_import_removes_only_old_abandoned_snapshots(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    snapshots = exports / ".import_sources"
    snapshots.mkdir(parents=True)
    old = snapshots / "player_import_source_old.zip"
    recent = snapshots / "player_import_source_recent.zip"
    unrelated = snapshots / "user-export.zip"
    directory = snapshots / "player_import_source_directory.zip"
    for path in (old, recent, unrelated):
        path.write_bytes(b"synthetic")
    directory.mkdir()
    for path in (old, unrelated, directory):
        os.utime(path, (0, 0))
    source = tmp_path / "source.zip"
    source.write_bytes(b"source")
    monkeypatch.setattr(players, "player_export_dir_for_world", lambda _: str(exports))
    players.snapshot_player_export_for_import(str(source), str(tmp_path / "world"))
    assert not old.exists()
    assert recent.read_bytes() == b"synthetic"
    assert unrelated.read_bytes() == b"synthetic"
    assert directory.is_dir()
