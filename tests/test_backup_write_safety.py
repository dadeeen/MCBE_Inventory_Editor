"""Synthetic regressions for the shared recovery-copy boundary."""

import errno
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import backup, nbt
from mcbe_editor.backup_consistency import BackupSourceChangedError
from mcbe_editor.bedrock_nbt import save_player_nbt
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import LOCAL_PLAYER_KEY


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "world"
    (root / "db").mkdir(parents=True)
    (root / "db" / "a.bin").write_bytes(b"old-a")
    (root / "db" / "b.bin").write_bytes(b"old-b")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    return root


def assert_no_backup(world):
    directory = Path(backup.get_backups_dir(str(world)))
    assert not list(directory.glob("*.zip"))
    assert not list(directory.glob("*.part"))


def change_during_zip(monkeypatch, world, action="edit"):
    original_write = zipfile.ZipFile.write
    changed = False

    def write(archive, filename, *args, **kwargs):
        nonlocal changed
        result = original_write(archive, filename, *args, **kwargs)
        if not changed and Path(filename).is_file():
            changed = True
            if action == "edit":
                for source in (world / "db").glob("*.bin"):
                    source.write_bytes(b"new-source-content")
            elif action == "add":
                (world / "db" / "added.bin").write_bytes(b"new")
            elif action == "remove":
                # Remove an already-read file, so the writer itself cannot see it.
                Path(filename).unlink()
            elif action == "rename":
                Path(filename).rename(world / "db" / "renamed.bin")
        return result

    monkeypatch.setattr(zipfile.ZipFile, "write", write)


@pytest.mark.parametrize("kind", [backup.BACKUP_KIND_AUTOMATIC, backup.BACKUP_KIND_MANUAL, backup.BACKUP_KIND_PRE_RESTORE])
@pytest.mark.parametrize("action", ["edit", "add", "remove", "rename"])
def test_every_backup_kind_rejects_source_changes_without_pruning(world, monkeypatch, kind, action):
    directory = Path(backup.get_backups_dir(str(world)))
    directory.mkdir(parents=True)
    previous = directory / "previous.zip"
    with zipfile.ZipFile(previous, "w") as archive:
        archive.writestr("db/old.bin", b"recovery")
    original = previous.read_bytes()
    prune = Mock()
    monkeypatch.setattr(backup, "prune_backups", prune)
    change_during_zip(monkeypatch, world, action)

    with pytest.raises(BackupSourceChangedError):
        backup.create_backup(str(world), backup_kind=kind)

    assert list(directory.glob("*.zip")) == [previous]
    assert previous.read_bytes() == original
    assert not list(directory.glob("*.part"))
    prune.assert_not_called()


def test_source_change_during_publication_is_also_rejected(world, monkeypatch):
    original_publish = backup._publish_archive_no_clobber

    def publish(source, target):
        result = original_publish(source, target)
        (world / "db" / "a.bin").write_bytes(b"changed after compression")
        return result

    monkeypatch.setattr(backup, "_publish_archive_no_clobber", publish)
    with pytest.raises(BackupSourceChangedError):
        backup.create_backup(str(world))
    assert_no_backup(world)


@pytest.mark.parametrize("interruption", ["process_stop", "cleanup_denied"])
def test_mixed_archive_is_never_published_before_consistency_check(world, monkeypatch, interruption):
    change_during_zip(monkeypatch, world)
    original_publish = backup._publish_archive_no_clobber
    original_remove = os.remove
    published = []

    def publish(source, target):
        result = original_publish(source, target)
        if result:
            published.append(target)
            if interruption == "process_stop":
                raise KeyboardInterrupt("synthetic stop immediately after publication")
        return result

    def remove(path):
        if Path(path).suffix == ".zip" and interruption == "cleanup_denied":
            raise PermissionError(errno.EACCES, "synthetic cleanup failure")
        original_remove(path)

    monkeypatch.setattr(backup, "_publish_archive_no_clobber", publish)
    monkeypatch.setattr(backup.os, "remove", remove)
    try:
        with pytest.raises((BackupSourceChangedError, KeyboardInterrupt)) as raised:
            backup.create_backup(str(world), prune_after=False)
        assert published == [], "An inconsistent recovery archive must never reach the public ZIP name"
        assert isinstance(raised.value, BackupSourceChangedError)
        assert backup.list_backups(str(world)) == []
    finally:
        for path in published:
            if os.path.exists(path):
                original_remove(path)


@pytest.mark.parametrize("failing_check", [2, 3], ids=["before-publication", "after-publication"])
def test_backup_snapshot_failure_removes_archive(world, monkeypatch, failing_check):
    original_snapshot = backup.source_snapshot
    calls = 0

    def snapshot(path):
        nonlocal calls
        calls += 1
        if calls == failing_check:
            raise PermissionError("synthetic source access failure")
        return original_snapshot(path)

    monkeypatch.setattr(backup, "source_snapshot", snapshot)
    with pytest.raises(PermissionError, match="synthetic source access"):
        backup.create_backup(str(world))
    assert_no_backup(world)


@pytest.mark.parametrize("fallback", [False, True])
def test_completed_archive_is_synced_before_publication_and_return(world, monkeypatch, fallback):
    # Existing directory keeps ancestor-creation sync separate from publication.
    directory = Path(backup.get_backups_dir(str(world)))
    directory.mkdir(parents=True)
    original_sync = os.fsync
    original_link = os.link
    events = []

    def sync(fd):
        identity = os.fstat(fd)
        for path in directory.iterdir():
            if path.suffix in {".part", ".zip"} and os.path.samestat(identity, path.stat()):
                with zipfile.ZipFile(path) as archive:
                    assert archive.testzip() is None
                    assert archive.read("db/a.bin") == b"old-a"
                events.append("archive" if path.suffix == ".part" else "copy")
        original_sync(fd)

    def link(source, target):
        events.append("link")
        if fallback:
            raise OSError(errno.EPERM, "synthetic filesystem without hardlinks")
        original_link(source, target)

    monkeypatch.setattr(backup.os, "fsync", sync)
    monkeypatch.setattr(backup.os, "link", link)
    monkeypatch.setattr(backup, "_sync_backup_directory", lambda path: events.append("directory"))

    path = backup.create_backup(str(world), prune_after=False)
    events.append("returned")
    assert events == (["archive", "link", "copy", "directory", "returned"] if fallback else ["archive", "link", "directory", "returned"])
    with zipfile.ZipFile(path) as archive:
        assert archive.read("db/b.bin") == b"old-b"


@pytest.mark.parametrize("failure", ["archive", "directory"])
def test_sync_failure_rejects_backup_without_pruning(world, monkeypatch, failure):
    Path(backup.get_backups_dir(str(world))).mkdir(parents=True)
    prune = Mock()
    monkeypatch.setattr(backup, "prune_backups", prune)

    def fail(*_args):
        raise OSError(errno.EIO, "synthetic synchronization failure")

    if failure == "archive":
        monkeypatch.setattr(backup.os, "fsync", fail)
    else:
        monkeypatch.setattr(backup, "_sync_backup_directory", fail)
    with pytest.raises(OSError, match="synthetic synchronization"):
        backup.create_backup(str(world))
    assert_no_backup(world)
    prune.assert_not_called()


def test_publication_permission_error_keeps_cleanup_warning(world, monkeypatch):
    directory = Path(backup.get_backups_dir(str(world)))
    directory.mkdir(parents=True)
    original_remove = os.remove

    def sync_denied(_path):
        raise PermissionError(errno.EACCES, "synthetic directory sync failure")

    def remove_denied(path):
        if Path(path).suffix == ".zip":
            raise PermissionError(errno.EACCES, "synthetic cleanup failure")
        original_remove(path)

    monkeypatch.setattr(backup, "_sync_backup_directory", sync_denied)
    monkeypatch.setattr(backup.os, "remove", remove_denied)
    with pytest.raises(ValueError, match="Backup abgebrochen") as raised:
        backup.create_backup(str(world))
    leftover = next(directory.glob("*.zip"))
    assert str(leftover) in raised.value.cleanup_warning
    assert "synthetic cleanup failure" in raised.value.cleanup_warning
    # Remove only the artifact this synthetic failure deliberately left behind.
    original_remove(leftover)


@pytest.mark.parametrize("error_number", [errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EIO, errno.EACCES])
def test_directory_sync_only_ignores_unsupported_operations(monkeypatch, error_number):
    # Exercise POSIX policy on Windows too, without changing process-wide os.name.
    close = Mock()
    operating_system = SimpleNamespace(
        name="posix", O_DIRECTORY=1, O_RDONLY=0, open=Mock(return_value=123), close=close,
        fsync=Mock(side_effect=OSError(error_number, "synthetic directory error")),
    )
    monkeypatch.setattr(backup, "os", operating_system)
    if error_number in {errno.EIO, errno.EACCES}:
        with pytest.raises(OSError):
            backup._sync_backup_directory("synthetic-directory")
    else:
        backup._sync_backup_directory("synthetic-directory")
    close.assert_called_once_with(123)


@pytest.mark.parametrize("sync_errno,close_errno,expected_errno", [
    (errno.EIO, errno.EINVAL, errno.EIO),
    (errno.EIO, errno.EBADF, errno.EIO),
    (errno.EINVAL, errno.EIO, errno.EIO),
    (None, errno.EINVAL, errno.EINVAL),
])
def test_directory_close_cannot_hide_sync_errors(monkeypatch, sync_errno, close_errno, expected_errno):
    operating_system = SimpleNamespace(
        name="posix", O_DIRECTORY=1, O_RDONLY=0, open=Mock(return_value=123),
        fsync=Mock(side_effect=OSError(sync_errno, "synthetic sync failure") if sync_errno else None),
        close=Mock(side_effect=OSError(close_errno, "synthetic close failure")),
    )
    monkeypatch.setattr(backup, "os", operating_system)
    with pytest.raises(OSError) as raised:
        backup._sync_backup_directory("synthetic-directory")
    assert raised.value.errno == expected_errno
    operating_system.close.assert_called_once_with(123)


def test_new_backup_directory_entries_are_synced(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(backup, "_sync_backup_directory", calls.append)
    target = tmp_path / "new" / "backups" / "world"
    backup._create_backup_directory(str(target))
    assert calls == [str(tmp_path), str(target.parent.parent), str(target.parent)]
    calls.clear()
    backup._create_backup_directory(str(target))
    assert calls == []


def test_world_keyword_argument_and_full_backup_remain_supported(world):
    archive_path = backup.create_backup(world_path=str(world), prune_after=False)
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {"db/", "db/a.bin", "db/b.bin"}
    entries = backup.list_backups(world_path=str(world))
    assert entries[0]["filename"] == Path(archive_path).name


@pytest.mark.parametrize("failure", ["source", "archive_sync", "directory_sync"])
@pytest.mark.parametrize("workspace", [False, True])
def test_save_never_opens_mutating_database_without_safe_backup(world, monkeypatch, failure, workspace):
    original = save_player_nbt(nbt.NamedTag(nbt.CompoundTag({
        "Health": nbt.FloatTag(20),
        "PlayerGameType": nbt.IntTag(0),
        "Inventory": nbt.ListTag([]),
    })))
    readonly = SimpleNamespace(get=lambda _key: original, iter_items=lambda: [(LOCAL_PLAYER_KEY, original)], close=lambda: None)
    write_factory = Mock(side_effect=AssertionError("mutating database must remain closed"))
    builder = Mock(side_effect=AssertionError("write builder must not run"))
    service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=write_factory, readonly_db_factory=lambda _path: readonly)
    if failure == "source":
        change_during_zip(monkeypatch, world)
    else:
        def fail(*_args):
            raise OSError(errno.EIO, "synthetic sync failure")
        if failure == "archive_sync":
            monkeypatch.setattr(backup.os, "fsync", fail)
        else:
            monkeypatch.setattr(backup, "_sync_backup_directory", fail)

    with pytest.raises((BackupSourceChangedError, OSError)):
        service.save_player(
            str(world), encode_player_key(LOCAL_PLAYER_KEY), None, {"health": 19},
            base_revision=service._player_revision(original), extra_batch_builder=builder if workspace else None,
        )
    write_factory.assert_not_called()
    builder.assert_not_called()
    assert readonly.get(LOCAL_PLAYER_KEY) == original
    assert_no_backup(world)


def test_restore_aborts_when_pre_restore_backup_source_changes(world, monkeypatch):
    from mcbe_editor import services

    selected = backup.create_backup(str(world))
    original_archive = Path(selected).read_bytes()
    restore = Mock(side_effect=AssertionError("restore must not start"))
    monkeypatch.setattr(services, "restore_world_backup", restore)
    change_during_zip(monkeypatch, world)
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)

    with pytest.raises(BackupSourceChangedError):
        service.restore_backup(str(world), Path(selected).name)
    restore.assert_not_called()
    assert Path(selected).read_bytes() == original_archive
    assert list(Path(selected).parent.glob("*.zip")) == [Path(selected)]
    assert not list((Path(selected).parent / ".restore_sources").glob("*.zip"))


@pytest.mark.parametrize("change_phase", ["after_backup", "extraction", "final_gate"])
def test_restore_rejects_source_changes_after_pre_restore_backup(world, monkeypatch, change_phase):
    from mcbe_editor import services

    selected = Path(backup.create_backup(str(world), prune_after=False))
    selected_bytes = selected.read_bytes()
    current = world / "db" / "a.bin"
    current.write_bytes(b"before-restore")
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    token = service.preview_backup_restore(str(world), selected.name)["backup_token"]
    original_create = services.create_backup
    original_extract = backup.safe_extract_zip
    created = []

    def create(*args, **kwargs):
        result = original_create(*args, **kwargs)
        created.append(Path(result))
        if change_phase == "after_backup":
            current.write_bytes(b"external-change")
        return result

    def extract(*args, **kwargs):
        original_extract(*args, **kwargs)
        if change_phase == "extraction":
            current.write_bytes(b"external-change")

    def final_gate():
        if change_phase == "final_gate":
            current.write_bytes(b"external-change")

    monkeypatch.setattr(services, "create_backup", create)
    monkeypatch.setattr(backup, "safe_extract_zip", extract)
    with pytest.raises(BackupSourceChangedError, match="Restore abgelehnt"):
        service.restore_backup(str(world), selected.name, backup_token=token, pre_restore_check=final_gate)

    assert current.read_bytes() == b"external-change"
    assert selected.read_bytes() == selected_bytes
    assert len(created) == 1 and created[0].exists()
    with zipfile.ZipFile(created[0]) as archive:
        assert archive.read("db/a.bin") == b"before-restore"
    assert not list(world.parent.glob(".world_restoring_*"))
    assert not list(world.parent.glob(".world_rollback_*"))
    assert not list(world.parent.glob(".mcbe_restore_*.json"))
    assert not list((selected.parent / ".restore_sources").glob("*.zip"))


def test_direct_restore_checks_source_before_swap(world, monkeypatch):
    selected = Path(backup.create_backup(str(world), prune_after=False))
    current = world / "db" / "a.bin"
    current.write_bytes(b"before-restore")
    original_extract = backup.safe_extract_zip

    def extract(*args, **kwargs):
        original_extract(*args, **kwargs)
        current.write_bytes(b"external-change")

    monkeypatch.setattr(backup, "safe_extract_zip", extract)
    with pytest.raises(BackupSourceChangedError, match="Restore abgelehnt"):
        backup.restore_backup(str(world), selected.name)

    assert current.read_bytes() == b"external-change"
    assert not list(world.parent.glob(".world_restoring_*"))
    assert not list(world.parent.glob(".world_rollback_*"))


def test_restore_rechecks_server_gate_after_source_snapshot(world, monkeypatch):
    selected = Path(backup.create_backup(str(world), prune_after=False))
    current = world / "db" / "a.bin"
    current.write_bytes(b"before-restore")
    original_snapshot = backup.source_snapshot
    scans = 0
    gate_calls = []

    def snapshot(path):
        nonlocal scans
        result = original_snapshot(path)
        scans += 1
        return result

    def final_gate():
        gate_calls.append(scans)
        if scans == 2:
            raise ValueError("server started during metadata check")

    monkeypatch.setattr(backup, "source_snapshot", snapshot)
    with pytest.raises(ValueError, match="server started"):
        backup.restore_backup(str(world), selected.name, pre_restore_check=final_gate)

    assert gate_calls == [1, 2]
    assert current.read_bytes() == b"before-restore"
    assert not list(world.parent.glob(".world_restoring_*"))
    assert not list(world.parent.glob(".world_rollback_*"))
