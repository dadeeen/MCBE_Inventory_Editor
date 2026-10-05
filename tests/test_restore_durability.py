"""A restore must persist its staged contents before replacing the current world."""

import builtins
import errno
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import backup


@pytest.fixture
def restore_world(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "resource_packs" / "nested").mkdir(parents=True)
    contents = {
        "db/CURRENT": b"archived database",
        "levelname.txt": b"Synthetic restore test",
        "resource_packs/nested/data.bin": b"pack contents" * 1000,
    }
    for name, value in contents.items():
        (world / name).write_bytes(value)
    archive = Path(backup.create_backup(str(world), prune_after=False))
    (world / "db" / "CURRENT").write_bytes(b"current database")
    return world, archive, contents


def _track_open_files(monkeypatch):
    opened = {}

    @contextmanager
    def track(path, *args, **kwargs):
        with builtins.open(path, *args, **kwargs) as stream:
            fd = stream.fileno()
            opened[fd] = Path(path)
            try:
                yield stream
            finally:
                opened.pop(fd, None)

    monkeypatch.setattr(backup, "open", track, raising=False)
    return opened


def _staged(path):
    return any(part.startswith(".world_restoring_") for part in path.parts)


def test_restore_syncs_all_files_and_directories_before_replacing_world(restore_world, monkeypatch):
    world, archive, contents = restore_world
    opened = _track_open_files(monkeypatch)
    synced_files = set()
    synced_directories = set()
    real_sync = os.fsync
    real_sync_directory = backup._sync_backup_directory
    real_replace = os.replace

    def sync(fd):
        path = opened.get(fd)
        if path is not None and _staged(path):
            relative = path.relative_to(next(parent for parent in path.parents if parent.name.startswith(".world_restoring_")))
            # Reading through another handle also verifies that Python's write
            # buffer was flushed before the OS durability barrier.
            assert path.read_bytes() == contents[relative.as_posix()]
            synced_files.add(relative.as_posix())
        return real_sync(fd)

    def sync_directory(path):
        if _staged(Path(path)):
            # Child entries must be synchronized before their parent's entry.
            children = {child for child in Path(path).iterdir() if child.is_dir()}
            assert children <= synced_directories
            synced_directories.add(Path(path))
        return real_sync_directory(path)

    def replace(source, target):
        if Path(source) == world:
            assert synced_files == set(contents)
            staging = next(world.parent.glob(".world_restoring_*"))
            expected_dirs = {staging, *(path for path in staging.rglob("*") if path.is_dir())}
            assert synced_directories == expected_dirs
        return real_replace(source, target)

    monkeypatch.setattr(backup.os, "fsync", sync)
    monkeypatch.setattr(backup, "_sync_backup_directory", sync_directory)
    monkeypatch.setattr(backup.os, "replace", replace)
    backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))
    for name, value in contents.items():
        assert (world / name).read_bytes() == value


@pytest.mark.parametrize("failure", ["file", "directory"])
def test_staging_sync_failure_preserves_current_world_and_archive(restore_world, monkeypatch, failure):
    world, archive, _contents = restore_world
    before = {path.relative_to(world): path.read_bytes() for path in world.rglob("*") if path.is_file()}
    archive_bytes = archive.read_bytes()
    opened = _track_open_files(monkeypatch)
    real_sync = os.fsync
    real_sync_directory = backup._sync_backup_directory

    def sync(fd):
        path = opened.get(fd)
        if failure == "file" and path is not None and _staged(path):
            raise OSError(errno.EIO, "synthetic restore synchronization failure")
        return real_sync(fd)

    def sync_directory(path):
        if failure == "directory" and _staged(Path(path)):
            raise OSError(errno.EIO, "synthetic restore synchronization failure")
        return real_sync_directory(path)

    monkeypatch.setattr(backup.os, "fsync", sync)
    monkeypatch.setattr(backup, "_sync_backup_directory", sync_directory)
    with pytest.raises(OSError, match="synthetic restore synchronization failure"):
        backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))

    assert {path.relative_to(world): path.read_bytes() for path in world.rglob("*") if path.is_file()} == before
    assert archive.read_bytes() == archive_bytes
    assert not list(world.parent.glob(".world_restoring_*"))
    assert not list(world.parent.glob(".world_rollback_*"))
    assert not list(world.parent.glob(".mcbe_restore_*.json"))


@pytest.mark.parametrize("error_number", [errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EIO, errno.EACCES])
def test_restore_directory_sync_does_not_hide_io_or_permission_errors(monkeypatch, error_number):
    operating_system = SimpleNamespace(
        name="posix",
        O_DIRECTORY=1,
        O_RDONLY=0,
        open=Mock(return_value=123),
        close=Mock(),
        fsync=Mock(side_effect=OSError(error_number, "synthetic restore directory error")),
    )
    monkeypatch.setattr(backup, "os", operating_system)
    if error_number in {errno.EIO, errno.EACCES}:
        with pytest.raises(OSError) as raised:
            backup._fsync_directory("synthetic-directory")
        assert raised.value.errno == error_number
    else:
        backup._fsync_directory("synthetic-directory")
    operating_system.close.assert_called_once_with(123)


@pytest.mark.parametrize("parent_sync", [1, 2, 3], ids=["journal", "original-renamed", "replacement-renamed"])
def test_directory_transaction_sync_failure_keeps_recoverable_world(restore_world, monkeypatch, parent_sync):
    world, archive, contents = restore_world
    real_sync_directory = backup._sync_backup_directory
    calls = 0

    def sync_directory(path):
        nonlocal calls
        if Path(path) == world.parent:
            calls += 1
            if calls == parent_sync:
                raise OSError(errno.EIO, "synthetic parent synchronization failure")
        return real_sync_directory(path)

    monkeypatch.setattr(backup, "_sync_backup_directory", sync_directory)
    with pytest.raises(OSError, match="synthetic parent synchronization failure"):
        backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))

    journals = list(world.parent.glob(".mcbe_restore_*.json"))
    rollbacks = list(world.parent.glob(".world_rollback_*"))
    if parent_sync == 1:
        assert not journals
        assert not rollbacks
    else:
        assert len(journals) == len(rollbacks) == 1
        assert (rollbacks[0] / "db" / "CURRENT").read_bytes() == b"current database"
        if parent_sync == 3:
            # Recovery must persist the completed rename before deleting the
            # original directory, even if that rename's first sync failed.
            calls = parent_sync - 1
            with pytest.raises(OSError, match="synthetic parent synchronization failure"):
                backup.recover_restore_transaction(str(journals[0]))
            assert journals[0].is_file()
            assert (rollbacks[0] / "db" / "CURRENT").read_bytes() == b"current database"
        result = backup.recover_restore_transaction(str(journals[0]))
        assert result["status"] == ("original-restored" if parent_sync == 2 else "committed-cleaned")
        assert not journals[0].exists()
        assert not rollbacks[0].exists()

    expected = contents["db/CURRENT"] if parent_sync == 3 else b"current database"
    assert (world / "db" / "CURRENT").read_bytes() == expected
    assert archive.is_file()
    assert not list(world.parent.glob(".world_restoring_*"))
