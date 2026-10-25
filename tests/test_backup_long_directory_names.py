"""Long valid world folders must remain backuppable and recoverable."""

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from mcbe_editor import backup


def _world(tmp_path, monkeypatch, name, *, sibling_backups=False):
    world = tmp_path / name
    (world / "db").mkdir(parents=True)
    (world / "db" / "data.bin").write_bytes(b"original")
    (world / "levelname.txt").write_text("Short display name", encoding="utf-8")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    if sibling_backups:
        config = replace(backup.load_config(), backup_root=None)
        monkeypatch.setattr(backup, "load_config", lambda: config)
    return world


@pytest.mark.parametrize(
    "name,sibling_backups",
    [
        ("界" * 80, False),
        ("𐐀" * 61, False),
        pytest.param("x" * 250, True, marks=pytest.mark.skipif(os.name == "nt", reason="Long POSIX filename component")),
    ],
    ids=["cjk-folder", "supplementary-folder", "legacy-sibling"],
)
def test_long_world_directory_backup_and_restore_roundtrip(tmp_path, monkeypatch, name, sibling_backups):
    world = _world(tmp_path, monkeypatch, name, sibling_backups=sibling_backups)
    archive = Path(backup.create_backup(str(world), prune_after=False))
    assert len(archive.parent.name.encode("utf-8")) <= 255
    assert archive.parent == Path(backup.get_backups_dir(str(world)))
    assert backup.list_backups(str(world))[0]["filename"] == archive.name
    if name == "界" * 80:
        assert archive.parent.name == f"{name}_{backup._world_backup_id(str(world))}"

    (world / "db" / "data.bin").write_bytes(b"changed")
    backup.restore_backup(str(world), archive.name)

    assert (world / "db" / "data.bin").read_bytes() == b"original"
    assert not list(tmp_path.glob(".mcbe_restore_*.json"))
    assert not [entry for entry in tmp_path.iterdir() if "_restoring_" in entry.name or "_rollback_" in entry.name]


@pytest.mark.parametrize("commit_completed", [False, True])
def test_interrupted_long_world_restore_recovers_from_bounded_names(tmp_path, monkeypatch, commit_completed):
    world = _world(tmp_path, monkeypatch, "界" * 80)
    archive = Path(backup.create_backup(str(world), prune_after=False))
    (world / "db" / "data.bin").write_bytes(b"current")
    real_replace = backup.os.replace

    def interrupt(source, destination):
        if Path(destination) == world:
            if commit_completed:
                real_replace(source, destination)
            raise SystemExit("synthetic process stop")
        return real_replace(source, destination)

    with monkeypatch.context() as interrupted:
        interrupted.setattr(backup.os, "replace", interrupt)
        with pytest.raises(SystemExit, match="synthetic process stop"):
            backup.restore_backup(str(world), archive.name)

    journal = next(tmp_path.glob(".mcbe_restore_*.json"))
    payload = json.loads(journal.read_text(encoding="utf-8"))
    assert payload["world_dir_name"] == world.name
    for key in ("rollback_dir_name", "staging_dir_name"):
        assert len(payload[key].encode("utf-8")) <= 255
        assert backup._world_backup_id(str(world)) in payload[key]

    # A different world with the same shortened readable prefix must not be
    # able to claim these transaction directories through its journal target.
    original_journal = journal.read_bytes()
    journal.write_text(json.dumps({**payload, "world_dir_name": "界" * 79 + "異"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Rollback-Ordner"):
        backup._load_restore_transaction(str(journal))
    journal.write_bytes(original_journal)

    (result,) = backup.recover_interrupted_restores([str(world)])
    assert result["status"] == ("committed-cleaned" if commit_completed else "original-restored")
    assert (world / "db" / "data.bin").read_bytes() == (b"original" if commit_completed else b"current")
    assert not journal.exists()
    assert backup.recover_interrupted_restores([str(world)]) == []


def test_long_world_recovery_still_accepts_legacy_directory_names(tmp_path):
    # These names can be legal on Windows. Loading a journal must retain the
    # old scheme even when newly generated names would use the bounded scheme.
    world_name = "界" * 80
    transaction_id = "0123456789abcdef"
    rollback = tmp_path / f".{world_name}_rollback_2026-01-01_00-00-00-000000_{transaction_id}"
    staging = tmp_path / f".{world_name}_restoring_interrupted"
    journal = backup._write_restore_transaction(str(tmp_path), world_name, str(rollback), str(staging), transaction_id)

    loaded = backup._load_restore_transaction(journal)
    assert loaded["rollback_dir_name"] == rollback.name
    assert loaded["staging_dir_name"] == staging.name


def test_existing_long_backup_directory_keeps_its_identity(tmp_path, monkeypatch):
    world = tmp_path / ("𐐀" * 61)
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    existing = tmp_path / "backups" / f"{world.name}_{backup._world_backup_id(str(world))}"
    real_isdir = backup.os.path.isdir
    monkeypatch.setattr(backup.os.path, "isdir", lambda path: Path(path) == existing or real_isdir(path))

    assert Path(backup.get_backups_dir(str(world))) == existing


def test_shortened_sibling_backup_directories_do_not_collide(tmp_path, monkeypatch):
    config = replace(backup.load_config(), backup_root=None)
    monkeypatch.setattr(backup, "load_config", lambda: config)
    worlds = [tmp_path / ("x" * 249 + suffix) for suffix in ("a", "b")]

    first, second = (backup.get_backups_dir(str(world)) for world in worlds)

    assert first != second
    assert all(len(Path(path).name.encode("utf-8")) <= 255 for path in (first, second))
