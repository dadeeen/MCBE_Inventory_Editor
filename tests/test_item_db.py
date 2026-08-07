import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mcbe_editor.item_data import (
    ADDABLE_ITEM_IDS,
    BLOCK_ITEM_IDS,
    BLOCK_ONLY_ITEM_IDS,
    COMPAT_ITEM_ALIASES,
    DURABILITY,
    EFFECTS,
    ENCHANTMENTS,
    ENCHANTMENT_COMPATIBILITY,
    ENCHANTMENT_ITEM_SLOT_SUFFIXES,
    ITEM_COMPONENTS,
    ITEMS,
    ITEM_DB_SOURCE_PATH,
    InvalidItemDatabaseError,
    canonical_item_id,
    enchantment_slots_for_item,
    get_max_damage,
    get_max_stack,
    is_addable_item_id,
    is_block_item_id,
    is_block_only_item_id,
    is_enchantable_item_id,
    is_enchantment_compatible_with_item,
    is_known_item_id,
    item_component,
    load_item_database,
)
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON


class TestGetMaxStack(unittest.TestCase):
    def test_returns_default_for_unknown_item(self):
        self.assertEqual(get_max_stack("minecraft:unknown"), 64)

    def test_returns_default_for_unlisted_item(self):
        self.assertEqual(get_max_stack("minecraft:stone"), 64)

    def test_returns_specific_limit_for_diamond_sword(self):
        self.assertEqual(get_max_stack("minecraft:diamond_sword"), 1)

    def test_returns_official_component_limits_for_spears(self):
        self.assertEqual(get_max_stack("minecraft:copper_spear"), 1)
        self.assertEqual(get_max_damage("minecraft:copper_spear"), 190)
        self.assertEqual(get_max_damage("minecraft:wooden_spear"), 60)
        self.assertEqual(get_max_damage("minecraft:netherite_spear"), 2030)
        self.assertEqual(
            ITEM_COMPONENTS["enchantable"]["minecraft:copper_spear"],
            {"slot": "melee_spear", "value": 13},
        )
        self.assertEqual(item_component("minecraft:copper_spear", "enchantable")["slot"], "melee_spear")

    def test_shipped_database_carries_official_item_components(self):
        """Die Komponenten-Extraktion darf nicht still ins Leere laufen.

        Bei einem Mojang-Layoutwechsel liefert ``parse_json_item_components``
        einfach nichts mehr, und alle Aufrufer fallen klaglos auf die
        Namensheuristik zurück. Der Verlust wäre ohne diesen Test unsichtbar.
        """

        enchantable = ITEM_COMPONENTS["enchantable"]
        self.assertGreaterEqual(len(enchantable), 7)
        for spear_material in ("copper", "diamond", "golden", "iron", "netherite", "stone", "wooden"):
            item_id = f"minecraft:{spear_material}_spear"
            self.assertEqual(enchantable[item_id]["slot"], "melee_spear", item_id)
        # Ohne die offizielle Komponente würde das _spear-Suffix hier den
        # Trident-Slot liefern und damit Impaling/Riptide statt Sharpness.
        self.assertEqual(enchantment_slots_for_item("minecraft:iron_spear"), {"melee_spear"})
        self.assertEqual(set(ITEM_COMPONENTS), {"enchantable", "wearable"})

    def test_returns_curated_engine_limits_for_damageable_items_missing_from_behavior_json(self):
        expected_durability = {
            "minecraft:brush": 64,
            "minecraft:copper_axe": 190,
            "minecraft:copper_boots": 143,
            "minecraft:copper_chestplate": 176,
            "minecraft:copper_helmet": 121,
            "minecraft:copper_hoe": 190,
            "minecraft:copper_leggings": 165,
            "minecraft:copper_pickaxe": 190,
            "minecraft:copper_shovel": 190,
            "minecraft:copper_sword": 190,
            "minecraft:mace": 500,
            "minecraft:turtle_helmet": 275,
            "minecraft:wolf_armor": 64,
        }
        for item_name, max_damage in expected_durability.items():
            with self.subTest(item_name=item_name):
                self.assertEqual(get_max_stack(item_name), 1)
                self.assertEqual(get_max_damage(item_name), max_damage)
        self.assertEqual(get_max_damage("minecraft:crossbow"), 464)

    def test_every_known_durable_vanilla_item_is_unstackable(self):
        for item_name in DURABILITY:
            with self.subTest(item_name=item_name):
                self.assertEqual(get_max_stack(item_name), 1)

    def test_returns_specific_limit_for_ender_pearl(self):
        self.assertEqual(get_max_stack("minecraft:ender_pearl"), 16)

    def test_returns_specific_limit_for_water_bucket(self):
        self.assertEqual(get_max_stack("minecraft:water_bucket"), 1)

    def test_returns_specific_limit_for_potions(self):
        self.assertEqual(get_max_stack("minecraft:potion"), 1)
        self.assertEqual(get_max_stack("minecraft:splash_potion"), 1)
        self.assertEqual(get_max_stack("minecraft:lingering_potion"), 1)

    def test_returns_curated_limits_for_variant_items_and_entity_buckets(self):
        self.assertEqual(get_max_stack("minecraft:bed"), 1)
        self.assertEqual(get_max_stack("minecraft:banner"), 16)
        self.assertEqual(get_max_stack("minecraft:goat_horn"), 1)
        self.assertEqual(get_max_stack("minecraft:suspicious_stew"), 1)
        self.assertEqual(get_max_stack("minecraft:axolotl_bucket"), 1)
        self.assertEqual(get_max_stack("minecraft:tropical_fish_bucket"), 1)

    def test_uses_canonical_limits_for_compatibility_aliases(self):
        self.assertTrue(is_known_item_id("minecraft:item.bed"))
        self.assertFalse("minecraft:item.bed" in ITEMS)
        self.assertEqual(canonical_item_id("minecraft:item.bed"), "minecraft:bed")
        self.assertEqual(get_max_stack("minecraft:item.bed"), get_max_stack("minecraft:bed"))

    def test_cornflower_is_a_first_class_known_item(self):
        self.assertTrue(is_known_item_id("minecraft:cornflower"))
        self.assertIn("minecraft:cornflower", ITEMS)
        self.assertEqual(ITEMS["minecraft:cornflower"], ("Kornblume", "Cornflower"))

    def test_keeps_reserved_runtime_ids_unknown(self):
        self.assertFalse(is_known_item_id("minecraft:reserved6"))

    def test_returns_default_for_air(self):
        self.assertEqual(get_max_stack("minecraft:air"), 64)

    def test_bundled_database_maps_and_identifier_lists_are_sorted(self):
        raw = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
        for section, value in raw.items():
            if isinstance(value, dict):
                self.assertEqual(list(value), sorted(value), section)
            elif isinstance(value, list) and all(isinstance(entry, str) for entry in value):
                self.assertEqual(value, sorted(value), section)


class TestEnchantmentCompatibility(unittest.TestCase):
    def test_compatibility_data_is_loaded_from_tracked_json(self):
        self.assertEqual(ENCHANTMENT_COMPATIBILITY["schema_version"], 1)
        self.assertIn("17", ENCHANTMENT_COMPATIBILITY["compatible_slots"])
        self.assertIn("g_tool", ENCHANTMENT_COMPATIBILITY["slot_groups"])
        self.assertIn(("_spear", "melee_spear"), ENCHANTMENT_ITEM_SLOT_SUFFIXES)

    def test_unbreaking_is_compatible_with_golden_sword(self):
        self.assertTrue(is_enchantment_compatible_with_item(17, "minecraft:golden_sword"))

    def test_tool_group_enchantments_include_swords(self):
        self.assertTrue(is_enchantment_compatible_with_item(26, "minecraft:golden_sword"))
        self.assertTrue(is_enchantment_compatible_with_item(28, "minecraft:golden_sword"))

    def test_digging_only_enchantments_still_exclude_swords(self):
        self.assertFalse(is_enchantment_compatible_with_item(18, "minecraft:golden_sword"))

    def test_melee_spear_uses_dedicated_bedrock_slot(self):
        self.assertEqual(enchantment_slots_for_item("minecraft:copper_spear"), {"melee_spear"})
        self.assertTrue(is_enchantment_compatible_with_item(41, "minecraft:copper_spear"))
        self.assertTrue(is_enchantment_compatible_with_item(9, "minecraft:copper_spear"))
        self.assertTrue(is_enchantment_compatible_with_item(17, "minecraft:copper_spear"))
        self.assertFalse(is_enchantment_compatible_with_item(31, "minecraft:copper_spear"))

    def test_trident_and_melee_spear_slots_stay_separate(self):
        self.assertEqual(enchantment_slots_for_item("minecraft:trident"), {"spear"})
        self.assertTrue(is_enchantment_compatible_with_item(31, "minecraft:trident"))
        self.assertFalse(is_enchantment_compatible_with_item(41, "minecraft:trident"))

    def test_cosmetic_head_items_accept_vanilla_curses(self):
        self.assertEqual(enchantment_slots_for_item("minecraft:carved_pumpkin"), {"cosmetic_head"})
        self.assertEqual(enchantment_slots_for_item("minecraft:player_head"), {"cosmetic_head"})
        self.assertEqual(enchantment_slots_for_item("minecraft:wither_skeleton_skull"), {"cosmetic_head"})
        self.assertTrue(is_enchantment_compatible_with_item(27, "minecraft:carved_pumpkin"))
        self.assertTrue(is_enchantment_compatible_with_item(28, "minecraft:player_head"))
        self.assertFalse(is_enchantment_compatible_with_item(17, "minecraft:player_head"))

    def test_enchanted_books_expand_all_vanilla_slots(self):
        for enchantment_id in ENCHANTMENTS:
            self.assertTrue(is_enchantment_compatible_with_item(enchantment_id, "minecraft:enchanted_book"))
        self.assertFalse(is_enchantable_item_id("minecraft:book"))

    def test_compatibility_data_covers_known_enchantments(self):
        from mcbe_editor.item_data import ENCHANTMENT_COMPATIBLE_SLOTS

        self.assertEqual(set(ENCHANTMENT_COMPATIBLE_SLOTS), set(ENCHANTMENTS))

    def test_available_enchantments_match_bedrock_relevant_wiki_rows(self):
        normalized_names = {values[1].lower().replace(" ", "_") for values in ENCHANTMENTS.values()}

        self.assertIn("lunge", normalized_names)
        self.assertIn("wind_burst", normalized_names)
        self.assertNotIn("sweeping_edge", normalized_names)
        self.assertNotIn("cleaving", normalized_names)


if __name__ == "__main__":
    unittest.main()


class TestJsonBackedItemDb(unittest.TestCase):
    def test_json_database_is_loaded_directly(self):
        self.assertTrue(ITEM_DB_SOURCE_PATH.replace("\\", "/").endswith("mcbe_editor/resources/item_db.json"))
        self.assertIn("minecraft:air", ITEMS)
        self.assertIn("minecraft:potion", ITEMS)
        self.assertIn("minecraft:item.bed", COMPAT_ITEM_ALIASES)

    def test_enderchest_legacy_id_aliases_to_ender_chest(self):
        self.assertTrue(is_known_item_id("minecraft:enderchest"))
        self.assertEqual(canonical_item_id("minecraft:enderchest"), "minecraft:ender_chest")

    def test_glazed_terracotta_uses_real_bedrock_ids_with_german_names(self):
        # Echte IDs laut mojang-items.json; Hellgrau heißt in Bedrock "silver".
        colors = (
            "white",
            "orange",
            "magenta",
            "light_blue",
            "yellow",
            "lime",
            "pink",
            "gray",
            "silver",
            "cyan",
            "purple",
            "blue",
            "brown",
            "green",
            "red",
            "black",
        )
        for color in colors:
            item_id = f"minecraft:{color}_glazed_terracotta"
            self.assertIn(item_id, ITEMS)
            de, en = ITEMS[item_id]
            self.assertIn("glasierte Keramik", de, item_id)
            self.assertIn("Glazed Terracotta", en, item_id)
            self.assertNotEqual(de, en, item_id)
        self.assertEqual(ITEMS["minecraft:silver_glazed_terracotta"], ("Hellgraue glasierte Keramik", "Light Gray Glazed Terracotta"))

    def test_glazed_terracotta_localization_keys_are_aliases_not_items(self):
        # tile.glazedTerracotta*.name sind Lokalisierungsschlüssel; als Item-ID
        # geschrieben verwirft Minecraft den Slot. Sie bleiben nur als Alias lesbar.
        self.assertFalse(any(key.startswith("minecraft:glazedterracotta") for key in ITEMS))
        self.assertEqual(canonical_item_id("minecraft:glazedterracotta"), "minecraft:white_glazed_terracotta")
        for source, target in COMPAT_ITEM_ALIASES.items():
            if not source.startswith("minecraft:glazedterracotta"):
                continue
            self.assertTrue(is_known_item_id(source))
            self.assertIn(target, ITEMS)
            self.assertTrue(target.endswith("_glazed_terracotta"), target)
        self.assertEqual(canonical_item_id("minecraft:glazedterracottablack"), "minecraft:black_glazed_terracotta")
        self.assertEqual(canonical_item_id("minecraft:glazedterracottasilver"), "minecraft:silver_glazed_terracotta")

    def test_dotted_localization_key_families_have_german_names_on_real_item_ids(self):
        expected = {
            "minecraft:acacia_boat": ("Akazienboot", "Acacia Boat"),
            "minecraft:acacia_chest_boat": ("Akazien-Truhenboot", "Acacia Chest Boat"),
            "minecraft:allay_spawn_egg": ("Hilfsgeist-Spawn-Ei", "Allay Spawn Egg"),
            "minecraft:oak_slab": ("Eichenstufe", "Oak Slab"),
            "minecraft:andesite_wall": ("Andesitmauer", "Andesite Wall"),
        }
        for item_id, names in expected.items():
            self.assertEqual(ITEMS[item_id], names)
        self.assertFalse(any("boat.acacia" in item_id for item_id in ITEMS))
        self.assertFalse(any("spawn_egg.entity" in item_id for item_id in ITEMS))

    def test_stonecutter_entries_are_distinguishable(self):
        # minecraft:stonecutter ist der Legacy-Block ohne Funktion; nur
        # minecraft:stonecutter_block steht in Mojangs Item-Liste.
        self.assertEqual(ITEMS["minecraft:stonecutter_block"], ("Steinsäge", "Stonecutter"))
        legacy_de, legacy_en = ITEMS["minecraft:stonecutter"]
        self.assertNotEqual((legacy_de, legacy_en), ITEMS["minecraft:stonecutter_block"])
        self.assertIn("ohne Funktion", legacy_de)
        self.assertIn("Legacy", legacy_en)

    def test_entity_variant_labels_are_not_items(self):
        self.assertNotIn("minecraft:axolotlcolorblue", ITEMS)
        self.assertFalse(is_known_item_id("minecraft:axolotlcolorblue"))
        self.assertNotIn("minecraft:tropicalcolorblue", ITEMS)
        self.assertFalse(is_known_item_id("minecraft:tropicalcolorblue"))
        self.assertNotIn("minecraft:tropicalschoolclownfish", ITEMS)
        self.assertFalse(is_known_item_id("minecraft:tropicalschoolclownfish"))


class TestBlockOnlyItemIds(unittest.TestCase):
    def test_block_only_section_flags_technical_block_forms(self):
        # Laut Mojang-Registries Block, aber kein Item: solche IDs ergeben im
        # Inventar keine brauchbaren Items (Steinsäge-Muster) und werden aus
        # den Vorschlägen ausgeblendet.
        self.assertGreaterEqual(len(BLOCK_ONLY_ITEM_IDS), 300)
        for item_id in (
            "minecraft:acacia_standing_sign",
            "minecraft:acacia_wall_sign",
            "minecraft:oak_double_slab",
            "minecraft:candle_cake",
            "minecraft:bubble_column",
            "minecraft:brain_coral_wall_fan",
            "minecraft:fire",
            # Legacy-IDs (Vor-Flattening) und experimentelle Holzarten stehen in
            # keiner Registry; das Suffix-Muster markiert sie trotzdem.
            "minecraft:double_wooden_slab",
            "minecraft:double_stone_slab4",
            "minecraft:poplar_double_slab",
            "minecraft:poplar_standing_sign",
        ):
            self.assertIn(item_id, BLOCK_ONLY_ITEM_IDS, item_id)
            self.assertTrue(is_block_only_item_id(item_id), item_id)
            # Anzeige-Namen für Alt-Inventare bleiben erhalten.
            self.assertIn(item_id, ITEMS, item_id)

    def test_real_items_are_never_flagged_block_only(self):
        for item_id in (
            "minecraft:oak_slab",
            "minecraft:oak_sign",
            "minecraft:cake",
            "minecraft:stonecutter_block",
            "minecraft:white_glazed_terracotta",
            "minecraft:diamond_sword",
            # Experimentelle Basis-Items bleiben vorschlagbar.
            "minecraft:poplar_slab",
            "minecraft:poplar_sign",
        ):
            self.assertNotIn(item_id, BLOCK_ONLY_ITEM_IDS, item_id)
            self.assertFalse(is_block_only_item_id(item_id), item_id)

    def test_block_only_ids_reference_catalog_entries(self):
        missing = sorted(item_id for item_id in BLOCK_ONLY_ITEM_IDS if item_id not in ITEMS)
        self.assertEqual(missing, [])


class TestAddableItemIds(unittest.TestCase):
    def test_positive_registry_separates_new_items_from_preserved_catalog(self):
        self.assertGreaterEqual(len(ADDABLE_ITEM_IDS), 1500)
        for item_id in ("minecraft:apple", "minecraft:wooden_button", "minecraft:turtle_egg", "minecraft:allow"):
            self.assertTrue(is_addable_item_id(item_id), item_id)
        for item_id in (
            "minecraft:element_32",
            "minecraft:oak_double_slab",
            "minecraft:written_book",
            "minecraft:entity_axolotl_gold",
        ):
            self.assertFalse(is_addable_item_id(item_id), item_id)

    def test_every_addable_id_has_its_own_display_names(self):
        # Registry-IDs dürfen für technische Fallbacks auf eine ältere
        # Serialisierung zeigen, müssen im Browser aber ihre eigene Identität
        # behalten (z. B. Andesit statt Stein).
        missing = sorted(item_id for item_id in ADDABLE_ITEM_IDS if item_id not in ITEMS)
        self.assertEqual(missing, [])

    def test_modern_serialization_aliases_keep_distinct_display_names(self):
        expected = {
            "minecraft:allium": ("Zierlauch", "Allium"),
            "minecraft:andesite": ("Andesit", "Andesite"),
            "minecraft:diorite": ("Diorit", "Diorite"),
            "minecraft:fern": ("Farn", "Fern"),
            "minecraft:granite": ("Granit", "Granite"),
            "minecraft:lilac": ("Flieder", "Lilac"),
            "minecraft:peony": ("Pfingstrose", "Peony"),
            "minecraft:sunflower": ("Sonnenblume", "Sunflower"),
        }
        for item_id, names in expected.items():
            self.assertEqual(ITEMS[item_id], names)


class TestBlockItemIds(unittest.TestCase):
    def test_block_item_section_tracks_registry_intersection(self):
        self.assertGreaterEqual(len(BLOCK_ITEM_IDS), 900)
        for item_id in (
            "minecraft:black_shulker_box",
            "minecraft:brewing_stand",
            "minecraft:cake",
            "minecraft:crafter",
            "minecraft:hopper",
            "minecraft:kelp",
        ):
            self.assertIn(item_id, BLOCK_ITEM_IDS, item_id)
            self.assertTrue(is_block_item_id(item_id), item_id)

    def test_block_items_are_known_items_and_never_block_only(self):
        self.assertEqual(sorted(BLOCK_ITEM_IDS - set(ITEMS)), [])
        self.assertEqual(sorted(BLOCK_ITEM_IDS & BLOCK_ONLY_ITEM_IDS), [])
        self.assertNotIn("minecraft:beetroot", BLOCK_ITEM_IDS)
        self.assertNotIn("minecraft:wheat", BLOCK_ITEM_IDS)


class TestEffectDescriptions(unittest.TestCase):
    def test_bundled_effects_have_distinct_german_and_english_descriptions(self):
        self.assertTrue(EFFECTS)
        for effect_id, effect in EFFECTS.items():
            self.assertEqual(len(effect), 4, effect_id)
            _name_de, _name_en, description_de, description_en = effect
            self.assertTrue(description_de.strip(), effect_id)
            self.assertTrue(description_en.strip(), effect_id)
            self.assertNotEqual(description_de, description_en, effect_id)


class TestBundledCurationForPersistentCopies(unittest.TestCase):
    def test_load_reconciles_persistent_copy_with_bundled_curation(self):
        # Persistente Kopien (data/item_db.json) erhalten vom Updater nur
        # Ergänzungen. Kuratierte Korrekturen der gebündelten DB müssen beim
        # Laden übernommen werden, sonst bleiben Altinstallationen fehlerhaft.
        from mcbe_editor.item_data import load_item_database

        legacy_db = {
            "schema_version": 1,
            "defaults": {"max_stack": 64, "max_damage": 1561, "max_data_value": 32767},
            "stack_limits": {},
            "durability": {},
            "effects": {
                "1": ["Lokales Tempo", "Local Speed", "Legacy English description."],
                "99": ["Nautilusatem", "Breath of the Nautilus", "Legacy DE.", "Legacy EN."],
            },
            "enchantments": {
                "40": ["Durchbruch", "Breach", 4, ""],
                "41": ["Dichte", "Density", 5, ""],
                "42": ["Ausfallschritt", "Lunge", 3, ""],
                "44": ["Windstoß", "Wind Burst", 3, ""],
                "99": ["Add-on-Zauber", "Add-on Enchantment", 1, ""],
            },
            "compat_item_aliases": {"minecraft:enderchest": "minecraft:ender_chest"},
            "items": {
                "minecraft:glazedterracottablack": ["Schwarze glasierte Keramik", "Black Glazed Terracotta"],
                "minecraft:black_glazed_terracotta": ["Black Glazed Terracotta", "Black Glazed Terracotta"],
                "minecraft:silver_glazed_terracotta": ["Silver Glazed Terracotta", "Silver Glazed Terracotta"],
                "minecraft:stonecutter": ["Steinsäge", "Stonecutter"],
                "minecraft:stonecutter_block": ["Steinsäge", "Stonecutter"],
                "minecraft:cornflower": ["Kornblume", "Cornflower"],
                "minecraft:brand_new_item": ["Brand New Item", "Brand New Item"],
                "minecraft:acacia_boat": ["Acacia Boat", "Acacia Boat"],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text(json.dumps(legacy_db, ensure_ascii=False), encoding="utf-8")
            db = load_item_database(db_path)

        items = db["ITEMS"]
        aliases = db["COMPAT_ITEM_ALIASES"]
        # Pseudo-ID verschwindet aus dem Katalog, bleibt aber als Alias lesbar.
        self.assertNotIn("minecraft:glazedterracottablack", items)
        self.assertEqual(aliases["minecraft:glazedterracottablack"], "minecraft:black_glazed_terracotta")
        self.assertEqual(aliases["minecraft:enderchest"], "minecraft:ender_chest")
        # Fallback-Labels (de == en) übernehmen die gebündelte Übersetzung.
        self.assertEqual(items["minecraft:black_glazed_terracotta"], ("Schwarze glasierte Keramik", "Black Glazed Terracotta"))
        self.assertEqual(items["minecraft:silver_glazed_terracotta"], ("Hellgraue glasierte Keramik", "Light Gray Glazed Terracotta"))
        self.assertEqual(items["minecraft:acacia_boat"], ("Akazienboot", "Acacia Boat"))
        # Neue kuratierte Registry-IDs müssen auch in bereits vorhandenen
        # persistenten Kopien eigene Anzeigenamen erhalten.
        self.assertEqual(items["minecraft:andesite"], ("Andesit", "Andesite"))
        self.assertEqual(items["minecraft:diorite"], ("Diorit", "Diorite"))
        self.assertEqual(items["minecraft:granite"], ("Granit", "Granite"))
        self.assertEqual(sorted(db["ADDABLE_ITEM_IDS"] - set(items)), [])
        # Bekannter Altstand des Legacy-Stonecutters wird migriert.
        self.assertEqual(items["minecraft:stonecutter"], ("Steinsäge (alt, ohne Funktion)", "Stonecutter (Legacy, No Function)"))
        self.assertEqual(items["minecraft:stonecutter_block"], ("Steinsäge", "Stonecutter"))
        # Erstklassige Alias-Quellen und unbekannte neue Einträge bleiben erhalten.
        self.assertIn("minecraft:cornflower", items)
        self.assertIn("minecraft:brand_new_item", items)
        # Alte Kopien ohne block_only_items-Sektion erben die gebündelte Liste.
        self.assertIn("minecraft:acacia_standing_sign", db["BLOCK_ONLY_ITEM_IDS"])
        self.assertIn("minecraft:oak_double_slab", db["BLOCK_ONLY_ITEM_IDS"])
        # Dasselbe gilt für die registry-basierten Browser-Blocktags.
        self.assertIn("minecraft:black_shulker_box", db["BLOCK_ITEM_IDS"])
        self.assertIn("minecraft:hopper", db["BLOCK_ITEM_IDS"])
        # Sicherheitsrelevante Stackgrenzen gelten auch für persistente
        # Altstände, denen diese neuere Kuration noch fehlt.
        self.assertEqual(db["STACK_LIMITS"]["minecraft:bed"], 1)
        self.assertEqual(db["STACK_LIMITS"]["minecraft:banner"], 16)
        self.assertEqual(db["STACK_LIMITS"]["minecraft:axolotl_bucket"], 1)
        self.assertEqual(db["STACK_LIMITS"]["minecraft:iron_hoe"], 1)
        self.assertEqual(db["STACK_LIMITS"]["minecraft:leather_chestplate"], 1)
        # Normale Haltbarkeit darf auch mit einer persistenten Altdatei nicht
        # als geschützte Zusatz-NBT fehlklassifiziert werden.
        self.assertEqual(db["DURABILITY"]["minecraft:mace"], 500)
        self.assertEqual(db["DURABILITY"]["minecraft:copper_sword"], 190)
        self.assertEqual(db["DURABILITY"]["minecraft:crossbow"], 464)
        self.assertEqual(
            db["ITEM_COMPONENTS"]["enchantable"]["minecraft:copper_spear"],
            {"slot": "melee_spear", "value": 13},
        )
        # Schema-1-Beschreibungen werden durch eigenständige, lokalisierte
        # Projekttexte aus der gebündelten Datenbank ersetzt.
        self.assertEqual(db["EFFECTS"][1][:2], ("Lokales Tempo", "Local Speed"))
        self.assertEqual(db["EFFECTS"][1][2:], EFFECTS[1][2:])
        self.assertNotIn(99, db["EFFECTS"])
        self.assertEqual(db["EFFECTS"][37][:2], ("Nautilusatem", "Breath of the Nautilus"))
        self.assertEqual(db["EFFECTS"][37][2:], EFFECTS[37][2:])
        # Auch die fehlerhafte frühere Vergabe moderner Verzauberungs-IDs wird
        # in persistenten Kopien zur Laufzeit auf die geprüften Bedrock-IDs
        # zurückgeführt. Ein fremder Add-on-Eintrag bleibt erhalten.
        self.assertEqual(db["ENCHANTMENTS"][38][1], "Wind Burst")
        self.assertEqual(db["ENCHANTMENTS"][39][1], "Density")
        self.assertEqual(db["ENCHANTMENTS"][40][1], "Breach")
        self.assertEqual(db["ENCHANTMENTS"][41][1], "Lunge")
        self.assertNotIn(42, db["ENCHANTMENTS"])
        self.assertNotIn(44, db["ENCHANTMENTS"])
        self.assertEqual(db["ENCHANTMENTS"][99][1], "Add-on Enchantment")
        self.assertEqual(db["SCHEMA_VERSION"], 3)

    def test_newer_bundled_behavior_data_replaces_stale_persistent_values(self):
        legacy_db = {
            "schema_version": 3,
            "items": {},
            "stack_limits": {
                "minecraft:manual": 16,
                "minecraft:removed_behavior_item": 8,
                "minecraft:copper_spear": 2,
            },
            "durability": {
                "minecraft:manual": 12,
                "minecraft:removed_behavior_item": 99,
                "minecraft:copper_spear": 191,
            },
            "item_components": {
                "enchantable": {
                    "minecraft:copper_spear": {"slot": "melee_spear", "value": 1},
                },
            },
            "behavior_item_source": {
                "resource_pack_release": "v1.25.0.0",
                "stack_limit_items": [
                    "minecraft:copper_spear",
                    "minecraft:removed_behavior_item",
                ],
                "durability_items": [
                    "minecraft:copper_spear",
                    "minecraft:removed_behavior_item",
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text(json.dumps(legacy_db), encoding="utf-8")
            db = load_item_database(db_path)

        self.assertEqual(db["STACK_LIMITS"]["minecraft:manual"], 16)
        self.assertEqual(db["DURABILITY"]["minecraft:manual"], 12)
        self.assertNotIn("minecraft:removed_behavior_item", db["STACK_LIMITS"])
        self.assertNotIn("minecraft:removed_behavior_item", db["DURABILITY"])
        self.assertEqual(db["STACK_LIMITS"]["minecraft:copper_spear"], 1)
        self.assertEqual(db["DURABILITY"]["minecraft:copper_spear"], 190)
        self.assertEqual(
            db["ITEM_COMPONENTS"]["enchantable"]["minecraft:copper_spear"],
            {"slot": "melee_spear", "value": 13},
        )

    def test_newer_persistent_behavior_data_is_not_masked_by_older_bundle(self):
        future_db = {
            "schema_version": 3,
            "items": {},
            "stack_limits": {"minecraft:copper_spear": 2},
            "durability": {"minecraft:copper_spear": 191},
            "item_components": {
                "enchantable": {
                    "minecraft:copper_spear": {"slot": "melee_spear", "value": 14},
                },
            },
            "behavior_item_source": {
                "resource_pack_release": "v9.0.0.0",
                "stack_limit_items": ["minecraft:copper_spear"],
                "durability_items": ["minecraft:copper_spear"],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text(json.dumps(future_db), encoding="utf-8")
            db = load_item_database(db_path)

        self.assertEqual(db["STACK_LIMITS"]["minecraft:copper_spear"], 2)
        self.assertEqual(db["DURABILITY"]["minecraft:copper_spear"], 191)
        self.assertEqual(
            db["ITEM_COMPONENTS"]["enchantable"]["minecraft:copper_spear"],
            {"slot": "melee_spear", "value": 14},
        )

    def test_bundle_wins_for_same_release_so_packaged_corrections_are_not_masked(self):
        bundled_source = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))["behavior_item_source"]
        same_release_db = {
            "schema_version": 3,
            "items": {},
            "stack_limits": {"minecraft:copper_spear": 2},
            "durability": {"minecraft:copper_spear": 191},
            "item_components": {
                "enchantable": {
                    "minecraft:copper_spear": {"slot": "melee_spear", "value": 1},
                },
            },
            "behavior_item_source": {
                "resource_pack_release": bundled_source["resource_pack_release"],
                "stack_limit_items": ["minecraft:copper_spear"],
                "durability_items": ["minecraft:copper_spear"],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text(json.dumps(same_release_db), encoding="utf-8")
            db = load_item_database(db_path)

        self.assertEqual(db["STACK_LIMITS"]["minecraft:copper_spear"], 1)
        self.assertEqual(db["DURABILITY"]["minecraft:copper_spear"], 190)
        self.assertEqual(
            db["ITEM_COMPONENTS"]["enchantable"]["minecraft:copper_spear"],
            {"slot": "melee_spear", "value": 13},
        )


class TestItemDbStatusApi(unittest.TestCase):
    def test_item_db_status_route_reports_loaded_database(self):
        from main import app
        from mcbe_editor.item_data import EFFECTS, ENCHANTMENTS, ENCHANTMENT_COMPATIBLE_SLOTS

        client = app.test_client()
        resp = client.get("/api/item-db/status")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        status = data["item_db"]
        self.assertIn(status["status"], {"ok", "metadata-missing"})
        self.assertEqual(status["schema_version"], 3)
        self.assertEqual(status["counts"]["items"], len(ITEMS))
        self.assertEqual(status["counts"]["compat_item_aliases"], len(COMPAT_ITEM_ALIASES))
        self.assertEqual(status["counts"]["block_items"], len(BLOCK_ITEM_IDS))
        self.assertEqual(status["counts"]["effects"], len(EFFECTS))
        self.assertEqual(status["counts"]["enchantments"], len(ENCHANTMENTS))
        self.assertEqual(status["counts"]["enchantment_compatibility"], len(ENCHANTMENT_COMPATIBLE_SLOTS))
        self.assertEqual(status["enchantment_compatibility"]["schema_version"], 1)
        self.assertTrue(status["path"].endswith("item_db.json"))

    def test_item_db_versions_route_reports_history_inline_data(self):
        from main import app

        client = app.test_client()
        resp = client.get("/api/item-db/versions")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["entries"], list)
        self.assertEqual(data["count"], len(data["entries"]))


class ExclusiveEnchantmentGroupTests(unittest.TestCase):
    def test_exclusive_groups_reference_known_enchantments(self):
        from mcbe_editor.item_data import ENCHANTMENT_COMPATIBILITY, ENCHANTMENTS

        groups = ENCHANTMENT_COMPATIBILITY.get("exclusive_groups")
        self.assertIsInstance(groups, list)
        self.assertGreaterEqual(len(groups), 8)
        known_ids = {int(key) for key in ENCHANTMENTS}
        for group in groups:
            self.assertIsInstance(group, list)
            self.assertGreaterEqual(len(group), 2)
            for ench_id in group:
                self.assertIn(int(ench_id), known_ids)

    def test_exclusive_groups_cover_wiki_rules(self):
        from mcbe_editor.item_data import ENCHANTMENT_COMPATIBILITY

        groups = [set(group) for group in ENCHANTMENT_COMPATIBILITY["exclusive_groups"]]

        def conflicting(a, b):
            return any(a in group and b in group for group in groups)

        # Kernregeln laut Minecraft Wiki "Enchanting".
        self.assertTrue(conflicting(9, 10))  # Schärfe <-> Bann
        self.assertTrue(conflicting(0, 4))  # Schutz <-> Schusssicher
        self.assertTrue(conflicting(16, 18))  # Behutsamkeit <-> Glück
        self.assertTrue(conflicting(22, 26))  # Unendlichkeit <-> Reparatur
        self.assertTrue(conflicting(30, 31))  # Sog <-> Treue
        self.assertTrue(conflicting(30, 32))  # Sog <-> Entladung
        self.assertTrue(conflicting(39, 40))  # Dichte <-> Durchbruch
        self.assertTrue(conflicting(33, 34))  # Mehrfachschuss <-> Durchschuss
        self.assertTrue(conflicting(7, 25))  # Wasserläufer <-> Eisläufer
        # Treue + Entladung sind ausdrücklich kompatibel.
        self.assertFalse(conflicting(31, 32))


class TestPersistentItemDbRecovery(unittest.TestCase):
    def test_configured_missing_database_is_seeded_at_configured_path(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"

            with patch.dict("os.environ", {"MCBE_ITEM_DB_PATH": str(db_path)}):
                db = load_item_database()

            self.assertEqual(Path(db["SOURCE_PATH"]), db_path)
            self.assertTrue(db_path.is_file())
            self.assertIn("minecraft:air", json.loads(db_path.read_text(encoding="utf-8"))["items"])

    def test_configured_corrupt_database_is_quarantined_and_reseeded(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text('{"schema_version":', encoding="utf-8")

            with patch.dict("os.environ", {"MCBE_ITEM_DB_PATH": str(db_path)}):
                db = load_item_database()

            self.assertEqual(Path(db["SOURCE_PATH"]), db_path)
            self.assertIn("minecraft:air", db["ITEMS"])
            self.assertEqual(json.loads(db_path.read_text(encoding="utf-8"))["schema_version"], 3)
            quarantined = list(db_path.parent.glob("item_db.invalid-*.json"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_text(encoding="utf-8"), '{"schema_version":')

    def test_configured_semantically_invalid_database_is_recovered(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text('{"schema_version":1,"items":[]}', encoding="utf-8")

            with patch.dict("os.environ", {"MCBE_ITEM_DB_PATH": str(db_path)}):
                db = load_item_database()

            self.assertIn("minecraft:air", db["ITEMS"])
            self.assertEqual(len(list(db_path.parent.glob("item_db.invalid-*.json"))), 1)

    def test_explicit_invalid_database_is_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            original = '{"schema_version":'
            db_path.write_text(original, encoding="utf-8")

            with self.assertRaises(InvalidItemDatabaseError):
                load_item_database(db_path)

            self.assertEqual(db_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(db_path.parent.glob("item_db.invalid-*.json")), [])

    def test_explicit_database_rejects_unknown_enchantable_component_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "items": {},
                        "item_components": {
                            "enchantable": {
                                "minecraft:future_item": {"slot": "future_slot", "value": 1},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(InvalidItemDatabaseError):
                load_item_database(db_path)

    def test_failed_reseed_restores_original_corrupt_database(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            original = '{"schema_version":'
            db_path.write_text(original, encoding="utf-8")

            with (
                patch.dict("os.environ", {"MCBE_ITEM_DB_PATH": str(db_path)}),
                patch("mcbe_editor.item_data.atomic_seed_file", side_effect=OSError("simulated full volume")),
                self.assertRaisesRegex(OSError, "full volume"),
            ):
                load_item_database()

            self.assertEqual(db_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(db_path.parent.glob("item_db.invalid-*.json")), [])

    def test_deeply_nested_configured_database_is_recovered(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            db_path.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")

            with patch.dict("os.environ", {"MCBE_ITEM_DB_PATH": str(db_path)}):
                db = load_item_database()

            self.assertIn("minecraft:air", db["ITEMS"])
            self.assertEqual(len(list(db_path.parent.glob("item_db.invalid-*.json"))), 1)

    def test_concurrent_recovery_preserves_one_quarantine_copy(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "item_db.json"
            original = '{"schema_version":'
            db_path.write_text(original, encoding="utf-8")
            workers = 8
            barrier = threading.Barrier(workers)

            def load_after_barrier(_index):
                barrier.wait(timeout=5)
                return load_item_database()["SOURCE_PATH"]

            with (
                patch.dict("os.environ", {"MCBE_ITEM_DB_PATH": str(db_path)}),
                ThreadPoolExecutor(max_workers=workers) as executor,
            ):
                results = list(executor.map(load_after_barrier, range(workers)))

            self.assertEqual(results, [str(db_path)] * workers)
            quarantined = list(db_path.parent.glob("item_db.invalid-*.json"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_text(encoding="utf-8"), original)
            self.assertIn("minecraft:air", json.loads(db_path.read_text(encoding="utf-8"))["items"])
