"""Backup policy persistence, operator controls and early resource checks."""

import errno
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import backup, backup_settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("MCBE_READ_ONLY", "false")
    monkeypatch.delenv(backup_settings.BACKUP_LIMIT_ENV, raising=False)


def _world(tmp_path):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_bytes(b"MANIFEST-000001\n")
    (world / "db" / "data").write_bytes(b"original")
    return world


def test_default_persistence_and_fresh_process(tmp_path):
    assert backup_settings.get_backup_settings() == {"max_uncompressed_mib": 1024, "source": "default", "editable": True}
    assert not (tmp_path / "data").exists()
    saved = backup_settings.save_backup_settings(3072)
    assert saved == {"max_uncompressed_mib": 3072, "source": "saved", "editable": True}
    result = subprocess.run(
        [sys.executable, "-c", "from mcbe_editor.backup_settings import get_backup_settings; print(get_backup_settings()['max_uncompressed_mib'])"],
        capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[1],
    )
    assert result.stdout.strip() == "3072"


def test_environment_override_cannot_be_changed_by_api(tmp_path, monkeypatch):
    import main

    backup_settings.save_backup_settings(2048)
    settings_path = tmp_path / "data" / "backup_settings.json"
    before = settings_path.read_bytes()
    monkeypatch.setenv(backup_settings.BACKUP_LIMIT_ENV, "4096")
    client = main.app.test_client()
    loaded = client.get("/api/backup/settings").get_json()
    assert loaded["settings"] == {"max_uncompressed_mib": 4096, "source": "environment", "editable": False}
    response = client.post("/api/backup/settings", json={"max_uncompressed_mib": 8192}, headers={"X-CSRF-Token": main.CSRF_TOKEN})
    assert response.status_code == 403
    assert settings_path.read_bytes() == before
    monkeypatch.delenv(backup_settings.BACKUP_LIMIT_ENV)
    assert backup_settings.get_backup_settings()["max_uncompressed_mib"] == 2048


@pytest.mark.parametrize("invalid", [None, True, "2048", 1.5, 0, -1, 1048577])
def test_invalid_api_setting_never_persists(invalid, tmp_path):
    import main

    response = main.app.test_client().post(
        "/api/backup/settings", json={"max_uncompressed_mib": invalid}, headers={"X-CSRF-Token": main.CSRF_TOKEN},
    )
    assert response.status_code == 400
    assert not (tmp_path / "data" / "backup_settings.json").exists()


@pytest.mark.parametrize("override", ["0", "-4", "no", "2.5", "1048577"])
def test_invalid_operator_override_fails_explicitly(monkeypatch, override):
    monkeypatch.setenv(backup_settings.BACKUP_LIMIT_ENV, override)
    with pytest.raises(ValueError, match=backup_settings.BACKUP_LIMIT_ENV):
        backup_settings.get_backup_settings()


def test_api_requires_csrf_and_rejects_readonly(tmp_path, monkeypatch):
    import main

    client = main.app.test_client()
    assert client.post("/api/backup/settings", json={"max_uncompressed_mib": 2048}).status_code == 403
    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, read_only=True))
    assert client.post(
        "/api/backup/settings", json={"max_uncompressed_mib": 2048}, headers={"X-CSRF-Token": main.CSRF_TOKEN},
    ).status_code == 403
    assert not (tmp_path / "data" / "backup_settings.json").exists()


def test_settings_save_failure_preserves_previous_value(monkeypatch):
    backup_settings.save_backup_settings(2048)
    monkeypatch.setattr(backup_settings, "atomic_write_private_text", Mock(side_effect=OSError(errno.ENOSPC, "full")))
    with pytest.raises(OSError):
        backup_settings.save_backup_settings(4096)
    assert backup_settings.get_backup_settings()["max_uncompressed_mib"] == 2048


def test_explicit_save_repairs_invalid_settings(tmp_path):
    path = tmp_path / "data" / "backup_settings.json"
    path.parent.mkdir()
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        backup_settings.get_backup_settings()
    assert backup_settings.save_backup_settings(2048)["max_uncompressed_mib"] == 2048


def test_size_limit_rejects_before_creating_zip_and_can_be_raised(tmp_path, monkeypatch):
    world = _world(tmp_path)
    (world / "db" / "data").write_bytes(b"x" * (1024 * 1024 + 1))
    backup_settings.save_backup_settings(1)
    write = Mock(side_effect=AssertionError("ZIP creation must not start"))
    with monkeypatch.context() as scoped:
        scoped.setattr(backup.zipfile, "ZipFile", write)
        with pytest.raises(backup_settings.BackupLimitError):
            backup.create_backup(str(world))
    write.assert_not_called()
    backup_settings.save_backup_settings(2)
    created = backup.create_backup(str(world))
    backup_settings.save_backup_settings(1)
    with pytest.raises(backup_settings.BackupLimitError):
        backup.restore_backup(str(world), os.path.basename(created))
    backup_settings.save_backup_settings(2)
    backup.restore_backup(str(world), os.path.basename(created))


def test_low_disk_space_blocks_backup_before_zip_creation(tmp_path, monkeypatch):
    world = _world(tmp_path)
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    write = Mock(side_effect=AssertionError("ZIP creation must not start"))
    monkeypatch.setattr(backup.zipfile, "ZipFile", write)
    with pytest.raises(ValueError, match="Speicherplatz"):
        backup.create_backup(str(world))
    write.assert_not_called()
    assert (world / "db" / "data").read_bytes() == b"original"


def test_restore_preflight_blocks_before_snapshot_or_safety_backup(tmp_path, monkeypatch):
    from mcbe_editor.services import BedrockEditorService

    world = _world(tmp_path)
    created = Path(backup.create_backup(str(world)))
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="Speicherplatz"):
        BedrockEditorService({}, {}).restore_backup(str(world), created.name)
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("separate_volume", [False, True])
def test_restore_space_combines_only_requirements_on_same_volume(tmp_path, monkeypatch, separate_volume):
    world = _world(tmp_path)
    created = Path(backup.create_backup(str(world)))
    sizes = []
    monkeypatch.setattr(backup, "_ensure_space", lambda path, size: sizes.append(size))
    if separate_volume:
        original_stat = os.stat

        def volume_stat(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if str(path) == str(created.parent):
                return SimpleNamespace(st_dev=info.st_dev + 1)
            return info

        monkeypatch.setattr(backup.os, "stat", volume_stat)
    backup._preflight_restore(str(world), str(created), str(created.parent))
    world_bytes = sum(p.stat().st_size for p in (world / "db").iterdir())
    expected = [world_bytes, created.stat().st_size + backup._zip_space_estimate(world_bytes, 3)]
    assert sizes == (expected if separate_volume else [sum(expected)])


def test_disk_full_during_extraction_preserves_world_and_cleans_staging(tmp_path, monkeypatch):
    world = _world(tmp_path)
    created = Path(backup.create_backup(str(world)))

    def fail_write(_src, dst, *_args, **_kwargs):
        dst.write(b"partial")
        raise OSError(errno.ENOSPC, "full")

    monkeypatch.setattr(backup.shutil, "copyfileobj", fail_write)
    with pytest.raises(OSError):
        backup.restore_backup(str(world), created.name)
    assert (world / "db" / "data").read_bytes() == b"original"
    assert not list(tmp_path.glob(".world_restoring_*"))


def test_backup_limit_api_error_has_navigation_code():
    import main

    with main.app.test_request_context():
        response, status = main.api_error(backup_settings.BackupLimitError("limit"))
    assert status == 400
    assert response.get_json()["code"] == "backup_limit_exceeded"


@pytest.mark.parametrize("operation", ["save", "restore"])
@pytest.mark.parametrize("with_cleanup", [False, True])
def test_backup_limit_survives_route_error_handling(monkeypatch, operation, with_cleanup):
    import main

    error = backup_settings.BackupLimitError("Backup limit exceeded")
    if with_cleanup:
        error.cleanup_warning = "Snapshot cleanup failed"
        error.source_snapshot_path = "snapshot.zip"
        if operation == "restore":
            error.pre_restore_backup = "before.zip"
    if operation == "save":
        deps = replace(
            main.player_route_deps(),
            service=SimpleNamespace(save_player=Mock(side_effect=error)),
            require_world_write_allowed=lambda: None,
            require_server_guard_current=lambda _data: None,
            presence_conflict_response=lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(main, "player_route_deps", lambda: deps)
        endpoint = "/api/player/save"
        payload = {"world_path": "world", "player_key": "~local_player", "inventory": []}
    else:
        deps = replace(
            main.backup_route_deps(),
            service=SimpleNamespace(restore_backup=Mock(side_effect=error)),
            require_world_write_allowed=lambda: None,
            presence_conflict_response=lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(main, "backup_route_deps", lambda: deps)
        endpoint = "/api/restore_backup"
        payload = {"world_path": "world", "backup_file": "backup.zip", "backup_token": {}}
    response = main.app.test_client().post(endpoint, json=payload, headers={"X-CSRF-Token": main.CSRF_TOKEN})
    assert response.status_code == 400
    result = response.get_json()
    assert result["code"] == "backup_limit_exceeded"
    if with_cleanup:
        assert result["cleanup_warning"] == error.cleanup_warning
        assert result["source_snapshot_path"] == error.source_snapshot_path
        if operation == "restore":
            assert result["pre_restore_backup"] == error.pre_restore_backup


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("MCBE_RUN_LARGE_BACKUP_TESTS") != "1", reason="Large backup roundtrip requires explicit disk/time opt-in")
def test_real_zip64_backup_and_service_restore_over_two_gib(tmp_path):
    import hashlib
    import zipfile

    from mcbe_editor.services import BedrockEditorService

    world = _world(tmp_path)
    payload = world / "db" / "data"
    block = b"synthetic-backup-content\0" * 4096
    total_size = 2 * 1024**3 + 1024**2
    expected_hash = hashlib.sha256()
    with payload.open("wb") as handle:
        remaining = total_size
        while remaining:
            chunk = block[:min(len(block), remaining)]
            handle.write(chunk)
            expected_hash.update(chunk)
            remaining -= len(chunk)

    backup_settings.save_backup_settings(3072)
    created = Path(backup.create_backup(str(world)))
    with zipfile.ZipFile(created) as archive:
        assert archive.getinfo("db/data").file_size == total_size
        assert archive.getinfo("db/data").extract_version >= 45
    preview = backup.preview_backup(str(world), created.name)
    with payload.open("r+b") as handle:
        handle.write(b"changed")
    result = BedrockEditorService({}, {}).restore_backup(str(world), created.name, backup_token=preview["backup_token"])
    assert result["success"] and result["pre_restore_backup"]
    with payload.open("rb") as handle:
        assert hashlib.file_digest(handle, "sha256").digest() == expected_hash.digest()
    with zipfile.ZipFile(created.parent / result["pre_restore_backup"]) as archive, archive.open("db/data") as handle:
        assert handle.read(7) == b"changed"
