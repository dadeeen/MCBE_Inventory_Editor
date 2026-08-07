from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import mcbe_editor.db as db_module
from mcbe_editor.bedrock_nbt import load_player_nbt
from mcbe_editor.db import LevelDbAdapter, ReadonlyLevelDbAdapter
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.player_state_transfer import PLAYER_DEATH_LOCATION_FIELDS, PLAYER_IDENTITY_ROOT_KEYS
from mcbe_editor.players import decode_player_key
from mcbe_editor.service_errors import PlayerStateTransferRolledBackError
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import scan_minecraft_worlds

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_WORLD_ROOT = PROJECT_ROOT / "fixtures" / "private"
TRUE_VALUES = {"1", "true", "yes", "ja", "on"}
DEFAULT_MAX_WORLDS = 3
DEFAULT_MAX_PLAYERS = 6

pytestmark = [pytest.mark.private_world, pytest.mark.slow]


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUE_VALUES


def _env_limit(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _skip_unless_private_tests_enabled() -> None:
    if not _env_enabled("MCBE_RUN_PRIVATE_WORLD_TESTS"):
        pytest.skip("Private Welten werden nur mit MCBE_RUN_PRIVATE_WORLD_TESTS=1 geprüft.")


def _private_world_paths() -> list[Path]:
    _skip_unless_private_tests_enabled()
    if not PRIVATE_WORLD_ROOT.is_dir():
        pytest.skip("Keine privaten Welt-Fixtures unter fixtures/private vorhanden.")
    entries = scan_minecraft_worlds(paths=[str(PRIVATE_WORLD_ROOT)])
    if not entries:
        pytest.skip("Keine direkten Bedrock-Weltordner unter fixtures/private gefunden.")
    limit = _env_limit("MCBE_PRIVATE_WORLD_MAX_WORLDS", DEFAULT_MAX_WORLDS)
    return [Path(entry["path"]) for entry in entries[:limit]]


def _redacted_error(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    try:
        private_root = str(PRIVATE_WORLD_ROOT.resolve())
    except OSError:
        private_root = str(PRIVATE_WORLD_ROOT)
    return text.replace(private_root, "<fixtures/private>")


def _service() -> BedrockEditorService:
    return BedrockEditorService(ITEMS, ENCHANTMENTS)


def _editable_players(service: BedrockEditorService, world_path: Path) -> list[dict[str, Any]]:
    result = service.list_players(str(world_path))
    assert result["success"] is True
    players = result.get("players")
    assert isinstance(players, list)
    return [player for player in players if player.get("editable") and player.get("player_key")]


def _copy_world_for_write_test(source: Path, tmp_path: Path, index: int) -> Path:
    target = tmp_path / f"world_copy_{index}"

    def ignore_generated_or_linked_entries(directory: str, names: list[str]) -> list[str]:
        ignored = []
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_symlink() or name.endswith("_backups") or "_rollback_" in name or "_restoring_" in name or "_player_import_" in name:
                ignored.append(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore_generated_or_linked_entries)
    return target


def _allow_direct_writes_to_temporary_world_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the web write guard out of explicit offline tests on disposable copies."""

    monkeypatch.setattr(db_module, "_runtime_app_modules", lambda: ())
    monkeypatch.setattr(db_module, "_registered_write_guard", None)


def _first_loadable_player(service: BedrockEditorService, world_paths: list[Path]) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    max_players = _env_limit("MCBE_PRIVATE_WORLD_MAX_PLAYERS", DEFAULT_MAX_PLAYERS)
    attempts = 0
    for world_index, world_path in enumerate(world_paths):
        try:
            players = _editable_players(service, world_path)
        except Exception as exc:
            pytest.fail(f"Private Welt #{world_index + 1}: Spielerauflistung fehlgeschlagen ({_redacted_error(exc)}).")
        for player_index, player in enumerate(players):
            if attempts >= max_players:
                return None
            attempts += 1
            try:
                loaded = service.load_player(str(world_path), player["player_key"])
            except Exception as exc:
                pytest.fail(f"Private Welt #{world_index + 1}, Spieler #{player_index + 1}: Laden fehlgeschlagen ({_redacted_error(exc)}).")
            return world_path, player, loaded
    return None


def _stat_update_for_loaded_player(loaded: dict[str, Any]) -> tuple[str, Any] | None:
    stats = loaded.get("stats") if isinstance(loaded.get("stats"), dict) else {}
    protected = loaded.get("protected_nbt") if isinstance(loaded.get("protected_nbt"), dict) else {}
    opaque_stats = protected.get("stat_fields_opaque") if isinstance(protected.get("stat_fields_opaque"), dict) else {}

    if "xp_level" not in opaque_stats:
        current = int(stats.get("xp_level") or 0)
        return "xp_level", current + 1 if current < 24791 else current - 1
    if "health" not in opaque_stats:
        current = float(stats.get("health") or 20.0)
        return "health", 20.0 if current != 20.0 else 19.0
    if "food_level" not in opaque_stats:
        current = int(stats.get("food_level") or 20)
        return "food_level", 20 if current != 20 else 19
    if "xp_progress" not in opaque_stats:
        current = float(stats.get("xp_progress") or 0.0)
        return "xp_progress", 0.0 if current > 0.5 else 0.75
    return None


def test_private_worlds_scan_list_and_load_players_readonly() -> None:
    world_paths = _private_world_paths()
    service = _service()
    loaded_count = 0
    max_players = _env_limit("MCBE_PRIVATE_WORLD_MAX_PLAYERS", DEFAULT_MAX_PLAYERS)

    for world_index, world_path in enumerate(world_paths):
        try:
            players = _editable_players(service, world_path)
        except Exception as exc:
            pytest.fail(f"Private Welt #{world_index + 1}: Spielerauflistung fehlgeschlagen ({_redacted_error(exc)}).")
        for player_index, player in enumerate(players):
            if loaded_count >= max_players:
                break
            try:
                loaded = service.load_player(str(world_path), player["player_key"])
            except Exception as exc:
                pytest.fail(f"Private Welt #{world_index + 1}, Spieler #{player_index + 1}: Laden fehlgeschlagen ({_redacted_error(exc)}).")
            assert loaded["success"] is True
            assert isinstance(loaded.get("player_revision"), str)
            assert len(loaded["player_revision"]) == 64
            assert isinstance(loaded.get("stats"), dict)
            assert isinstance(loaded.get("compatibility"), dict)
            player_report = loaded["compatibility"].get("player")
            assert isinstance(player_report, dict)
            assert player_report.get("roundtrip", {}).get("readable_before_edit") is True
            loaded_count += 1

    if loaded_count == 0:
        pytest.skip("Private Welten gefunden, aber kein editierbarer Spieler erkannt.")


@pytest.mark.destructive
def test_private_world_backup_restore_on_temporary_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _env_enabled("MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS"):
        pytest.skip("Schreibtests auf privaten Weltkopien laufen nur mit MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS=1.")
    world_paths = _private_world_paths()
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    _allow_direct_writes_to_temporary_world_copies(monkeypatch)
    service = _service()

    copied_world = _copy_world_for_write_test(world_paths[0], tmp_path, 1)
    result = service.create_manual_backup(str(copied_world))
    assert result["success"] is True
    backup_file = result["backup_file"]

    marker_file = copied_world / "private_restore_marker.tmp"
    marker_file.write_text("restore should remove this file\n", encoding="utf-8")

    preview = service.preview_backup_restore(str(copied_world), backup_file)
    assert preview["success"] is True
    assert preview["backup"]["has_db"] is True

    restored = service.restore_backup(str(copied_world), backup_file)
    assert restored["success"] is True
    assert not marker_file.exists()


@pytest.mark.destructive
def test_private_world_save_player_stat_on_temporary_copy_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _env_enabled("MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS"):
        pytest.skip("Schreibtests auf privaten Weltkopien laufen nur mit MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS=1.")
    source_world_paths = _private_world_paths()
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    _allow_direct_writes_to_temporary_world_copies(monkeypatch)

    copied_world_paths = [_copy_world_for_write_test(path, tmp_path, index + 1) for index, path in enumerate(source_world_paths)]
    service = _service()
    selected = _first_loadable_player(service, copied_world_paths)
    if selected is None:
        pytest.skip("Keine editierbaren privaten Spieler für Schreibtest gefunden.")
    world_path, player, loaded = selected

    stat_update = _stat_update_for_loaded_player(loaded)
    if stat_update is None:
        pytest.skip("Kein sicher editierbares Statistikfeld für den privaten Spieler gefunden.")
    field_name, changed_value = stat_update

    save_result = service.save_player(
        str(world_path),
        player["player_key"],
        None,
        {field_name: changed_value},
        base_revision=loaded["player_revision"],
    )
    assert save_result["success"] is True
    assert save_result["no_op"] is False
    assert isinstance(save_result.get("backup_file"), str)

    changed = service.load_player(str(world_path), player["player_key"])
    assert changed["stats"][field_name] == pytest.approx(changed_value)
    assert changed["player_revision"] != loaded["player_revision"]

    restored = service.restore_backup(str(world_path), save_result["backup_file"])
    assert restored["success"] is True
    reloaded = service.load_player(str(world_path), player["player_key"])
    assert reloaded["player_revision"] == loaded["player_revision"]


@pytest.mark.destructive
def test_private_world_export_and_import_player_on_temporary_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _env_enabled("MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS"):
        pytest.skip("Schreibtests auf privaten Weltkopien laufen nur mit MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS=1.")
    source_world_paths = _private_world_paths()
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    _allow_direct_writes_to_temporary_world_copies(monkeypatch)

    copied_world_paths = [_copy_world_for_write_test(path, tmp_path, index + 1) for index, path in enumerate(source_world_paths)]
    service = _service()
    selected = _first_loadable_player(service, copied_world_paths)
    if selected is None:
        pytest.skip("Keine editierbaren privaten Spieler für Importtest gefunden.")
    world_path, player, loaded = selected

    export_result = service.export_player(str(world_path), player["player_key"])
    assert export_result["success"] is True
    export_path = Path(export_result["export_path"])
    assert export_path.is_file()

    preview = service.preview_player_export(str(export_path), str(world_path))
    assert preview["success"] is True
    assert preview["importable"] is True

    import_result = service.import_player(
        str(export_path),
        str(world_path),
        player["player_key"],
        confirm_overwrite=True,
        import_token=preview["import_token"],
        base_revision=loaded["player_revision"],
    )
    assert import_result["success"] is True

    imported = service.load_player(str(world_path), player["player_key"])
    assert imported["success"] is True
    assert imported["player_revision"] == loaded["player_revision"]


@pytest.mark.destructive
def test_private_world_player_state_transfer_on_temporary_combined_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not _env_enabled("MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS"):
        pytest.skip("Schreibtests auf privaten Weltkopien laufen nur mit MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS=1.")
    source_world_paths = _private_world_paths()
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    _allow_direct_writes_to_temporary_world_copies(monkeypatch)
    service = _service()

    local_candidate = None
    remote_candidate = None
    for world_path in source_world_paths:
        for player in _editable_players(service, world_path):
            if player.get("kind") == "local" and local_candidate is None:
                local_candidate = (world_path, player)
            elif player.get("kind") == "remote" and remote_candidate is None:
                remote_candidate = (world_path, player)
    if local_candidate is None or remote_candidate is None:
        pytest.skip("Für den Migrationstest werden eine lokale und eine Multiplayer-Spieler-Fixture benötigt.")

    local_world, local_player = local_candidate
    remote_world, remote_player = remote_candidate
    copied_world = _copy_world_for_write_test(local_world, tmp_path, 1)
    remote_key = decode_player_key(remote_player["player_key"])
    remote_db = ReadonlyLevelDbAdapter(str(remote_world / "db"))
    try:
        remote_before_raw = remote_db.get(remote_key)
    finally:
        remote_db.close()

    copied_db = LevelDbAdapter(str(copied_world / "db"))
    try:
        copied_db.put(remote_key, remote_before_raw)
    finally:
        copied_db.close()

    combined_players = _editable_players(service, copied_world)
    copied_local = next(player for player in combined_players if player.get("kind") == "local")
    copied_remote = next(player for player in combined_players if player["player_key"] == remote_player["player_key"])
    local_key = decode_player_key(copied_local["player_key"])
    before_db = ReadonlyLevelDbAdapter(str(copied_world / "db"))
    try:
        local_before_raw = before_db.get(local_key)
        target_before_raw = before_db.get(remote_key)
    finally:
        before_db.close()

    preview = service.preview_player_state_transfer(str(copied_world), copied_local["player_key"], copied_remote["player_key"])
    result = service.transfer_player_state(
        str(copied_world),
        copied_local["player_key"],
        copied_remote["player_key"],
        confirm_transfer=True,
        transfer_token=preview["transfer_token"],
    )

    assert result["success"] is True
    assert result["validation"]["valid"] is True
    assert result["validation"]["target_identity_preserved"] is True
    assert result["source_deleted"] is False
    assert isinstance(result.get("backup_file"), str)

    after_db = ReadonlyLevelDbAdapter(str(copied_world / "db"))
    try:
        assert after_db.get(local_key) == local_before_raw
        target_after_raw = after_db.get(remote_key)
    finally:
        after_db.close()
    assert target_after_raw != target_before_raw

    source_tag = load_player_nbt(local_before_raw).tag
    target_before_tag = load_player_nbt(target_before_raw).tag
    target_after_tag = load_player_nbt(target_after_raw).tag
    for field in PLAYER_IDENTITY_ROOT_KEYS:
        if field in target_before_tag:
            assert field in target_after_tag
            assert target_after_tag[field] == target_before_tag[field]
    assert target_after_tag["TimeSinceRest"] == source_tag["TimeSinceRest"]
    assert all(field not in target_after_tag for field in PLAYER_DEATH_LOCATION_FIELDS)
    source_recipes = {entry.py_data for entry in source_tag["recipe_unlocking"]["unlocked_recipes"]}
    target_before_recipes = {entry.py_data for entry in target_before_tag["recipe_unlocking"]["unlocked_recipes"]}
    target_after_recipes = {entry.py_data for entry in target_after_tag["recipe_unlocking"]["unlocked_recipes"]}
    assert source_recipes <= target_after_recipes
    assert target_before_recipes <= target_after_recipes

    restored = service.restore_backup(str(copied_world), result["backup_file"])
    assert restored["success"] is True
    restored_db = ReadonlyLevelDbAdapter(str(copied_world / "db"))
    try:
        assert restored_db.get(local_key) == local_before_raw
        assert restored_db.get(remote_key) == target_before_raw
    finally:
        restored_db.close()

    rollback_preview = service.preview_player_state_transfer(str(copied_world), copied_local["player_key"], copied_remote["player_key"])
    with (
        patch("mcbe_editor.services.validate_player_state_transfer", side_effect=ValueError("forced private-world validation failure")),
        pytest.raises(PlayerStateTransferRolledBackError, match="forced private-world validation failure"),
    ):
        service.transfer_player_state(
            str(copied_world),
            copied_local["player_key"],
            copied_remote["player_key"],
            confirm_transfer=True,
            transfer_token=rollback_preview["transfer_token"],
        )

    rolled_back_db = ReadonlyLevelDbAdapter(str(copied_world / "db"))
    try:
        assert rolled_back_db.get(local_key) == local_before_raw
        assert rolled_back_db.get(remote_key) == target_before_raw
    finally:
        rolled_back_db.close()
