"""The same typed-NBT damage policy applies to direct and contained items."""

from copy import deepcopy

import pytest

from mcbe_editor import inventory, item_data, nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt


@pytest.fixture(params=["inventory", "ender_chest", "shulker", "bundle"])
def location(request):
    return request.param


def _item(name="minecraft:stone", damage=0):
    return nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(6),
            "Name": nbt.StringTag(name),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.IntTag(damage),
            "tag": nbt.CompoundTag({"addon": nbt.CompoundTag({"bits": nbt.ByteArrayTag([0, -1, 127])})}),
        }
    )


def _save(location, original, **changes):
    """Use the real parser, origin resolution, writer and wire serialization."""
    if location in {"inventory", "ender_chest"}:
        field = "Inventory" if location == "inventory" else "EnderChestInventory"
        build = inventory.build_inventory_nbt if location == "inventory" else inventory.build_ender_chest_nbt
        player = nbt.CompoundTag({field: nbt.ListTag([original] if original is not None else [], 10)})
        parsed = inventory.nbt_to_json(player)[0] if location == "inventory" else inventory.parse_ender_chest(player)
        payload = parsed[6] if original is not None else {"slot": 6, "count": 1, "damage": 0}
        payload.update(changes)
        before = player.save_to()
        result = build(player, [payload], item_data.ENCHANTMENTS)
        assert player.save_to() == before
        stored = result[0]
    else:
        name, field = ("minecraft:undyed_shulker_box", "Items") if location == "shulker" else ("minecraft:bundle", "storage_item_component_content")
        parent = _item(name)
        parent["tag"][field] = nbt.ListTag([original] if original is not None else [], 10)
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([parent], 10)})
        payload = inventory.nbt_to_json(player)[0][6]
        data = deepcopy(payload["special_item"]["data"])
        child = data["items"][0] if original is not None else {"slot": 6, "count": 1, "damage": 0}
        child.update(changes)
        data["items"] = [child]
        payload["special_edit"] = {"kind": location, "data": data}
        before = player.save_to()
        saved_parent = inventory.build_inventory_nbt(player, [payload], item_data.ENCHANTMENTS)[0]
        assert player.save_to() == before
        assert saved_parent["tag"]["addon"].save_to() == parent["tag"]["addon"].save_to()
        stored = next(entry for entry in saved_parent["tag"][field] if entry["Slot"].py_data == 6)
    return load_player_nbt(save_player_nbt(nbt.NamedTag(stored))).tag


@pytest.mark.parametrize("value", [-7, 73, 40000])
def test_uninterpreted_original_damage_and_extra_nbt_survive_a_name_edit(location, value):
    original = _item(damage=value)
    expected = deepcopy(original)
    expected["tag"]["display"] = nbt.CompoundTag({"Name": nbt.StringTag("Renamed")})

    saved = _save(location, original, display_name="Renamed")

    assert saved.save_to() == expected.save_to()
    assert _save(location, saved).save_to() == saved.save_to()


@pytest.mark.parametrize("name,value", [("minecraft:potion", 99), ("minecraft:diamond_sword", 2000)])
def test_unknown_variant_or_out_of_range_wear_survives_other_edits(location, name, value):
    original = _item(name, value)
    expected = deepcopy(original)
    expected["tag"]["display"] = nbt.CompoundTag({"Lore": nbt.ListTag([nbt.StringTag("Added lore")], 8)})

    saved = _save(location, original, lore=["Added lore"])

    assert saved.save_to() == expected.save_to()


@pytest.mark.parametrize(
    "name,value",
    [("minecraft:stone", 1), ("minecraft:empty_map", 1), ("minecraft:potion", 47), ("minecraft:diamond_sword", 1562)],
)
def test_new_values_require_documented_item_semantics(location, name, value):
    with pytest.raises(ValueError, match="Datenwert|Damage-Wert"):
        _save(location, None, name=name, damage=value)


@pytest.mark.parametrize("name,value", [("minecraft:stone", 0), ("minecraft:empty_map", 2), ("minecraft:potion", 46), ("minecraft:diamond_sword", 1561)])
def test_documented_values_remain_creatable(location, name, value):
    saved = _save(location, None, name=name, damage=value)
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([saved], 10)})
    assert inventory.nbt_to_json(player)[0][6]["damage"] == value


def test_unknown_value_can_only_be_kept_or_explicitly_reset(location):
    original = _item(damage=73)
    before = original.save_to()
    with pytest.raises(ValueError, match="nicht belegt"):
        _save(location, original, damage=74)
    assert original.save_to() == before

    saved = _save(location, original, damage=0)
    expected = deepcopy(original)
    expected["Damage"] = nbt.IntTag(0)
    assert saved.save_to() == expected.save_to()


def test_selecting_a_known_variant_changes_only_the_value(location):
    original = _item("minecraft:potion", 99)
    saved = _save(location, original, damage=5)
    expected = deepcopy(original)
    expected["Damage"] = nbt.IntTag(5)
    assert saved.save_to() == expected.save_to()


def test_modern_wear_edits_keep_legacy_root_value_and_unknown_tags(location):
    original = _item("minecraft:diamond_sword", 12345)
    original["tag"]["Damage"] = nbt.LongTag(20)
    saved = _save(location, original, damage=21)
    expected = deepcopy(original)
    expected["tag"]["Damage"] = nbt.LongTag(21)
    assert saved.save_to() == expected.save_to()


def test_durability_is_proven_by_the_catalog_entry_not_by_the_numeric_fallback(monkeypatch):
    catalog = dict(item_data.catalog_values())
    catalog["MAX_DATA_VALUE"] = 9000
    catalog["DURABILITY"] = {"addon:tool": 32767}
    catalog["COMPAT_ITEM_ALIASES"] = {"addon:old_tool": "addon:tool"}
    monkeypatch.setattr(item_data, "catalog_values", lambda: catalog)

    stone = _item()
    stone["tag"]["Damage"] = nbt.IntTag(17)
    expected = deepcopy(stone)
    expected["tag"]["display"] = nbt.CompoundTag({"Name": nbt.StringTag("Renamed")})
    assert _save("inventory", stone, display_name="Renamed").save_to() == expected.save_to()

    tool = _item("addon:old_tool")
    tool["tag"]["Damage"] = nbt.IntTag(17)
    expected = deepcopy(tool)
    expected["tag"]["Damage"] = nbt.IntTag(18)
    assert _save("inventory", tool, damage=18).save_to() == expected.save_to()
