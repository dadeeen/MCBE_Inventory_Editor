"""Independent duplicate-slot checks for identity, merges and safe exceptions."""

from copy import deepcopy

import pytest

from mcbe_editor import inventory, nbt
from mcbe_editor.item_data import ENCHANTMENTS


def _entry(slot, marker, name="diamond"):
    return nbt.CompoundTag(
        {
            "Slot": nbt.IntTag(slot),
            "Name": nbt.StringTag("minecraft:" + name),
            "Count": nbt.ShortTag(1),
            "tag": nbt.CompoundTag({"addon": nbt.LongTag(marker), "future": nbt.ListTag([], 8)}),
        }
    )


@pytest.fixture(params=["inventory", "ender_chest"])
def container(request):
    if request.param == "inventory":
        return "Inventory", "inventory", inventory.nbt_to_json, inventory.build_inventory_nbt
    return "EnderChestInventory", "ender_chest", inventory.parse_ender_chest, inventory.build_ender_chest_nbt


def _visible(read, player):
    parsed = read(player)
    return parsed[0] if isinstance(parsed, tuple) else parsed


def test_identical_duplicate_items_remain_protected_across_a_third_occurrence_and_unrelated_changes(container):
    tag, name, read, build = container
    duplicate = _entry(3, 1024)
    entries = nbt.ListTag(
        [deepcopy(duplicate), _entry(1, 41), deepcopy(duplicate), nbt.CompoundTag({"Slot": nbt.ByteTag(3)}), _entry(3, 2048)],
        10,
    )
    player = nbt.CompoundTag({tag: entries})
    before = player.save_to()
    view = _visible(read, player)
    assert inventory.items_by_slot_for_origin(entries)[3] is None
    assert inventory.count_hidden_unknown_slots(player)[name + "_protected_known_slots"] == [3]
    view[1]["count"] = 7
    expected = deepcopy(entries)
    expected[1]["Count"] = nbt.ShortTag(7)
    actual = build(player, list(view.values()), ENCHANTMENTS)
    assert actual.save_to() == expected.save_to()
    assert player.save_to() == before
    player[tag] = actual
    assert build(player, list(_visible(read, player).values()), ENCHANTMENTS).save_to() == actual.save_to()


def test_one_visible_item_plus_an_opaque_duplicate_stays_editable_without_losing_opaque_bytes(container):
    tag, name, read, build = container
    opaque = _entry(3, 999)
    opaque["Count"] = nbt.StringTag("future-count-format")
    entries = nbt.ListTag([opaque, _entry(3, 1024)], 10)
    player = nbt.CompoundTag({tag: entries})
    view = _visible(read, player)
    assert inventory.count_hidden_unknown_slots(player)[name + "_protected_known_slots"] == []
    assert inventory.items_by_slot_for_origin(entries)[3] is entries[1]
    view[3]["count"] = 2
    expected = deepcopy(entries)
    expected[1]["Count"] = nbt.ShortTag(2)
    actual = build(player, list(view.values()), ENCHANTMENTS)
    assert actual.save_to() == expected.save_to()


def test_duplicate_unknown_slots_do_not_lock_or_rewrite_visible_slots(container):
    tag, name, read, build = container
    entries = nbt.ListTag([_entry(500, 1), _entry(2, 2), _entry(500, 3)], 10)
    player = nbt.CompoundTag({tag: entries})
    view = _visible(read, player)
    assert set(view) == {2}
    assert inventory.count_hidden_unknown_slots(player)[name + "_protected_known_slots"] == []
    view[2]["count"] = 4
    expected = deepcopy(entries)
    expected[1]["Count"] = nbt.ShortTag(4)
    assert build(player, list(view.values()), ENCHANTMENTS).save_to() == expected.save_to()


@pytest.mark.parametrize("explicit_source", [False, True])
def test_known_addable_item_cannot_turn_an_explicit_ambiguous_origin_into_a_fresh_copy(container, explicit_source):
    tag, name, read, build = container
    entries = nbt.ListTag([_entry(3, 10), _entry(3, 20)], 10)
    player = nbt.CompoundTag({tag: entries})
    view = _visible(read, player)
    copied = {
        "slot": 4,
        "name": "minecraft:diamond",
        "count": 1,
        "damage": 0,
        "source_slot": 3,
    }
    kwargs = {"target_player_key": "current"}
    if explicit_source:
        copied.update(source_player_key="other", source_container=name, source_item_digest="a" * 64)
        kwargs["source_item_maps"] = {("other", name): {3: None}}
    with pytest.raises(ValueError):
        build(player, [*view.values(), copied], ENCHANTMENTS, **kwargs)
    assert len(player[tag]) == 2


def test_ambiguous_book_allows_editor_echo_but_rejects_a_nested_page_change(container):
    tag, _name, read, build = container
    first = _entry(3, 10, "writable_book")
    last = _entry(3, 20, "writable_book")
    first["tag"]["pages"] = nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag("Earlier")})], 10)
    last["tag"]["pages"] = nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag("Visible"), "unknown": nbt.LongTag(99)})], 10)
    player = nbt.CompoundTag({tag: nbt.ListTag([first, last], 10)})
    view = _visible(read, player)
    view[3]["special_edit"] = {"kind": "book", "data": {"pages": [{"source_index": 0, "text": "Visible"}]}}
    assert build(player, list(view.values()), ENCHANTMENTS).save_to() == player[tag].save_to()
    view[3]["special_edit"]["data"]["pages"][0]["text"] = "Changed"
    with pytest.raises(ValueError):
        build(player, list(view.values()), ENCHANTMENTS)
