"""Synthetic player NBT for the tests.

The builders depend on the NBT module only, not on Flask or the service, so
any test can import them without loading the app.
"""

from mcbe_editor import nbt


def make_minimal_player_tag():
    return nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
        }
    )


def make_player_bytes(item_tag, *additional_item_tags):
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([item_tag, *additional_item_tags]),
            "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(2.0), nbt.DoubleTag(3.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
        }
    )
    return nbt.NamedTag(player).save_to(compressed=False, little_endian=True)


def make_full_player_tag(items=None):
    tag = nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
            "XPLevel": nbt.IntTag(5),
            "XPProgress": nbt.FloatTag(0.5),
            "foodLevel": nbt.IntTag(18),
            "foodSaturationLevel": nbt.FloatTag(15.0),
        }
    )
    if items:
        tag["Inventory"] = nbt.ListTag(items)
    return tag
