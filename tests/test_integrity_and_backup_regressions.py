import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_item_moves_keep_one_immutable_origin_tuple() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/inventory_state.js", "utf8"), context);

            const state = context.window.MCBEInventoryState;
            const source = {
                slot: 1,
                source_slot: 7,
                source_player_key: "player-a",
                source_container: "inventory",
                source_world_path: "C:/world",
                source_item_digest: "a".repeat(64),
                name: "minecraft:stone",
                count: 1,
            };
            const moved = state.cloneItemForSlot(source, 5, "inventory");
            assert.strictEqual(moved.slot, 5);
            assert.strictEqual(moved.source_slot, 7);
            assert.strictEqual(moved.source_player_key, "player-a");
            assert.strictEqual(moved.source_container, "inventory");
            assert.strictEqual(moved.source_world_path, "C:/world");
            assert.strictEqual(moved.source_item_digest, "a".repeat(64));

            const pasted = state.cloneClipboardForTarget(source, 8, "inventory");
            assert.strictEqual(pasted.slot, 8);
            assert.strictEqual(pasted.source_player_key, "player-a");
            assert.strictEqual(pasted.source_slot, 7);
            assert.strictEqual(pasted.source_item_digest, "a".repeat(64));
            """
        )
    )


def test_cross_world_clipboard_clone_is_marked_and_save_validation_blocks_it() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = {
                window: {
                    t(text, params) {
                        return String(text).replace(/\{(\w+)\}/g, (match, key) => params && key in params ? String(params[key]) : match);
                    },
                },
            };
            vm.runInNewContext(fs.readFileSync("static/inventory_state.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/save_logic.js", "utf8"), context);

            const source = {
                slot: 5,
                source_slot: 5,
                source_player_key: "local-player",
                source_container: "inventory",
                source_world_path: "C:/World-A",
                source_item_digest: "b".repeat(64),
                name: "minecraft:stone",
                count: 1,
                damage: 0,
            };
            const cloned = context.window.MCBEInventoryState.cloneClipboardForTarget(
                source,
                8,
                "inventory",
                {
                    ensureOrigin(item, containerName) {
                        if (!Number.isInteger(item.source_slot) && Number.isInteger(item.slot)) item.source_slot = item.slot;
                        if (!item.source_player_key) item.source_player_key = "local-player";
                        if (!item.source_container) item.source_container = containerName;
                        if (!item.source_world_path) item.source_world_path = "C:/World-B";
                        return item;
                    },
                },
            );

            assert.strictEqual(cloned.origin_world_mismatch, true);
            assert.strictEqual(cloned.source_player_key, "");
            assert.strictEqual(cloned.source_container, "__cross_world__");
            assert.strictEqual(cloned.source_item_digest, "b".repeat(64));

            const saveLogic = context.window.MCBESaveLogic.createSaveLogic({
                slotDisplayName: slot => `Slot ${slot}`,
                getMaxStack: () => 64,
                getMaxDamage: () => 32767,
                isValidItemId: () => true,
                isKnownItemId: () => true,
                maxBedrockStackCount: 127,
            });
            const issues = saveLogic.validateItemInSlot(cloned, 8, "inventory");
            assert.ok(issues.some(issue => issue.level === "error" && issue.label.includes("anderen Welt")));
            """
        )
    )


def _item_tag(
    nbt,
    *,
    slot: int,
    name: str,
    marker: int | None = None,
    was_picked_up: int | None = None,
    count: int = 1,
    damage: int = 0,
):
    fields = {
        "Slot": nbt.ByteTag(slot),
        "Name": nbt.StringTag(name),
        "Count": nbt.ByteTag(count),
        "Damage": nbt.ShortTag(damage),
    }
    if was_picked_up is not None:
        fields["WasPickedUp"] = nbt.ByteTag(was_picked_up)
    if marker is not None:
        fields["tag"] = nbt.CompoundTag({"addon_marker": nbt.IntTag(marker)})
    return nbt.CompoundTag(fields)


def _payload(*, slot: int, name: str, protected: bool = False) -> dict:
    return {
        "slot": slot,
        "source_slot": 5,
        "source_player_key": "player-a",
        "source_container": "inventory",
        "source_world_path": "C:/world",
        "name": name,
        "count": 1,
        "damage": 0,
        "display_name": "",
        "lore": [],
        "enchantments": [],
        "has_preserved_nbt": protected,
    }


def test_load_payload_contains_preservation_digest() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    source = _item_tag(nbt, slot=5, name="minecraft:stone", marker=123, was_picked_up=1)
    data, _originals = inventory.nbt_to_json(nbt.CompoundTag({"Inventory": nbt.ListTag([source])}))

    assert len(data[5]["source_item_digest"]) == 64
    assert data[5]["source_item_digest"] == inventory._item_source_digest(source)


def test_preservation_digest_ignores_editable_fields_but_tracks_preserved_nbt() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    first = _item_tag(nbt, slot=5, name="minecraft:stone", was_picked_up=1, count=1, damage=0)
    edited = _item_tag(nbt, slot=8, name="minecraft:stone", was_picked_up=1, count=32, damage=7)
    changed_preserved = _item_tag(nbt, slot=8, name="minecraft:stone", was_picked_up=0, count=32, damage=7)

    assert inventory._item_source_digest(first) == inventory._item_source_digest(edited)
    assert inventory._item_source_digest(first) != inventory._item_source_digest(changed_preserved)


def test_plain_addable_item_preserves_exact_external_source_nbt() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    foreign = _item_tag(nbt, slot=5, name="minecraft:stone", marker=1234)
    target = _item_tag(nbt, slot=8, name="minecraft:dirt", marker=9876)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([target])})
    payload = _payload(slot=8, name="minecraft:stone")
    payload["source_item_digest"] = inventory._item_source_digest(foreign)

    saved = inventory.build_inventory_nbt(
        player,
        [payload],
        inventory.ENCHANTMENTS,
        source_item_maps={("player-a", "inventory"): {5: foreign}},
        target_player_key="player-b",
    )
    result = {entry["Slot"].py_data: entry for entry in saved}[8]

    assert result["tag"]["addon_marker"].py_data == 1234


def test_stale_cross_player_source_digest_is_rejected() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    loaded_source = _item_tag(nbt, slot=5, name="minecraft:stone", was_picked_up=1)
    current_source = _item_tag(nbt, slot=5, name="minecraft:stone", was_picked_up=0)
    payload = _payload(slot=8, name="minecraft:stone")
    payload["source_item_digest"] = inventory._item_source_digest(loaded_source)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            player,
            [payload],
            inventory.ENCHANTMENTS,
            source_item_maps={("player-a", "inventory"): {5: current_source}},
            target_player_key="player-b",
        )


def test_stale_same_player_source_digest_is_rejected() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    loaded_source = _item_tag(nbt, slot=5, name="minecraft:stone", marker=1)
    current_source = _item_tag(nbt, slot=5, name="minecraft:stone", marker=2)
    payload = _payload(slot=8, name="minecraft:stone")
    payload["source_item_digest"] = inventory._item_source_digest(loaded_source)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([current_source])})

    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            player,
            [payload],
            inventory.ENCHANTMENTS,
            target_player_key="player-a",
        )


def test_partial_external_origin_is_rejected_before_target_nbt_fallback() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    target = _item_tag(nbt, slot=8, name="minecraft:stone", marker=9876)
    payload = _payload(slot=8, name="minecraft:stone")
    payload["source_slot"] = 8
    payload.pop("source_container")

    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            nbt.CompoundTag({"Inventory": nbt.ListTag([target])}),
            [payload],
            inventory.ENCHANTMENTS,
            target_player_key="player-b",
        )


def test_plain_addable_item_rejects_unverifiable_external_source_instead_of_falling_back() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    target = _item_tag(nbt, slot=8, name="minecraft:stone", marker=9876)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([target])})

    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            player,
            [_payload(slot=8, name="minecraft:stone")],
            inventory.ENCHANTMENTS,
            source_item_maps={},
            target_player_key="player-b",
        )


def test_plain_same_player_move_preserves_standard_unedited_root_nbt() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    source = _item_tag(nbt, slot=5, name="minecraft:stone", was_picked_up=1)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([source])})

    saved = inventory.build_inventory_nbt(
        player,
        [_payload(slot=8, name="minecraft:stone")],
        inventory.ENCHANTMENTS,
        target_player_key="player-a",
    )
    result = {entry["Slot"].py_data: entry for entry in saved}[8]

    assert result["WasPickedUp"].py_data == 1


def test_saving_an_unedited_item_keeps_empty_list_element_types() -> None:
    """copy.deepcopy resets empty ListTags to byte and silently rewrites add-on NBT."""

    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    # 0 = TAG_End (canonical empty list), 8 = string, 10 = compound.
    for element_type in (0, 3, 8, 10):
        source = _item_tag(nbt, slot=5, name="minecraft:stone")
        source["AddonRootList"] = nbt.ListTag([], element_type)
        source["tag"] = nbt.CompoundTag({"AddonTagList": nbt.ListTag([], element_type)})
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([source])})
        payload = _payload(slot=5, name="minecraft:stone", protected=True)
        payload["source_slot"] = 5
        payload["source_player_key"] = None
        payload["source_world_path"] = None
        payload["source_item_digest"] = inventory._item_source_digest(source)

        saved = inventory.build_inventory_nbt(player, [payload], inventory.ENCHANTMENTS, target_player_key=None)
        result = {entry["Slot"].py_data: entry for entry in saved}[5]

        assert result["AddonRootList"].list_data_type == element_type
        assert result["tag"]["AddonTagList"].list_data_type == element_type


def test_saving_an_unedited_item_preserves_lore_formatting_byte_exact() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory
    from mcbe_editor.bedrock_nbt import save_player_nbt

    source = _item_tag(nbt, slot=5, name="minecraft:stone")
    source["tag"] = nbt.CompoundTag(
        {
            "display": nbt.CompoundTag(
                {
                    "Lore": nbt.ListTag(
                        [
                            nbt.StringTag("Block A"),
                            nbt.StringTag(""),
                            nbt.StringTag("  eingerückt  "),
                        ]
                    )
                }
            )
        }
    )
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([source])})
    inventory_data, _originals = inventory.nbt_to_json(player)

    saved = inventory.build_inventory_nbt(
        player,
        [inventory_data[5]],
        inventory.ENCHANTMENTS,
        target_player_key=None,
    )
    result = {entry["Slot"].py_data: entry for entry in saved}[5]

    assert [line.py_data for line in result["tag"]["display"]["Lore"]] == ["Block A", "", "  eingerückt  "]
    assert save_player_nbt(nbt.NamedTag(result)) == save_player_nbt(nbt.NamedTag(source))


def test_non_addable_item_keeps_exact_external_source_even_without_extra_nbt_flags() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    addon_name = "example:custom_item"
    foreign = _item_tag(nbt, slot=5, name=addon_name, marker=2468)
    payload = _payload(slot=8, name=addon_name)
    payload["source_item_digest"] = inventory._item_source_digest(foreign)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

    saved = inventory.build_inventory_nbt(
        player,
        [payload],
        inventory.ENCHANTMENTS,
        source_item_maps={("player-a", "inventory"): {5: foreign}},
        target_player_key="player-b",
    )
    result = {entry["Slot"].py_data: entry for entry in saved}[8]

    assert result["tag"]["addon_marker"].py_data == 2468


def test_protected_item_rejects_missing_or_mismatched_external_origin() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
    mismatched = _item_tag(nbt, slot=5, name="minecraft:dirt", marker=1)

    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            player,
            [_payload(slot=8, name="minecraft:stone", protected=True)],
            inventory.ENCHANTMENTS,
            source_item_maps={("player-a", "inventory"): {5: mismatched}},
            target_player_key="player-b",
        )


@pytest.mark.parametrize(
    ("name", "protected"),
    [("minecraft:stone", True), ("example:custom_item", False)],
)
def test_moved_source_dependent_item_rejects_incomplete_origin(name: str, protected: bool) -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    original = _item_tag(nbt, slot=5, name=name, marker=777)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
    payload = _payload(slot=8, name=name, protected=protected)
    payload.pop("source_player_key")

    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            player,
            [payload],
            inventory.ENCHANTMENTS,
            target_player_key="player-b",
        )


def _backup_deps(service, *, final_gate=None):
    from mcbe_editor.backup_api_routes import BackupRouteDeps

    class FinalGateBlocked(Exception):
        def __init__(self, message="blocked"):
            super().__init__(message)
            self.write_gate = {"blocked_operation": "final_write_gate"}

    return BackupRouteDeps(
        service=service,
        jsonify=lambda payload: payload,
        api_error=lambda error, status=400: ({"success": False, "error": str(error)}, status),
        log_api_exception=lambda *_args: None,
        json_string=lambda data, key: str(data[key]),
        require_world_write_allowed=lambda: None,
        require_final_world_write_allowed=final_gate or (lambda _operation: None),
        presence_conflict_response=lambda *_args, **_kwargs: None,
        audit_event=lambda *_args, **_kwargs: None,
        final_write_gate_blocked_error=FinalGateBlocked,
    ), FinalGateBlocked


def test_manual_backup_discards_archive_when_source_changes(monkeypatch) -> None:
    from mcbe_editor import backup_api_routes

    service = SimpleNamespace(
        create_manual_backup=Mock(return_value={"success": True, "backup_file": "world_manual.zip"}),
        delete_backup=Mock(return_value={"success": True}),
    )
    deps, _error_type = _backup_deps(service)
    snapshots = iter(["before", "after"])
    monkeypatch.setattr(backup_api_routes, "ensure_valid_world_path", lambda path: path)
    monkeypatch.setattr(backup_api_routes, "_source_snapshot", lambda _path: next(snapshots))

    response, status = backup_api_routes.create_backup({"world_path": "C:/world"}, deps)

    assert status == 409
    assert response["code"] == "backup_source_changed"
    service.delete_backup.assert_called_once_with("C:/world", "world_manual.zip")


def test_source_snapshot_does_not_suppress_directory_walk_errors(monkeypatch, tmp_path) -> None:
    from mcbe_editor import backup_api_routes

    denied_path = tmp_path / "db"

    def inaccessible_walk(_root, *, topdown, onerror, followlinks):
        assert topdown is True
        assert followlinks is False
        onerror(PermissionError(13, "denied", str(denied_path)))
        return []

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(backup_api_routes.os, "walk", inaccessible_walk)

        with pytest.raises(ValueError, match="kann nicht durchsucht werden"):
            backup_api_routes._source_snapshot(str(tmp_path))


def test_manual_backup_discards_archive_when_server_starts_after_snapshot(monkeypatch) -> None:
    from mcbe_editor import backup_api_routes

    service = SimpleNamespace(
        create_manual_backup=Mock(return_value={"success": True, "backup_file": "world_manual.zip"}),
        delete_backup=Mock(return_value={"success": True}),
    )
    calls = 0
    deps, error_type = _backup_deps(service)

    def final_gate(_operation):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error_type("Server läuft inzwischen.")

    deps = type(deps)(**{**deps.__dict__, "require_final_world_write_allowed": final_gate})
    monkeypatch.setattr(backup_api_routes, "ensure_valid_world_path", lambda path: path)
    monkeypatch.setattr(backup_api_routes, "_source_snapshot", lambda _path: "stable")

    response, status = backup_api_routes.create_backup({"world_path": "C:/world"}, deps)

    assert status == 409
    assert response["code"] == "final_write_gate_blocked"
    service.delete_backup.assert_called_once_with("C:/world", "world_manual.zip")


@pytest.mark.parametrize(
    ("verification_error", "expected_status"),
    [
        (ValueError("Weltdatei kann nach der Sicherung nicht gelesen werden."), 400),
        (OSError("Nachprüfung ist fehlgeschlagen."), 500),
    ],
)
def test_manual_backup_discards_archive_on_any_post_create_verification_error(monkeypatch, verification_error, expected_status) -> None:
    from mcbe_editor import backup_api_routes

    service = SimpleNamespace(
        create_manual_backup=Mock(return_value={"success": True, "backup_file": "world_manual.zip"}),
        delete_backup=Mock(return_value={"success": True}),
    )
    deps, _error_type = _backup_deps(service)
    calls = 0

    def source_snapshot(_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "before"
        raise verification_error

    monkeypatch.setattr(backup_api_routes, "ensure_valid_world_path", lambda path: path)
    monkeypatch.setattr(backup_api_routes, "_source_snapshot", source_snapshot)

    _response, status = backup_api_routes.create_backup({"world_path": "C:/world"}, deps)

    assert status == expected_status
    service.delete_backup.assert_called_once_with("C:/world", "world_manual.zip")


def test_manual_backup_reports_cleanup_failure_after_verification_error(monkeypatch) -> None:
    from mcbe_editor import backup_api_routes

    service = SimpleNamespace(
        create_manual_backup=Mock(return_value={"success": True, "backup_file": "world_manual.zip"}),
        delete_backup=Mock(side_effect=OSError("Datei ist gesperrt")),
    )
    deps, _error_type = _backup_deps(service)
    calls = 0

    def source_snapshot(_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "before"
        raise ValueError("Nachprüfung fehlgeschlagen")

    monkeypatch.setattr(backup_api_routes, "ensure_valid_world_path", lambda path: path)
    monkeypatch.setattr(backup_api_routes, "_source_snapshot", source_snapshot)

    response, status = backup_api_routes.create_backup({"world_path": "C:/world"}, deps)

    assert status == 400
    assert response["code"] == "backup_verification_failed"
    assert "world_manual.zip" in response["cleanup_warning"]


def test_manual_backup_route_is_protected_from_local_heartbeat_shutdown() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    route_start = source.index('@app.route("/api/backup/create"')
    route_end = source.index("def create_backup_route", route_start)
    decorators = source[route_start:route_end]

    assert "@save_in_progress" in decorators
