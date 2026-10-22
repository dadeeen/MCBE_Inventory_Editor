"""Independent boundary checks for preservation and first-time metadata creation."""

from copy import deepcopy

import pytest

from mcbe_editor import inventory, nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.item_data import ENCHANTMENTS


def _stored_item(name, metadata=None):
    item = nbt.CompoundTag(
        {
            "Name": nbt.StringTag("minecraft:" + name),
            "Slot": nbt.ByteTag(0),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
        }
    )
    if metadata is not None:
        item["tag"] = nbt.CompoundTag(metadata)
    return item


def _persist(name, kind, data, original=None):
    root = nbt.CompoundTag({"Inventory": nbt.ListTag([original] if original is not None else [], 10)})
    # The parser supplies provenance only. Requested edits and expected typed
    # data below are explicit fixtures, independent of its presentation values.
    payload = inventory.nbt_to_json(root)[0][0] if original is not None else {"slot": 0, "name": "minecraft:" + name, "count": 1, "damage": 0}
    payload["special_edit"] = {"kind": kind, "data": data}
    built = inventory.build_inventory_nbt(root, [payload], ENCHANTMENTS)[0]
    return load_player_nbt(save_player_nbt(nbt.NamedTag(built))).tag


def _effect(*, origin=None, colors=None, shape=0):
    result = {"shape": shape, "colors": [15] if colors is None else colors, "fade": [], "trail": False, "flicker": False}
    if origin is not None:
        result["source_index"] = origin
    return result


def _expected_effect(colors=(15,), shape=0):
    return nbt.CompoundTag(
        {
            "FireworkType": nbt.ByteTag(shape),
            "FireworkColor": nbt.ByteArrayTag(colors),
            "FireworkFade": nbt.ByteArrayTag([]),
            "FireworkTrail": nbt.ByteTag(0),
            "FireworkFlicker": nbt.ByteTag(0),
        }
    )


@pytest.mark.parametrize("empty_field", ["title", "author"])
@pytest.mark.parametrize("pages_type", [None, 1, 8, 10])
def test_explicit_empty_book_fields_survive_add_remove_and_repeated_saves(empty_field, pages_type):
    other_field = "author" if empty_field == "title" else "title"
    metadata = {
        empty_field: nbt.StringTag(""),
        "addon": nbt.CompoundTag({"future": nbt.ListTag([], 6), "bits": nbt.ByteArrayTag([0, -1, 127])}),
    }
    if pages_type is not None:
        metadata["pages"] = nbt.ListTag([], pages_type)
    original = _stored_item("written_book", metadata)
    original_bytes = original.save_to()
    first_data = {"pages": [], empty_field: "", other_field: "User text"}
    first = _persist("written_book", "book", first_data, original)
    expected = deepcopy(original)
    expected["tag"][other_field] = nbt.StringTag("User text")
    assert first.save_to() == expected.save_to()
    assert original.save_to() == original_bytes

    added = _persist("written_book", "book", {**first_data, "pages": [{"text": ""}]}, first)
    expected["tag"]["pages"] = nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag(""), "photoname": nbt.StringTag("")})], 10)
    assert added.save_to() == expected.save_to()
    removed = _persist("written_book", "book", first_data, added)
    expected["tag"]["pages"] = nbt.ListTag([], 10)
    assert removed.save_to() == expected.save_to()
    assert _persist("written_book", "book", first_data, removed).save_to() == expected.save_to()
    assert "generation" not in removed["tag"]


def test_new_writable_book_initializes_blank_page_and_preserves_it_on_later_edits():
    first = _persist("writable_book", "book", {"pages": [{"text": ""}]})
    expected = _stored_item(
        "writable_book",
        {"pages": nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag(""), "photoname": nbt.StringTag("")})], 10)},
    )
    assert first["tag"].save_to() == expected["tag"].save_to()
    assert first["Name"].py_data == "minecraft:writable_book"
    assert type(first["Count"]) is nbt.ByteTag and first["Count"].py_data == 1
    first["tag"]["pages"][0]["addon"] = nbt.StringTag("row-owned extra")
    first["tag"]["unknown"] = nbt.IntArrayTag([1, -2, 3])
    changed = _persist("writable_book", "book", {"pages": [{"source_index": 0, "text": "Now filled"}]}, first)
    expected = deepcopy(first)
    expected["tag"]["pages"][0]["text"] = nbt.StringTag("Now filled")
    assert changed.save_to() == expected.save_to()
    assert _persist("writable_book", "book", {"pages": [{"source_index": 0, "text": "Now filled"}]}, changed).save_to() == expected.save_to()


@pytest.mark.parametrize("explicit_empty", [False, True])
def test_rocket_first_effect_initializes_defaults_without_changing_existing_flight_presence(explicit_empty):
    metadata = {"addon": nbt.LongTag(987654321)}
    if explicit_empty:
        metadata["Fireworks"] = nbt.CompoundTag({"Explosions": nbt.ListTag([], 8), "unknown": nbt.IntTag(77)})
    original = _stored_item("firework_rocket", metadata)
    first = _persist("firework_rocket", "fireworks", {"flight": 1, "explosions": [_effect()]}, original)
    expected = deepcopy(original)
    if "Fireworks" not in expected["tag"]:
        expected["tag"]["Fireworks"] = nbt.CompoundTag()
    expected["tag"]["Fireworks"]["Explosions"] = nbt.ListTag([_expected_effect()], 10)
    assert first.save_to() == expected.save_to()
    changed = _persist("firework_rocket", "fireworks", {"flight": 2, "explosions": [_effect(origin=0)]}, first)
    expected["tag"]["Fireworks"]["Flight"] = nbt.ByteTag(2)
    assert changed.save_to() == expected.save_to()
    reverted = _persist("firework_rocket", "fireworks", {"flight": 1, "explosions": [_effect(origin=0)]}, changed)
    expected["tag"]["Fireworks"]["Flight"] = nbt.ByteTag(1)
    assert reverted.save_to() == expected.save_to()


@pytest.mark.parametrize("name", ["firework_star", "fireworkscharge"])
def test_star_effect_creation_initializes_defaults_and_only_derived_icon_color_tracks_edits(name):
    # The legacy alias is intentionally not addable, but existing old items can
    # receive their first effect through the same metadata creation path.
    original = _stored_item(name) if name == "fireworkscharge" else None
    first = _persist(name, "firework_star", {"explosions": [_effect(colors=[0])]}, original)
    expected = _stored_item(
        name,
        {"FireworksItem": _expected_effect(colors=(0,)), "customColor": nbt.IntTag(-14869215)},
    )
    assert first["tag"].save_to() == expected["tag"].save_to()
    assert first["Name"].py_data == "minecraft:" + name
    first["tag"]["FireworksItem"]["addon"] = nbt.LongTag(99)
    first["tag"]["customColor"] = nbt.IntTag(-1)
    changed = _persist(name, "firework_star", {"explosions": [_effect(origin=0, colors=[1], shape=2)]}, first)
    expected = deepcopy(first)
    expected["tag"]["FireworksItem"]["FireworkColor"] = nbt.ByteArrayTag([1])
    expected["tag"]["FireworksItem"]["FireworkType"] = nbt.ByteTag(2)
    assert changed.save_to() == expected.save_to()
    assert _persist(name, "firework_star", {"explosions": [_effect(origin=0, colors=[1], shape=2)]}, changed).save_to() == expected.save_to()
