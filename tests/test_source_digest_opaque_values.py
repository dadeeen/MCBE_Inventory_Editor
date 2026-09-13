import pytest


def _assert_stale_copy_rejected(original, changed):
    from mcbe_editor import inventory, nbt

    source = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
    parsed, _ = inventory.nbt_to_json(source)
    payload = {**parsed[5], "slot": 6, "source_slot": 5,
               "source_player_key": "source", "source_container": "inventory"}
    target = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
    # The same copy remains valid while the source is unchanged.
    result = inventory.build_inventory_nbt(
        target, [payload], inventory.ENCHANTMENTS,
        source_item_maps={("source", "inventory"): {5: original}}, target_player_key="target",
    )
    assert result[0]["Slot"].py_data == 6
    assert inventory._item_source_digest(original) != inventory._item_source_digest(changed)
    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            target, [payload], inventory.ENCHANTMENTS,
            source_item_maps={("source", "inventory"): {5: changed}}, target_player_key="target",
        )


@pytest.mark.parametrize("location", ["root", "nested", "ench", "enchantments", "lore"])
def test_empty_list_element_type_change_rejects_stale_cross_player_copy(location) -> None:
    from mcbe_editor import nbt

    def item(element_type):
        value = nbt.ListTag([], element_type)
        fields = _base_item(nbt)
        if location == "root":
            fields["Future"] = value
        elif location == "nested":
            fields["tag"] = nbt.CompoundTag({"Future": nbt.CompoundTag({"values": value})})
        elif location == "lore":
            fields["tag"] = nbt.CompoundTag({"display": nbt.CompoundTag({"Lore": value})})
        else:
            fields["tag"] = nbt.CompoundTag({location: value})
        return nbt.CompoundTag(fields)

    _assert_stale_copy_rejected(item(3), item(10))


@pytest.mark.parametrize("difference", ["string_bytes", "name_bytes", "nan_bits", "negative_zero"])
def test_opaque_wire_changes_reject_stale_cross_player_copy(difference) -> None:
    import struct
    from mcbe_editor import nbt

    def string(raw):
        return nbt.load(b"\x08\x00\x00" + struct.pack("<H", len(raw)) + raw).tag

    if difference == "string_bytes":
        values = [string(b"\xff"), string("\u241bxff".encode("utf-8"))]
        assert values[0].py_data == values[1].py_data
    elif difference == "name_bytes":
        values = [nbt.load(b"\x0a\x00\x00\x01" + struct.pack("<H", len(raw)) + raw + b"\x01\x00").tag
                  for raw in (b"\xff", "\u241bxff".encode("utf-8"))]
        assert list(values[0]) == list(values[1])
    else:
        bits = (0x7FC00001, 0x7FC00002) if difference == "nan_bits" else (0, 0x80000000)
        values = [nbt.load(b"\x05\x00\x00" + struct.pack("<I", value)).tag for value in bits]
    items = [nbt.CompoundTag({**_base_item(nbt), "Future": value}) for value in values]
    _assert_stale_copy_rejected(*items)


def _base_item(nbt):
    return {
        "Slot": nbt.ByteTag(5),
        "Name": nbt.StringTag("minecraft:stone"),
        "Count": nbt.ByteTag(1),
        "Damage": nbt.ShortTag(0),
    }


def test_zero_valued_opaque_item_tag_affects_source_digest() -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    absent = nbt.CompoundTag(_base_item(nbt))
    zero_tag = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.ByteTag(0)})
    one_tag = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.ByteTag(1)})

    assert inventory._item_source_digest(absent) != inventory._item_source_digest(zero_tag)
    assert inventory._item_source_digest(zero_tag) != inventory._item_source_digest(one_tag)


def test_zero_valued_opaque_enchantment_shape_affects_source_digest() -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    zero_ench = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.CompoundTag({"ench": nbt.ByteTag(0)})})
    one_ench = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.CompoundTag({"ench": nbt.ByteTag(1)})})

    assert inventory._item_source_digest(zero_ench) != inventory._item_source_digest(one_ench)


def test_non_damageable_item_tag_damage_is_preservation_relevant() -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    first = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.CompoundTag({"Damage": nbt.IntTag(1)})})
    changed = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.CompoundTag({"Damage": nbt.IntTag(2)})})

    assert inventory._core._item_has_protected_nbt(first) is True
    assert inventory._item_source_digest(first) != inventory._item_source_digest(changed)


def test_damageable_item_tag_damage_ignores_value_but_tracks_numeric_type() -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    base = {
        "Slot": nbt.ByteTag(5),
        "Name": nbt.StringTag("minecraft:diamond_sword"),
        "Count": nbt.ByteTag(1),
        "Damage": nbt.ShortTag(0),
    }
    first = nbt.CompoundTag({**base, "tag": nbt.CompoundTag({"Damage": nbt.IntTag(1)})})
    edited = nbt.CompoundTag({**base, "tag": nbt.CompoundTag({"Damage": nbt.IntTag(2)})})
    changed_type = nbt.CompoundTag({**base, "tag": nbt.CompoundTag({"Damage": nbt.ShortTag(2)})})

    assert inventory._item_source_digest(first) == inventory._item_source_digest(edited)
    assert inventory._item_source_digest(first) != inventory._item_source_digest(changed_type)


@pytest.mark.parametrize("field", ["Slot", "Count", "Damage"])
def test_editable_root_numeric_fields_ignore_value_but_track_numeric_type(field: str) -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    first_fields = _base_item(nbt)
    edited_fields = _base_item(nbt)
    changed_type_fields = _base_item(nbt)
    first_fields[field] = nbt.ByteTag(1)
    edited_fields[field] = nbt.ByteTag(2)
    changed_type_fields[field] = nbt.IntTag(2)

    first = nbt.CompoundTag(first_fields)
    edited = nbt.CompoundTag(edited_fields)
    changed_type = nbt.CompoundTag(changed_type_fields)

    assert inventory._item_source_digest(first) == inventory._item_source_digest(edited)
    assert inventory._item_source_digest(first) != inventory._item_source_digest(changed_type)


def test_damageable_root_damage_is_preserved_when_tag_damage_is_active() -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    base = {
        "Slot": nbt.ByteTag(5),
        "Name": nbt.StringTag("minecraft:diamond_sword"),
        "Count": nbt.ByteTag(1),
        "tag": nbt.CompoundTag({"Damage": nbt.IntTag(7)}),
    }
    first = nbt.CompoundTag({**base, "Damage": nbt.ShortTag(0)})
    changed_root = nbt.CompoundTag({**base, "Damage": nbt.ShortTag(1)})
    edited_tag = nbt.CompoundTag(
        {
            **base,
            "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"Damage": nbt.IntTag(8)}),
        }
    )

    assert inventory._item_source_digest(first) != inventory._item_source_digest(changed_root)
    assert inventory._item_source_digest(first) == inventory._item_source_digest(edited_tag)


def test_known_enchantment_structure_affects_source_digest_but_level_does_not() -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    def item_with_enchantment(list_name: str, level_tag):
        enchantment = nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": level_tag})
        return nbt.CompoundTag(
            {
                **_base_item(nbt),
                "tag": nbt.CompoundTag({list_name: nbt.ListTag([enchantment])}),
            }
        )

    first = item_with_enchantment("ench", nbt.ShortTag(1))
    edited_level = item_with_enchantment("ench", nbt.ShortTag(2))
    changed_level_type = item_with_enchantment("ench", nbt.IntTag(2))
    changed_family = item_with_enchantment("enchantments", nbt.ShortTag(2))

    assert inventory._item_source_digest(first) == inventory._item_source_digest(edited_level)
    assert inventory._item_source_digest(first) != inventory._item_source_digest(changed_level_type)
    assert inventory._item_source_digest(first) != inventory._item_source_digest(changed_family)


def test_display_digest_ignores_editable_strings_but_tracks_opaque_shapes() -> None:
    from mcbe_editor import nbt
    from mcbe_editor import inventory

    editable_first = nbt.CompoundTag(
        {
            **_base_item(nbt),
            "tag": nbt.CompoundTag(
                {
                    "display": nbt.CompoundTag(
                        {
                            "Name": nbt.StringTag("First"),
                            "Lore": nbt.ListTag([nbt.StringTag("A")]),
                        }
                    )
                }
            ),
        }
    )
    editable_changed = nbt.CompoundTag(
        {
            **_base_item(nbt),
            "tag": nbt.CompoundTag(
                {
                    "display": nbt.CompoundTag(
                        {
                            "Name": nbt.StringTag("Second"),
                            "Lore": nbt.ListTag([nbt.StringTag("B")]),
                        }
                    )
                }
            ),
        }
    )
    opaque_first = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.CompoundTag({"display": nbt.CompoundTag({"Name": nbt.IntTag(1)})})})
    opaque_changed = nbt.CompoundTag({**_base_item(nbt), "tag": nbt.CompoundTag({"display": nbt.CompoundTag({"Name": nbt.IntTag(2)})})})

    assert inventory._item_source_digest(editable_first) == inventory._item_source_digest(editable_changed)
    assert inventory._item_source_digest(opaque_first) != inventory._item_source_digest(opaque_changed)


@pytest.mark.parametrize("empty_type", [0, 8])
def test_editable_lore_digest_ignores_adding_the_first_line(empty_type) -> None:
    from mcbe_editor import inventory, nbt

    def item(lore):
        return nbt.CompoundTag({**_base_item(nbt), "tag": nbt.CompoundTag({
            "display": nbt.CompoundTag({"Lore": lore}),
        })})

    empty = item(nbt.ListTag([], empty_type))
    edited = item(nbt.ListTag([nbt.StringTag("First line")]))
    assert inventory._item_source_digest(empty) == inventory._item_source_digest(edited)
