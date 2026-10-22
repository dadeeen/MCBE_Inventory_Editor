"""Single-field requests must have only their explicitly expected typed-NBT delta."""

from copy import deepcopy

import pytest

from mcbe_editor import inventory, nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.item_data import ENCHANTMENTS


def _item(name, **metadata):
    return nbt.CompoundTag(
        {
            "Name": nbt.StringTag("minecraft:" + name),
            "Slot": nbt.ByteTag(0),
            "Count": nbt.ByteTag(1),
            "tag": nbt.CompoundTag(metadata),
        }
    )


def _edit(original, change):
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([original], 10)})
    payload = inventory.nbt_to_json(player)[0][0]
    data = deepcopy(payload["special_item"]["data"])
    change(data)
    payload["special_edit"] = {"kind": payload["special_item"]["kind"], "data": data}
    saved = inventory.build_inventory_nbt(player, [payload], ENCHANTMENTS)[0]
    return load_player_nbt(save_player_nbt(nbt.NamedTag(saved))).tag


@pytest.mark.parametrize("field", ["title", "author"])
@pytest.mark.parametrize("pages_type", [None, 0, 3, 10])
def test_written_book_text_edit_keeps_unrelated_absent_tags_and_empty_list_types(field, pages_type):
    original = _item("written_book", addon=nbt.LongTag(41))
    if pages_type is not None:
        original["tag"]["pages"] = nbt.ListTag([], pages_type)
    before = original.save_to()
    expected = deepcopy(original)
    expected["tag"][field] = nbt.StringTag("Changed")

    actual = _edit(original, lambda data: data.update({field: "Changed"}))

    assert actual.save_to() == expected.save_to()
    assert original.save_to() == before
    # Use the newly serialized state as the next source, as a real save response
    # does. An echo and a second edit must not synthesize defaults either.
    assert _edit(actual, lambda data: None).save_to() == actual.save_to()
    expected["tag"][field] = nbt.StringTag("Changed again")
    actual = _edit(actual, lambda data: data.update({field: "Changed again"}))
    assert actual.save_to() == expected.save_to()


@pytest.mark.parametrize("generation", [None, nbt.IntTag(2), nbt.StringTag("future generation format")])
def test_written_book_page_edit_does_not_sign_or_add_absent_author_and_title(generation):
    original = _item(
        "written_book",
        pages=nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag("Original"), "photoname": nbt.StringTag("image"), "addon": nbt.ByteArrayTag([1, -2])})], 10),
    )
    if generation is not None:
        original["tag"]["generation"] = generation
    expected = deepcopy(original)
    expected["tag"]["pages"][0]["text"] = nbt.StringTag("Changed")

    actual = _edit(original, lambda data: data["pages"][0].update(text="Changed"))

    assert actual.save_to() == expected.save_to()


@pytest.mark.parametrize("explosions_type", [None, 0, 3, 10])
def test_flight_edit_keeps_absent_explosions_and_empty_list_types(explosions_type):
    firework = nbt.CompoundTag({"addon": nbt.IntTag(3)})
    if explosions_type is not None:
        firework["Explosions"] = nbt.ListTag([], explosions_type)
    original = _item("firework_rocket", Fireworks=firework)
    expected = deepcopy(original)
    expected["tag"]["Fireworks"]["Flight"] = nbt.ByteTag(3)

    actual = _edit(original, lambda data: data.update(flight=3))

    assert actual.save_to() == expected.save_to()
    assert _edit(actual, lambda data: None).save_to() == actual.save_to()


def test_star_shape_edit_keeps_absent_custom_color_until_colors_change():
    original = _item(
        "firework_star",
        FireworksItem=nbt.CompoundTag({"FireworkColor": nbt.ByteArrayTag([1]), "addon": nbt.IntArrayTag([7, -8])}),
    )
    expected = deepcopy(original)
    expected["tag"]["FireworksItem"]["FireworkType"] = nbt.ByteTag(4)

    actual = _edit(original, lambda data: data["explosions"][0].update(shape=4))

    assert actual.save_to() == expected.save_to()
    actual = _edit(actual, lambda data: data["explosions"][0].update(colors=[4]))
    assert actual["tag"]["customColor"].py_data == -12827478
