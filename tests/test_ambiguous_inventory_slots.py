"""Multiple visible entries for one slot are opaque identities, never a cleanup request."""

from copy import deepcopy

import pytest

from mcbe_editor import inventory, nbt
from mcbe_editor.item_data import ENCHANTMENTS
from mcbe_editor.players import encode_player_key
from mcbe_editor.world import LOCAL_PLAYER_KEY
from tests.test_item_preservation_service import SOURCE_KEY, _load, _player, _save, editor as editor
from tests.test_root_equipment import modern_equipped_player


def _item(slot, name, marker=None):
    fields = {"Slot": nbt.ByteTag(slot), "Name": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(1)}
    if marker is not None:
        fields["Future"] = nbt.CompoundTag({"identity": nbt.LongTag(marker), "empty": nbt.ListTag([], 12), "zero": nbt.FloatTag(-0.0)})
    return nbt.CompoundTag(fields)


def _entries(*, plain=False):
    return nbt.ListTag(
        [
            _item(0, "stone", None if plain else 17),
            _item(1, "diamond", 19),
            _item(0, "dirt", None if plain else 23),
            nbt.CompoundTag({"Slot": nbt.ByteTag(0)}),
        ],
        10,
    )


@pytest.fixture(params=["inventory", "ender_chest"])
def container(request):
    if request.param == "inventory":
        return "inventory", "Inventory", inventory.build_inventory_nbt, lambda player: inventory.nbt_to_json(player)[0]
    return "ender_chest", "EnderChestInventory", inventory.build_ender_chest_nbt, inventory.parse_ender_chest


def test_ambiguous_slot_echo_and_other_slot_edits_preserve_every_original_entry(container):
    name, tag, build, read = container
    player = nbt.CompoundTag({tag: _entries()})
    before = player.save_to()
    visible = read(player)
    assert visible[0]["name"] == "minecraft:dirt"
    assert build(player, list(visible.values()), ENCHANTMENTS).save_to() == player[tag].save_to()
    assert "source_item_digest" not in visible[0]
    assert inventory.count_hidden_unknown_slots(player)[name + "_protected_known_slots"] == [0]

    visible[1]["count"] = 3
    expected = deepcopy(player)
    expected[tag][1]["Count"] = nbt.ByteTag(3)
    player_after = nbt.load(nbt.CompoundTag({tag: build(player, list(visible.values()), ENCHANTMENTS)}).save_to()).tag
    assert player_after.save_to() == expected.save_to()
    assert player.save_to() == before
    # An authoritative reload still exposes one read-only view and preserves all
    # duplicate occurrences on a subsequent no-op.
    assert build(player_after, list(read(player_after).values()), ENCHANTMENTS).save_to() == player_after[tag].save_to()


@pytest.mark.parametrize("change", ["count", "replace", "clear", "clear_all", "move", "copy", "rename"])
def test_ambiguous_slot_cannot_be_changed_deleted_moved_or_copied(container, change):
    _name, tag, build, read = container
    player = nbt.CompoundTag({tag: _entries(plain=True)})
    before = player.save_to()
    visible = read(player)
    if change == "clear":
        del visible[0]
    elif change == "clear_all":
        visible.clear()
    elif change in {"move", "copy"}:
        visible[2] = {**deepcopy(visible[0]), "slot": 2}
        if change == "move":
            del visible[0]
    elif change == "count":
        visible[0]["count"] = 2
    elif change == "replace":
        visible[0]["replace_original_nbt"] = True
    else:
        visible[0]["display_name"] = "Changed"
    with pytest.raises(ValueError):
        build(player, list(visible.values()), ENCHANTMENTS)
    assert player.save_to() == before


def test_ambiguous_slot_service_echo_and_omitted_section_are_no_ops_without_backups(editor, container):
    name, tag, _build, _read = container
    original = _player(**{tag: _entries()})
    editor.store[LOCAL_PLAYER_KEY] = original
    loaded = _load(editor)
    kwargs = {"ender_chest_list": list(loaded[name].values())} if name == "ender_chest" else {}
    echoed = list(loaded[name].values()) if name == "inventory" else None
    assert _save(editor, loaded, echoed, **kwargs)["no_op"]
    assert loaded["hidden_unknown_slots"][name + "_protected_known_slots"] == [0]
    assert _save(editor, loaded, None)["no_op"]
    assert editor.store[LOCAL_PLAYER_KEY] == original
    assert editor.writes == editor.backups == []
    kwargs = {"ender_chest_list": []} if name == "ender_chest" else {}
    with pytest.raises(ValueError, match="mehrere Originaleinträge"):
        _save(editor, loaded, [] if name == "inventory" else None, **kwargs)
    assert editor.store[LOCAL_PLAYER_KEY] == original
    assert editor.writes == editor.backups == []


@pytest.mark.parametrize("cross_player", [False, True])
def test_ambiguous_slot_cannot_be_an_external_container_or_player_copy_source(editor, container, cross_player):
    name, tag, _build, _read = container
    source_key = SOURCE_KEY if cross_player else LOCAL_PLAYER_KEY
    editor.store[source_key] = _player(**{tag: _entries(plain=True)})
    if cross_player:
        editor.store[LOCAL_PLAYER_KEY] = _player(Inventory=nbt.ListTag([], 10), EnderChestInventory=nbt.ListTag([], 10))
    else:
        source = nbt.load(editor.store[source_key]).tag
        source["EnderChestInventory" if tag == "Inventory" else "Inventory"] = nbt.ListTag([], 10)
        editor.store[source_key] = source.save_to()
    source_view = _load(editor, source_key)
    target_view = _load(editor)
    copied = deepcopy(source_view[name][0])
    copied["slot"] = 2
    copied["source_player_key"] = encode_player_key(source_key)
    destination = "ender_chest" if name == "inventory" else "inventory"
    before = dict(editor.store)
    with pytest.raises(ValueError):
        _save(
            editor,
            target_view,
            [copied] if destination == "inventory" else None,
            **({"ender_chest_list": [copied]} if destination == "ender_chest" else {}),
        )
    assert editor.store == before
    assert editor.writes == editor.backups == []


@pytest.mark.parametrize("source_slot,target_slot,name", [(103, -106, "shield"), (-106, 103, "leather_helmet")])
def test_ambiguous_inventory_origin_cannot_fall_back_to_shadowed_root_equipment(editor, source_slot, target_slot, name):
    player = modern_equipped_player()
    source = _item(source_slot, name)
    player["Inventory"] = nbt.ListTag([source, deepcopy(source)], 10)
    original = _player(**player)
    editor.store[LOCAL_PLAYER_KEY] = original
    loaded = _load(editor)
    items = deepcopy(loaded["inventory"])
    assert "source_item_digest" not in items[source_slot]
    items[target_slot] = {**deepcopy(items[source_slot]), "slot": target_slot}

    with pytest.raises(ValueError, match="sichere Originalquelle"):
        _save(editor, loaded, list(items.values()), root_equipment_editable=True)

    assert editor.store[LOCAL_PLAYER_KEY] == original
    assert editor.writes == editor.backups == []
