import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mcbe_editor.backup import create_backup, preview_backup, restore_backup
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.services import BedrockEditorService


def _world(tmp_path: Path, value: str = "BACKUP") -> Path:
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text(value, encoding="utf-8")
    (world / "levelname.txt").write_text("Cleanup Test", encoding="utf-8")
    return world


def test_low_level_restore_reports_leftover_rollback_directory(tmp_path: Path) -> None:
    world = _world(tmp_path)
    backup_path = Path(create_backup(str(world), prune_after=False))
    (world / "db" / "CURRENT").write_text("CURRENT", encoding="utf-8")
    original_rmtree = __import__("shutil").rmtree

    def fail_rollback_cleanup(path, *args, **kwargs):
        if "_rollback_" in os.path.basename(os.fspath(path)):
            raise PermissionError("rollback locked")
        return original_rmtree(path, *args, **kwargs)

    with patch("mcbe_editor.backup.shutil.rmtree", side_effect=fail_rollback_cleanup):
        warnings = restore_backup(
            str(world),
            backup_path.name,
            resolved_backup_path=str(backup_path),
        )

    assert (world / "db" / "CURRENT").read_text(encoding="utf-8") == "BACKUP"
    assert warnings
    assert "rollback locked" in warnings[0]
    rollback_dirs = list(tmp_path.glob(".world_rollback_*"))
    assert len(rollback_dirs) == 1
    assert (rollback_dirs[0] / "db" / "CURRENT").read_text(encoding="utf-8") == "CURRENT"


def test_service_restore_reports_leftover_private_snapshot(tmp_path: Path) -> None:
    world = _world(tmp_path)
    backup_path = Path(create_backup(str(world), prune_after=False))
    preview = preview_backup(str(world), backup_path.name)
    (world / "db" / "CURRENT").write_text("CURRENT", encoding="utf-8")
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    original_remove = os.remove

    def fail_snapshot_cleanup(path, *args, **kwargs):
        if ".restore_sources" in os.fspath(path):
            raise PermissionError("snapshot locked")
        return original_remove(path, *args, **kwargs)

    with patch("mcbe_editor.services.os.remove", side_effect=fail_snapshot_cleanup):
        result = service.restore_backup(
            str(world),
            backup_path.name,
            backup_token=preview["backup_token"],
        )

    assert result["success"] is True
    assert "snapshot locked" in result["cleanup_warning"]
    assert (world / "db" / "CURRENT").read_text(encoding="utf-8") == "BACKUP"
    snapshots = list((backup_path.parent / ".restore_sources").glob("restore_source_*.zip"))
    assert len(snapshots) == 1


def test_failed_restore_exposes_created_pre_restore_backup(tmp_path: Path) -> None:
    world = _world(tmp_path)
    backup_path = Path(create_backup(str(world), prune_after=False))
    preview = preview_backup(str(world), backup_path.name)
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)

    def block_before_replace():
        raise ValueError("Restore final block")

    try:
        service.restore_backup(
            str(world),
            backup_path.name,
            backup_token=preview["backup_token"],
            pre_restore_check=block_before_replace,
        )
    except ValueError as exc:
        assert str(exc) == "Restore final block"
        pre_restore_name = getattr(exc, "pre_restore_backup", None)
    else:
        raise AssertionError("Restore should have been blocked")

    assert pre_restore_name
    assert "__pre_restore__" in pre_restore_name
    assert (backup_path.parent / pre_restore_name).is_file()


def test_failed_restore_still_applies_separate_recovery_retention(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with patch.dict(
        os.environ,
        {
            "MCBE_BACKUP_ROOT": str(tmp_path / "backups"),
            "MCBE_MAX_PRE_RESTORE_BACKUPS_PER_WORLD": "1",
        },
        clear=False,
    ):
        old_recovery = Path(
            create_backup(
                str(world),
                prune_after=False,
                backup_kind="pre_restore",
                restore_source="older.zip",
            )
        )
        source = Path(create_backup(str(world), prune_after=False))
        preview = preview_backup(str(world), source.name)
        service = BedrockEditorService(ITEMS, ENCHANTMENTS)

        def block_before_replace():
            raise ValueError("Restore final block")

        with pytest.raises(ValueError, match="Restore final block") as error:
            service.restore_backup(
                str(world),
                source.name,
                backup_token=preview["backup_token"],
                pre_restore_check=block_before_replace,
            )

        new_recovery = source.parent / error.value.pre_restore_backup
        assert new_recovery.is_file()
        assert not old_recovery.exists()
