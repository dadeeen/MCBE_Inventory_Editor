import pytest
import unittest

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor import _inventory_core as inventory_core
from mcbe_editor.item_data import ENCHANTMENTS
from mcbe_editor.inventory import (
    ENDER_CHEST_SLOTS,
    MAX_DAMAGE,
    MAX_LORE_LINES,
    MAX_TEXT_LENGTH,
    apply_abilities,
    apply_editable_item_tags,
    apply_effects,
    apply_player_stats,
    build_ender_chest_nbt,
    build_inventory_nbt,
    count_hidden_unknown_slots,
    extract_player_stats,
    nbt_to_json,
    parse_abilities,
    parse_effects,
    parse_ender_chest,
    protected_player_nbt_flags,
    validate_effect,
    validate_inventory_item,
)
from tests.conftest import make_full_player_tag, make_minimal_player_tag


class TestNbtToJson(unittest.TestCase):
    def test_empty_inventory_returns_empty_dicts(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        inv, orig = nbt_to_json(player)
        self.assertEqual(inv, {})
        self.assertEqual(orig, {})

    def test_parses_basic_item(self):
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
                            }
                        )
                    ]
                )
            }
        )
        inv, orig = nbt_to_json(player)
        self.assertIn(0, inv)
        self.assertEqual(inv[0]["name"], "minecraft:stone")
        self.assertEqual(inv[0]["count"], 1)
        self.assertEqual(inv[0]["damage"], 0)
        self.assertEqual(inv[0]["nbt_view"]["type"], "CompoundTag")
        self.assertEqual(inv[0]["nbt_view"]["value"]["Name"], {"type": "StringTag", "value": "minecraft:stone"})

    def test_extracts_axolotl_bucket_entity_variant_from_color_id(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "ActorIdentifier": nbt.StringTag("minecraft:axolotl<>"),
                                        "ColorID": nbt.IntTag(2),
                                        "IsBaby": nbt.ByteTag(0),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inv, _orig = nbt_to_json(player)

        self.assertFalse(inv[0]["has_protected_nbt"])
        self.assertTrue(inv[0]["has_preserved_nbt"])
        self.assertEqual(
            inv[0]["entity_variant"],
            {
                "entity_id": "minecraft:axolotl",
                "variant": 2,
                "key": "gold",
                "kind_label_de": "Entity-Variante",
                "kind_label_en": "Entity variant",
                "value_label_de": "Axolotl-Datenwert",
                "value_label_en": "Axolotl data value",
                "label_de": "Gold",
                "label_en": "Gold",
                "display_name_de": "Gold-Axolotl",
                "display_name_en": "Gold Axolotl",
                "icon_key": "mcbe:axolotl_gold",
                "adult_icon_key": "mcbe:axolotl_gold",
                "baby_icon_key": "mcbe:axolotl_gold_baby",
                "is_baby": False,
                "source": "ColorID",
                "can_edit": True,
            },
        )

    def test_extracts_real_world_axolotl_bucket_shape(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "identifier": nbt.StringTag("minecraft:axolotl"),
                                        "Variant": nbt.IntTag(1),
                                        "ColorID": nbt.StringTag("item.axolotlColorCyan.name"),
                                        "BodyID": nbt.StringTag("item.axolotlAdultBodySingle.name"),
                                        "IsBaby": nbt.ByteTag(0),
                                        "definitions": nbt.ListTag(
                                            [
                                                nbt.StringTag("+minecraft:axolotl"),
                                                nbt.StringTag("+axolotl_adult"),
                                                nbt.StringTag("+axolotl_cyan"),
                                                nbt.StringTag("-axolotl_in_water"),
                                            ]
                                        ),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)

        self.assertEqual(inventory[0]["entity_variant"]["variant"], 1)
        self.assertEqual(inventory[0]["entity_variant"]["display_name_de"], "Türkiser Axolotl")
        self.assertEqual(inventory[0]["entity_variant"]["display_name_en"], "Cyan Axolotl")
        self.assertTrue(inventory[0]["entity_variant"]["can_edit"])

    def test_rejects_a_bucket_variant_with_a_conflicting_actor_identifier(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "ActorIdentifier": nbt.StringTag("minecraft:tropicalfish<>"),
                                        "Variant": nbt.IntTag(4),
                                        "IsBaby": nbt.ByteTag(0),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)

        self.assertIsNone(inventory[0]["entity_variant"])

    def test_extracts_baby_axolotl_entity_variant_from_nested_save_data(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(1),
                                "Name": nbt.StringTag("minecraft:bucketaxolotl"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "Variant": nbt.IntTag(0),
                                        "IsBaby": nbt.ByteTag(0),
                                        "SaveData": nbt.CompoundTag(
                                            {
                                                "identifier": nbt.StringTag("minecraft:axolotl"),
                                                "Variant": nbt.IntTag(4),
                                                "IsBaby": nbt.ByteTag(1),
                                            }
                                        ),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inv, _orig = nbt_to_json(player)

        self.assertEqual(inv[1]["entity_variant"]["display_name_de"], "Blauer Axolotl")
        self.assertEqual(inv[1]["entity_variant"]["icon_key"], "mcbe:axolotl_blue_baby")
        self.assertTrue(inv[1]["entity_variant"]["is_baby"])

    def test_extracts_tropical_fish_bucket_variant_fields(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(2),
                                "Name": nbt.StringTag("minecraft:buckettropical"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "AppendCustomName": nbt.ByteTag(1),
                                        "BodyID": nbt.StringTag("tropicalSchoolClownfish"),
                                        "ColorID": nbt.StringTag("tropicalColorOrange"),
                                        "Color2ID": nbt.StringTag("tropicalColorWhite"),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inv, _orig = nbt_to_json(player)

        self.assertFalse(inv[2]["has_protected_nbt"])
        self.assertTrue(inv[2]["has_preserved_nbt"])
        self.assertEqual(inv[2]["entity_variant"]["entity_id"], "minecraft:tropical_fish")
        self.assertEqual(inv[2]["entity_variant"]["key"], "clownfish_orange_white")
        self.assertEqual(inv[2]["entity_variant"]["kind_label_de"], "Tropenfisch-Bucket")
        self.assertEqual(inv[2]["entity_variant"]["display_name_de"], "Tropenfisch: Clownfisch, Orange/Weiß")
        self.assertEqual(inv[2]["entity_variant"]["source"], "BodyID, ColorID, Color2ID")
        self.assertEqual(
            [(field["key"], field["display_de"], field["raw"]) for field in inv[2]["entity_variant"]["fields"]],
            [
                ("BodyID", "Clownfisch", "tropicalSchoolClownfish"),
                ("ColorID", "Orange", "tropicalColorOrange"),
                ("Color2ID", "Weiß", "tropicalColorWhite"),
            ],
        )
        self.assertFalse(inv[2]["entity_variant"]["can_edit"])
        self.assertEqual(
            (
                inv[2]["entity_variant"]["variant"],
                inv[2]["entity_variant"]["mark_variant"],
                inv[2]["entity_variant"]["color"],
                inv[2]["entity_variant"]["color2"],
            ),
            (0, 0, 1, 0),
        )

    def test_resolves_dottyback_group_only_preset(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(3),
                                "Name": nbt.StringTag("minecraft:tropical_fish_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "GroupName": nbt.StringTag("item.tropicalSchoolDottyback.name"),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)
        variant = inventory[3]["entity_variant"]

        self.assertEqual(variant["display_name_de"], "Tropenfisch: Zwergbarsch, Pflaumenblau/Gelb")
        self.assertEqual(variant["display_name_en"], "Tropical Fish: Dottyback, Plum/Yellow")
        self.assertEqual(
            (variant["variant"], variant["mark_variant"], variant["color"], variant["color2"]),
            (1, 3, 10, 4),
        )
        self.assertFalse(variant["can_edit"])

    def test_vanilla_tropical_fish_presets_have_unique_canonical_language_tokens(self):
        self.assertEqual(
            set(inventory_core.TROPICAL_FISH_PRESET_VALUES),
            set(inventory_core.TROPICAL_FISH_GROUP_LANG_TOKEN_BY_KEY),
        )
        self.assertEqual(
            len(set(inventory_core.TROPICAL_FISH_PRESET_VALUES.values())),
            len(inventory_core.TROPICAL_FISH_PRESET_VALUES),
        )
        self.assertEqual(
            inventory_core.TROPICAL_FISH_GROUP_LANG_TOKEN_BY_KEY["yellowtang"],
            "YellowTang",
        )
        self.assertEqual(
            inventory_core.TROPICAL_FISH_GROUP_LANG_TOKEN_BY_KEY["yellowtailparrot"],
            "YellowtailParrot",
        )

    def test_incomplete_dasher_display_uses_body_id_shape_instead_of_none_colors(self):
        entries = []
        for slot, shape in enumerate(("Single", "Multi")):
            entries.append(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(slot),
                        "Name": nbt.StringTag("minecraft:tropical_fish_bucket"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                        "tag": nbt.CompoundTag(
                            {
                                "BodyID": nbt.StringTag(f"item.tropicalBodyDasher{shape}.name"),
                            }
                        ),
                    }
                )
            )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag(entries)})

        inventory, _original = nbt_to_json(player)

        self.assertEqual(inventory[0]["entity_variant"]["display_name_de"], "Tropenfisch: Dasher")
        self.assertEqual(inventory[1]["entity_variant"]["display_name_de"], "Tropenfisch: Flitzer")

    def test_extracts_axolotl_variant_from_current_language_keys(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(4),
                                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "ActorIdentifier": nbt.StringTag("minecraft:axolotl"),
                                        "ColorID": nbt.StringTag("item.axolotlColorBlue.name"),
                                        "BodyID": nbt.StringTag("item.axolotlAdultBodySingle.name"),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)

        self.assertEqual(inventory[4]["entity_variant"]["variant"], 4)
        self.assertEqual(inventory[4]["entity_variant"]["display_name_en"], "Blue Axolotl")
        self.assertFalse(inventory[4]["entity_variant"]["is_baby"])
        self.assertFalse(inventory[4]["entity_variant"]["can_edit"])

    def test_accepts_namespaceless_and_spaced_axolotl_actor_identifiers(self):
        for actor_identifier in ("axolotl", "minecraft:axolotl <legacy-data>"):
            with self.subTest(actor_identifier=actor_identifier):
                player = nbt.CompoundTag(
                    {
                        "Inventory": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "Slot": nbt.ByteTag(0),
                                        "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                        "Count": nbt.ByteTag(1),
                                        "Damage": nbt.ShortTag(0),
                                        "tag": nbt.CompoundTag(
                                            {
                                                "identifier": nbt.StringTag(actor_identifier),
                                                "Variant": nbt.IntTag(4),
                                                "IsBaby": nbt.ByteTag(0),
                                            }
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                )

                inventory, _original = nbt_to_json(player)

                self.assertEqual(inventory[0]["entity_variant"]["variant"], 4)
                self.assertTrue(inventory[0]["entity_variant"]["can_edit"])

    def test_ignores_non_string_actor_id_metadata(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "id": nbt.IntTag(12),
                                        "Variant": nbt.IntTag(2),
                                        "IsBaby": nbt.ByteTag(0),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)

        self.assertEqual(inventory[0]["entity_variant"]["variant"], 2)
        self.assertTrue(inventory[0]["entity_variant"]["can_edit"])

    def test_does_not_treat_numeric_looking_axolotl_values_as_integer_state(self):
        for variant_tag in (nbt.StringTag("4"), nbt.FloatTag(4.0)):
            with self.subTest(tag_type=type(variant_tag).__name__):
                player = nbt.CompoundTag(
                    {
                        "Inventory": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "Slot": nbt.ByteTag(0),
                                        "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                        "Count": nbt.ByteTag(1),
                                        "Damage": nbt.ShortTag(0),
                                        "tag": nbt.CompoundTag(
                                            {
                                                "Variant": variant_tag,
                                                "IsBaby": nbt.ByteTag(0),
                                            }
                                        ),
                                    }
                                )
                            ]
                        )
                    }
                )

                inventory, _original = nbt_to_json(player)

                self.assertIsNone(inventory[0]["entity_variant"])

    def test_deeper_malformed_axolotl_numeric_state_does_not_fall_back_to_outer_values(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "Variant": nbt.IntTag(2),
                                        "IsBaby": nbt.ByteTag(0),
                                        "SaveData": nbt.CompoundTag(
                                            {
                                                "Variant": nbt.FloatTag(4.0),
                                                "IsBaby": nbt.ByteTag(1),
                                            }
                                        ),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)

        self.assertIsNone(inventory[0]["entity_variant"])

    def test_invalid_axolotl_numeric_state_still_uses_language_key_for_read_only_label(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "Variant": nbt.IntTag(99),
                                        "ColorID": nbt.StringTag("item.axolotlColorBlue.name"),
                                        "BodyID": nbt.StringTag("item.axolotlAdultBodySingle.name"),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)

        self.assertEqual(inventory[0]["entity_variant"]["variant"], 4)
        self.assertEqual(inventory[0]["entity_variant"]["display_name_en"], "Blue Axolotl")
        self.assertEqual(inventory[0]["entity_variant"]["source"], "ColorID")
        self.assertFalse(inventory[0]["entity_variant"]["can_edit"])

    def test_extracts_editable_tropical_fish_variant_from_numeric_save_data(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(5),
                                "Name": nbt.StringTag("minecraft:tropical_fish_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "SaveData": nbt.CompoundTag(
                                            {
                                                "identifier": nbt.StringTag("minecraft:tropical_fish"),
                                                "Variant": nbt.IntTag(1),
                                                "MarkVariant": nbt.IntTag(3),
                                                "Color": nbt.ByteTag(14),
                                                "Color2": nbt.ByteTag(0),
                                            }
                                        )
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)
        variant = inventory[5]["entity_variant"]

        self.assertTrue(variant["can_edit"])
        self.assertEqual(
            (variant["variant"], variant["mark_variant"], variant["color"], variant["color2"]),
            (1, 3, 14, 0),
        )
        self.assertEqual(variant["display_name_en"], "Tropical Fish: Blockfish, Red/White")

    def test_deeper_malformed_tropical_fish_state_does_not_fall_back_to_outer_values(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:tropical_fish_bucket"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "Variant": nbt.IntTag(0),
                                        "MarkVariant": nbt.IntTag(0),
                                        "Color": nbt.ByteTag(1),
                                        "Color2": nbt.ByteTag(0),
                                        "SaveData": nbt.CompoundTag(
                                            {
                                                "Color": nbt.FloatTag(4.0),
                                            }
                                        ),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inventory, _original = nbt_to_json(player)

        self.assertIsNone(inventory[0]["entity_variant"])

    def test_flags_unknown_enchantments_but_only_exposes_known_ones(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:diamond_sword"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "ench": nbt.ListTag(
                                            [
                                                nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(3)}),
                                                nbt.CompoundTag({"id": nbt.ShortTag(999), "lvl": nbt.ShortTag(1)}),
                                            ]
                                        )
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )
        inv, _orig = nbt_to_json(player)
        self.assertEqual(inv[0]["enchantments"], [{"id": 9, "lvl": 3}])
        self.assertTrue(inv[0]["has_unknown_enchantments"])

    def test_reads_damageable_item_damage_from_item_tag(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:iron_sword"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag({"Damage": nbt.IntTag(7)}),
                            }
                        )
                    ]
                )
            }
        )
        inv, _orig = nbt_to_json(player)
        self.assertEqual(inv[0]["damage"], 7)
        self.assertFalse(inv[0]["has_protected_nbt"])

    def test_standard_bedrock_block_item_snapshot_is_not_protected_nbt(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(20),
                                "Name": nbt.StringTag("minecraft:cornflower"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "WasPickedUp": nbt.ByteTag(0),
                                "Block": nbt.CompoundTag(
                                    {
                                        "name": nbt.StringTag("minecraft:cornflower"),
                                        "states": nbt.CompoundTag({}),
                                        "version": nbt.IntTag(18168865),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inv, _orig = nbt_to_json(player)

        self.assertFalse(inv[20]["has_protected_nbt"])
        self.assertTrue(inv[20]["has_preserved_nbt"])
        self.assertEqual(inv[20]["protected_nbt_summary"], [])
        self.assertEqual(inv[20]["preserved_nbt_summary"], ["Standard-Root-Felder: Block"])
        self.assertEqual(inv[20]["nbt_view"]["value"]["Block"]["value"]["name"]["value"], "minecraft:cornflower")

    def test_standard_bedrock_block_item_snapshot_is_preserved_on_save(self):
        original_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(20),
                "Name": nbt.StringTag("minecraft:cornflower"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "WasPickedUp": nbt.ByteTag(0),
                "Block": nbt.CompoundTag(
                    {
                        "name": nbt.StringTag("minecraft:cornflower"),
                        "states": nbt.CompoundTag({}),
                        "version": nbt.IntTag(18168865),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original_item])})

        saved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 20,
                    "source_slot": 20,
                    "name": "minecraft:cornflower",
                    "count": 2,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual(saved[0]["Count"].py_data, 2)
        self.assertIn("Block", saved[0])
        self.assertEqual(saved[0]["Block"]["name"].py_data, "minecraft:cornflower")
        self.assertEqual(saved[0]["Block"]["version"].py_data, 18168865)

    def test_standard_itemstack_root_metadata_is_preserved_not_protected(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(2),
                                "Name": nbt.StringTag("minecraft:stone"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "CanDestroy": nbt.ListTag([nbt.StringTag("minecraft:dirt")]),
                                "CanPlaceOn": nbt.ListTag([nbt.StringTag("minecraft:grass")]),
                            }
                        )
                    ]
                )
            }
        )

        inv, _orig = nbt_to_json(player)

        self.assertFalse(inv[2]["has_protected_nbt"])
        self.assertTrue(inv[2]["has_preserved_nbt"])
        self.assertEqual(inv[2]["protected_nbt_summary"], [])
        self.assertIn("Standard-Root-Felder: CanDestroy, CanPlaceOn", inv[2]["preserved_nbt_summary"])

    def test_known_filled_map_tag_metadata_is_preserved_not_protected(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(12),
                                "Name": nbt.StringTag("minecraft:filled_map"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(10),
                                "tag": nbt.CompoundTag(
                                    {
                                        "map_display_players": nbt.ByteTag(1),
                                        "map_uuid": nbt.LongTag(-386546980069),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )

        inv, _orig = nbt_to_json(player)

        self.assertFalse(inv[12]["has_protected_nbt"])
        self.assertTrue(inv[12]["has_preserved_nbt"])
        self.assertEqual(inv[12]["protected_nbt_summary"], [])
        self.assertEqual(inv[12]["preserved_nbt_summary"], ["Bekannte Item-tag-Felder: map_display_players, map_uuid"])

    def test_repair_cost_metadata_is_preserved_not_protected(self):
        original_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(6),
                "Name": nbt.StringTag("minecraft:bow"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "WasPickedUp": nbt.ByteTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "Damage": nbt.IntTag(0),
                        "RepairCost": nbt.IntTag(3),
                        "ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(17), "lvl": nbt.ShortTag(3)})]),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original_item])})

        inv, _orig = nbt_to_json(player)

        self.assertFalse(inv[6]["has_protected_nbt"])
        self.assertTrue(inv[6]["has_preserved_nbt"])
        self.assertEqual(inv[6]["protected_nbt_summary"], [])
        self.assertEqual(inv[6]["preserved_nbt_summary"], ["Bekannte Item-tag-Felder: RepairCost"])

        saved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 6,
                    "source_slot": 6,
                    "name": "minecraft:bow",
                    "count": 1,
                    "damage": 4,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [{"id": 17, "lvl": 3}],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual(saved[0]["tag"]["Damage"].py_data, 4)
        self.assertEqual(saved[0]["tag"]["RepairCost"].py_data, 3)

    def test_save_rejects_preserved_item_nbt_when_original_source_is_missing(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        with self.assertRaisesRegex(ValueError, "erhaltene Item-NBT-Daten"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 12,
                        "name": "minecraft:filled_map",
                        "count": 1,
                        "damage": 10,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [],
                        "has_preserved_nbt": True,
                    }
                ],
                ENCHANTMENTS,
            )

    def test_summarizes_protected_item_nbt_categories(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:diamond_sword"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "FutureRootField": nbt.StringTag("root"),
                                "tag": nbt.CompoundTag(
                                    {
                                        "FutureTagField": nbt.StringTag("tag"),
                                        "display": nbt.CompoundTag(
                                            {
                                                "Name": nbt.StringTag("Sword"),
                                                "Color": nbt.IntTag(123),
                                            }
                                        ),
                                        "ench": nbt.ListTag(
                                            [
                                                nbt.CompoundTag(
                                                    {
                                                        "id": nbt.ShortTag(9),
                                                        "lvl": nbt.ShortTag(3),
                                                        "FutureEnchantField": nbt.StringTag("extra"),
                                                    }
                                                )
                                            ]
                                        ),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )
        inv, _orig = nbt_to_json(player)
        self.assertTrue(inv[0]["has_protected_nbt"])
        self.assertEqual(
            inv[0]["protected_nbt_summary"],
            [
                "Root-Felder: FutureRootField",
                "Item-tag-Felder: FutureTagField",
                "Display-Felder: Color",
                "1 Verzauberungseintrag/Einträge mit Zusatzfeldern",
            ],
        )
        self.assertEqual(inv[0]["nbt_view"]["value"]["FutureRootField"], {"type": "StringTag", "value": "root"})
        self.assertEqual(inv[0]["nbt_view"]["value"]["tag"]["value"]["FutureTagField"], {"type": "StringTag", "value": "tag"})

    def test_entity_state_keys_are_only_known_metadata_on_entity_variant_items(self):
        ordinary_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "Color": nbt.ByteTag(1),
                        "Color2": nbt.ByteTag(2),
                        "MarkVariant": nbt.IntTag(3),
                    }
                ),
            }
        )
        fish_bucket = ordinary_item.copy()
        fish_bucket["Slot"] = nbt.ByteTag(1)
        fish_bucket["Name"] = nbt.StringTag("minecraft:tropical_fish_bucket")
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([ordinary_item, fish_bucket])})

        inventory, _original = nbt_to_json(player)

        self.assertTrue(inventory[0]["has_protected_nbt"])
        self.assertIn("Item-tag-Felder: Color, Color2, MarkVariant", inventory[0]["protected_nbt_summary"])
        self.assertFalse(inventory[1]["has_protected_nbt"])
        self.assertTrue(inventory[1]["has_preserved_nbt"])

    def test_extracts_display_name_and_lore(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:diamond_sword"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "display": nbt.CompoundTag(
                                            {
                                                "Name": nbt.StringTag("§bExcalibur"),
                                                "Lore": nbt.ListTag([nbt.StringTag("Line1"), nbt.StringTag("Line2")]),
                                            }
                                        ),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )
        inv, _orig = nbt_to_json(player)
        self.assertEqual(inv[0]["display_name"], "§bExcalibur")
        self.assertEqual(inv[0]["lore"], ["Line1", "Line2"])

    def test_extracts_legacy_enchantments(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(0),
                                "Name": nbt.StringTag("minecraft:diamond_sword"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                                "tag": nbt.CompoundTag(
                                    {
                                        "ench": nbt.ListTag(
                                            [
                                                nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(3)}),
                                                nbt.CompoundTag({"id": nbt.ShortTag(17), "lvl": nbt.ShortTag(2)}),
                                            ]
                                        ),
                                    }
                                ),
                            }
                        )
                    ]
                )
            }
        )
        inv, _orig = nbt_to_json(player)
        self.assertEqual(inv[0]["enchantments"], [{"id": 9, "lvl": 3}, {"id": 17, "lvl": 2}])

    def test_rejects_new_enchantments_on_non_enchantable_item(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        with self.assertRaisesRegex(ValueError, "nicht verzauberbar"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:wool",
                        "count": 1,
                        "damage": 0,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [{"id": 9, "lvl": 1}],
                    }
                ],
                ENCHANTMENTS,
            )

    def test_preserves_existing_unusual_enchantments_on_non_enchantable_item(self):
        original_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:wool"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(1)})])}),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original_item])})
        inv, _orig = nbt_to_json(player)
        payload = dict(inv[0])
        payload["count"] = 2

        saved = build_inventory_nbt(player, [payload], ENCHANTMENTS)

        self.assertEqual(saved[0]["Count"].py_data, 2)
        self.assertEqual(saved[0]["tag"]["ench"][0]["id"].py_data, 9)
        self.assertEqual(saved[0]["tag"]["ench"][0]["lvl"].py_data, 1)

    def test_rejects_incompatible_enchantment_for_enchantable_item(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        with self.assertRaisesRegex(ValueError, "passen nicht"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:diamond_sword",
                        "count": 1,
                        "damage": 0,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [{"id": 19, "lvl": 1}],
                    }
                ],
                ENCHANTMENTS,
            )

    def test_accepts_compatible_enchantment_for_item_type(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        saved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:diamond_axe",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [{"id": 9, "lvl": 1}],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual(saved[0]["tag"]["ench"][0]["id"].py_data, 9)

    def test_accepts_unbreaking_for_golden_sword(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        saved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:golden_sword",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [{"id": 17, "lvl": 3}],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual(saved[0]["tag"]["ench"][0]["id"].py_data, 17)
        self.assertEqual(saved[0]["tag"]["ench"][0]["lvl"].py_data, 3)

    def test_accepts_melee_spear_enchantments(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        saved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:copper_spear",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [{"id": 9, "lvl": 5}, {"id": 17, "lvl": 3}, {"id": 41, "lvl": 3}],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual([ench["id"].py_data for ench in saved[0]["tag"]["ench"]], [9, 17, 41])

    def test_rejects_trident_only_enchantments_for_melee_spear(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        with self.assertRaisesRegex(ValueError, "passen nicht"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:copper_spear",
                        "count": 1,
                        "damage": 0,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [{"id": 31, "lvl": 1}],
                    }
                ],
                ENCHANTMENTS,
            )

    def test_accepts_curses_for_cosmetic_head_items(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        saved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:carved_pumpkin",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [{"id": 27, "lvl": 1}, {"id": 28, "lvl": 1}],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual([ench["id"].py_data for ench in saved[0]["tag"]["ench"]], [27, 28])

    def test_accepts_mace_and_compass_wiki_compatible_enchantments(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        saved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:mace",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [{"id": 13, "lvl": 1}, {"id": 26, "lvl": 1}],
                },
                {
                    "slot": 1,
                    "name": "minecraft:recovery_compass",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [{"id": 28, "lvl": 1}],
                },
            ],
            ENCHANTMENTS,
        )

        by_slot = {item["Slot"].py_data: item for item in saved}
        self.assertEqual([ench["id"].py_data for ench in by_slot[0]["tag"]["ench"]], [13, 26])
        self.assertEqual(by_slot[1]["tag"]["ench"][0]["id"].py_data, 28)

    def test_preserves_existing_incompatible_enchantment_for_normal_save(self):
        original_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(19), "lvl": nbt.ShortTag(1)})])}),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original_item])})
        inv, _orig = nbt_to_json(player)
        payload = dict(inv[0])
        payload["damage"] = 1

        saved = build_inventory_nbt(player, [payload], ENCHANTMENTS)

        self.assertEqual(saved[0]["tag"]["Damage"].py_data, 1)
        self.assertEqual(saved[0]["tag"]["ench"][0]["id"].py_data, 19)

    def test_no_tag_compound_returns_empty_fields(self):
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
                            }
                        )
                    ]
                )
            }
        )
        inv, _orig = nbt_to_json(player)
        self.assertEqual(inv[0]["display_name"], "")
        self.assertEqual(inv[0]["lore"], [])
        self.assertEqual(inv[0]["enchantments"], [])

    def test_no_inventory_tag_returns_empty(self):
        player = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.DoubleTag(0.0)])})
        inv, orig = nbt_to_json(player)
        self.assertEqual(inv, {})
        self.assertEqual(orig, {})

    def test_original_items_preserves_references(self):
        raw_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([raw_item])})
        _inv, orig = nbt_to_json(player)
        self.assertIs(orig[0], raw_item)

    def test_counts_hidden_unknown_inventory_and_ender_slots(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1)}),
                        nbt.CompoundTag({"Slot": nbt.IntTag(200), "Name": nbt.StringTag("minecraft:future_item"), "Count": nbt.ByteTag(1)}),
                    ]
                ),
                "EnderChestInventory": nbt.ListTag(
                    [
                        nbt.CompoundTag({"Slot": nbt.ByteTag(5), "Name": nbt.StringTag("minecraft:diamond"), "Count": nbt.ByteTag(1)}),
                        nbt.CompoundTag({"Slot": nbt.IntTag(99), "Name": nbt.StringTag("minecraft:future_chest"), "Count": nbt.ByteTag(1)}),
                    ]
                ),
            }
        )

        self.assertEqual(
            count_hidden_unknown_slots(player),
            {
                "inventory": 1,
                "ender_chest": 1,
                "inventory_protected_known": 0,
                "ender_chest_protected_known": 0,
                "inventory_protected_known_slots": [],
                "ender_chest_protected_known_slots": [],
                "inventory_opaque": False,
                "ender_chest_opaque": False,
            },
        )

    def test_reports_present_root_item_lists_without_counting_empty_placeholders(self):
        player = nbt.CompoundTag(
            {
                "Armor": nbt.ListTag(
                    [
                        nbt.CompoundTag({"Name": nbt.StringTag("minecraft:air"), "Count": nbt.ByteTag(0)}),
                        nbt.CompoundTag({"Name": nbt.StringTag("minecraft:diamond_helmet"), "Count": nbt.ByteTag(1)}),
                    ]
                ),
                "Offhand": nbt.ListTag([nbt.CompoundTag({"Count": nbt.ByteTag(0)})]),
                "PlayerUIItems": nbt.ListTag([nbt.CompoundTag({"FuturePayload": nbt.StringTag("keep")})]),
            }
        )

        flags = protected_player_nbt_flags(player)

        self.assertEqual(flags["root_item_lists_present"], {"Armor": 1, "PlayerUIItems": 1})
        self.assertEqual(flags["root_item_lists_opaque"], {})

    def test_reports_opaque_root_item_lists(self):
        player = nbt.CompoundTag({"Armor": nbt.StringTag("future-armor")})

        flags = protected_player_nbt_flags(player)

        self.assertEqual(flags["root_item_lists_present"], {})
        self.assertEqual(flags["root_item_lists_opaque"], {"Armor": True})

    def test_hides_unknown_inventory_slots_but_keeps_original_reference(self):
        unknown_item = nbt.CompoundTag(
            {
                "Slot": nbt.IntTag(200),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([unknown_item])})
        inv, orig = nbt_to_json(player)
        self.assertNotIn(200, inv)
        self.assertIs(orig[200], unknown_item)


class TestExtractPlayerStats(unittest.TestCase):
    def test_extracts_all_stats_from_complete_tag(self):
        tag = make_full_player_tag()
        stats = extract_player_stats(tag)
        self.assertEqual(stats["pos"], [0.0, 64.0, 0.0])
        self.assertIsNone(stats["dimension_id"])
        self.assertEqual(stats["health"], 20.0)
        self.assertEqual(stats["gamemode"], 0)
        self.assertEqual(stats["xp_level"], 5)
        self.assertEqual(stats["xp_progress"], 0.5)
        self.assertEqual(stats["food_level"], 18)
        self.assertEqual(stats["food_saturation"], 15.0)

    def test_extracts_bedrock_player_level_aliases(self):
        tag = make_minimal_player_tag()
        tag["PlayerLevel"] = nbt.IntTag(12)
        tag["PlayerLevelProgress"] = nbt.FloatTag(0.6)
        stats = extract_player_stats(tag)
        self.assertEqual(stats["xp_level"], 12)
        self.assertAlmostEqual(stats["xp_progress"], 0.6)

    def test_extracts_stats_from_attributes_when_root_tags_are_missing(self):
        tag = make_minimal_player_tag()
        tag["Attributes"] = nbt.ListTag(
            [
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.level"), "Current": nbt.FloatTag(9.0)}),
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.experience"), "Current": nbt.FloatTag(0.4)}),
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.hunger"), "Current": nbt.FloatTag(16.0)}),
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.saturation"), "Current": nbt.FloatTag(6.5)}),
            ]
        )
        stats = extract_player_stats(tag)
        self.assertEqual(stats["xp_level"], 9)
        self.assertAlmostEqual(stats["xp_progress"], 0.4)
        self.assertEqual(stats["food_level"], 16)
        self.assertAlmostEqual(stats["food_saturation"], 6.5)

    def test_defaults_for_missing_tags(self):
        tag = nbt.CompoundTag()
        stats = extract_player_stats(tag)
        self.assertEqual(stats["pos"], [0.0, 70.0, 0.0])
        self.assertIsNone(stats["dimension_id"])
        self.assertEqual(stats["health"], 20.0)
        self.assertEqual(stats["gamemode"], 0)
        self.assertEqual(stats["xp_level"], 0)
        self.assertEqual(stats["xp_progress"], 0.0)
        self.assertEqual(stats["food_level"], 20)
        self.assertEqual(stats["food_saturation"], 20.0)

    def test_handles_float_parsing(self):
        tag = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(2.5), nbt.DoubleTag(3.5)]),
            }
        )
        stats = extract_player_stats(tag)
        self.assertEqual(stats["pos"], [1.5, 2.5, 3.5])

    def test_extracts_vanilla_dimension_id(self):
        tag = make_minimal_player_tag()
        tag["DimensionId"] = nbt.IntTag(1)

        stats = extract_player_stats(tag)

        self.assertEqual(stats["dimension_id"], 1)
        flags = protected_player_nbt_flags(tag)
        self.assertFalse(flags["dimension_id_missing"])
        self.assertFalse(flags["dimension_id_opaque"])


class TestApplyEditableItemTags(unittest.TestCase):
    def make_item(self, tag_comp=None):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        if tag_comp is not None:
            item["tag"] = tag_comp
        return item

    def test_sets_display_name(self):
        item = self.make_item(nbt.CompoundTag({"display": nbt.CompoundTag({})}))
        apply_editable_item_tags(item, {"display_name": "Custom", "lore": [], "enchantments": []})
        self.assertEqual(item["tag"]["display"]["Name"].py_data, "Custom")

    def test_removes_display_name_but_keeps_tag_with_other_data(self):
        item = self.make_item(
            nbt.CompoundTag(
                {
                    "display": nbt.CompoundTag({"Name": nbt.StringTag("Old")}),
                    "otherData": nbt.StringTag("keep"),
                }
            )
        )
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertIn("tag", item)
        self.assertEqual(item["tag"]["otherData"].py_data, "keep")

    def test_sets_lore(self):
        item = self.make_item(nbt.CompoundTag({"display": nbt.CompoundTag({})}))
        apply_editable_item_tags(item, {"display_name": "", "lore": ["L1", "L2"], "enchantments": []})
        lore = item["tag"]["display"]["Lore"]
        self.assertEqual([x.py_data for x in lore], ["L1", "L2"])

    def test_removes_lore_but_keeps_tag_with_other_data(self):
        item = self.make_item(
            nbt.CompoundTag(
                {
                    "display": nbt.CompoundTag({"Lore": nbt.ListTag([nbt.StringTag("Old")])}),
                    "otherData": nbt.StringTag("keep"),
                }
            )
        )
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertIn("tag", item)
        self.assertEqual(item["tag"]["otherData"].py_data, "keep")

    def test_keeps_a_display_compound_that_was_already_empty(self):
        """An empty display the user never filled is not something they removed.

        Deleting it here would contradict the item-level skip, which keeps exactly
        this input byte-identical when nothing changed.
        """

        item = self.make_item(
            nbt.CompoundTag(
                {
                    "display": nbt.CompoundTag({}),
                    "otherData": nbt.StringTag("keep"),
                }
            )
        )
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertIn("display", item["tag"])
        self.assertEqual(len(item["tag"]["display"]), 0)
        self.assertEqual(item["tag"]["otherData"].py_data, "keep")

    def test_removes_display_compound_after_a_real_removal(self):
        item = self.make_item(
            nbt.CompoundTag(
                {
                    "display": nbt.CompoundTag({"Name": nbt.StringTag("Alt")}),
                    "otherData": nbt.StringTag("keep"),
                }
            )
        )
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertIn("tag", item)
        self.assertNotIn("display", item["tag"])
        self.assertEqual(item["tag"]["otherData"].py_data, "keep")

    def test_preserves_unknown_display_metadata_when_name_and_lore_empty(self):
        item = self.make_item(
            nbt.CompoundTag(
                {
                    "display": nbt.CompoundTag(
                        {
                            "Name": nbt.StringTag("Old"),
                            "Color": nbt.IntTag(12345),
                        }
                    ),
                }
            )
        )
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertIn("display", item["tag"])
        self.assertNotIn("Name", item["tag"]["display"])
        self.assertEqual(item["tag"]["display"]["Color"].py_data, 12345)

    def test_creates_tag_when_missing(self):
        item = self.make_item(None)
        apply_editable_item_tags(item, {"display_name": "Name", "lore": [], "enchantments": []})
        self.assertIn("tag", item)
        self.assertEqual(item["tag"]["display"]["Name"].py_data, "Name")

    def test_preserves_tag_with_non_editable_data_when_editable_fields_empty(self):
        item = self.make_item(nbt.CompoundTag({"someOther": nbt.StringTag("keep")}))
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertIn("tag", item)
        self.assertEqual(item["tag"]["someOther"].py_data, "keep")

    def test_writes_legacy_ench_format(self):
        item = self.make_item(nbt.CompoundTag({}))
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": [{"id": 9, "lvl": 3}]})
        ench = item["tag"]["ench"]
        self.assertEqual(len(ench), 1)
        self.assertEqual(ench[0]["id"].py_data, 9)
        self.assertEqual(ench[0]["lvl"].py_data, 3)

    def test_preserves_existing_enchantment_tag_family(self):
        item = self.make_item(nbt.CompoundTag({"enchantments": nbt.ListTag([nbt.CompoundTag({"id": nbt.StringTag("9"), "lvl": nbt.ShortTag(3)})])}))
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": [{"id": 9, "lvl": 3}]})
        self.assertNotIn("ench", item["tag"])
        self.assertIn("enchantments", item["tag"])
        self.assertEqual(len(item["tag"]["enchantments"]), 1)
        # The level is unchanged, so the entry is not rebuilt at all. A malformed
        # string ID stays as it was found instead of being silently normalized.
        self.assertEqual(item["tag"]["enchantments"][0]["id"].py_data, "9")
        self.assertEqual(item["tag"]["enchantments"][0]["lvl"].py_data, 3)

    def test_editing_a_string_id_enchantment_normalizes_it(self):
        item = self.make_item(nbt.CompoundTag({"enchantments": nbt.ListTag([nbt.CompoundTag({"id": nbt.StringTag("9"), "lvl": nbt.ShortTag(3)})])}))
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": [{"id": 9, "lvl": 4}]})
        self.assertIn("enchantments", item["tag"])
        self.assertEqual(item["tag"]["enchantments"][0]["id"].py_data, 9)
        self.assertEqual(item["tag"]["enchantments"][0]["lvl"].py_data, 4)

    def test_removes_ench_when_empty_but_keeps_tag_with_other_data(self):
        item = self.make_item(
            nbt.CompoundTag(
                {
                    "ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(3)})]),
                    "otherData": nbt.StringTag("keep"),
                }
            )
        )
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertIn("tag", item)
        self.assertNotIn("ench", item["tag"])
        self.assertEqual(item["tag"]["otherData"].py_data, "keep")

    def test_preserves_unknown_tags(self):
        item = self.make_item(nbt.CompoundTag({"customData": nbt.StringTag("keep-me")}))
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []})
        self.assertEqual(item["tag"]["customData"].py_data, "keep-me")

    def test_preserves_unknown_enchantments_when_known_enchantments_are_cleared(self):
        item = self.make_item(
            nbt.CompoundTag(
                {
                    "ench": nbt.ListTag(
                        [
                            nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(3)}),
                            nbt.CompoundTag({"id": nbt.ShortTag(999), "lvl": nbt.ShortTag(1), "custom": nbt.StringTag("keep")}),
                        ]
                    )
                }
            )
        )
        apply_editable_item_tags(item, {"display_name": "", "lore": [], "enchantments": []}, ENCHANTMENTS)
        self.assertIn("ench", item["tag"])
        self.assertEqual(len(item["tag"]["ench"]), 1)
        self.assertEqual(item["tag"]["ench"][0]["id"].py_data, 999)
        self.assertEqual(item["tag"]["ench"][0]["custom"].py_data, "keep")


class TestValidateInventoryItem(unittest.TestCase):
    def test_rejects_non_integer_numeric_fields_instead_of_truncating(self):
        base = {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0}
        for field, value in (("slot", 0.9), ("count", 1.9), ("damage", 0.9), ("count", True)):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "Item-Daten"):
                validate_inventory_item({**base, field: value}, ENCHANTMENTS)

    def test_rejects_fractional_enchantment_values_instead_of_truncating(self):
        base = {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0}
        for enchantment in ({"id": 0.9, "lvl": 1}, {"id": 0, "lvl": 1.9}):
            with self.subTest(enchantment=enchantment), self.assertRaisesRegex(ValueError, "Verzauberung"):
                validate_inventory_item({**base, "enchantments": [enchantment]}, ENCHANTMENTS)

    def test_rejects_item_id_without_colon(self):
        with self.assertRaisesRegex(ValueError, "Item-ID"):
            validate_inventory_item(
                {"slot": 0, "name": "notvalid", "count": 1, "damage": 0},
                ENCHANTMENTS,
            )

    def test_rejects_item_id_with_null_byte(self):
        with self.assertRaisesRegex(ValueError, "Item-ID"):
            validate_inventory_item(
                {"slot": 0, "name": "minecraft:stone\0", "count": 1, "damage": 0},
                ENCHANTMENTS,
            )

    def test_rejects_excessive_damage(self):
        with self.assertRaisesRegex(ValueError, "Damage"):
            validate_inventory_item(
                {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": MAX_DAMAGE + 1},
                ENCHANTMENTS,
            )

    def test_rejects_too_long_display_name(self):
        with self.assertRaisesRegex(ValueError, "Anzeigename"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "display_name": "X" * (MAX_TEXT_LENGTH + 1),
                },
                ENCHANTMENTS,
            )

    def test_rejects_too_many_lore_lines(self):
        with self.assertRaisesRegex(ValueError, "Lore"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "lore": ["x"] * (MAX_LORE_LINES + 1),
                },
                ENCHANTMENTS,
            )

    def test_preserves_empty_lore_lines_and_surrounding_spaces(self):
        result = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:stone",
                "count": 1,
                "damage": 0,
                "lore": ["Block A", "", "  eingerückt  "],
            },
            ENCHANTMENTS,
        )

        self.assertEqual(result["lore"], ["Block A", "", "  eingerückt  "])

    def test_rejects_unknown_ench_id(self):
        with self.assertRaisesRegex(ValueError, "Verzauberung"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "enchantments": [{"id": 9999, "lvl": 1}],
                },
                ENCHANTMENTS,
            )

    def test_rejects_ench_level_above_max(self):
        with self.assertRaisesRegex(ValueError, "Verzauberungslevel"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "enchantments": [{"id": 0, "lvl": 99}],
                },
                ENCHANTMENTS,
            )

    def test_accepts_valid_ench_level(self):
        result = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:stone",
                "count": 1,
                "damage": 0,
                "enchantments": [{"id": 0, "lvl": 4}],
            },
            ENCHANTMENTS,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["enchantments"], [{"id": 0, "lvl": 4}])

    def test_accepts_valid_full_item(self):
        result = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:stone",
                "count": 64,
                "damage": 0,
                "display_name": "My Stone",
                "lore": ["Line1", "Line2"],
                "enchantments": [],
            },
            ENCHANTMENTS,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "minecraft:stone")
        self.assertEqual(result["count"], 64)
        self.assertEqual(result["display_name"], "My Stone")
        self.assertEqual(result["lore"], ["Line1", "Line2"])

    def test_validates_entity_variant_edits_strictly(self):
        axolotl = validate_inventory_item(
            {
                "slot": 0,
                "name": "minecraft:axolotl_bucket",
                "count": 1,
                "damage": 0,
                "entity_variant_edit": {
                    "kind": "axolotl",
                    "variant": 4,
                    "is_baby": True,
                },
            },
            ENCHANTMENTS,
        )
        self.assertEqual(
            axolotl["entity_variant_edit"],
            {"kind": "axolotl", "variant": 4, "is_baby": True},
        )

        with self.assertRaisesRegex(ValueError, "Entityvariante"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "entity_variant_edit": {
                        "kind": "axolotl",
                        "variant": 0,
                        "is_baby": False,
                    },
                },
                ENCHANTMENTS,
            )
        with self.assertRaisesRegex(ValueError, "Entityvarianten-Daten"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:tropical_fish_bucket",
                    "count": 1,
                    "damage": 0,
                    "entity_variant_edit": {
                        "kind": "tropical_fish",
                        "variant": 0,
                        "mark_variant": 6,
                        "color": 0,
                        "color2": 0,
                    },
                },
                ENCHANTMENTS,
            )

    def test_uses_curated_stack_limits_for_variant_items_and_entity_buckets(self):
        self.assertEqual(
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:banner",
                    "count": 16,
                    "damage": 15,
                },
                ENCHANTMENTS,
            )["count"],
            16,
        )
        for item_name in (
            "minecraft:bed",
            "minecraft:goat_horn",
            "minecraft:suspicious_stew",
            "minecraft:axolotl_bucket",
            "minecraft:tropical_fish_bucket",
        ):
            with self.assertRaisesRegex(ValueError, "Ungültige Menge"):
                validate_inventory_item(
                    {
                        "slot": 0,
                        "name": item_name,
                        "count": 2,
                        "damage": 0,
                    },
                    ENCHANTMENTS,
                )

    def test_returns_none_for_air(self):
        result = validate_inventory_item(
            {"slot": 0, "name": "minecraft:air", "count": 1, "damage": 0},
            ENCHANTMENTS,
        )
        self.assertIsNone(result)

    def test_rejects_lore_not_a_list(self):
        with self.assertRaisesRegex(ValueError, "Lore"):
            validate_inventory_item(
                {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0, "lore": "not_a_list"},
                ENCHANTMENTS,
            )

    def test_rejects_too_long_item_id(self):
        with self.assertRaisesRegex(ValueError, "Item-ID"):
            validate_inventory_item(
                {"slot": 0, "name": f"minecraft:{'x' * (MAX_TEXT_LENGTH + 1)}", "count": 1, "damage": 0},
                ENCHANTMENTS,
            )

    def test_rejects_duplicate_enchantments(self):
        with self.assertRaisesRegex(ValueError, "Doppelte"):
            validate_inventory_item(
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "enchantments": [{"id": 0, "lvl": 1}, {"id": 0, "lvl": 1}],
                },
                ENCHANTMENTS,
            )


class TestBuildInventoryNbt(unittest.TestCase):
    def test_builds_list_tag_with_valid_items(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0}],
            ENCHANTMENTS,
        )
        self.assertIsInstance(result, nbt.ListTag)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Name"].py_data, "minecraft:stone")

    def test_preserves_existing_overstack_but_rejects_new_or_changed_overstack(self):
        oversized_bed = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:bed"),
                "Count": nbt.ByteTag(64),
                "Damage": nbt.ShortTag(0),
            }
        )
        stone = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(1),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([oversized_bed, stone])})

        saved = build_inventory_nbt(
            player,
            [
                {"slot": 0, "name": "minecraft:bed", "count": 64, "damage": 0},
                {"slot": 1, "name": "minecraft:stone", "count": 2, "damage": 0},
            ],
            ENCHANTMENTS,
        )
        self.assertEqual(saved[0]["Count"].py_data, 64)
        self.assertEqual(saved[1]["Count"].py_data, 2)

        with self.assertRaisesRegex(ValueError, "Vanilla-Stacklimit"):
            build_inventory_nbt(
                player,
                [{"slot": 0, "name": "minecraft:bed", "count": 32, "damage": 0}],
                ENCHANTMENTS,
            )
        with self.assertRaisesRegex(ValueError, "Vanilla-Stacklimit"):
            build_inventory_nbt(
                nbt.CompoundTag({"Inventory": nbt.ListTag([])}),
                [{"slot": 0, "name": "minecraft:bed", "count": 64, "damage": 0}],
                ENCHANTMENTS,
            )

        normalized = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:bed", "count": 1, "damage": 0}],
            ENCHANTMENTS,
        )
        self.assertEqual(normalized[0]["Count"].py_data, 1)

    def _sword_outside_bounds(self, slot=0, damage=0, display=None):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(slot),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(damage),
            }
        )
        if display is not None:
            item["tag"] = nbt.CompoundTag({"display": display})
        return item

    def _save_editing_only_the_stone(self, odd_item, edit=None):
        """Echo the full container, editing the stone in slot 1 -- and only it."""

        stone = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(1),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        keys = ("slot", "source_slot", "name", "count", "damage", "display_name", "lore", "enchantments", "source_item_digest")
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([odd_item, stone])})
        parsed, _originals = nbt_to_json(player)
        payload = []
        for slot in sorted(parsed):
            entry = {key: parsed[slot][key] for key in keys if key in parsed[slot]}
            if slot == 1:
                entry["count"] = 5
            if slot == 0 and edit:
                entry.update(edit)
            payload.append(entry)
        target = nbt.CompoundTag({"Inventory": nbt.ListTag([odd_item, stone])})
        return build_inventory_nbt(target, payload, ENCHANTMENTS)

    def test_an_existing_out_of_bounds_item_does_not_block_another_slot(self):
        """One add-on item must not make the whole world unsavable.

        The payload always carries the complete container, so an untouched entry
        outside the editor's limits would otherwise fail validation before its
        original was ever resolved.
        """

        long_lore = nbt.CompoundTag({"Lore": nbt.ListTag([nbt.StringTag("z")] * 51)})
        cases = {
            "damage above the catalog maximum": self._sword_outside_bounds(damage=9999),
            "negative damage": self._sword_outside_bounds(damage=-5),
            "51 lore lines": self._sword_outside_bounds(display=long_lore),
            "overlong lore line": self._sword_outside_bounds(display=nbt.CompoundTag({"Lore": nbt.ListTag([nbt.StringTag("z" * 600)])})),
            "overlong display name": self._sword_outside_bounds(display=nbt.CompoundTag({"Name": nbt.StringTag("x" * 600)})),
        }
        for label, odd_item in cases.items():
            with self.subTest(case=label):
                saved = self._save_editing_only_the_stone(odd_item)
                self.assertEqual(saved[1]["Count"].py_data, 5)

    def test_a_new_or_changed_out_of_bounds_value_is_still_rejected(self):
        long_lore = nbt.CompoundTag({"Lore": nbt.ListTag([nbt.StringTag("z")] * 51)})
        long_name = nbt.CompoundTag({"Name": nbt.StringTag("x" * 600)})
        cases = (
            ("damage newly set", self._sword_outside_bounds(), {"damage": 9999}, "Damage-Wert"),
            ("damage changed to another out-of-range value", self._sword_outside_bounds(damage=9999), {"damage": 8888}, "Damage-Wert"),
            ("display name newly set", self._sword_outside_bounds(), {"display_name": "y" * 600}, "Anzeigename ist zu lang"),
            (
                "display name replaced by another long one",
                self._sword_outside_bounds(display=long_name),
                {"display_name": "y" * 600},
                "Anzeigename ist zu lang",
            ),
            ("lore newly set", self._sword_outside_bounds(), {"lore": ["z"] * 51}, "Lore ist zu lang"),
            ("lore grown by one line", self._sword_outside_bounds(display=long_lore), {"lore": ["z"] * 52}, "Lore ist zu lang"),
        )
        for label, odd_item, edit, message in cases:
            with self.subTest(case=label), self.assertRaisesRegex(ValueError, message):
                self._save_editing_only_the_stone(odd_item, edit)

    def test_each_bound_is_checked_on_its_own(self):
        """An untouched oversized lore must not also permit a new overlong name."""

        long_lore = nbt.CompoundTag({"Lore": nbt.ListTag([nbt.StringTag("z")] * 51)})
        with self.assertRaisesRegex(ValueError, "Anzeigename ist zu lang"):
            self._save_editing_only_the_stone(self._sword_outside_bounds(display=long_lore), {"display_name": "y" * 600})

        saved = self._save_editing_only_the_stone(self._sword_outside_bounds(display=long_lore), {"display_name": "Neu"})
        self.assertEqual(saved[0]["tag"]["display"]["Name"].py_data, "Neu")
        self.assertEqual(len(saved[0]["tag"]["display"]["Lore"]), 51)

    def test_an_out_of_bounds_value_needs_a_resolvable_original(self):
        """Without an original the strict limit applies, so nothing new slips through."""

        with self.assertRaisesRegex(ValueError, "Damage-Wert"):
            build_inventory_nbt(
                nbt.CompoundTag({"Inventory": nbt.ListTag([])}),
                [{"slot": 0, "name": "minecraft:diamond_sword", "count": 1, "damage": 9999}],
                ENCHANTMENTS,
            )

    def test_direct_validation_keeps_the_strict_limits(self):
        """Only the write builders defer; a direct caller sees the old behaviour."""

        with self.assertRaisesRegex(ValueError, "Ungültiger Damage-Wert"):
            validate_inventory_item(
                {"slot": 0, "name": "minecraft:diamond_sword", "count": 1, "damage": 9999},
                ENCHANTMENTS,
            )

    def test_rejects_new_unknown_data_value_variant_but_preserves_an_existing_one(self):
        empty_player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        with self.assertRaisesRegex(ValueError, "keine unterstützte Variante"):
            build_inventory_nbt(
                empty_player,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:empty_map",
                        "count": 1,
                        "damage": 1,
                    }
                ],
                ENCHANTMENTS,
            )

        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:empty_map"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(99),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        preserved = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:empty_map",
                    "count": 1,
                    "damage": 99,
                }
            ],
            ENCHANTMENTS,
        )
        self.assertEqual(preserved[0]["Damage"].py_data, 99)

        with self.assertRaisesRegex(ValueError, "keine unterstützte Variante"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:empty_map",
                        "count": 1,
                        "damage": 98,
                    }
                ],
                ENCHANTMENTS,
            )

    def test_builds_enchanted_book_with_multiple_stored_enchantments(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        result = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:enchanted_book",
                    "count": 1,
                    "damage": 0,
                    "enchantments": [
                        {"id": 9, "lvl": 5},
                        {"id": 10, "lvl": 5},
                        {"id": 31, "lvl": 3},
                    ],
                }
            ],
            ENCHANTMENTS,
        )

        self.assertEqual(result[0]["Name"].py_data, "minecraft:enchanted_book")
        self.assertEqual(
            [(entry["id"].py_data, entry["lvl"].py_data) for entry in result[0]["tag"]["ench"]],
            [(9, 5), (10, 5), (31, 3)],
        )

    def test_rejects_new_enchantment_nbt_on_regular_book(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        with self.assertRaisesRegex(ValueError, "nicht verzauberbar"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:book",
                        "count": 1,
                        "damage": 0,
                        "enchantments": [{"id": 9, "lvl": 1}],
                    }
                ],
                ENCHANTMENTS,
            )

    def test_density_id_39_on_book_is_known_and_preserves_a_truly_unknown_entry(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:enchanted_book"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "ench": nbt.ListTag(
                            [
                                nbt.CompoundTag({"id": nbt.ShortTag(4), "lvl": nbt.ShortTag(4)}),
                                nbt.CompoundTag({"id": nbt.ShortTag(39), "lvl": nbt.ShortTag(4)}),
                                nbt.CompoundTag({"id": nbt.ShortTag(19), "lvl": nbt.ShortTag(4)}),
                                nbt.CompoundTag({"id": nbt.ShortTag(99), "lvl": nbt.ShortTag(2)}),
                            ]
                        )
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        self.assertEqual(
            parsed[0]["enchantments"],
            [{"id": 4, "lvl": 4}, {"id": 39, "lvl": 4}, {"id": 19, "lvl": 4}],
        )
        self.assertTrue(parsed[0]["has_unknown_enchantments"])

        parsed[0]["enchantments"] = [
            {"id": 4, "lvl": 2},
            {"id": 39, "lvl": 5},
            {"id": 19, "lvl": 5},
            {"id": 26, "lvl": 1},
        ]
        result = build_inventory_nbt(player, [parsed[0]], ENCHANTMENTS)

        # The unknown entry 99 keeps the position it had in the original list; only
        # the genuinely new enchantment 26 is appended.
        self.assertEqual(
            [(entry["id"].py_data, entry["lvl"].py_data) for entry in result[0]["tag"]["ench"]],
            [(4, 2), (39, 5), (19, 5), (99, 2), (26, 1)],
        )

    def test_reuses_original_item_when_name_matches(self):
        orig = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag({"custom": nbt.StringTag("preserved")}),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([orig])})
        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 1}],
            ENCHANTMENTS,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Count"].py_data, 2)
        self.assertEqual(result[0]["tag"]["custom"].py_data, "preserved")

    def test_generic_creative_axolotl_bucket_is_valid_without_inventing_a_variant(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "WasPickedUp": nbt.ByteTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})

        parsed, _originals = nbt_to_json(player)
        result = build_inventory_nbt(player, [parsed[0]], ENCHANTMENTS)

        self.assertIsNone(parsed[0]["entity_variant"])
        self.assertEqual(parsed[0]["entity_variant_state"], "generic")
        self.assertNotIn("tag", result[0])
        self.assertEqual(result[0]["WasPickedUp"].py_data, 0)

    def test_unresolvable_axolotl_payload_is_not_mislabeled_as_generic(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag({"Variant": nbt.IntTag(99)}),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})

        parsed, _originals = nbt_to_json(player)

        self.assertIsNone(parsed[0]["entity_variant"])
        self.assertEqual(parsed[0]["entity_variant_state"], "unresolved")

    def test_edits_existing_axolotl_variant_and_preserves_complete_entity_nbt(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "ColorID": nbt.StringTag("item.axolotlColorGold.name"),
                        "BodyID": nbt.StringTag("item.axolotlAdultBodySingle.name"),
                        "SaveData": nbt.CompoundTag(
                            {
                                "identifier": nbt.StringTag("minecraft:axolotl"),
                                "Variant": nbt.IntTag(2),
                                "Age": nbt.IntTag(0),
                                "definitions": nbt.ListTag(
                                    [
                                        nbt.StringTag("+minecraft:axolotl"),
                                        nbt.StringTag("+axolotl_adult"),
                                        nbt.StringTag("+axolotl_gold"),
                                        nbt.StringTag("-axolotl_in_water"),
                                        nbt.StringTag("+future_definition"),
                                    ]
                                ),
                                "UnknownFutureField": nbt.StringTag("preserve-me"),
                            }
                        ),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        self.assertEqual(parsed[0]["entity_variant_state"], "captured")
        parsed[0]["entity_variant_edit"] = {
            "kind": "axolotl",
            "variant": 4,
            "is_baby": True,
        }

        result = build_inventory_nbt(player, [parsed[0]], ENCHANTMENTS)
        saved_tag = result[0]["tag"]
        saved_entity = saved_tag["SaveData"]

        self.assertEqual(saved_entity["Variant"].py_data, 4)
        self.assertEqual(saved_entity["Age"].py_data, -24_000)
        self.assertEqual(saved_entity["UnknownFutureField"].py_data, "preserve-me")
        self.assertEqual(saved_tag["ColorID"].py_data, "item.axolotlColorBlue.name")
        self.assertEqual(saved_tag["BodyID"].py_data, "item.axolotlBabyBodySingle.name")
        self.assertEqual(saved_tag["AppendCustomName"].py_data, 1)
        self.assertEqual(
            [entry.py_data for entry in saved_entity["definitions"]],
            [
                "+minecraft:axolotl",
                "+axolotl_baby",
                "+axolotl_blue",
                "-axolotl_in_water",
                "+future_definition",
            ],
        )
        self.assertEqual(original["tag"]["SaveData"]["Variant"].py_data, 2)

    def test_editing_an_existing_baby_axolotl_preserves_its_running_growth_timer(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "SaveData": nbt.CompoundTag(
                            {
                                "identifier": nbt.StringTag("minecraft:axolotl"),
                                "Variant": nbt.IntTag(2),
                                "Age": nbt.IntTag(-12_000),
                            }
                        )
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        parsed[0]["entity_variant_edit"] = {
            "kind": "axolotl",
            "variant": 4,
            "is_baby": True,
        }

        result = build_inventory_nbt(player, [parsed[0]], ENCHANTMENTS)

        self.assertEqual(result[0]["tag"]["SaveData"]["Age"].py_data, -12_000)

    def test_edits_numeric_axolotl_legacy_fields_without_replacing_their_types(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "ActorIdentifier": nbt.StringTag("minecraft:axolotl"),
                        "ColorID": nbt.IntTag(2),
                        "BodyID": nbt.IntTag(2),
                        "IsBaby": nbt.ByteTag(0),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        parsed[0]["entity_variant_edit"] = {
            "kind": "axolotl",
            "variant": 4,
            "is_baby": True,
        }

        result = build_inventory_nbt(player, [parsed[0]], ENCHANTMENTS)
        saved_tag = result[0]["tag"]

        self.assertIsInstance(saved_tag["ColorID"], nbt.IntTag)
        self.assertIsInstance(saved_tag["BodyID"], nbt.IntTag)
        self.assertEqual(saved_tag["ColorID"].py_data, 4)
        self.assertEqual(saved_tag["BodyID"].py_data, 4)
        self.assertEqual(saved_tag["Variant"].py_data, 4)
        self.assertEqual(saved_tag["IsBaby"].py_data, 1)

    def test_entity_variant_helpers_create_state_inside_a_new_item_tag(self):
        axolotl = nbt.CompoundTag(
            {
                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )

        inventory_core._apply_axolotl_variant_edit(
            axolotl,
            {"kind": "axolotl", "variant": 4, "is_baby": True},
        )

        self.assertNotIn("IsBaby", axolotl)
        self.assertEqual(axolotl["tag"]["IsBaby"].py_data, 1)

    def test_rejects_tropical_fish_display_only_variant_without_entity_payload(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(1),
                "Name": nbt.StringTag("minecraft:buckettropical"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "GroupName": nbt.StringTag("item.tropicalSchoolClownfish.name"),
                        "BodyID": nbt.StringTag("item.tropicalBodyKobMulti.name"),
                        "ColorID": nbt.StringTag("item.tropicalColorOrange.name"),
                        "Color2ID": nbt.StringTag("item.tropicalColorWhite.name"),
                        "UnknownFutureField": nbt.StringTag("preserve-me"),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        parsed[1]["entity_variant_edit"] = {
            "kind": "tropical_fish",
            "variant": 1,
            "mark_variant": 3,
            "color": 14,
            "color2": 0,
        }

        self.assertFalse(parsed[1]["entity_variant"]["can_edit"])
        with self.assertRaisesRegex(ValueError, "vorhandenen Entity-Daten"):
            build_inventory_nbt(player, [parsed[1]], ENCHANTMENTS)

    def test_edits_existing_numeric_tropical_fish_state_as_one_correlated_unit(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(2),
                "Name": nbt.StringTag("minecraft:tropical_fish_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "SaveData": nbt.CompoundTag(
                            {
                                "identifier": nbt.StringTag("minecraft:tropical_fish"),
                                "Variant": nbt.IntTag(0),
                                "MarkVariant": nbt.IntTag(0),
                                "Color": nbt.ByteTag(1),
                                "Color2": nbt.ByteTag(0),
                                "GroupName": nbt.StringTag("item.tropicalSchoolClownfish.name"),
                                "BodyID": nbt.StringTag("item.tropicalBodyKobMulti.name"),
                                "ColorID": nbt.StringTag("item.tropicalColorOrange.name"),
                                "Color2ID": nbt.StringTag("item.tropicalColorWhite.name"),
                                "UnknownFutureField": nbt.LongTag(99),
                            }
                        )
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        parsed[2]["entity_variant_edit"] = {
            "kind": "tropical_fish",
            "variant": 1,
            "mark_variant": 5,
            "color": 9,
            "color2": 4,
        }

        result = build_inventory_nbt(player, [parsed[2]], ENCHANTMENTS)
        saved_tag = result[0]["tag"]
        saved_entity = saved_tag["SaveData"]

        self.assertEqual(saved_entity["Variant"].py_data, 1)
        self.assertEqual(saved_entity["MarkVariant"].py_data, 5)
        self.assertEqual(saved_entity["Color"].py_data, 9)
        self.assertEqual(saved_entity["Color2"].py_data, 4)
        self.assertNotIn("GroupName", saved_entity)
        self.assertEqual(saved_entity["BodyID"].py_data, "item.tropicalBodyClayfishMulti.name")
        self.assertEqual(saved_entity["ColorID"].py_data, "item.tropicalColorTeal.name")
        self.assertEqual(saved_entity["Color2ID"].py_data, "item.tropicalColorYellow.name")
        self.assertEqual(saved_entity["UnknownFutureField"].py_data, 99)
        self.assertEqual(saved_tag["BodyID"].py_data, "item.tropicalBodyClayfishMulti.name")
        reparsed, _originals = nbt_to_json(nbt.CompoundTag({"Inventory": result}))
        self.assertEqual(
            reparsed[2]["entity_variant"]["display_name_en"],
            "Tropical Fish: Clayfish, Teal/Yellow",
        )

    def test_editing_tropical_fish_to_a_vanilla_preset_restores_its_group_name(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(2),
                "Name": nbt.StringTag("minecraft:tropical_fish_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "SaveData": nbt.CompoundTag(
                            {
                                "identifier": nbt.StringTag("minecraft:tropical_fish"),
                                "Variant": nbt.IntTag(1),
                                "MarkVariant": nbt.IntTag(1),
                                "Color": nbt.ByteTag(4),
                                "Color2": nbt.ByteTag(4),
                                "GroupName": nbt.StringTag("item.tropicalSchoolYellowTang.name"),
                                "BodyID": nbt.StringTag("item.tropicalBodyStripeySingle.name"),
                                "ColorID": nbt.StringTag("item.tropicalColorYellow.name"),
                                "Color2ID": nbt.StringTag("item.tropicalColorYellow.name"),
                            }
                        )
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        parsed[2]["entity_variant_edit"] = {
            "kind": "tropical_fish",
            "variant": 0,
            "mark_variant": 0,
            "color": 1,
            "color2": 0,
        }

        result = build_inventory_nbt(player, [parsed[2]], ENCHANTMENTS)
        saved_tag = result[0]["tag"]
        saved_entity = saved_tag["SaveData"]
        reparsed, _originals = nbt_to_json(nbt.CompoundTag({"Inventory": result}))

        self.assertEqual(saved_entity["GroupName"].py_data, "item.tropicalSchoolClownfish.name")
        self.assertEqual(saved_tag["GroupName"].py_data, "item.tropicalSchoolClownfish.name")
        self.assertEqual(
            reparsed[2]["entity_variant"]["display_name_en"],
            "Tropical Fish: Clownfish, Orange/White",
        )

    def test_edits_tropical_fish_with_numeric_legacy_display_keys(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(2),
                "Name": nbt.StringTag("minecraft:tropical_fish_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "identifier": nbt.StringTag("minecraft:tropical_fish"),
                        "Variant": nbt.IntTag(0),
                        "MarkVariant": nbt.IntTag(0),
                        "Color": nbt.ByteTag(1),
                        "Color2": nbt.ByteTag(0),
                        "BodyID": nbt.IntTag(17),
                        "ColorID": nbt.IntTag(18),
                        "Color2ID": nbt.IntTag(19),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        parsed[2]["entity_variant_edit"] = {
            "kind": "tropical_fish",
            "variant": 1,
            "mark_variant": 3,
            "color": 10,
            "color2": 4,
        }

        result = build_inventory_nbt(player, [parsed[2]], ENCHANTMENTS)
        saved = result[0]["tag"]
        reparsed, _originals = nbt_to_json(nbt.CompoundTag({"Inventory": result}))

        self.assertEqual(
            (saved["Variant"].py_data, saved["MarkVariant"].py_data, saved["Color"].py_data, saved["Color2"].py_data),
            (1, 3, 10, 4),
        )
        self.assertEqual((saved["BodyID"].py_data, saved["ColorID"].py_data, saved["Color2ID"].py_data), (17, 18, 19))
        self.assertEqual(saved["GroupName"].py_data, "item.tropicalSchoolDottyback.name")
        self.assertEqual(reparsed[2]["entity_variant"]["display_name_en"], "Tropical Fish: Dottyback, Plum/Yellow")

    def test_rejects_entity_variant_edit_without_resolvable_original_entity_data(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})

        with self.assertRaisesRegex(ValueError, "auflösbaren Originalitem"):
            build_inventory_nbt(
                player,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:axolotl_bucket",
                        "count": 1,
                        "damage": 0,
                        "entity_variant_edit": {
                            "kind": "axolotl",
                            "variant": 4,
                            "is_baby": False,
                        },
                    }
                ],
                ENCHANTMENTS,
            )

    def test_entity_variant_edit_does_not_replace_an_opaque_item_tag(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:axolotl_bucket"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "Variant": nbt.IntTag(2),
                "IsBaby": nbt.ByteTag(0),
                "tag": nbt.StringTag("opaque-future-data"),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
        parsed, _originals = nbt_to_json(player)
        parsed[0]["entity_variant_edit"] = {
            "kind": "axolotl",
            "variant": 4,
            "is_baby": True,
        }

        with self.assertRaisesRegex(ValueError, "unbekannten NBT-Typ"):
            build_inventory_nbt(player, [parsed[0]], ENCHANTMENTS)
        self.assertEqual(original["tag"].py_data, "opaque-future-data")
        self.assertEqual(original["Variant"].py_data, 2)

    def test_updates_damageable_item_tag_damage_without_changing_root_damage(self):
        orig = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:iron_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag({"Damage": nbt.IntTag(4), "custom": nbt.StringTag("preserved")}),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([orig])})
        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:iron_sword", "count": 1, "damage": 8}],
            ENCHANTMENTS,
        )
        self.assertEqual(result[0]["Damage"].py_data, 0)
        self.assertEqual(result[0]["tag"]["Damage"].py_data, 8)
        self.assertEqual(result[0]["tag"]["custom"].py_data, "preserved")

    def test_copper_spear_tag_damage_is_visible_editable_and_not_extra_nbt(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(31),
                "Name": nbt.StringTag("minecraft:copper_spear"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "WasPickedUp": nbt.ByteTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "Damage": nbt.IntTag(7),
                        "ench": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "id": nbt.ShortTag(41),
                                        "lvl": nbt.ShortTag(1),
                                    }
                                )
                            ]
                        ),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})

        inventory, _originals = nbt_to_json(player)

        self.assertEqual(inventory[31]["damage"], 7)
        self.assertEqual(inventory[31]["enchantments"], [{"id": 41, "lvl": 1}])
        self.assertFalse(inventory[31]["has_protected_nbt"])
        self.assertEqual(inventory[31]["protected_nbt_summary"], [])

        inventory[31]["damage"] = 9
        saved = build_inventory_nbt(player, [inventory[31]], ENCHANTMENTS)

        self.assertEqual(saved[0]["Damage"].py_data, 0)
        self.assertEqual(saved[0]["tag"]["Damage"].py_data, 9)
        self.assertEqual(saved[0]["tag"]["ench"][0]["id"].py_data, 41)

    def test_mace_tag_damage_is_visible_editable_and_not_extra_nbt(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(30),
                "Name": nbt.StringTag("minecraft:mace"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "WasPickedUp": nbt.ByteTag(0),
                "tag": nbt.CompoundTag(
                    {
                        "Damage": nbt.IntTag(7),
                        "ench": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "id": nbt.ShortTag(40),
                                        "lvl": nbt.ShortTag(1),
                                    }
                                )
                            ]
                        ),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})

        inventory, _originals = nbt_to_json(player)

        self.assertEqual(inventory[30]["damage"], 7)
        self.assertEqual(inventory[30]["enchantments"], [{"id": 40, "lvl": 1}])
        self.assertFalse(inventory[30]["has_protected_nbt"])
        self.assertFalse(inventory[30]["has_preserved_nbt"])
        self.assertEqual(inventory[30]["protected_nbt_summary"], [])
        self.assertEqual(inventory[30]["preserved_nbt_summary"], [])

        inventory[30]["damage"] = 9
        saved = build_inventory_nbt(player, [inventory[30]], ENCHANTMENTS)

        self.assertEqual(saved[0]["Damage"].py_data, 0)
        self.assertEqual(saved[0]["tag"]["Damage"].py_data, 9)
        self.assertEqual(saved[0]["tag"]["ench"][0]["id"].py_data, 40)

    def test_curated_engine_damageable_items_do_not_report_tag_damage_as_extra_nbt(self):
        item_names = [
            "minecraft:brush",
            "minecraft:copper_axe",
            "minecraft:copper_boots",
            "minecraft:copper_chestplate",
            "minecraft:copper_helmet",
            "minecraft:copper_hoe",
            "minecraft:copper_leggings",
            "minecraft:copper_pickaxe",
            "minecraft:copper_shovel",
            "minecraft:copper_sword",
            "minecraft:crossbow",
            "minecraft:mace",
            "minecraft:turtle_helmet",
            "minecraft:wolf_armor",
        ]
        originals = [
            nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(slot),
                    "Name": nbt.StringTag(item_name),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "WasPickedUp": nbt.ByteTag(0),
                    "tag": nbt.CompoundTag({"Damage": nbt.IntTag(7)}),
                }
            )
            for slot, item_name in enumerate(item_names)
        ]
        player = nbt.CompoundTag({"Inventory": nbt.ListTag(originals)})

        inventory, _originals = nbt_to_json(player)

        for slot, item_name in enumerate(item_names):
            with self.subTest(item_name=item_name):
                self.assertEqual(inventory[slot]["damage"], 7)
                self.assertFalse(inventory[slot]["has_protected_nbt"])
                self.assertFalse(inventory[slot]["has_preserved_nbt"])
                self.assertEqual(inventory[slot]["protected_nbt_summary"], [])
                self.assertEqual(inventory[slot]["preserved_nbt_summary"], [])
                inventory[slot]["damage"] = 9

        saved = build_inventory_nbt(player, list(inventory.values()), ENCHANTMENTS)

        for item in saved:
            self.assertEqual(item["Damage"].py_data, 0)
            self.assertEqual(item["tag"]["Damage"].py_data, 9)

    def test_creates_tag_damage_for_new_damageable_item(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:iron_sword", "count": 1, "damage": 8}],
            ENCHANTMENTS,
        )
        self.assertEqual(result[0]["Damage"].py_data, 0)
        self.assertEqual(result[0]["tag"]["Damage"].py_data, 8)

    def test_creates_new_item_when_name_differs(self):
        orig = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:dirt"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([orig])})
        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0}],
            ENCHANTMENTS,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Name"].py_data, "minecraft:stone")

    def test_skips_air_items(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:air", "count": 1, "damage": 0}],
            ENCHANTMENTS,
        )
        self.assertEqual(len(result), 0)

    def test_prefers_new_item_tag_and_applies_edits(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        result = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "name": "minecraft:stone",
                    "count": 1,
                    "damage": 0,
                    "display_name": "My Stone",
                }
            ],
            ENCHANTMENTS,
        )
        self.assertEqual(result[0]["tag"]["display"]["Name"].py_data, "My Stone")

    def test_rejects_duplicate_inventory_slots(self):
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
        with self.assertRaisesRegex(ValueError, "Doppelter"):
            build_inventory_nbt(
                player,
                [
                    {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0},
                    {"slot": 0, "name": "minecraft:dirt", "count": 1, "damage": 0},
                ],
                ENCHANTMENTS,
            )

    def test_preserves_unknown_original_inventory_slots_on_save(self):
        unknown = nbt.CompoundTag(
            {
                "Slot": nbt.IntTag(200),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "custom_tag": nbt.StringTag("keep"),
            }
        )
        editable = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([unknown, editable])})
        result = build_inventory_nbt(
            player,
            [{"slot": 0, "name": "minecraft:dirt", "count": 1, "damage": 0}],
            ENCHANTMENTS,
        )
        by_slot = {int(item["Slot"].py_data): item for item in result}
        self.assertEqual(by_slot[0]["Name"].py_data, "minecraft:dirt")
        self.assertEqual(by_slot[200]["custom_tag"].py_data, "keep")


class TestApplyPlayerStats(unittest.TestCase):
    def test_rejects_fractional_integer_stats_instead_of_truncating(self):
        for field, value in (("xp_level", 7.9), ("food_level", 12.9)):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "XP-Level|Food-Level"):
                apply_player_stats(make_minimal_player_tag(), {field: value})

    def test_rejects_boolean_stats_instead_of_coercing_to_numbers(self):
        # bool ist in Python ein int-Subtyp; ohne explizite Ablehnung würde
        # True stillschweigend als 1.0 bzw. 1 gespeichert.
        cases = (
            ("health", "Health-Wert"),
            ("xp_progress", "XP-Fortschritt"),
            ("food_saturation", "Food-Sättigung"),
            ("xp_level", "XP-Level"),
        )
        for field, message in cases:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                apply_player_stats(make_minimal_player_tag(), {field: True})
        with self.assertRaisesRegex(ValueError, "Positionswert"):
            apply_player_stats(make_minimal_player_tag(), {"pos": [True, 0.0, 0.0]})

    def test_rejects_xp_level_above_24791(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "XP-Level"):
            apply_player_stats(tag, {"xp_level": 25000})

    def test_rejects_xp_progress_above_1(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "XP-Fortschritt"):
            apply_player_stats(tag, {"xp_progress": 1.5})

    def test_rejects_xp_progress_at_next_level_boundary(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "XP-Fortschritt"):
            apply_player_stats(tag, {"xp_progress": 1.0})

    def test_rejects_opaque_bedrock_xp_alias(self):
        tag = make_minimal_player_tag()
        tag["PlayerLevelProgress"] = nbt.StringTag("opaque")
        with self.assertRaisesRegex(ValueError, "PlayerLevelProgress"):
            apply_player_stats(tag, {"xp_progress": 0.6})

    def test_rejects_opaque_xp_attribute_current(self):
        tag = make_minimal_player_tag()
        tag["Attributes"] = nbt.ListTag(
            [
                nbt.CompoundTag(
                    {
                        "Name": nbt.StringTag("minecraft:player.experience"),
                        "Current": nbt.StringTag("opaque"),
                    }
                )
            ]
        )
        with self.assertRaisesRegex(ValueError, "minecraft:player.experience.Current"):
            apply_player_stats(tag, {"xp_progress": 0.6})

    def test_rejects_negative_xp_progress(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "XP-Fortschritt"):
            apply_player_stats(tag, {"xp_progress": -0.1})

    def test_rejects_food_level_above_20(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Food-Level"):
            apply_player_stats(tag, {"food_level": 21})

    def test_rejects_negative_food_level(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Food-Level"):
            apply_player_stats(tag, {"food_level": -1})

    def test_rejects_food_saturation_above_20(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Food-Sättigung"):
            apply_player_stats(tag, {"food_saturation": 25.0})

    def test_rejects_negative_food_saturation(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Food-Sättigung"):
            apply_player_stats(tag, {"food_saturation": -1.0})

    def test_accepts_valid_xp_food_values(self):
        tag = make_minimal_player_tag()
        apply_player_stats(
            tag,
            {
                "xp_level": 10,
                "xp_progress": 0.75,
                "food_level": 15,
                "food_saturation": 12.0,
            },
        )
        self.assertEqual(tag["PlayerLevel"].py_data, 10)
        self.assertEqual(tag["PlayerLevelProgress"].py_data, 0.75)
        self.assertEqual(tag["foodLevel"].py_data, 15)
        self.assertEqual(tag["foodSaturationLevel"].py_data, 12.0)

    def test_updates_existing_xp_aliases(self):
        tag = make_minimal_player_tag()
        tag["XPLevel"] = nbt.IntTag(5)
        tag["XPProgress"] = nbt.FloatTag(0.25)
        apply_player_stats(tag, {"xp_level": 10, "xp_progress": 0.6})
        self.assertEqual(tag["XPLevel"].py_data, 10)
        self.assertAlmostEqual(tag["XPProgress"].py_data, 0.6)
        self.assertNotIn("PlayerLevel", tag)
        self.assertNotIn("PlayerLevelProgress", tag)

    def test_syncs_existing_bedrock_stat_attributes(self):
        tag = make_minimal_player_tag()
        tag["Attributes"] = nbt.ListTag(
            [
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.level"), "Current": nbt.FloatTag(5.0)}),
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.experience"), "Current": nbt.FloatTag(0.25)}),
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.hunger"), "Current": nbt.FloatTag(18.0)}),
                nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.saturation"), "Current": nbt.FloatTag(12.0)}),
            ]
        )
        apply_player_stats(tag, {"xp_level": 10, "xp_progress": 0.6, "food_level": 15, "food_saturation": 8.5})
        by_name = {entry["Name"].py_data: entry for entry in tag["Attributes"]}
        self.assertAlmostEqual(by_name["minecraft:player.level"]["Current"].py_data, 10.0)
        self.assertAlmostEqual(by_name["minecraft:player.experience"]["Current"].py_data, 0.6)
        self.assertAlmostEqual(by_name["minecraft:player.hunger"]["Current"].py_data, 15.0)
        self.assertAlmostEqual(by_name["minecraft:player.saturation"]["Current"].py_data, 8.5)

    def test_narrow_attribute_type_rejects_a_value_it_cannot_carry(self):
        """Reusing the original tag class must not wrap the value silently.

        A raw ByteTag(200) becomes -56 and would be written to the world, which is
        worse than refusing the edit.
        """

        # Only ByteTag is actually narrow enough to overflow: health is capped at
        # 1024 and xp_level at 24791, so both still fit a ShortTag.
        for label, attribute, stats in (
            ("health", "minecraft:health", {"health": 200.0}),
            ("xp_level", "minecraft:player.level", {"xp_level": 200}),
        ):
            tag = make_minimal_player_tag()
            tag["Attributes"] = nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag(attribute), "Current": nbt.ByteTag(20)})])
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "passt nicht in den vorhandenen NBT-Typ"):
                apply_player_stats(tag, stats)

    def test_integer_attribute_type_rejects_a_fractional_value(self):
        tag = make_minimal_player_tag()
        tag["Attributes"] = nbt.ListTag(
            [nbt.CompoundTag({"Name": nbt.StringTag("minecraft:player.experience"), "Current": nbt.IntTag(0)})]
        )
        with self.assertRaisesRegex(ValueError, "passt nicht in den vorhandenen NBT-Typ"):
            apply_player_stats(tag, {"xp_progress": 0.6})

    def test_narrow_attribute_type_still_accepts_a_representable_value(self):
        """The guard must reject only what genuinely does not fit."""

        tag = make_minimal_player_tag()
        tag["Attributes"] = nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag("minecraft:health"), "Current": nbt.ByteTag(20)})])
        apply_player_stats(tag, {"health": 100.0})
        entry = tag["Attributes"][0]["Current"]
        self.assertIsInstance(entry, nbt.ByteTag)
        self.assertEqual(entry.py_data, 100)

    def test_does_nothing_on_empty_stats(self):
        tag = make_minimal_player_tag()
        apply_player_stats(tag, {})
        self.assertIn("Pos", tag)
        self.assertEqual(tag["Health"].py_data, 20.0)


class EnderChestParseTests(unittest.TestCase):
    def test_parse_ender_chest_no_tag_returns_empty_dict(self):
        tag = make_minimal_player_tag()
        self.assertEqual(parse_ender_chest(tag), {})

    def test_parse_ender_chest_empty_list(self):
        tag = make_minimal_player_tag()
        tag["EnderChestInventory"] = nbt.ListTag([])
        self.assertEqual(parse_ender_chest(tag), {})

    def test_parse_ender_chest_returns_items(self):
        tag = make_minimal_player_tag()
        item = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:diamond"), "Count": nbt.ByteTag(5), "Slot": nbt.ByteTag(3)})
        tag["EnderChestInventory"] = nbt.ListTag([item])
        result = parse_ender_chest(tag)
        self.assertIn(3, result)
        self.assertEqual(result[3]["name"], "minecraft:diamond")
        self.assertEqual(result[3]["count"], 5)

    def test_parse_ender_chest_skips_air_placeholder(self):
        tag = make_minimal_player_tag()
        air = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:air"), "Count": nbt.ByteTag(1), "Slot": nbt.ByteTag(0)})
        tag["EnderChestInventory"] = nbt.ListTag([air])
        result = parse_ender_chest(tag)
        self.assertNotIn(0, result)

    def test_parse_ender_chest_hides_unknown_slots(self):
        tag = make_minimal_player_tag()
        unknown = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:diamond"), "Count": nbt.ByteTag(1), "Slot": nbt.ByteTag(99)})
        tag["EnderChestInventory"] = nbt.ListTag([unknown])
        self.assertEqual(parse_ender_chest(tag), {})


class EnderChestBuildNbtTests(unittest.TestCase):
    def make_item(self, slot, name="minecraft:diamond", count=1):
        return {"name": name, "count": count, "slot": slot, "damage": 0, "components": {}}

    def make_original(self, slot, name="minecraft:diamond"):
        return nbt.CompoundTag({"Name": nbt.StringTag(name), "Count": nbt.ByteTag(1), "Slot": nbt.ByteTag(slot)})

    def test_build_ender_chest_nbt_creates_tag(self):
        tag = make_minimal_player_tag()
        items = [self.make_item(0)]
        tag["EnderChestInventory"] = build_ender_chest_nbt(tag, items, ENCHANTMENTS)
        self.assertIn("EnderChestInventory", tag)
        self.assertEqual(len(tag["EnderChestInventory"]), 1)

    def test_build_ender_chest_nbt_preserves_original_tags(self):
        tag = make_minimal_player_tag()
        original = nbt.CompoundTag(
            {
                "Name": nbt.StringTag("minecraft:diamond"),
                "Count": nbt.ByteTag(1),
                "Slot": nbt.ByteTag(0),
                "custom_tag": nbt.IntTag(42),
            }
        )
        tag["EnderChestInventory"] = nbt.ListTag([original])
        items = [self.make_item(0)]
        build_ender_chest_nbt(tag, items, ENCHANTMENTS)
        slot0 = tag["EnderChestInventory"][0]
        self.assertEqual(slot0["custom_tag"].py_data, 42)

    def test_build_ender_chest_nbt_skips_air(self):
        tag = make_minimal_player_tag()
        items = [{"name": "minecraft:air", "count": 1, "slot": 0, "damage": 0, "components": {}}]
        result = build_ender_chest_nbt(tag, items, ENCHANTMENTS)
        self.assertEqual(len(result), 0)

    def test_build_ender_chest_nbt_new_item_when_original_differs(self):
        tag = make_minimal_player_tag()
        original = nbt.CompoundTag(
            {
                "Name": nbt.StringTag("minecraft:dirt"),
                "Count": nbt.ByteTag(1),
                "Slot": nbt.ByteTag(0),
            }
        )
        tag["EnderChestInventory"] = nbt.ListTag([original])
        items = [self.make_item(0, "minecraft:diamond")]
        tag["EnderChestInventory"] = build_ender_chest_nbt(tag, items, ENCHANTMENTS)
        slot0 = tag["EnderChestInventory"][0]
        self.assertEqual(slot0["Name"].py_data, "minecraft:diamond")

    def test_build_ender_chest_nbt_rejects_duplicate_slots(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Doppelter"):
            build_ender_chest_nbt(tag, [self.make_item(0), self.make_item(0, "minecraft:emerald")], ENCHANTMENTS)

    def test_build_ender_chest_nbt_preserves_unknown_original_slots(self):
        tag = make_minimal_player_tag()
        unknown = nbt.CompoundTag(
            {
                "Name": nbt.StringTag("minecraft:diamond"),
                "Count": nbt.ByteTag(1),
                "Slot": nbt.ByteTag(99),
                "custom_tag": nbt.StringTag("keep"),
            }
        )
        tag["EnderChestInventory"] = nbt.ListTag([unknown])
        result = build_ender_chest_nbt(tag, [self.make_item(0, "minecraft:emerald")], ENCHANTMENTS)
        by_slot = {int(item["Slot"].py_data): item for item in result}
        self.assertEqual(by_slot[0]["Name"].py_data, "minecraft:emerald")
        self.assertEqual(by_slot[99]["custom_tag"].py_data, "keep")


class EnderChestValidateTests(unittest.TestCase):
    def test_validate_accepts_slot_0_through_26(self):
        for slot in [0, 13, 26]:
            result = validate_inventory_item({"slot": slot, "name": "minecraft:diamond", "count": 1}, ENCHANTMENTS, is_ender_chest=True)
            self.assertIsNotNone(result)

    def test_validate_rejects_slot_outside_ender_chest_range(self):
        with self.assertRaises(ValueError):
            validate_inventory_item({"slot": 50, "name": "minecraft:diamond", "count": 1}, ENCHANTMENTS, is_ender_chest=True)

    def test_validate_ender_chest_uses_correct_enum(self):
        self.assertEqual(ENDER_CHEST_SLOTS, set(range(27)))


class EffectsTests(unittest.TestCase):
    def test_parse_effects_empty_when_no_tag(self):
        tag = make_minimal_player_tag()
        self.assertEqual(parse_effects(tag), [])

    def test_parse_effects_returns_list(self):
        tag = make_minimal_player_tag()
        tag["ActiveEffects"] = nbt.ListTag(
            [
                nbt.CompoundTag(
                    {
                        "Id": nbt.ByteTag(4),
                        "Amplifier": nbt.ByteTag(1),
                        "Duration": nbt.IntTag(6000),
                        "Ambient": nbt.ByteTag(False),
                        "ShowParticles": nbt.ByteTag(True),
                        "ShowIcon": nbt.ByteTag(True),
                    }
                ),
            ]
        )
        result = parse_effects(tag)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 4)
        self.assertEqual(result[0]["amplifier"], 1)
        self.assertEqual(result[0]["duration"], 6000)

    def test_apply_effects_creates_tag(self):
        tag = make_minimal_player_tag()
        apply_effects(tag, [{"id": 4, "amplifier": 1, "duration": 6000, "ambient": False, "show_particles": True, "show_icon": True}])
        self.assertIn("ActiveEffects", tag)
        self.assertEqual(tag["ActiveEffects"][0]["Id"].py_data, 4)
        self.assertIsInstance(tag["ActiveEffects"][0]["Id"], nbt.ByteTag)

    def test_apply_effects_removes_tag_when_empty_list(self):
        tag = make_minimal_player_tag()
        tag["ActiveEffects"] = nbt.ListTag(
            [
                nbt.CompoundTag({"Id": nbt.ByteTag(4), "Amplifier": nbt.ByteTag(0), "Duration": nbt.IntTag(100)}),
            ]
        )
        apply_effects(tag, [])
        self.assertNotIn("ActiveEffects", tag)

    def test_apply_effects_does_nothing_when_none(self):
        tag = make_minimal_player_tag()
        apply_effects(tag, None)
        self.assertNotIn("ActiveEffects", tag)

    def test_apply_effects_preserves_existing_when_none(self):
        tag = make_minimal_player_tag()
        tag["ActiveEffects"] = nbt.ListTag(
            [
                nbt.CompoundTag({"Id": nbt.ByteTag(4), "Amplifier": nbt.ByteTag(0), "Duration": nbt.IntTag(100)}),
            ]
        )
        apply_effects(tag, None)
        self.assertIn("ActiveEffects", tag)
        self.assertEqual(tag["ActiveEffects"][0]["Id"].py_data, 4)

    def test_apply_effects_rejects_non_list(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Liste"):
            apply_effects(tag, {})

    def test_validate_effect_accepts_valid(self):
        result = validate_effect({"id": 4, "amplifier": 2, "duration": 6000})
        self.assertEqual(result["id"], 4)
        self.assertEqual(result["amplifier"], 2)

    def test_validate_effect_rejects_fractional_integer_fields(self):
        base = {"id": 4, "amplifier": 2, "duration": 6000}
        for field, value in (("id", 4.9), ("amplifier", 2.9), ("duration", 6000.9)):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Effekt-Daten"):
                validate_effect({**base, field: value})

    def test_validate_effect_rejects_unknown_id(self):
        with self.assertRaisesRegex(ValueError, "Unbekannte Effekt-ID"):
            validate_effect({"id": 250, "amplifier": 0, "duration": 100})

    def test_validate_effect_rejects_id_outside_byte_range_before_database_lookup(self):
        for effect_id in (-1, 256):
            with self.subTest(effect_id=effect_id), self.assertRaisesRegex(ValueError, "gültigen Bereichs"):
                validate_effect({"id": effect_id, "amplifier": 0, "duration": 100})

    def test_validate_effect_rejects_amplifier_above_255(self):
        with self.assertRaisesRegex(ValueError, "Verstärkung"):
            validate_effect({"id": 4, "amplifier": 300, "duration": 100})

    def test_parse_effects_decodes_signed_byte_amplifier_as_unsigned(self):
        tag = make_minimal_player_tag()
        tag["ActiveEffects"] = nbt.ListTag(
            [
                nbt.CompoundTag(
                    {
                        "Id": nbt.ByteTag(4),
                        "Amplifier": nbt.ByteTag(-1),
                        "Duration": nbt.IntTag(100),
                    }
                ),
            ]
        )
        self.assertEqual(parse_effects(tag)[0]["amplifier"], 255)

    def test_apply_effects_encodes_high_amplifier_as_signed_byte(self):
        tag = make_minimal_player_tag()
        apply_effects(tag, [{"id": 4, "amplifier": 255, "duration": 100, "ambient": False, "show_particles": True, "show_icon": True}])
        self.assertEqual(tag["ActiveEffects"][0]["Amplifier"].py_data, -1)

    def test_apply_effects_rejects_duplicate_effect_ids(self):
        tag = make_minimal_player_tag()
        duplicate_effects = [
            {"id": 4, "amplifier": 1, "duration": 100, "ambient": False, "show_particles": True, "show_icon": True},
            {"id": 4, "amplifier": 2, "duration": 200, "ambient": False, "show_particles": True, "show_icon": True},
        ]
        with self.assertRaisesRegex(ValueError, "Doppelter Effekt"):
            apply_effects(tag, duplicate_effects)

    def test_apply_effects_preserves_unknown_effect_fields(self):
        tag = make_minimal_player_tag()
        tag["ActiveEffects"] = nbt.ListTag(
            [
                nbt.CompoundTag(
                    {
                        "Id": nbt.ByteTag(4),
                        "Amplifier": nbt.ByteTag(0),
                        "Duration": nbt.IntTag(100),
                        "CustomField": nbt.StringTag("keep"),
                    }
                ),
            ]
        )
        apply_effects(tag, [{"id": 4, "amplifier": 2, "duration": 200, "ambient": False, "show_particles": True, "show_icon": True}])
        effect = tag["ActiveEffects"][0]
        self.assertEqual(effect["Duration"].py_data, 200)
        self.assertEqual(effect["CustomField"].py_data, "keep")

    def test_apply_effects_preserves_original_unknown_effects(self):
        tag = make_minimal_player_tag()
        tag["ActiveEffects"] = nbt.ListTag(
            [
                nbt.CompoundTag(
                    {
                        "Id": nbt.ByteTag(-56),  # unsigned 200
                        "Amplifier": nbt.ByteTag(7),
                        "Duration": nbt.IntTag(12345),
                        "FutureField": nbt.StringTag("keep"),
                    }
                ),
            ]
        )
        apply_effects(tag, [{"id": 200, "amplifier": 99, "duration": 1, "ambient": False, "show_particles": False, "show_icon": False}])
        effect = tag["ActiveEffects"][0]
        self.assertEqual(effect["Id"].py_data, -56)
        self.assertEqual(effect["Amplifier"].py_data, 7)
        self.assertEqual(effect["Duration"].py_data, 12345)
        self.assertEqual(effect["FutureField"].py_data, "keep")

    def test_apply_effects_rejects_invented_unknown_effects(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Unbekannter Effekt"):
            apply_effects(tag, [{"id": 200, "amplifier": 0, "duration": 1, "ambient": False, "show_particles": True, "show_icon": True}])


class AbilitiesTests(unittest.TestCase):
    def test_parse_abilities_returns_empty_when_no_tag(self):
        tag = make_minimal_player_tag()
        self.assertEqual(parse_abilities(tag), {})

    def test_parse_abilities_returns_values(self):
        tag = make_minimal_player_tag()
        tag["abilities"] = nbt.CompoundTag(
            {
                "mayfly": nbt.ByteTag(1),
                "invulnerable": nbt.ByteTag(1),
                "mayBuild": nbt.ByteTag(1),
                "flySpeed": nbt.FloatTag(0.1),
                "walkSpeed": nbt.FloatTag(0.2),
            }
        )
        result = parse_abilities(tag)
        self.assertTrue(result["mayfly"])
        self.assertTrue(result["invulnerable"])
        self.assertTrue(result["maybuild"])
        self.assertAlmostEqual(result["fly_speed"], 0.1)
        self.assertAlmostEqual(result["walk_speed"], 0.2)

    def test_parse_abilities_accepts_legacy_lowercase_maybuild(self):
        tag = make_minimal_player_tag()
        tag["abilities"] = nbt.CompoundTag({"maybuild": nbt.ByteTag(0)})
        result = parse_abilities(tag)
        self.assertFalse(result["maybuild"])

    def test_apply_abilities_creates_tag(self):
        tag = make_minimal_player_tag()
        apply_abilities(tag, {"mayfly": True, "invulnerable": True, "maybuild": True})
        self.assertIn("abilities", tag)
        self.assertEqual(tag["abilities"]["mayfly"].py_data, 1)
        self.assertEqual(tag["abilities"]["mayBuild"].py_data, 1)
        self.assertNotIn("maybuild", tag["abilities"])

    def test_apply_abilities_canonicalizes_legacy_lowercase_maybuild(self):
        tag = make_minimal_player_tag()
        tag["abilities"] = nbt.CompoundTag({"maybuild": nbt.ByteTag(0)})
        apply_abilities(tag, {"maybuild": True})
        self.assertEqual(tag["abilities"]["mayBuild"].py_data, 1)
        self.assertNotIn("maybuild", tag["abilities"])

    def test_apply_abilities_rejects_invalid_fly_speed(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Fluggeschwindigkeit"):
            apply_abilities(tag, {"fly_speed": 5.0})

    def test_apply_abilities_does_nothing_when_empty(self):
        tag = make_minimal_player_tag()
        apply_abilities(tag, {})
        self.assertNotIn("abilities", tag)


class MoveCopyNbtPreservationTests(unittest.TestCase):
    def test_nbt_to_json_exposes_source_slot_for_preserving_moved_items(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Slot": nbt.ByteTag(7),
                                "Name": nbt.StringTag("minecraft:stone"),
                                "Count": nbt.ByteTag(1),
                                "Damage": nbt.ShortTag(0),
                            }
                        )
                    ]
                )
            }
        )
        inv, _orig = nbt_to_json(player)
        self.assertEqual(inv[7]["source_slot"], 7)

    def test_moving_item_preserves_unknown_root_and_tag_data_from_source_slot(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(4),
                "WasPickedUp": nbt.ByteTag(1),
                "FutureRootField": nbt.StringTag("keep-root"),
                "tag": nbt.CompoundTag(
                    {
                        "FutureTagField": nbt.StringTag("keep-tag"),
                        "ench": nbt.ListTag(
                            [nbt.CompoundTag({"id": nbt.ShortTag(999), "lvl": nbt.ShortTag(1), "FutureEnchantField": nbt.StringTag("keep-ench")})]
                        ),
                    }
                ),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})

        result = build_inventory_nbt(
            player,
            [
                {
                    "slot": 5,
                    "source_slot": 0,
                    "name": "minecraft:diamond_sword",
                    "count": 1,
                    "damage": 8,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [],
                }
            ],
            ENCHANTMENTS,
        )

        moved = result[0]
        self.assertEqual(moved["Slot"].py_data, 5)
        self.assertEqual(moved["Damage"].py_data, 8)
        self.assertEqual(moved["FutureRootField"].py_data, "keep-root")
        self.assertEqual(moved["tag"]["FutureTagField"].py_data, "keep-tag")
        self.assertEqual(moved["tag"]["ench"][0]["FutureEnchantField"].py_data, "keep-ench")

    def test_source_slot_is_not_used_when_item_id_changed(self):
        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:diamond_sword"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "FutureRootField": nbt.StringTag("do-not-carry-to-different-item"),
                "tag": nbt.CompoundTag({"FutureTagField": nbt.StringTag("do-not-carry-tag")}),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})

        result = build_inventory_nbt(
            player,
            [
                {
                    "slot": 5,
                    "source_slot": 0,
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

        self.assertNotIn("FutureRootField", result[0])
        self.assertNotIn("tag", result[0])


class TestFutureNbtEdgeCases(unittest.TestCase):
    def test_source_slot_uses_source_container_slot_range_for_inventory_to_ender_copy(self):
        item = validate_inventory_item(
            {
                "slot": 0,
                "source_slot": 35,
                "source_container": "inventory",
                "name": "minecraft:stone",
                "count": 1,
                "damage": 0,
                "display_name": "",
                "lore": [],
                "enchantments": [],
            },
            ENCHANTMENTS,
            is_ender_chest=True,
        )
        self.assertEqual(item["source_slot"], 35)

    def test_inventory_to_ender_copy_preserves_protected_nbt_from_high_inventory_slot(self):
        source_item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(35),
                "Name": nbt.StringTag("minecraft:diamond"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "FutureRootField": nbt.StringTag("keep-cross-container"),
            }
        )
        player = nbt.CompoundTag({"EnderChestInventory": nbt.ListTag([])})
        result = build_ender_chest_nbt(
            player,
            [
                {
                    "slot": 0,
                    "source_slot": 35,
                    "source_player_key": "player-a",
                    "source_container": "inventory",
                    "name": "minecraft:diamond",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [],
                }
            ],
            ENCHANTMENTS,
            source_item_maps={("player-a", "inventory"): {35: source_item}},
            target_player_key="player-a",
        )
        self.assertEqual(result[0]["FutureRootField"].py_data, "keep-cross-container")

    def test_normal_save_preserves_non_compound_display_tag_when_not_editing_display(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag({"display": nbt.StringTag("future-display-shape")}),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([item])})
        result = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "source_slot": 0,
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
        self.assertEqual(result[0]["tag"]["display"].py_data, "future-display-shape")

    def test_existing_unknown_item_id_case_is_preserved_on_normal_save(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("Addon:Future_Item"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "FutureRootField": nbt.StringTag("keep"),
            }
        )
        player = nbt.CompoundTag({"Inventory": nbt.ListTag([item])})
        result = build_inventory_nbt(
            player,
            [
                {
                    "slot": 0,
                    "source_slot": 0,
                    "name": "Addon:Future_Item",
                    "count": 1,
                    "damage": 0,
                    "display_name": "",
                    "lore": [],
                    "enchantments": [],
                }
            ],
            ENCHANTMENTS,
        )
        self.assertEqual(result[0]["Name"].py_data, "Addon:Future_Item")
        self.assertEqual(result[0]["FutureRootField"].py_data, "keep")

    def test_non_registry_item_cannot_be_created_but_existing_original_is_preserved(self):
        payload = {
            "slot": 0,
            "source_slot": 0,
            "name": "minecraft:element_32",
            "count": 1,
            "damage": 0,
            "display_name": "",
            "lore": [],
            "enchantments": [],
        }
        with self.assertRaisesRegex(ValueError, "kein von Mojang registriertes Inventaritem"):
            build_inventory_nbt(nbt.CompoundTag({"Inventory": nbt.ListTag([])}), [payload], ENCHANTMENTS)

        original = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:element_32"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
                "FutureRootField": nbt.StringTag("keep"),
            }
        )
        result = build_inventory_nbt(
            nbt.CompoundTag({"Inventory": nbt.ListTag([original])}),
            [payload],
            ENCHANTMENTS,
        )
        self.assertEqual(result[0]["Name"].py_data, "minecraft:element_32")
        self.assertEqual(result[0]["FutureRootField"].py_data, "keep")

    def test_opaque_ability_subfields_are_preserved_when_omitted(self):
        player = nbt.CompoundTag(
            {
                "abilities": nbt.CompoundTag(
                    {
                        "mayfly": nbt.IntTag(1),
                        "flying": nbt.ByteTag(0),
                        "flySpeed": nbt.DoubleTag(0.05),
                        "walkSpeed": nbt.FloatTag(0.1),
                    }
                )
            }
        )
        flags = protected_player_nbt_flags(player)
        self.assertEqual(flags["ability_fields_opaque"], {"fly_speed": "flySpeed", "mayfly": "mayfly"})
        apply_abilities(player, {"flying": True, "walk_speed": 0.3})
        self.assertIsInstance(player["abilities"]["mayfly"], nbt.IntTag)
        self.assertEqual(player["abilities"]["mayfly"].py_data, 1)
        self.assertIsInstance(player["abilities"]["flySpeed"], nbt.DoubleTag)
        self.assertEqual(player["abilities"]["flySpeed"].py_data, 0.05)
        self.assertEqual(player["abilities"]["flying"].py_data, 1)
        self.assertAlmostEqual(player["abilities"]["walkSpeed"].py_data, 0.3)

    def test_opaque_ability_subfield_write_is_rejected(self):
        player = nbt.CompoundTag({"abilities": nbt.CompoundTag({"mayfly": nbt.IntTag(1), "flying": nbt.ByteTag(0)})})
        with self.assertRaisesRegex(ValueError, "mayfly.*unbekannten NBT-Typ"):
            apply_abilities(player, {"mayfly": False})
        self.assertIsInstance(player["abilities"]["mayfly"], nbt.IntTag)
        self.assertEqual(player["abilities"]["mayfly"].py_data, 1)

    def test_known_effect_with_opaque_field_type_is_preserved(self):
        player = nbt.CompoundTag(
            {
                "ActiveEffects": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "Id": nbt.ByteTag(1),
                                "Amplifier": nbt.ByteTag(0),
                                "Duration": nbt.LongTag(1234),
                                "Ambient": nbt.ByteTag(0),
                                "ShowParticles": nbt.ByteTag(1),
                                "ShowIcon": nbt.ByteTag(1),
                                "FutureEffectField": nbt.StringTag("keep"),
                            }
                        )
                    ]
                )
            }
        )
        parsed = parse_effects(player)
        self.assertTrue(parsed[0]["opaque"])
        self.assertEqual(protected_player_nbt_flags(player)["active_effect_entries_opaque"], 1)
        apply_effects(player, parsed)
        effect = player["ActiveEffects"][0]
        self.assertIsInstance(effect["Duration"], nbt.LongTag)
        self.assertEqual(effect["Duration"].py_data, 1234)
        self.assertEqual(effect["FutureEffectField"].py_data, "keep")

    def test_normal_and_opaque_effect_with_same_id_are_both_preserved(self):
        normal = nbt.CompoundTag(
            {
                "Id": nbt.ByteTag(1),
                "Amplifier": nbt.ByteTag(0),
                "Duration": nbt.IntTag(600),
                "Ambient": nbt.ByteTag(0),
                "ShowParticles": nbt.ByteTag(1),
                "ShowIcon": nbt.ByteTag(1),
                "Marker": nbt.StringTag("normal"),
            }
        )
        opaque = nbt.CompoundTag(
            {
                "Id": nbt.ByteTag(1),
                "Amplifier": nbt.ByteTag(1),
                "Duration": nbt.LongTag(1200),
                "Ambient": nbt.ByteTag(0),
                "ShowParticles": nbt.ByteTag(1),
                "ShowIcon": nbt.ByteTag(1),
                "Marker": nbt.StringTag("opaque"),
            }
        )
        player = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([normal, opaque])})

        parsed = parse_effects(player)
        self.assertNotIn("opaque", parsed[0])
        self.assertTrue(parsed[1]["opaque"])
        self.assertEqual(protected_player_nbt_flags(player)["active_effect_entries_opaque"], 1)

        parsed[0]["duration"] = 700
        apply_effects(player, parsed)

        self.assertEqual(len(player["ActiveEffects"]), 2)
        by_marker = {effect["Marker"].py_data: effect for effect in player["ActiveEffects"]}
        self.assertEqual(by_marker["normal"]["Duration"].py_data, 700)
        self.assertIsInstance(by_marker["normal"]["Duration"], nbt.IntTag)
        self.assertEqual(by_marker["opaque"]["Duration"].py_data, 1200)
        self.assertIsInstance(by_marker["opaque"]["Duration"], nbt.LongTag)

    def test_duplicate_normal_effect_entry_is_treated_as_protected(self):
        first = nbt.CompoundTag(
            {
                "Id": nbt.ByteTag(1),
                "Amplifier": nbt.ByteTag(0),
                "Duration": nbt.IntTag(100),
                "Marker": nbt.StringTag("first"),
            }
        )
        duplicate = nbt.CompoundTag(
            {
                "Id": nbt.ByteTag(1),
                "Amplifier": nbt.ByteTag(1),
                "Duration": nbt.IntTag(200),
                "Marker": nbt.StringTag("duplicate"),
            }
        )
        player = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([first, duplicate])})

        parsed = parse_effects(player)
        self.assertNotIn("opaque", parsed[0])
        self.assertTrue(parsed[1]["opaque"])
        apply_effects(player, parsed)

        self.assertEqual(len(player["ActiveEffects"]), 2)
        self.assertEqual(
            {effect["Marker"].py_data for effect in player["ActiveEffects"]},
            {"first", "duplicate"},
        )

    def test_multiple_opaque_effect_entries_do_not_trip_duplicate_placeholder_id(self):
        first = nbt.StringTag("future-effect-a")
        second = nbt.StringTag("future-effect-b")
        player = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([first, second])})
        parsed = parse_effects(player)
        self.assertEqual([eff["id"] for eff in parsed], [-1, -1])
        apply_effects(player, parsed)
        self.assertEqual(len(player["ActiveEffects"]), 2)
        self.assertEqual(player["ActiveEffects"][0].py_data, "future-effect-a")
        self.assertEqual(player["ActiveEffects"][1].py_data, "future-effect-b")


if __name__ == "__main__":
    unittest.main()
