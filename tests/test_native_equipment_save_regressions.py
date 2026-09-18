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
from tests.conftest import make_minimal_player_tag


SOURCE_KEY = b"player_synthetic_source"
UNRELATED_KEY = b"synthetic-opaque-record"
UNRELATED_VALUE = b"\x00\xffpreserve-me"


def _item(name, slot=None, **extra):
    fields = {"Name": nbt.StringTag(name), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0), **extra}
    if slot is not None:
        fields["Slot"] = nbt.ByteTag(slot)
    return nbt.CompoundTag(fields)


def _empty_root_item():
    return nbt.CompoundTag({
        "Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0), "WasPickedUp": nbt.ByteTag(0),
    })


def _armor(helmet=None):
    return nbt.ListTag([helmet if helmet is not None else _empty_root_item(), *[_empty_root_item() for _ in range(3)]])


def _seed(tmp_path, monkeypatch, player_tags):
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr("mcbe_editor.db._run_runtime_leveldb_write_guard", lambda *_args: None)
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
        str(world), key, payload, {}, base_revision=loaded["player_revision"], root_equipment_editable=True,
    )

    assert result["success"] is True and result["no_op"] is False
    assert (Path(get_backups_dir(str(world))) / result["backup_file"]).is_file()
    records = _read_all(service, world)
    saved = load_player_nbt(records[LOCAL_PLAYER_KEY]).tag
    assert saved[root_tag].save_to() == root_before
    assert next(item for item in saved["Inventory"] if item["Slot"].py_data == 0)["Count"].py_data == 2
    assert records[UNRELATED_KEY] == UNRELATED_VALUE


@pytest.mark.parametrize("target_slot", [1, 103])
@pytest.mark.parametrize("source_has_inventory", [False, True])
def test_native_cross_player_root_copy_preserves_source_and_item_nbt(tmp_path, monkeypatch, target_slot, source_has_inventory):
    source = make_minimal_player_tag()
    helmet = _item("minecraft:diamond_helmet", tag=nbt.CompoundTag({"FutureData": nbt.StringTag("preserve copied equipment")}))
    source["Armor"] = _armor(helmet)
    if source_has_inventory:
        source["Inventory"] = nbt.ListTag([])
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
        str(world), target_key, [copied_item], {}, base_revision=target_loaded["player_revision"], root_equipment_editable=True,
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
