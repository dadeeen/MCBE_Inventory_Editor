"""Opaque NBT must remain loadable, immutable and safe to echo."""

import json

import pytest

from mcbe_editor import inventory, nbt
from mcbe_editor.item_data import ENCHANTMENTS
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import LOCAL_PLAYER_KEY


def _item(**fields):
    return nbt.CompoundTag({
        "Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"),
        "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0), **fields,
    })


def _display_player(field, value):
    return nbt.CompoundTag({"Inventory": nbt.ListTag([_item(tag=nbt.CompoundTag({
        "display": nbt.CompoundTag({field: value}),
    }))])})


@pytest.mark.parametrize("value", [
    nbt.IntTag(123), nbt.FloatTag(float("nan")),
    nbt.CompoundTag({"Future": nbt.IntTag(7)}),
    nbt.ListTag([nbt.CompoundTag({"Future": nbt.StringTag("keep")})]),
])
def test_opaque_display_name_is_json_safe_and_survives_count_edit(value):
    player = _display_player("Name", value)
    original = player["Inventory"][0]["tag"]["display"].save_to()
    parsed, _ = inventory.nbt_to_json(player)
    json.dumps(parsed, allow_nan=False)
    assert isinstance(parsed[0]["display_name"], str)
    result = inventory.build_inventory_nbt(player, [{**parsed[0], "count": 2}], ENCHANTMENTS)
    assert result[0]["tag"]["display"].save_to() == original
    assert result[0]["Count"].py_data == 2


@pytest.mark.parametrize("field,value,edit", [
    ("Name", nbt.IntTag(123), {"display_name": "renamed"}),
    ("Name", nbt.CompoundTag({"Future": nbt.IntTag(7)}), {"display_name": "renamed"}),
    ("Lore", nbt.IntTag(123), {"lore": ["new lore"]}),
    ("Lore", nbt.ListTag([nbt.IntTag(123)]), {"lore": ["new lore"]}),
])
def test_display_edits_cannot_replace_opaque_children(field, value, edit):
    player = _display_player(field, value)
    before = player.save_to()
    parsed, _ = inventory.nbt_to_json(player)
    with pytest.raises(ValueError, match="NBT"):
        inventory.build_inventory_nbt(player, [{**parsed[0], **edit}], ENCHANTMENTS)
    assert player.save_to() == before


@pytest.mark.parametrize("tag_name,builder,flag", [
    ("Inventory", inventory.build_inventory_nbt, "inventory_opaque"),
    ("EnderChestInventory", inventory.build_ender_chest_nbt, "ender_chest_opaque"),
])
@pytest.mark.parametrize("value", [nbt.IntTag(7), nbt.StringTag("future"), nbt.ListTag([nbt.IntTag(7)])])
def test_noncompound_item_lists_are_protected(tag_name, builder, flag, value):
    player = nbt.CompoundTag({tag_name: nbt.ListTag([value])})
    before = player.save_to()
    assert inventory.protected_player_nbt_flags(player)[flag] is True
    assert builder(player, [], ENCHANTMENTS).save_to() == player[tag_name].save_to()
    with pytest.raises(ValueError, match="NBT"):
        builder(player, [{"slot": 0, "name": "minecraft:stone", "count": 1}], ENCHANTMENTS)
    assert player.save_to() == before


@pytest.mark.parametrize("value", [nbt.IntTag(7), nbt.StringTag("future"), nbt.ListTag([nbt.IntTag(7)])])
def test_noncompound_effect_lists_are_protected_but_opaque_echoes_survive(value):
    player = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([value])})
    before = player.save_to()
    assert inventory.protected_player_nbt_flags(player)["active_effects_opaque"] is True
    inventory.apply_effects(player, inventory.parse_effects(player))
    inventory.apply_effects(player, [])
    assert player.save_to() == before
    with pytest.raises(ValueError, match="NBT"):
        inventory.apply_effects(player, [{"id": 1, "duration": 100}])
    assert player.save_to() == before


@pytest.mark.parametrize("tag_name,builder", [
    ("Inventory", inventory.build_inventory_nbt),
    ("EnderChestInventory", inventory.build_ender_chest_nbt),
])
@pytest.mark.parametrize("element_type", range(13))
def test_empty_item_list_echo_keeps_its_declared_type(tag_name, builder, element_type):
    player = nbt.CompoundTag({tag_name: nbt.ListTag([], element_type)})
    assert builder(player, [], ENCHANTMENTS).save_to() == player[tag_name].save_to()


def _service_with_player(tmp_path, monkeypatch, player):
    from mcbe_editor import services

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "data" / "backups"))
    player["Pos"] = nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(64), nbt.DoubleTag(0)])
    player["Health"] = nbt.FloatTag(20)
    raw = player.save_to()

    class Db:
        def __init__(self, _path):
            pass

        def get(self, key):
            if key != LOCAL_PLAYER_KEY:
                raise KeyError(key)
            return raw

        def iter_items(self):
            return [(LOCAL_PLAYER_KEY, raw)]

        def close(self):
            pass

        def put(self, *_args):
            pytest.fail("A no-op must not write the database")

    def forbidden_backup(*_args, **_kwargs):
        pytest.fail("A no-op must not create a backup")

    monkeypatch.setattr(services, "create_backup", forbidden_backup)
    return BedrockEditorService({}, ENCHANTMENTS, db_factory=Db, readonly_db_factory=Db), str(world), raw


def test_service_load_with_opaque_display_name_is_json_serializable(tmp_path, monkeypatch):
    player = _display_player("Name", nbt.CompoundTag({"Future": nbt.IntTag(7)}))
    service, world, _raw = _service_with_player(tmp_path, monkeypatch, player)
    result = service.load_player(world, encode_player_key(LOCAL_PLAYER_KEY))
    json.dumps(result, allow_nan=False)
    assert result["success"] is True


@pytest.mark.parametrize("tag_name,argument", [("Inventory", "inventory_list"), ("EnderChestInventory", "ender_chest_list")])
def test_service_empty_typed_list_echo_is_a_real_no_op(tmp_path, monkeypatch, tag_name, argument):
    player = nbt.CompoundTag({tag_name: nbt.ListTag([], 10)})
    service, world, raw = _service_with_player(tmp_path, monkeypatch, player)
    kwargs = {"inventory_list": None, "stats": {}, "base_revision": service._player_revision(raw), argument: []}
    result = service.save_player(world, encode_player_key(LOCAL_PLAYER_KEY), **kwargs)
    assert result["no_op"] is True
    assert result["backup_file"] is None
