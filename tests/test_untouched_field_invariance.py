"""A visible but untouched field must stay structurally unchanged.

The browser always echoes the complete container (docs/save_contract.md), so a
normal save carries mostly untouched entries. The existing safety layers cover
provenance, opaque/unknown data and atomic writes; these tests cover the fourth
invariant: applying only the concrete user change and leaving everything else
byte-for-byte intact -- including list order, empty standard containers and
control tags an older world never carried.
"""

from __future__ import annotations

import pytest

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor import inventory  # noqa: E402
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt  # noqa: E402
from mcbe_editor.item_data import ENCHANTMENTS  # noqa: E402

ECHO_KEYS = (
    "slot",
    "source_slot",
    "name",
    "count",
    "damage",
    "display_name",
    "lore",
    "enchantments",
    "source_item_digest",
)


def _item(slot: int, name: str = "minecraft:diamond_sword", **tag_fields):
    item = nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(slot),
            "Name": nbt.StringTag(name),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
        }
    )
    if tag_fields:
        item["tag"] = nbt.CompoundTag(tag_fields)
    return item


def _echo(parsed: dict, **overrides) -> dict:
    payload = {key: parsed[key] for key in ECHO_KEYS if key in parsed}
    payload.update(overrides)
    return payload


def _save(items, edit_slot: int | None = None, **edit):
    """Round trip a player through the writer, optionally editing one slot.

    Returns ``(before_bytes, after_bytes, after_items_by_slot)``.
    """

    player = nbt.CompoundTag({"Inventory": nbt.ListTag(list(items))})
    before = save_player_nbt(nbt.NamedTag(player))
    parsed, _originals = inventory.nbt_to_json(load_player_nbt(before).tag)
    payload = [_echo(entry, **(edit if slot == edit_slot else {})) for slot, entry in sorted(parsed.items())]

    target = load_player_nbt(before).tag
    target["Inventory"] = inventory.build_inventory_nbt(target, payload, ENCHANTMENTS)
    after = save_player_nbt(nbt.NamedTag(target))
    by_slot = {int(entry["Slot"].py_data): entry for entry in load_player_nbt(after).tag["Inventory"]}
    return before, after, by_slot


def test_custom_name_keeps_leading_and_trailing_spaces() -> None:
    """Name padding is valid Bedrock formatting, exactly like Lore padding."""

    padded = "   Excalibur   "
    sword = _item(1, display=nbt.CompoundTag({"Name": nbt.StringTag(padded)}))
    before, after, by_slot = _save([_item(0, "minecraft:stone"), sword], edit_slot=0, count=5)

    assert str(by_slot[1]["tag"]["display"]["Name"].py_data) == padded
    assert int(by_slot[0]["Count"].py_data) == 5


def test_editing_one_slot_keeps_an_unknown_enchantment_in_place() -> None:
    """IDs 42/44 stopped being known in 7ecd6ac; they must not be reshuffled."""

    ench = nbt.ListTag(
        [
            nbt.CompoundTag({"id": nbt.ShortTag(44), "lvl": nbt.ShortTag(1)}),
            nbt.CompoundTag({"id": nbt.ShortTag(16), "lvl": nbt.ShortTag(1)}),
        ]
    )
    before, after, by_slot = _save([_item(0, "minecraft:stone"), _item(1, ench=ench)], edit_slot=0, count=5)

    assert [int(entry["id"].py_data) for entry in by_slot[1]["tag"]["ench"]] == [44, 16]


def test_renaming_an_item_keeps_its_own_unknown_enchantment_in_place() -> None:
    """Editing the same item reaches the writer, unlike the cross-slot case above.

    The payload echoes every known enchantment, so the list must not count as
    edited merely because a known entry exists next to an unknown one.
    """

    ench = nbt.ListTag(
        [
            nbt.CompoundTag({"id": nbt.ShortTag(44), "lvl": nbt.ShortTag(1)}),
            nbt.CompoundTag({"id": nbt.ShortTag(16), "lvl": nbt.ShortTag(1)}),
        ]
    )
    _before, _after, by_slot = _save([_item(0, ench=ench)], edit_slot=0, display_name="Neu")

    assert [int(entry["id"].py_data) for entry in by_slot[0]["tag"]["ench"]] == [44, 16]
    assert str(by_slot[0]["tag"]["display"]["Name"].py_data) == "Neu"


def test_changing_a_level_keeps_the_unknown_entry_at_its_position() -> None:
    """A real enchantment edit rebuilds the list; positions must still hold."""

    ench = nbt.ListTag(
        [
            nbt.CompoundTag({"id": nbt.ShortTag(44), "lvl": nbt.ShortTag(1)}),
            nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(1)}),
        ]
    )
    _before, _after, by_slot = _save([_item(0, ench=ench)], edit_slot=0, enchantments=[{"id": 9, "lvl": 3}])

    assert [(int(e["id"].py_data), int(e["lvl"].py_data)) for e in by_slot[0]["tag"]["ench"]] == [(44, 1), (9, 3)]


def test_renaming_an_item_keeps_its_own_empty_enchantment_list() -> None:
    item = _item(0)
    empty_compound_list = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(1)})])
    del empty_compound_list[0]
    item["tag"] = nbt.CompoundTag({"ench": empty_compound_list})
    element_type = item["tag"]["ench"].list_data_type

    _before, _after, by_slot = _save([item], edit_slot=0, display_name="Neu")

    assert "ench" in by_slot[0]["tag"], "eine leere ench-Liste darf bei einer Namensaenderung nicht verschwinden"
    assert by_slot[0]["tag"]["ench"].list_data_type == element_type


def test_removing_the_last_enchantment_still_drops_the_list() -> None:
    """The invariance guard must not freeze a genuine removal."""

    ench = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(1)})])
    _before, _after, by_slot = _save([_item(0, ench=ench)], edit_slot=0, enchantments=[])

    assert "ench" not in by_slot[0].get("tag", nbt.CompoundTag({}))


def test_a_new_enchantment_is_appended_behind_a_preserved_entry() -> None:
    ench = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(44), "lvl": nbt.ShortTag(1)})])
    _before, _after, by_slot = _save([_item(0, ench=ench)], edit_slot=0, enchantments=[{"id": 9, "lvl": 1}])

    assert [int(entry["id"].py_data) for entry in by_slot[0]["tag"]["ench"]] == [44, 9]


def test_out_of_range_enchantment_level_keeps_its_list_position() -> None:
    ench = nbt.ListTag(
        [
            nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(99)}),
            nbt.CompoundTag({"id": nbt.ShortTag(16), "lvl": nbt.ShortTag(1)}),
        ]
    )
    _before, _after, by_slot = _save([_item(0, "minecraft:stone"), _item(1, ench=ench)], edit_slot=0, count=5)

    assert [int(entry["id"].py_data) for entry in by_slot[1]["tag"]["ench"]] == [9, 16]


@pytest.mark.parametrize(
    ("label", "tag_fields"),
    [
        ("empty display compound", {"display": nbt.CompoundTag({})}),
        ("empty lore list", {"display": nbt.CompoundTag({"Lore": nbt.ListTag([])})}),
        ("empty display name", {"display": nbt.CompoundTag({"Name": nbt.StringTag("")})}),
        ("empty ench list", {"ench": nbt.ListTag([])}),
        ("empty enchantments list", {"enchantments": nbt.ListTag([])}),
    ],
)
def test_empty_standard_containers_survive_an_identical_round_trip(label: str, tag_fields: dict) -> None:
    before, after, _by_slot = _save([_item(1, **tag_fields)])

    assert after == before, f"{label} darf bei einem identischen Roundtrip nicht verschwinden"


def test_untouched_damageable_item_does_not_gain_a_root_damage_tag() -> None:
    sword = nbt.CompoundTag(
        {"Slot": nbt.ByteTag(1), "Name": nbt.StringTag("minecraft:diamond_sword"), "Count": nbt.ByteTag(1)}
    )
    _before, _after, by_slot = _save([_item(0, "minecraft:stone"), sword], edit_slot=0, count=5)

    assert "Damage" not in by_slot[1]


def test_renaming_an_item_does_not_add_a_root_damage_tag() -> None:
    """The companion to the cross-slot test above: here the writer really runs.

    A missing Damage reads back as the same value 0, so calling the damage writer
    for an unrelated edit would add a tag the original never carried.
    """

    sword = nbt.CompoundTag(
        {"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:diamond_sword"), "Count": nbt.ByteTag(1)}
    )
    _before, _after, by_slot = _save([sword], edit_slot=0, display_name="Neu")

    assert "Damage" not in by_slot[0]
    assert "Damage" not in by_slot[0]["tag"]
    assert str(by_slot[0]["tag"]["display"]["Name"].py_data) == "Neu"


def test_a_real_damage_change_is_still_written() -> None:
    sword = nbt.CompoundTag(
        {"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:diamond_sword"), "Count": nbt.ByteTag(1)}
    )
    _before, _after, by_slot = _save([sword], edit_slot=0, damage=100)

    assert int(by_slot[0]["tag"]["Damage"].py_data) == 100


def test_damage_edit_is_rejected_when_an_opaque_item_tag_cannot_store_it() -> None:
    sword = _item(0)
    sword["tag"] = nbt.StringTag("future opaque item metadata")

    with pytest.raises(ValueError, match="Item-Metadaten.*unbekannten NBT-Typ"):
        _save([sword], edit_slot=0, damage=100)


def test_opaque_item_tag_survives_an_unrelated_count_edit() -> None:
    stack = _item(0, "minecraft:stone")
    stack["tag"] = nbt.StringTag("future opaque item metadata")

    _before, _after, by_slot = _save([stack], edit_slot=0, count=2)

    assert int(by_slot[0]["Count"].py_data) == 2
    assert isinstance(by_slot[0]["tag"], nbt.StringTag)
    assert str(by_slot[0]["tag"].py_data) == "future opaque item metadata"


def test_display_edit_is_rejected_when_the_existing_display_tag_is_opaque() -> None:
    stack = _item(0, "minecraft:stone")
    stack["tag"] = nbt.CompoundTag(
        {
            "display": nbt.StringTag("future opaque display metadata"),
            "RepairCost": nbt.IntTag(7),
        }
    )

    with pytest.raises(ValueError, match="Item-Metadaten.*unbekannten NBT-Typ"):
        _save([stack], edit_slot=0, display_name="Neu")


def test_opaque_display_tag_survives_an_unrelated_count_edit() -> None:
    stack = _item(0, "minecraft:stone")
    stack["tag"] = nbt.CompoundTag(
        {
            "display": nbt.StringTag("future opaque display metadata"),
            "RepairCost": nbt.IntTag(7),
        }
    )

    _before, _after, by_slot = _save([stack], edit_slot=0, count=2)

    assert int(by_slot[0]["Count"].py_data) == 2
    assert isinstance(by_slot[0]["tag"]["display"], nbt.StringTag)
    assert str(by_slot[0]["tag"]["display"].py_data) == "future opaque display metadata"
    assert int(by_slot[0]["tag"]["RepairCost"].py_data) == 7


@pytest.mark.parametrize(
    ("label", "tag_fields", "expected"),
    [
        ("empty tag compound", {}, []),
        ("empty display compound", {"display": nbt.CompoundTag({})}, ["display"]),
        ("empty lore list", {"display": nbt.CompoundTag({"Lore": nbt.ListTag([])})}, ["display"]),
        ("empty display name", {"display": nbt.CompoundTag({"Name": nbt.StringTag("")})}, ["display"]),
    ],
)
def test_empty_containers_survive_a_count_change_on_the_same_item(label: str, tag_fields: dict, expected: list) -> None:
    stack = _item(0, "minecraft:stone", **tag_fields)
    if not tag_fields:
        stack["tag"] = nbt.CompoundTag({})

    _before, _after, by_slot = _save([stack], edit_slot=0, count=2)

    assert "tag" in by_slot[0], f"{label} darf bei einer Count-Aenderung nicht verschwinden"
    assert sorted(by_slot[0]["tag"].keys()) == expected
    assert int(by_slot[0]["Count"].py_data) == 2


def test_clearing_the_last_display_field_still_cleans_up() -> None:
    """The guard must not freeze a genuine removal."""

    stack = _item(0, "minecraft:stone", display=nbt.CompoundTag({"Name": nbt.StringTag("Alt")}))
    _before, _after, by_slot = _save([stack], edit_slot=0, display_name="")

    assert "tag" not in by_slot[0]


def test_a_pure_count_change_only_touches_count() -> None:
    stack = _item(
        1,
        "minecraft:stone",
        display=nbt.CompoundTag({"Name": nbt.StringTag("Klinge")}),
        ench=nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(5)})]),
    )
    _before, _after, by_slot = _save([stack], edit_slot=1, count=3)

    result = by_slot[1]
    assert int(result["Count"].py_data) == 3
    assert str(result["tag"]["display"]["Name"].py_data) == "Klinge"
    assert [int(e["id"].py_data) for e in result["tag"]["ench"]] == [9]


def test_a_real_metadata_edit_is_still_applied() -> None:
    """The invariance guard must not freeze genuine edits."""

    sword = _item(1, display=nbt.CompoundTag({"Name": nbt.StringTag("Alt")}))
    _before, _after, by_slot = _save([sword], edit_slot=1, display_name="Neu")

    assert str(by_slot[1]["tag"]["display"]["Name"].py_data) == "Neu"


def _player_with(**fields):
    tag = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.DoubleTag(0.0)] * 3), "Health": nbt.FloatTag(20.0)})
    for key, value in fields.items():
        tag[key] = value
    return tag


def test_editing_one_ability_does_not_synthesize_the_others() -> None:
    tag = _player_with(abilities=nbt.CompoundTag({"mayfly": nbt.ByteTag(0)}))
    echoed = inventory.parse_abilities(tag)
    echoed["mayfly"] = True

    inventory.apply_abilities(tag, echoed)

    assert int(tag["abilities"]["mayfly"].py_data) == 1
    assert set(tag["abilities"].keys()) == {"mayfly"}


def test_creating_the_abilities_compound_still_writes_the_requested_set() -> None:
    tag = _player_with()

    inventory.apply_abilities(tag, {"mayfly": True, "maybuild": True})

    assert int(tag["abilities"]["mayfly"].py_data) == 1
    assert int(tag["abilities"]["mayBuild"].py_data) == 1


def test_an_unchanged_legacy_ability_alias_is_not_canonicalized() -> None:
    tag = _player_with(abilities=nbt.CompoundTag({"maybuild": nbt.ByteTag(0)}))

    inventory.apply_abilities(tag, inventory.parse_abilities(tag))

    assert "maybuild" in tag["abilities"]
    assert "mayBuild" not in tag["abilities"]


def _effect(effect_id: int, **extra):
    compound = nbt.CompoundTag(
        {
            "Id": nbt.ByteTag(effect_id),
            "Amplifier": nbt.ByteTag(0),
            "Duration": nbt.IntTag(100),
            "Ambient": nbt.ByteTag(0),
            "ShowParticles": nbt.ByteTag(1),
        }
    )
    for key, value in extra.items():
        compound[key] = value
    return compound


def test_an_existing_effect_does_not_gain_show_icon() -> None:
    """Older Bedrock entries have no ShowIcon; the displayed default is not an edit."""

    tag = _player_with(ActiveEffects=nbt.ListTag([_effect(1)]))
    echoed = inventory.parse_effects(tag)

    inventory.apply_effects(tag, echoed)

    assert "ShowIcon" not in tag["ActiveEffects"][0]


def test_editing_one_effect_keeps_an_unknown_effect_in_place() -> None:
    # 100 is outside the known effect table but still fits a signed ByteTag,
    # so the stored value stays readable without unsigned round tripping.
    unknown = _effect(100)
    tag = _player_with(ActiveEffects=nbt.ListTag([unknown, _effect(1)]))
    echoed = inventory.parse_effects(tag)
    echoed[1]["duration"] = 500

    inventory.apply_effects(tag, echoed)

    assert [int(entry["Id"].py_data) for entry in tag["ActiveEffects"]] == [100, 1]
    assert int(tag["ActiveEffects"][1]["Duration"].py_data) == 500


def test_an_already_empty_active_effects_list_survives_an_identical_round_trip() -> None:
    tag = _player_with(ActiveEffects=nbt.ListTag([]))

    inventory.apply_effects(tag, inventory.parse_effects(tag))

    assert "ActiveEffects" in tag
    assert len(tag["ActiveEffects"]) == 0


def test_removing_the_last_effect_still_cleans_up_the_tag() -> None:
    """Explicit removal may keep producing a cleaned NBT shape."""

    tag = _player_with(ActiveEffects=nbt.ListTag([_effect(1)]))

    inventory.apply_effects(tag, [])

    assert "ActiveEffects" not in tag


def _sword_with_mixed_enchantment_list():
    """An ench list whose entries are not all compounds (add-on/damaged data)."""

    item = _item(0)
    item["tag"] = nbt.CompoundTag({"ench": nbt.ListTag([nbt.StringTag("x")])})
    return item


def test_a_mixed_enchantment_list_is_rejected_instead_of_crashing() -> None:
    """Rebuilding such a list raises TypeError; that must not reach the route."""

    player = nbt.CompoundTag({"Inventory": nbt.ListTag([_sword_with_mixed_enchantment_list()])})
    parsed, _originals = inventory.nbt_to_json(player)
    payload = _echo(parsed[0], enchantments=[{"id": 9, "lvl": 1}])

    target = nbt.CompoundTag({"Inventory": nbt.ListTag([_sword_with_mixed_enchantment_list()])})
    with pytest.raises(ValueError, match="unbekannten NBT-Typ"):
        inventory.build_inventory_nbt(target, [payload], ENCHANTMENTS)


def test_a_mixed_enchantment_list_survives_an_unrelated_save() -> None:
    before, after, by_slot = _save([_sword_with_mixed_enchantment_list()])

    assert after == before
    assert [str(entry.py_data) for entry in by_slot[0]["tag"]["ench"]] == ["x"]


def test_an_untouched_enchantment_list_keeps_its_declared_element_type() -> None:
    """An empty list must not be rebuilt: that resets its element type to byte."""

    item = _item(0)
    empty_compound_list = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(1)})])
    del empty_compound_list[0]
    item["tag"] = nbt.CompoundTag({"ench": empty_compound_list, "RepairCost": nbt.IntTag(1)})
    element_type = item["tag"]["ench"].list_data_type

    _before, _after, by_slot = _save([item])

    assert by_slot[0]["tag"]["ench"].list_data_type == element_type
