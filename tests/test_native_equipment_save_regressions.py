"""Equipment saves preserve unrelated records through the real backup/write path."""

from copy import deepcopy
from pathlib import Path

import pytest

from mcbe_editor import nbt
from mcbe_editor.backup import get_backups_dir
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import LOCAL_PLAYER_KEY
from tests.nbt_fixtures import make_minimal_player_tag


SOURCE_KEY = b"player_synthetic_source"
UNRELATED_KEY = b"synthetic-opaque-record"
UNRELATED_VALUE = b"\x00\xffpreserve-me"


def _item(name, slot=None, **extra):
    fields = {"Name": nbt.StringTag(name), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0), **extra}
    if slot is not None:
        fields["Slot"] = nbt.ByteTag(slot)
    return nbt.CompoundTag(fields)


def _empty_root_item():
    return nbt.CompoundTag(
        {
            "Name": nbt.StringTag(""),
            "Count": nbt.ByteTag(0),
            "Damage": nbt.ShortTag(0),
            "WasPickedUp": nbt.ByteTag(0),
        }
    )


def _armor(helmet=None):
    return nbt.ListTag([helmet if helmet is not None else _empty_root_item(), *[_empty_root_item() for _ in range(3)]])


def _seed(tmp_path, monkeypatch, player_tags):
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    raw = {key: save_player_nbt(nbt.NamedTag(tag)) for key, tag in player_tags.items()}
    raw[UNRELATED_KEY] = UNRELATED_VALUE
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch(raw)
    finally:
        db.close()
    return world, raw, BedrockEditorService(ITEMS, ENCHANTMENTS)


def _read_all(service, world):
    db = service._open_db_readonly(str(world))
    try:
        return dict(db.iter_items())
    finally:
        db.close()


@pytest.mark.parametrize("slot,root_tag,item_name", [(103, "Armor", "minecraft:diamond_helmet"), (-106, "Offhand", "minecraft:shield")])
def test_native_inventory_change_keeps_hidden_root_equipment(tmp_path, monkeypatch, slot, root_tag, item_name):
    player = make_minimal_player_tag()
    player["Inventory"] = nbt.ListTag([_item(item_name, slot), _item("minecraft:stone", 0)])
    hidden = _item(item_name, FutureData=nbt.StringTag("preserve hidden equipment"))
    player[root_tag] = _armor(hidden) if root_tag == "Armor" else nbt.ListTag([hidden])
    root_before = player[root_tag].save_to()
    world, _raw, service = _seed(tmp_path, monkeypatch, {LOCAL_PLAYER_KEY: player})
    key = encode_player_key(LOCAL_PLAYER_KEY)
    loaded = service.load_player(str(world), key)
    payload = deepcopy(list(loaded["inventory"].values()))
    next(item for item in payload if item["slot"] == 0)["count"] = 2

    result = service.save_player(
        str(world),
        key,
        payload,
        {},
        base_revision=loaded["player_revision"],
        root_equipment_editable=True,
    )

    assert result["success"] is True and result["no_op"] is False
    assert (Path(get_backups_dir(str(world))) / result["backup_file"]).is_file()
    records = _read_all(service, world)
    saved = load_player_nbt(records[LOCAL_PLAYER_KEY]).tag
    assert saved[root_tag].save_to() == root_before
    assert next(item for item in saved["Inventory"] if item["Slot"].py_data == 0)["Count"].py_data == 2
    assert records[UNRELATED_KEY] == UNRELATED_VALUE


@pytest.mark.parametrize("inventory_helmet", [False, True])
def test_native_inventory_change_preserves_unusual_armor_at_its_stored_index(tmp_path, monkeypatch, inventory_helmet):
    player = make_minimal_player_tag()
    player["Inventory"] = nbt.ListTag([_item("minecraft:stone", 0)])
    if inventory_helmet:
        player["Inventory"].append(_item("minecraft:iron_helmet", 103))
    player["Armor"] = _armor(_item("minecraft:diamond_helmet"))
    # Dense modern Armor uses the list index, even for equipment placed in an
    # unusual slot by a command/add-on. A second helmet must not be hidden by
    # the first helmet's inferred category and then cleared on an unrelated save.
    player["Armor"][1] = _item("minecraft:diamond_helmet", FutureData=nbt.StringTag("keep this equipment"))
    root_before = player["Armor"].save_to()
    world, _raw, service = _seed(tmp_path, monkeypatch, {LOCAL_PLAYER_KEY: player})
    key = encode_player_key(LOCAL_PLAYER_KEY)
    loaded = service.load_player(str(world), key)
    assert loaded["inventory"][102]["name"] == "minecraft:diamond_helmet"
    assert loaded["inventory"][102]["root_equipment_source_index"] == 1
    payload = deepcopy(list(loaded["inventory"].values()))
    next(entry for entry in payload if entry["slot"] == 0)["count"] = 2

    result = service.save_player(
        str(world),
        key,
        payload,
        {},
        base_revision=loaded["player_revision"],
        root_equipment_editable=True,
    )

    assert result["success"] is True and result["no_op"] is False
    records = _read_all(service, world)
    saved = load_player_nbt(records[LOCAL_PLAYER_KEY]).tag
    assert saved["Armor"].save_to() == root_before
    assert records[UNRELATED_KEY] == UNRELATED_VALUE
    reloaded = service.load_player(str(world), key)
    echoed = service.save_player(
        str(world),
        key,
        list(reloaded["inventory"].values()),
        {},
        base_revision=reloaded["player_revision"],
        root_equipment_editable=True,
    )
    assert echoed["no_op"] is True


@pytest.mark.parametrize("target_slot", [1, 103])
@pytest.mark.parametrize("source_inventory_shape", ["absent", "empty", "placeholder"])
def test_native_cross_player_root_copy_preserves_source_and_item_nbt(tmp_path, monkeypatch, target_slot, source_inventory_shape):
    source = make_minimal_player_tag()
    helmet = _item("minecraft:diamond_helmet", tag=nbt.CompoundTag({"FutureData": nbt.StringTag("preserve copied equipment")}))
    source["Armor"] = _armor(helmet)
    if source_inventory_shape != "absent":
        placeholder = _empty_root_item()
        placeholder["Slot"] = nbt.ByteTag(103)
        source["Inventory"] = nbt.ListTag([placeholder] if source_inventory_shape == "placeholder" else [], 10)
    target = make_minimal_player_tag()
    target["Inventory"] = nbt.ListTag([])
    target["Armor"] = _armor()
    world, original_records, service = _seed(tmp_path, monkeypatch, {LOCAL_PLAYER_KEY: target, SOURCE_KEY: source})
    source_loaded = service.load_player(str(world), encode_player_key(SOURCE_KEY))
    target_key = encode_player_key(LOCAL_PLAYER_KEY)
    target_loaded = service.load_player(str(world), target_key)
    copied_item = deepcopy(source_loaded["inventory"][103])
    copied_item["slot"] = target_slot

    result = service.save_player(
        str(world),
        target_key,
        [copied_item],
        {},
        base_revision=target_loaded["player_revision"],
        root_equipment_editable=True,
    )

    assert result["success"] is True and result["no_op"] is False
    records = _read_all(service, world)
    assert records[SOURCE_KEY] == original_records[SOURCE_KEY]
    assert records[UNRELATED_KEY] == UNRELATED_VALUE
    saved = load_player_nbt(records[LOCAL_PLAYER_KEY]).tag
    saved_item = saved["Armor"][0] if target_slot == 103 else saved["Inventory"][0]
    assert saved_item["Name"].py_data == "minecraft:diamond_helmet"
    assert saved_item["tag"].save_to() == helmet["tag"].save_to()
    if target_slot == 103:
        assert "Slot" not in saved_item
    else:
        assert saved_item["Slot"].py_data == target_slot


@pytest.mark.parametrize("source_slot,root_tag,item_name", [(103, "Armor", "minecraft:diamond_helmet"), (-106, "Offhand", "minecraft:shield")])
@pytest.mark.parametrize("destination", ["inventory", "ender_chest"])
@pytest.mark.parametrize("move", [False, True])
def test_root_equipment_origin_ignores_empty_inventory_placeholder(tmp_path, monkeypatch, source_slot, root_tag, item_name, destination, move):
    player = make_minimal_player_tag()
    placeholder = _empty_root_item()
    placeholder["Slot"] = nbt.ByteTag(source_slot)
    player["Inventory"] = nbt.ListTag([_item("minecraft:stone", 0), placeholder], 10)
    player["EnderChestInventory"] = nbt.ListTag([], 10)
    equipped = _item(item_name, tag=nbt.CompoundTag({"FutureData": nbt.StringTag("preserve moved equipment")}))
    player[root_tag] = _armor(equipped) if root_tag == "Armor" else nbt.ListTag([equipped], 10)
    world, original_records, service = _seed(tmp_path, monkeypatch, {LOCAL_PLAYER_KEY: player})
    key = encode_player_key(LOCAL_PLAYER_KEY)
    loaded = service.load_player(str(world), key)
    assert source_slot not in loaded["hidden_unknown_slots"]["inventory_protected_known_slots"]
    inventory, chest = deepcopy(loaded["inventory"]), deepcopy(loaded["ender_chest"])
    copied = deepcopy(inventory[source_slot])
    copied["slot"] = 1
    (inventory if destination == "inventory" else chest)[1] = copied
    if move:
        del inventory[source_slot]

    result = service.save_player(
        str(world),
        key,
        list(inventory.values()),
        {},
        ender_chest_list=list(chest.values()),
        base_revision=loaded["player_revision"],
        root_equipment_editable=True,
    )

    assert result["success"] and not result["no_op"]
    records = _read_all(service, world)
    assert records[UNRELATED_KEY] == original_records[UNRELATED_KEY]
    saved = load_player_nbt(records[LOCAL_PLAYER_KEY]).tag
    stored_items = saved["Inventory" if destination == "inventory" else "EnderChestInventory"]
    stored_copy = next(entry for entry in stored_items if entry["Slot"].py_data == 1)
    assert stored_copy["tag"].save_to() == equipped["tag"].save_to()
    stored_placeholder = next(entry for entry in saved["Inventory"] if entry["Slot"].py_data == source_slot)
    assert stored_placeholder.save_to() == placeholder.save_to()
    if move:
        assert saved[root_tag][0]["Count"].py_data == 0
    else:
        assert saved[root_tag].save_to() == player[root_tag].save_to()

    reloaded = service.load_player(str(world), key)
    echoed = service.save_player(
        str(world),
        key,
        list(reloaded["inventory"].values()),
        {},
        ender_chest_list=list(reloaded["ender_chest"].values()),
        base_revision=reloaded["player_revision"],
        root_equipment_editable=True,
    )
    assert echoed["no_op"]
    assert _read_all(service, world) == records


def test_air_placeholder_does_not_block_other_inventory_or_ender_changes(tmp_path, monkeypatch):
    player = make_minimal_player_tag()
    placeholder = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("air"), "Count": nbt.ByteTag(1)})
    player["Inventory"] = nbt.ListTag([deepcopy(placeholder), _item("minecraft:stone", 1)], 10)
    player["EnderChestInventory"] = nbt.ListTag([deepcopy(placeholder), _item("minecraft:diamond", 1)], 10)
    world, original_records, service = _seed(tmp_path, monkeypatch, {LOCAL_PLAYER_KEY: player})
    key = encode_player_key(LOCAL_PLAYER_KEY)
    loaded = service.load_player(str(world), key)
    for container in ("inventory", "ender_chest"):
        assert 0 not in loaded[container]
        assert loaded["hidden_unknown_slots"][container + "_protected_known_slots"] == []
        loaded[container][1]["count"] = 2

    result = service.save_player(
        str(world),
        key,
        list(loaded["inventory"].values()),
        {},
        ender_chest_list=list(loaded["ender_chest"].values()),
        base_revision=loaded["player_revision"],
    )

    assert result["success"] and not result["no_op"]
    records = _read_all(service, world)
    assert records[UNRELATED_KEY] == original_records[UNRELATED_KEY]
    saved = load_player_nbt(records[LOCAL_PLAYER_KEY]).tag
    for tag_name in ("Inventory", "EnderChestInventory"):
        assert saved[tag_name][0].save_to() == placeholder.save_to()
        assert saved[tag_name][1]["Count"].py_data == 2
