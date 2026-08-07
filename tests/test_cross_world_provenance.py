import pytest


def test_cross_world_marker_is_rejected_server_side_for_addable_item() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
    payload = {
        "slot": 8,
        "source_slot": 0,
        "source_player_key": "",
        "source_container": "__cross_world__",
        "source_world_path": "C:/World-A",
        "name": "minecraft:stone",
        "count": 1,
        "damage": 0,
        "display_name": "",
        "lore": [],
        "enchantments": [],
        "has_preserved_nbt": False,
    }

    with pytest.raises(ValueError, match="Originalquelle"):
        inventory.build_inventory_nbt(
            player,
            [payload],
            inventory.ENCHANTMENTS,
            target_player_key="local-player",
        )
