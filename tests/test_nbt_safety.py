import pytest
import io
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.item_data import ENCHANTMENTS
from mcbe_editor.backup import resolve_backup_path, validate_zip_members
from mcbe_editor.inventory import (
    _set_numeric_tag_preserving_type,
    apply_editable_item_tags,
    apply_effects,
    apply_player_stats,
    build_inventory_nbt,
    build_ender_chest_nbt,
    count_hidden_unknown_slots,
    nbt_to_json,
    parse_ender_chest,
    protected_player_nbt_flags,
    validate_inventory_item,
)


class NbtSafetyTests(unittest.TestCase):
    def test_preserves_unknown_item_tag_when_editable_fields_are_empty(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "customData": nbt.StringTag("keep-me"),
                    }
                ),
            }
        )
        item_data = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:diamond_sword",
                "count": 1,
                "damage": 0,
                "display_name": "",
                "lore": [],
                "enchantments": [],
            },
            ENCHANTMENTS,
        )

        apply_editable_item_tags(item, item_data)

        self.assertIn("tag", item)
        self.assertEqual(item["tag"]["customData"].py_data, "keep-me")

    def test_preserves_extra_fields_on_known_enchantment_compounds(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "ench": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "id": nbt.ShortTag(9),
                                        "lvl": nbt.ShortTag(1),
                                        "futureField": nbt.StringTag("keep-me"),
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        )
        item_data = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:diamond_sword",
                "count": 1,
                "damage": 0,
                "display_name": "",
                "lore": [],
                "enchantments": [{"id": 9, "lvl": 2}],
            },
            ENCHANTMENTS,
        )

        apply_editable_item_tags(item, item_data)

        self.assertEqual(item["tag"]["ench"][0]["lvl"].py_data, 2)
        self.assertEqual(item["tag"]["ench"][0]["futureField"].py_data, "keep-me")

    def test_preserves_duplicate_known_enchantment_entries_verbatim(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "ench": nbt.ListTag(
                            [
                                nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(1)}),
                                nbt.CompoundTag(
                                    {
                                        "id": nbt.ShortTag(9),
                                        "lvl": nbt.ShortTag(2),
                                        "addon_marker": nbt.IntTag(42),
                                    }
                                ),
                            ]
                        )
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([item])})
        parsed, _originals = nbt_to_json(player)

        self.assertEqual(parsed[0]["enchantments"], [{"id": 9, "lvl": 1}])
        self.assertTrue(parsed[0]["has_protected_nbt"])

        rebuilt = build_inventory_nbt(player, [parsed[0]], ENCHANTMENTS)
        enchantments = rebuilt[0]["tag"]["ench"]
        self.assertEqual(len(enchantments), 2)
        self.assertEqual(enchantments[0]["lvl"].py_data, 1)
        self.assertEqual(enchantments[1]["lvl"].py_data, 2)
        self.assertEqual(enchantments[1]["addon_marker"].py_data, 42)

    def test_preserves_malformed_known_enchantment_during_unrelated_save(self):
        protected_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "ench": nbt.ListTag(
                            [
                                nbt.CompoundTag({"id": nbt.ShortTag(9)}),
                            ]
                        )
                    }
                ),
            }
        )
        ordinary_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(1),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([protected_item, ordinary_item])})
        parsed, _originals = nbt_to_json(player)

        self.assertEqual(parsed[0]["enchantments"], [])
        self.assertTrue(parsed[0]["has_protected_nbt"])
        parsed[1]["count"] = 2

        rebuilt = build_inventory_nbt(player, [parsed[0], parsed[1]], ENCHANTMENTS)
        rebuilt_by_slot = {entry["Slot"].py_data: entry for entry in rebuilt}
        protected_enchantment = rebuilt_by_slot[0]["tag"]["ench"][0]
        self.assertEqual(protected_enchantment["id"].py_data, 9)
        self.assertNotIn("lvl", protected_enchantment)
        self.assertEqual(rebuilt_by_slot[1]["Count"].py_data, 2)

    def test_preserves_unknown_enchantment_list_family(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:book"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "enchantments": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "id": nbt.ShortTag(32000),
                                        "lvl": nbt.ShortTag(1),
                                        "addonField": nbt.StringTag("keep-me"),
                                    }
                                )
                            ]
                        )
                    }
                ),
            }
        )
        item_data = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:book",
                "count": 1,
                "damage": 0,
                "display_name": "",
                "lore": [],
                "enchantments": [],
            },
            ENCHANTMENTS,
        )

        apply_editable_item_tags(item, item_data)

        self.assertIn("enchantments", item["tag"])
        self.assertEqual(item["tag"]["enchantments"][0]["addonField"].py_data, "keep-me")

    def test_preserves_known_enchantment_list_family_when_both_lists_exist(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:book"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "ench": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "id": nbt.ShortTag(32000),
                                        "lvl": nbt.ShortTag(1),
                                        "addonField": nbt.StringTag("keep-unknown"),
                                    }
                                )
                            ]
                        ),
                        "enchantments": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "id": nbt.ShortTag(9),
                                        "lvl": nbt.ShortTag(1),
                                        "futureField": nbt.StringTag("keep-known"),
                                    }
                                )
                            ]
                        ),
                    }
                ),
            }
        )
        item_data = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:book",
                "count": 1,
                "damage": 0,
                "display_name": "",
                "lore": [],
                "enchantments": [{"id": 9, "lvl": 2}],
            },
            ENCHANTMENTS,
        )

        apply_editable_item_tags(item, item_data)

        self.assertEqual(item["tag"]["ench"][0]["addonField"].py_data, "keep-unknown")
        self.assertEqual(item["tag"]["enchantments"][0]["id"].py_data, 9)
        self.assertEqual(item["tag"]["enchantments"][0]["lvl"].py_data, 2)
        self.assertEqual(item["tag"]["enchantments"][0]["futureField"].py_data, "keep-known")

    def test_preserves_unknown_effects_even_when_payload_is_empty(self):
        player = nbt.CompoundTag(
            {
                "ActiveEffects": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Id": nbt.IntTag(500),
                                "Amplifier": nbt.ByteTag(1),
                                "Duration": nbt.IntTag(100),
                                "futureField": nbt.StringTag("keep-me"),
                            }
                        )
                    ]
                )
            }
        )

        apply_effects(player, [])

        self.assertIn("ActiveEffects", player)
        self.assertEqual(player["ActiveEffects"][0]["futureField"].py_data, "keep-me")

    def test_preserves_future_position_tail_values(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [
                        nbt.DoubleTag(1.0),
                        nbt.DoubleTag(2.0),
                        nbt.DoubleTag(3.0),
                        nbt.DoubleTag(4.0),
                    ]
                )
            }
        )

        apply_player_stats(player, {"pos": [10, 20, 30]})

        self.assertEqual([tag.py_data for tag in player["Pos"]], [10.0, 20.0, 30.0, 4.0])

    def test_updates_float_position_list_without_retyping_tail(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [
                        nbt.FloatTag(1.0),
                        nbt.FloatTag(2.0),
                        nbt.FloatTag(3.0),
                        nbt.FloatTag(4.5),
                    ]
                )
            }
        )

        self.assertFalse(protected_player_nbt_flags(player)["pos_opaque"])
        apply_player_stats(player, {"pos": [10, 20, 30]})
        self.assertEqual([tag.py_data for tag in player["Pos"]], [10.0, 20.0, 30.0, 4.5])
        self.assertTrue(all(isinstance(tag, nbt.FloatTag) for tag in player["Pos"]))

    def test_same_float_location_remains_byte_exact(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [nbt.FloatTag(-24.052806854248047), nbt.FloatTag(72.62001037597656), nbt.FloatTag(81.74593353271484)]
                ),
                "DimensionId": nbt.IntTag(0),
                "FuturePlayerData": nbt.StringTag("keep"),
            }
        )
        named_tag = nbt.NamedTag(player)
        before = named_tag.save_to(compressed=False, little_endian=True)

        apply_player_stats(
            player,
            {
                "pos": [-24.052806854248047, 72.62001037597656, 81.74593353271484],
                "dimension_id": 0,
            },
        )
        after = named_tag.save_to(compressed=False, little_endian=True)

        self.assertEqual(after, before)

    def test_rejects_short_position_list_instead_of_filling_defaults(self):
        player = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(2.0)])})

        self.assertTrue(protected_player_nbt_flags(player)["pos_opaque"])
        with self.assertRaisesRegex(ValueError, "Position.*unbekannten NBT-Typ"):
            apply_player_stats(player, {"pos": [10, 20, 30]})
        self.assertEqual([tag.py_data for tag in player["Pos"]], [1.0, 2.0])

    def test_missing_location_tags_are_not_silently_created(self):
        missing_position = nbt.CompoundTag({"DimensionId": nbt.IntTag(0)})
        self.assertTrue(protected_player_nbt_flags(missing_position)["pos_missing"])
        with self.assertRaisesRegex(ValueError, "Pos-Tag fehlt"):
            apply_player_stats(missing_position, {"pos": [1.0, 70.0, 1.0]})
        self.assertNotIn("Pos", missing_position)

        missing_dimension = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [nbt.FloatTag(8.0), nbt.FloatTag(70.0), nbt.FloatTag(8.0)]
                )
            }
        )
        self.assertTrue(protected_player_nbt_flags(missing_dimension)["dimension_id_missing"])
        with self.assertRaisesRegex(ValueError, "DimensionId fehlt"):
            apply_player_stats(missing_dimension, {"pos": [1.0, 70.0, 1.0], "dimension_id": 1})
        self.assertEqual([tag.py_data for tag in missing_dimension["Pos"]], [8.0, 70.0, 8.0])
        self.assertNotIn("DimensionId", missing_dimension)

    def test_rejects_float_position_overflow_without_mutating_source(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [nbt.FloatTag(1.0), nbt.FloatTag(2.0), nbt.FloatTag(3.0)]
                )
            }
        )

        with self.assertRaisesRegex(ValueError, "Zahlenbereich"):
            apply_player_stats(player, {"pos": [3.5e38, 20, 30]})
        self.assertEqual([tag.py_data for tag in player["Pos"]], [1.0, 2.0, 3.0])

    def test_updates_dimension_and_position_in_one_validated_location_write(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [nbt.DoubleTag(80.0), nbt.DoubleTag(70.0), nbt.DoubleTag(-40.0)]
                ),
                "DimensionId": nbt.IntTag(0),
            }
        )

        apply_player_stats(player, {"dimension_id": 1, "pos": [10.0, 70.0, -5.0]})

        self.assertEqual(player["DimensionId"].py_data, 1)
        self.assertEqual([tag.py_data for tag in player["Pos"]], [10.0, 70.0, -5.0])

    def test_rejects_dimension_without_position(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [nbt.DoubleTag(8.0), nbt.DoubleTag(70.0), nbt.DoubleTag(8.0)]
                ),
                "DimensionId": nbt.IntTag(0),
            }
        )

        with self.assertRaisesRegex(ValueError, "zusammen mit einer vollständigen Spielerposition"):
            apply_player_stats(player, {"dimension_id": 1})
        self.assertEqual(player["DimensionId"].py_data, 0)
        self.assertEqual([tag.py_data for tag in player["Pos"]], [8.0, 70.0, 8.0])

    def test_rejects_unknown_dimension_before_mutating_position(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [nbt.DoubleTag(8.0), nbt.DoubleTag(70.0), nbt.DoubleTag(8.0)]
                ),
                "DimensionId": nbt.IntTag(0),
            }
        )

        with self.assertRaisesRegex(ValueError, "Unbekannte Spielerdimension"):
            apply_player_stats(player, {"dimension_id": 7, "pos": [1.0, 2.0, 3.0]})
        self.assertEqual(player["DimensionId"].py_data, 0)
        self.assertEqual([tag.py_data for tag in player["Pos"]], [8.0, 70.0, 8.0])

    def test_protects_unknown_or_wrong_dimension_id(self):
        for dimension_tag in (nbt.IntTag(7), nbt.StringTag("minecraft:overworld")):
            with self.subTest(tag_type=type(dimension_tag).__name__):
                player = nbt.CompoundTag(
                    {
                        "Pos": nbt.ListTag(
                            [nbt.DoubleTag(8.0), nbt.DoubleTag(70.0), nbt.DoubleTag(8.0)]
                        ),
                        "DimensionId": dimension_tag,
                    }
                )
                self.assertTrue(protected_player_nbt_flags(player)["dimension_id_opaque"])
                with self.assertRaisesRegex(ValueError, "DimensionId.*geschützt"):
                    apply_player_stats(player, {"dimension_id": 1, "pos": [1.0, 2.0, 3.0]})
                self.assertEqual([tag.py_data for tag in player["Pos"]], [8.0, 70.0, 8.0])

    def test_rejects_large_integer_position_tail_without_precision_loss(self):
        precise_tail = 9_007_199_254_740_993
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag(
                    [
                        nbt.LongTag(1),
                        nbt.LongTag(2),
                        nbt.LongTag(3),
                        nbt.LongTag(precise_tail),
                    ]
                )
            }
        )

        self.assertTrue(protected_player_nbt_flags(player)["pos_opaque"])
        with self.assertRaisesRegex(ValueError, "Position.*unbekannten NBT-Typ"):
            apply_player_stats(player, {"pos": [10, 20, 30]})
        self.assertIsInstance(player["Pos"][3], nbt.LongTag)
        self.assertEqual(player["Pos"][3].py_data, precise_tail)

    def test_rejects_visible_metadata_edit_for_opaque_item_tag(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.StringTag("future-shape"),
            }
        )
        parsed, _originals = nbt_to_json(nbt.CompoundTag({"Inventory": nbt.ListTag([item])}))
        self.assertTrue(parsed[0]["item_tag_opaque"])

        with self.assertRaisesRegex(ValueError, "Item-Metadaten.*unbekannten NBT-Typ"):
            apply_editable_item_tags(item, {"display_name": "Neu", "lore": [], "enchantments": []})

        self.assertIsInstance(item["tag"], nbt.StringTag)
        self.assertEqual(item["tag"].py_data, "future-shape")

    def test_rejects_non_numeric_position_list(self):
        player = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.StringTag("x"), nbt.StringTag("y"), nbt.StringTag("z")])})

        self.assertTrue(protected_player_nbt_flags(player)["pos_opaque"])
        with self.assertRaisesRegex(ValueError, "Position.*unbekannten NBT-Typ"):
            apply_player_stats(player, {"pos": [1, 2, 3]})
        self.assertEqual([tag.py_data for tag in player["Pos"]], ["x", "y", "z"])

    def test_preserving_numeric_type_does_not_keep_wrapping_byte_tag(self):
        compound = nbt.CompoundTag({"Value": nbt.ByteTag(0)})

        _set_numeric_tag_preserving_type(compound, "Value", 200, nbt.IntTag)

        self.assertIsInstance(compound["Value"], nbt.IntTag)
        self.assertEqual(compound["Value"].py_data, 200)

    def test_numeric_type_fallback_rejects_wrapping_default_type(self):
        compound = nbt.CompoundTag({"Value": nbt.ByteTag(0)})

        with self.assertRaisesRegex(ValueError, "NBT-Zahlenbereich"):
            _set_numeric_tag_preserving_type(compound, "Value", 200, nbt.ByteTag)
        self.assertEqual(compound["Value"].py_data, 0)

    def test_nbt_view_serializes_array_tags_as_lists(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:stone"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag({"FutureBytes": nbt.ByteArrayTag([1, 2, 3])}),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)
        view = inventory[0]["nbt_view"]["value"]["tag"]["value"]["FutureBytes"]

        self.assertEqual(view["type"], "ByteArrayTag")
        self.assertEqual(view["value"], [1, 2, 3])
        json.dumps(inventory)

    def test_duplicate_original_editable_slots_are_not_cloned_on_save(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)}),
                        nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:dirt"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)}),
                    ]
                )
            }
        )

        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0, "display_name": "", "lore": [], "enchantments": []}],
            ENCHANTMENTS,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Name"].py_data, "minecraft:stone")

    def test_protected_duplicate_after_visible_item_does_not_hide_visible_source_nbt(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:stone"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag({"visibleFutureField": nbt.StringTag("keep-visible")}),
                            }
                        ),
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "OpaqueFutureEntry": nbt.StringTag("keep-protected"),
                            }
                        ),
                    ]
                )
            }
        )

        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 0, "display_name": "", "lore": [], "enchantments": []}],
            ENCHANTMENTS,
        )

        visible = [item for item in result if item.get("Name") and item["Name"].py_data == "minecraft:stone"]
        protected = [item for item in result if item.get("OpaqueFutureEntry")]
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["Count"].py_data, 2)
        self.assertEqual(visible[0]["tag"]["visibleFutureField"].py_data, "keep-visible")
        self.assertEqual(len(protected), 1)
        self.assertEqual(protected[0]["OpaqueFutureEntry"].py_data, "keep-protected")

    def test_allows_unknown_item_counts_up_to_bedrock_byte_limit(self):
        result = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:future_addon_stack",
                "count": 100,
                "damage": 0,
            },
            ENCHANTMENTS,
        )

        self.assertEqual(result["count"], 100)

    def test_rejects_counts_that_would_overflow_bedrock_byte_tags(self):
        with self.assertRaisesRegex(ValueError, "Ungültige Menge"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 65,
                    "damage": 0,
                },
                ENCHANTMENTS,
            )

    def test_rejects_exceeding_item_specific_stack_limit(self):
        with self.assertRaisesRegex(ValueError, "Ungültige Menge"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:diamond_sword",
                    "count": 2,
                    "damage": 0,
                },
                ENCHANTMENTS,
            )

    def test_accepts_item_specific_stack_limit_boundary(self):
        result = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:diamond_sword",
                "count": 1,
                "damage": 0,
            },
            ENCHANTMENTS,
        )
        self.assertIsNotNone(result)

    def test_rejects_ender_pearl_above_16(self):
        with self.assertRaisesRegex(ValueError, "Ungültige Menge"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:ender_pearl",
                    "count": 17,
                    "damage": 0,
                },
                ENCHANTMENTS,
            )

    def test_rejects_invalid_inventory_slot(self):
        with self.assertRaisesRegex(ValueError, "Ungültiger Slot"):
            validate_inventory_item(
                {
                    "slot": 99,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                },
                ENCHANTMENTS,
            )

    def test_malformed_known_inventory_slot_is_hidden_and_preserved(self):
        opaque_item = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Count": nbt.ByteTag(1), "FuturePayload": nbt.StringTag("keep-me")})
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([opaque_item])})

        inventory, _original = nbt_to_json(player)
        self.assertNotIn(0, inventory)
        self.assertEqual(count_hidden_unknown_slots(player)["inventory_protected_known"], 1)

        result = build_inventory_nbt(player, [], ENCHANTMENTS)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["FuturePayload"].py_data, "keep-me")

    def test_standard_item_fields_with_opaque_types_are_hidden_and_preserved(self):
        opaque_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.StringTag("1"),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([opaque_item])})

        inventory, _original = nbt_to_json(player)
        self.assertNotIn(0, inventory)
        self.assertEqual(count_hidden_unknown_slots(player)["inventory_protected_known"], 1)

        result = build_inventory_nbt(player, [], ENCHANTMENTS)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0]["Count"], nbt.StringTag)
        self.assertEqual(result[0]["Count"].py_data, "1")

    def test_missing_slot_item_is_hidden_and_preserved(self):
        opaque_item = nbt.CompoundTag(
            {
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "FuturePayload": nbt.StringTag("keep-missing-slot"),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([opaque_item])})

        inventory, _original = nbt_to_json(player)
        self.assertEqual(inventory, {})

        result = build_inventory_nbt(player, [], ENCHANTMENTS)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["FuturePayload"].py_data, "keep-missing-slot")

    def test_protected_duplicate_known_slot_is_not_dropped(self):
        protected = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "FuturePayload": nbt.StringTag("keep-duplicate")})
        editable = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([protected, editable])})

        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0, "display_name": "", "lore": [], "enchantments": []}],
            ENCHANTMENTS,
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["FuturePayload"].py_data, "keep-duplicate")
        self.assertEqual(result[1]["Name"].py_data, "minecraft:stone")

    def test_malformed_known_ender_slot_is_hidden_and_preserved(self):
        opaque_item = nbt.CompoundTag({"Slot": nbt.ByteTag(5), "FuturePayload": nbt.StringTag("keep-ec")})
        player = nbt.CompoundTag({"EnderChestInventory": nbt.ListTag([opaque_item])})

        self.assertEqual(parse_ender_chest(player), {})
        self.assertEqual(count_hidden_unknown_slots(player)["ender_chest_protected_known"], 1)

        result = build_ender_chest_nbt(player, [], ENCHANTMENTS)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["FuturePayload"].py_data, "keep-ec")

    def test_empty_inventory_placeholders_do_not_lock_slots(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag({"Slot": nbt.ByteTag(5)}),
                        nbt.CompoundTag({"Slot": nbt.ByteTag(6), "Name": nbt.StringTag("minecraft:air"), "Count": nbt.ByteTag(0)}),
                    ]
                ),
                "EnderChestInventory": nbt.ListTag(
                    [nbt.CompoundTag({"Slot": nbt.ByteTag(3), "Name": nbt.StringTag("minecraft:air"), "Count": nbt.ByteTag(0)})]
                ),
            }
        )

        summary = count_hidden_unknown_slots(player)

        self.assertEqual(summary["inventory_protected_known"], 0)
        self.assertEqual(summary["inventory_protected_known_slots"], [])
        self.assertEqual(summary["ender_chest_protected_known"], 0)
        self.assertEqual(summary["ender_chest_protected_known_slots"], [])

    def test_empty_inventory_placeholder_can_be_replaced_safely(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([nbt.CompoundTag({"Slot": nbt.ByteTag(5)})])})

        result = build_inventory_nbt(
            player,
            [
                {
                    "slot": 5,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Slot"].py_data, 5)
        self.assertEqual(result[0]["Name"].py_data, "minecraft:stone")

    def test_opaque_scalar_player_stats_are_preserved_when_omitted(self):
        player = nbt.CompoundTag(
            {
                "Health": nbt.StringTag("future-health"),
                "PlayerGameType": nbt.IntTag(0),
                "XPLevel": nbt.StringTag("future-xp"),
            }
        )

        flags = protected_player_nbt_flags(player)
        self.assertEqual(flags["stat_fields_opaque"]["health"], "Health")
        self.assertEqual(flags["stat_fields_opaque"]["xp_level"], "XPLevel")

        apply_player_stats(player, {})

        self.assertEqual(player["Health"].py_data, "future-health")
        self.assertEqual(player["XPLevel"].py_data, "future-xp")
        self.assertEqual(player["PlayerGameType"].py_data, 0)

    def test_opaque_scalar_player_stat_write_is_rejected(self):
        player = nbt.CompoundTag({"Health": nbt.StringTag("future-health")})
        with self.assertRaisesRegex(ValueError, "Health.*unbekannten NBT-Typ"):
            apply_player_stats(player, {"health": 10})
        self.assertEqual(player["Health"].py_data, "future-health")

    def test_opaque_position_write_is_rejected(self):
        player = nbt.CompoundTag({"Pos": nbt.StringTag("future-pos")})
        with self.assertRaisesRegex(ValueError, "Position.*unbekannten NBT-Typ"):
            apply_player_stats(player, {"pos": [1, 2, 3]})
        self.assertEqual(player["Pos"].py_data, "future-pos")

    def test_rejects_backup_path_traversal(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "Backup-Dateiname"):
                resolve_backup_path(str(world), "..\\outside.zip")

    def test_rejects_zip_members_outside_restore_directory(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zipf:
            zipf.writestr("../outside.txt", "bad")
        data.seek(0)

        with TemporaryDirectory() as tmp, zipfile.ZipFile(data, "r") as zipf, self.assertRaisesRegex(ValueError, "Unsicherer Pfad"):
            validate_zip_members(zipf, Path(tmp) / "restore")

    def test_reports_protected_known_slots_that_are_not_editable(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag({"Slot": nbt.ByteTag(5), "OpaquePayload": nbt.StringTag("keep-me")}),
                        nbt.CompoundTag({"Slot": nbt.ByteTag(99), "OpaquePayload": nbt.StringTag("future-slot")}),
                    ]
                ),
                "EnderChestInventory": nbt.ListTag([nbt.CompoundTag({"Slot": nbt.ByteTag(3), "OpaquePayload": nbt.StringTag("keep-me")})]),
            }
        )

        summary = count_hidden_unknown_slots(player)

        self.assertEqual(summary["inventory"], 1)
        self.assertEqual(summary["inventory_protected_known"], 1)
        self.assertEqual(summary["inventory_protected_known_slots"], [5])
        self.assertEqual(summary["ender_chest_protected_known_slots"], [3])

    def test_rejects_overwrite_of_protected_only_known_slot(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([nbt.CompoundTag({"Slot": nbt.ByteTag(5), "OpaquePayload": nbt.StringTag("keep-me")})])})

        with self.assertRaisesRegex(ValueError, "geschützten nicht darstellbaren"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 5,
                        "name": "minecraft:stone",
                        "count": 1,
                        "damage": 0,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [],
                    }
                ],
                ENCHANTMENTS,
            )


if __name__ == "__main__":
    unittest.main()


class MalformedPayloadEntryTests(unittest.TestCase):
    """A non-object list entry must fail as a client error, never as a 500.

    ``validate_inventory_item``/``validate_effect`` reach into the entry with
    ``entry["slot"]``. Before, a JSON list carrying a scalar or a nested list
    raised TypeError, which the routes could only report as an opaque HTTP 500.
    """

    BAD_ENTRIES = (1, True, "x", None, [], [{"slot": 0}], 1.5)

    def test_inventory_rejects_non_object_entries(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        for bad in self.BAD_ENTRIES:
            with self.subTest(entry=bad), self.assertRaisesRegex(ValueError, "Item-Daten"):
                build_inventory_nbt(player, [bad], ENCHANTMENTS)

    def test_ender_chest_rejects_non_object_entries(self):
        player = nbt.CompoundTag({"EnderChestInventory": nbt.ListTag([])})
        for bad in self.BAD_ENTRIES:
            with self.subTest(entry=bad), self.assertRaisesRegex(ValueError, "Item-Daten"):
                build_ender_chest_nbt(player, [bad], ENCHANTMENTS)

    def test_validate_inventory_item_rejects_non_object(self):
        for bad in self.BAD_ENTRIES:
            with self.subTest(entry=bad), self.assertRaisesRegex(ValueError, "Item-Daten"):
                validate_inventory_item(bad, ENCHANTMENTS)

    def test_effects_reject_non_object_entries(self):
        for bad in self.BAD_ENTRIES:
            player = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([])})
            with self.subTest(entry=bad), self.assertRaisesRegex(ValueError, "Effekt-Daten"):
                apply_effects(player, [bad])

    def test_validate_effect_rejects_non_object(self):
        from mcbe_editor.inventory import validate_effect

        for bad in self.BAD_ENTRIES:
            with self.subTest(entry=bad), self.assertRaisesRegex(ValueError, "Effekt-Daten"):
                validate_effect(bad)

    def test_enchantment_entries_reject_non_objects(self):
        """The same guard is needed one level down, inside ``enchantments``."""

        for bad in self.BAD_ENTRIES:
            item = {"slot": 0, "name": "minecraft:diamond_sword", "count": 1, "damage": 0, "enchantments": [bad]}
            with self.subTest(entry=bad), self.assertRaisesRegex(ValueError, "Ungültige Verzauberung"):
                validate_inventory_item(item, ENCHANTMENTS)
