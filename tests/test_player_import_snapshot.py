from pathlib import Path
from unittest.mock import patch

import pytest

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.players import create_player_export, encode_player_key
from mcbe_editor.services import (
    BedrockEditorService,
    PlayerImportRecordRollbackError,
    PlayerImportRolledBackError,
)
from mcbe_editor.world import LOCAL_PLAYER_KEY
from tests.test_service import PathFakeDb, make_player_bytes


def _player_raw(item_name: str) -> bytes:
    item = nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(0),
            "Name": nbt.StringTag(item_name),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
        }
    )
    return make_player_bytes(item)


def _export(world: Path, output: Path, raw: bytes) -> str:
    player = {
        "player_key": encode_player_key(LOCAL_PLAYER_KEY),
        "label": "Lokaler Spieler",
        "kind": "local",
        "editable": True,
        "exportable": True,
    }
    return create_player_export(str(world), player, raw, output_dir=str(output))


def _service():
    return BedrockEditorService(
        ITEMS,
        ENCHANTMENTS,
        db_factory=PathFakeDb,
        readonly_db_factory=PathFakeDb,
    )


def test_import_rejects_export_replaced_after_preview(tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    raw_a = _player_raw("minecraft:stone")
    raw_b = _player_raw("minecraft:diamond")
    PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: raw_b}
    export_a = Path(_export(world, tmp_path / "exports-a", raw_a))
    export_b = Path(_export(world, tmp_path / "exports-b", raw_b))
    service = _service()
    preview = service.preview_player_export(str(export_a), str(world))
    export_a.write_bytes(export_b.read_bytes())

    with pytest.raises(ValueError, match="seit der Vorschau verändert"):
        service.import_player(
            str(export_a),
            str(world),
            encode_player_key(LOCAL_PLAYER_KEY),
            True,
            import_token=preview["import_token"],
        )


def test_import_token_is_bound_to_previewed_target_world(tmp_path: Path) -> None:
    world_a = tmp_path / "world-a"
    world_b = tmp_path / "world-b"
    (world_a / "db").mkdir(parents=True)
    (world_b / "db").mkdir(parents=True)
    raw = _player_raw("minecraft:stone")
    PathFakeDb._shared_stores[str(world_a / "db")] = {LOCAL_PLAYER_KEY: raw}
    PathFakeDb._shared_stores[str(world_b / "db")] = {LOCAL_PLAYER_KEY: raw}
    export_path = _export(world_a, tmp_path / "exports", raw)
    service = _service()
    preview = service.preview_player_export(export_path, str(world_a))

    with pytest.raises(ValueError, match="Zielwelt wurde seit der Vorschau gewechselt"):
        service.import_player(
            export_path,
            str(world_b),
            encode_player_key(LOCAL_PLAYER_KEY),
            True,
            import_token=preview["import_token"],
        )


def test_import_retention_failure_is_post_commit_warning(tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    source_raw = _player_raw("minecraft:stone")
    target_raw = _player_raw("minecraft:dirt")
    PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: target_raw}
    export_path = _export(world, tmp_path / "exports", source_raw)
    service = _service()
    preview = service.preview_player_export(export_path, str(world))
    with patch("mcbe_editor.services.prune_backups", side_effect=PermissionError("retention locked")):
        result = service.import_player(
            export_path,
            str(world),
            encode_player_key(LOCAL_PLAYER_KEY),
            True,
            import_token=preview["import_token"],
            base_revision=service._player_revision(target_raw),
        )

    assert result["success"] is True
    assert result["write_committed"] is True
    assert "retention locked" in result["cleanup_warning"]
    assert PathFakeDb._shared_stores[str(world / "db")][LOCAL_PLAYER_KEY] == source_raw


def test_direct_import_restores_existing_record_when_readback_validation_fails(tmp_path: Path) -> None:
    class MismatchingReadonlyDb(PathFakeDb):
        opened = 0

        def __init__(self, db_path):
            super().__init__(db_path)
            type(self).opened += 1
            self.open_number = type(self).opened

        def get(self, key):
            value = super().get(key)
            if self.open_number == 2 and key == LOCAL_PLAYER_KEY:
                return b"mismatching readback"
            return value

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    source_raw = _player_raw("minecraft:stone")
    target_raw = _player_raw("minecraft:dirt")
    PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: target_raw}
    export_path = _export(world, tmp_path / "exports", source_raw)
    service = BedrockEditorService(
        ITEMS,
        ENCHANTMENTS,
        db_factory=PathFakeDb,
        readonly_db_factory=MismatchingReadonlyDb,
    )
    preview = service.preview_player_export(export_path, str(world))

    with pytest.raises(PlayerImportRolledBackError) as raised:
        service.import_player(
            export_path,
            str(world),
            encode_player_key(LOCAL_PLAYER_KEY),
            True,
            import_token=preview["import_token"],
            base_revision=service._player_revision(target_raw),
        )

    assert raised.value.rolled_back is True
    assert raised.value.backup_file
    assert PathFakeDb._shared_stores[str(world / "db")][LOCAL_PLAYER_KEY] == target_raw


def test_direct_import_removes_new_key_when_readback_validation_fails(tmp_path: Path) -> None:
    new_key = b"player_server_new"

    class MismatchingReadonlyDb(PathFakeDb):
        opened = 0

        def __init__(self, db_path):
            super().__init__(db_path)
            type(self).opened += 1
            self.open_number = type(self).opened

        def get(self, key):
            value = super().get(key)
            if self.open_number == 2 and key == new_key:
                return b"mismatching readback"
            return value

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    source_raw = _player_raw("minecraft:stone")
    PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: _player_raw("minecraft:dirt")}

    # Build the export with a multiplayer key so the new-key mode is valid.
    player = {
        "player_key": encode_player_key(new_key),
        "label": "New player",
        "kind": "remote",
        "editable": True,
        "exportable": True,
    }
    export_path = create_player_export(str(world), player, source_raw, output_dir=str(tmp_path / "new-key-export"))
    service = BedrockEditorService(
        ITEMS,
        ENCHANTMENTS,
        db_factory=PathFakeDb,
        readonly_db_factory=MismatchingReadonlyDb,
    )
    preview = service.preview_player_export(export_path, str(world))

    with pytest.raises(PlayerImportRolledBackError):
        service.import_player(
            export_path,
            str(world),
            "",
            True,
            import_as_exported_player=True,
            import_token=preview["import_token"],
        )

    assert new_key not in PathFakeDb._shared_stores[str(world / "db")]


def test_direct_import_keeps_backup_when_record_rollback_fails(tmp_path: Path) -> None:
    class FailingRollbackDb(PathFakeDb):
        puts = 0

        def put(self, key, value):
            type(self).puts += 1
            if type(self).puts == 2:
                raise OSError("rollback write failed")
            super().put(key, value)

    class MismatchingReadonlyDb(PathFakeDb):
        opened = 0

        def __init__(self, db_path):
            super().__init__(db_path)
            type(self).opened += 1
            self.open_number = type(self).opened

        def get(self, key):
            value = super().get(key)
            if self.open_number == 2 and key == LOCAL_PLAYER_KEY:
                return b"mismatching readback"
            return value

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    source_raw = _player_raw("minecraft:stone")
    target_raw = _player_raw("minecraft:dirt")
    PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: target_raw}
    export_path = _export(world, tmp_path / "exports", source_raw)
    service = BedrockEditorService(
        ITEMS,
        ENCHANTMENTS,
        db_factory=FailingRollbackDb,
        readonly_db_factory=MismatchingReadonlyDb,
    )
    preview = service.preview_player_export(export_path, str(world))

    with pytest.raises(PlayerImportRecordRollbackError) as raised:
        service.import_player(
            export_path,
            str(world),
            encode_player_key(LOCAL_PLAYER_KEY),
            True,
            import_token=preview["import_token"],
            base_revision=service._player_revision(target_raw),
        )

    assert raised.value.rolled_back is False
    assert raised.value.backup_file
    assert Path(raised.value.backup_file).is_file()
    assert "rollback write failed" in raised.value.rollback_warning


def test_preview_reports_snapshot_cleanup_failure(tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    raw = _player_raw("minecraft:stone")
    export_path = _export(world, tmp_path / "exports", raw)
    service = _service()

    with patch("mcbe_editor.services.os.remove", side_effect=PermissionError("snapshot locked")):
        result = service.preview_player_export(export_path, str(world))

    assert result["success"] is True
    assert "snapshot locked" in result["cleanup_warning"]
    assert ".import_sources" in result["cleanup_warning"]


def test_failed_import_attaches_snapshot_cleanup_warning_to_original_error(tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    raw = nbt.NamedTag(nbt.CompoundTag({"Inventory": nbt.StringTag("opaque")})).save_to(
        compressed=False,
        little_endian=True,
    )
    export_path = _export(world, tmp_path / "exports", raw)
    service = _service()
    preview = service.preview_player_export(export_path, str(world))

    with (
        patch("mcbe_editor.services.os.remove", side_effect=PermissionError("snapshot locked")),
        pytest.raises(ValueError, match="unbekanntem NBT-Typ") as raised,
    ):
        service.import_player(
            export_path,
            str(world),
            encode_player_key(LOCAL_PLAYER_KEY),
            True,
            import_token=preview["import_token"],
        )

    assert "snapshot locked" in raised.value.cleanup_warning
