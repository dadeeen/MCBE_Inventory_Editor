"""A restore must persist its staged contents before replacing the current world."""

import builtins
import errno
import os
import stat
import struct
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
@pytest.mark.parametrize("mode", [0o750, 0o2770])
def test_restore_preserves_world_directory_access_mode(restore_world, mode):
    world, archive, contents = restore_world
    world.chmod(mode)
    (world / "db").chmod(mode)
    (world / "db" / "CURRENT").chmod(0o660)

    backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))

    assert stat.S_IMODE(world.stat().st_mode) == mode
    assert stat.S_IMODE((world / "db").stat().st_mode) == mode
    assert stat.S_IMODE((world / "db" / "CURRENT").stat().st_mode) == 0o660
    assert (world / "db" / "CURRENT").read_bytes() == contents["db/CURRENT"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and permissions")
def test_restore_permission_copy_failure_keeps_original_world(restore_world, monkeypatch):
    world, archive, _contents = restore_world
    original = (world / "db" / "CURRENT").read_bytes()
    monkeypatch.setattr(backup.shutil, "copystat", Mock(side_effect=PermissionError("restore permissions")))

    with pytest.raises(ValueError, match="Dateirechte"):
        backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))

    assert (world / "db" / "CURRENT").read_bytes() == original
    assert archive.is_file()
    assert not list(world.parent.glob(".world_restoring_*"))
    assert not list(world.parent.glob(".world_rollback_*"))
    assert not list(world.parent.glob(".mcbe_restore_*.json"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and permissions")
@pytest.mark.parametrize("deny_ownership", [False, True])
def test_restore_keeps_owner_group_and_permissions_or_refuses_before_rename(restore_world, monkeypatch, deny_ownership):
    world, archive, contents = restore_world
    # The archive's old file is absent in the current world, so its restored
    # identity and group access must come from the current containing directory.
    (world / "resource_packs" / "nested" / "data.bin").unlink()
    paths = [world, *(path for path in world.rglob("*"))]
    try:
        for path in paths:
            os.chown(path, 10002, 10003)
            path.chmod(0o2770 if path.is_dir() else 0o660)
    except OSError as exc:
        pytest.skip(f"Distinct POSIX test ownership unavailable: {exc}")
    if deny_ownership:
        monkeypatch.setattr(backup.os, "chown", Mock(side_effect=PermissionError("foreign owner")))
        with pytest.raises(ValueError, match="Dateirechte"):
            backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))
        assert (world / "db" / "CURRENT").read_bytes() == b"current database"
        assert not list(world.parent.glob(".world_restoring_*"))
        assert not list(world.parent.glob(".world_rollback_*"))
        assert not list(world.parent.glob(".mcbe_restore_*.json"))
        return

    backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))

    for path in [world, *world.rglob("*")]:
        info = path.stat()
        assert (info.st_uid, info.st_gid) == (10002, 10003)
        assert stat.S_IMODE(info.st_mode) == (0o2770 if path.is_dir() else 0o660)
    for name, value in contents.items():
        assert (world / name).read_bytes() == value


@pytest.mark.skipif(not hasattr(os, "setxattr"), reason="POSIX ACL support")
@pytest.mark.parametrize("inherited_extra_acl", [False, True])
@pytest.mark.parametrize("deny_acl", [False, True])
def test_restore_preserves_existing_acls_without_inheriting_extra_access(restore_world, monkeypatch, inherited_extra_acl, deny_acl):
    world, archive, _contents = restore_world
    backup.shutil.rmtree(world / "resource_packs")
    # Linux's version-2 POSIX ACL: owner, named editor, group, mask, other.
    acl = struct.pack("<I", 2) + b"".join(
        struct.pack("<HHI", tag, permissions, identity)
        for tag, permissions, identity in [(1, 7, 0xFFFFFFFF), (2, 7, 10001), (4, 5, 0xFFFFFFFF), (16, 7, 0xFFFFFFFF), (32, 0, 0xFFFFFFFF)]
    )
    source = world.parent if inherited_extra_acl else world
    try:
        os.setxattr(source, "system.posix_acl_access", acl)
        os.setxattr(source, "system.posix_acl_default", acl)
    except OSError as exc:
        pytest.skip(f"POSIX ACLs unavailable: {exc}")

    if deny_acl:
        operation = "removexattr" if inherited_extra_acl else "setxattr"
        monkeypatch.setattr(backup.os, operation, Mock(side_effect=PermissionError(errno.EPERM, "restore ACL")))
        with pytest.raises(ValueError, match="Dateirechte"):
            backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))
        assert (world / "db" / "CURRENT").read_bytes() == b"current database"
        assert archive.is_file()
        assert not list(world.parent.glob(".world_restoring_*"))
        assert not list(world.parent.glob(".world_rollback_*"))
        assert not list(world.parent.glob(".mcbe_restore_*.json"))
        return

    backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))

    for path in (world, world / "resource_packs", world / "resource_packs" / "nested"):
        for name in ("system.posix_acl_access", "system.posix_acl_default"):
            if inherited_extra_acl:
                assert name not in os.listxattr(path)
            else:
                assert os.getxattr(path, name) == acl
    restored_file = world / "resource_packs" / "nested" / "data.bin"
    if inherited_extra_acl:
        assert "system.posix_acl_access" not in os.listxattr(restored_file)
    else:
        file_acl = struct.pack("<I", 2) + b"".join(
            struct.pack("<HHI", tag, permissions, identity)
            for tag, permissions, identity in [(1, 6, 0xFFFFFFFF), (2, 7, 10001), (4, 5, 0xFFFFFFFF), (16, 6, 0xFFFFFFFF), (32, 0, 0xFFFFFFFF)]
        )
        assert os.getxattr(restored_file, "system.posix_acl_access") == file_acl


@pytest.mark.skipif(not hasattr(os, "setxattr"), reason="POSIX ACL support")
@pytest.mark.parametrize("directory_mode,default_mask", [(0o2770, 5), (0o750, 7), (0o700, 5)])
@pytest.mark.parametrize("extended", [False, True], ids=["minimal-acl", "named-user-acl"])
def test_restored_only_paths_follow_default_acl_instead_of_parent_access_mode(restore_world, tmp_path, directory_mode, default_mask, extended):
    world, archive, contents = restore_world
    backup.shutil.rmtree(world / "resource_packs")
    expected = tmp_path / "expected"
    expected.mkdir()
    entries = (
        [(1, 7, 0xFFFFFFFF)]
        + ([(2, 7, 10001)] if extended else [])
        + [(4, 5 if extended else default_mask, 0xFFFFFFFF)]
        + ([(16, default_mask, 0xFFFFFFFF)] if extended else [])
        + [(32, 0, 0xFFFFFFFF)]
    )
    acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)
    for parent in (world, expected):
        parent.chmod(directory_mode)
        try:
            os.setxattr(parent, "system.posix_acl_default", acl)
        except OSError as exc:
            pytest.skip(f"POSIX ACLs unavailable: {exc}")
    # Let the filesystem establish the expected inheritance. The parent's
    # access mode deliberately differs from its default ACL's mask.
    (expected / "resource_packs" / "nested").mkdir(parents=True)
    (expected / "resource_packs" / "nested" / "data.bin").write_bytes(contents["resource_packs/nested/data.bin"])

    backup.restore_backup(str(world), archive.name, resolved_backup_path=str(archive))

    assert stat.S_IMODE(world.stat().st_mode) == directory_mode
    for relative in ("resource_packs", "resource_packs/nested", "resource_packs/nested/data.bin"):
        actual_path, expected_path = world / relative, expected / relative
        assert stat.S_IMODE(actual_path.stat().st_mode) == stat.S_IMODE(expected_path.stat().st_mode)
        if extended:
            assert os.getxattr(actual_path, "system.posix_acl_access") == os.getxattr(expected_path, "system.posix_acl_access")
        else:
            assert "system.posix_acl_access" not in os.listxattr(actual_path)
        if actual_path.is_dir():
            assert os.getxattr(actual_path, "system.posix_acl_default") == acl
    assert (world / "resource_packs/nested/data.bin").read_bytes() == contents["resource_packs/nested/data.bin"]


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
