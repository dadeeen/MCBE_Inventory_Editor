"""Shared exact-match migrations for reviewed Vanilla item labels.

Only known shipped pairs are replaced; user-defined names remain unchanged.
Replacement names come from the bundled catalog, never a second name table.
"""

from __future__ import annotations

from collections.abc import Mapping

from .update_source_quality import resolve_names

# Exact reviewed source/catalog pairs, not an exemption for these IDs in general.
# A changed source or catalog label must return to the ordinary comparison.
EXPECTED_ITEM_NAME_DIFFERENCES = {
    "minecraft:bed": (("Weißes Bett", "White Bed"), ("Bett", "Bed")),
    "minecraft:yellow_flower": (("Löwenzahn", "Dandelion"), ("Blume", "Flower")),
    "minecraft:stonecutter": (("Steinsäge (alt, ohne Funktion)", "Stonecutter (Legacy, No Function)"), ("Steinsäge", "Stonecutter")),
    "minecraft:undyed_shulker_box": (("Shulker-Kiste (ungefärbt)", "Undyed Shulker Box"), ("Shulker-Kiste", "Shulker Box")),
    "minecraft:petrified_oak_slab": (("Versteinerte Eichenstufe", "Petrified Oak Slab"), ("Holzstufe", "Wooden Slab")),
    "minecraft:underwater_tnt": (("Unterwasser-TNT", "Underwater TNT"), ("TNT", "TNT")),
    **{f"minecraft:light_block_{level}": ((f"Lichtblock {level}", f"Light Block {level}"), ("Hell", "Light")) for level in range(16)},
}


def is_expected_item_name_difference(item_id: str, names, source_names: Mapping) -> bool:
    expected = EXPECTED_ITEM_NAME_DIFFERENCES.get(item_id)
    if expected is None or not isinstance(names, (list, tuple)):
        return False
    catalog_pair, source_pair = expected
    return tuple(names) == catalog_pair and tuple(source_names.get(locale, {}).get(item_id) for locale in ("de", "en")) == source_pair


def _complete_pair(pair) -> bool:
    return isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(name, str) and name.strip() for name in pair)


def reviewed_variant_name_overrides(item_id: str, catalog: Mapping, source_names: Mapping) -> dict[str, str]:
    """Keep reviewed distinctions only when the source uses a known less specific name."""
    reviewed = catalog.get(item_id)
    if not _complete_pair(reviewed):
        return {}
    generic_pairs = []
    if item_id in LEGACY_VARIANT_GROUP_IDS:
        # These catalog groups carry an editorial color/type qualifier. A
        # double slab can also receive the name of its corresponding single slab.
        single_id = item_id.replace("double_stone_block_slab", "stone_block_slab").replace("_double_slab", "_slab")
        generic_pairs.append(tuple(name.partition(" (")[0] for name in reviewed))
        single = catalog.get(single_id)
        if single_id != item_id and _complete_pair(single):
            generic_pairs.extend((single, tuple(name.partition(" (")[0] for name in single)))
            expected_single = EXPECTED_ITEM_NAME_DIFFERENCES.get(single_id)
            if expected_single and tuple(single) == expected_single[0]:
                generic_pairs.append(expected_single[1])
    expected = EXPECTED_ITEM_NAME_DIFFERENCES.get(item_id)
    if expected and tuple(reviewed) == expected[0]:
        generic_pairs.append(expected[1])
    return {
        locale: reviewed[i]
        for i, locale in enumerate(("de", "en"))
        if source_names.get(locale) != reviewed[i] and any(source_names.get(locale) == pair[i] for pair in generic_pairs)
    }


SUPERSEDED_ITEM_LABELS: dict[str, tuple[str, str]] = {
    # Der Legacy-Block minecraft:stonecutter war identisch zur funktionalen
    # minecraft:stonecutter_block beschriftet; im Spiel ist er ohne Funktion.
    "minecraft:stonecutter": ("Steinsäge", "Stonecutter"),
    # Frühere Generatoren übernahmen für Varianten-IDs den ersten Schlüssel
    # tile.<id>.<variante>.name statt tile.<id>.name oder sogar eine UI-Meldung
    # wie tile.respawn_anchor.respawnSet.
    "minecraft:brown_mushroom_block": ("Pilz", "Mushroom"),
    "minecraft:carpet": ("Schwarzer Teppich", "Black Carpet"),
    "minecraft:cobblestone_wall": ("Bemooste Bruchsteinmauer", "Mossy Cobblestone Wall"),
    "minecraft:concrete": ("Schwarzer Beton", "Black Concrete"),
    "minecraft:concretepowder": ("Schwarzer Trockenbeton", "Black Concrete Powder"),
    "minecraft:disc_fragment_5": ("Schallplatte – 5", "Music Disc - 5"),
    "minecraft:double_plant": ("Großer Farn", "Large Fern"),
    "minecraft:double_stone_slab": ("Ziegelstufe", "Brick Slab"),
    "minecraft:double_wooden_slab": ("Akazien-Doppelstufe", "Acacia Double Slab"),
    "minecraft:fireworks": ("Flugdauer:", "Flight Duration:"),
    "minecraft:fireworkscharge": ("Schwarz", "Black"),
    "minecraft:log": ("Akazienstamm", "Acacia Log"),
    "minecraft:monster_egg": ("Befallene Steinziegel", "Infested Stone Bricks"),
    "minecraft:netherreactor": ("Aktiv!", "Active!"),
    "minecraft:planks": ("Akazienbretter", "Acacia Planks"),
    "minecraft:prismarine": ("Prismarinziegel", "Prismarine Bricks"),
    "minecraft:quartz_block": ("Gemeißelter Quarzblock", "Chiseled Quartz Block"),
    "minecraft:red_flower": ("Zierlauch", "Allium"),
    "minecraft:red_sandstone": ("Gemeißelter roter Sandstein", "Chiseled Red Sandstone"),
    "minecraft:respawn_anchor": ("Wiederbeleben-Punkt festgelegt", "Respawn point set"),
    "minecraft:sandstone": ("Gemeißelter Sandstein", "Chiseled Sandstone"),
    "minecraft:sapling": ("Akaziensetzling", "Acacia Sapling"),
    "minecraft:skull": ("Spielerkopf", "Player Head"),
    "minecraft:spawn_egg": ("Agenten-Spawn-Ei", "Agent Spawn Egg"),
    "minecraft:stained_hardened_clay": ("Schwarze Keramik", "Black Terracotta"),
    "minecraft:standing_banner": ("Schwarzes Banner", "Black Banner"),
    "minecraft:stonebrick": ("Gemeißelte Steinziegel", "Chiseled Stone Bricks"),
    "minecraft:tallgrass": ("Farn", "Fern"),
    "minecraft:wooden_slab": ("Akazienstufe", "Acacia Slab"),
    "minecraft:wool": ("Schwarze Wolle", "Black Wool"),
    # Die Variante item.banner_pattern.bricks und die Tooltip-Zeile
    # item.smithing_template.applies_to statt des Basisnamens <id>.name.
    "minecraft:banner_pattern": ("Gemauertes Feld", "Field Masoned"),
    "minecraft:smithing_template": ("Gilt für:", "Applies to:"),
    # Namen, die nicht Mojangs aktueller Bedrock-Übersetzung entsprachen
    # (z. B. Brustplatte statt Harnisch, Umbenennung in bedrock-samples 1.26.50).
    "minecraft:carrot_on_a_stick": ("Karottenrute", "Carrot on a Stick"),
    "minecraft:chainmail_boots": ("Kettenstiefel", "Chainmail Boots"),
    "minecraft:chainmail_chestplate": ("Kettenhemd", "Chainmail Chestplate"),
    "minecraft:chainmail_helmet": ("Kettenhaube", "Chainmail Helmet"),
    "minecraft:chainmail_leggings": ("Kettenhose", "Chainmail Leggings"),
    "minecraft:coal_block": ("Kohleblock", "Coal Block"),
    "minecraft:cod": ("Roher Kabeljau", "Cod"),
    "minecraft:comparator": ("Redstone-Komparator", "Redstone Comparator"),
    "minecraft:cooked_beef": ("Gebratenes Rindfleisch", "Cooked Beef"),
    "minecraft:diamond_block": ("Diamantblock", "Diamond Block"),
    "minecraft:diamond_chestplate": ("Diamantbrustplatte", "Diamond Chestplate"),
    "minecraft:diamond_leggings": ("Diamantbeinschienen", "Diamond Leggings"),
    "minecraft:emerald_block": ("Smaragdblock", "Emerald Block"),
    "minecraft:ender_eye": ("Enderauge", "Ender Eye"),
    "minecraft:filled_map": ("Karte", "Filled Map"),
    "minecraft:gold_block": ("Goldblock", "Gold Block"),
    "minecraft:golden_chestplate": ("Goldbrustplatte", "Golden Chestplate"),
    "minecraft:golden_leggings": ("Goldbeinschienen", "Golden Leggings"),
    "minecraft:iron_block": ("Eisenblock", "Iron Block"),
    "minecraft:iron_chestplate": ("Eisenbrustplatte", "Iron Chestplate"),
    "minecraft:iron_leggings": ("Eisenbeinschienen", "Iron Leggings"),
    "minecraft:lapis_block": ("Lapislazuliblock", "Lapis Lazuli Block"),
    "minecraft:mutton": ("Rohes Hammelfleisch", "Mutton"),
    "minecraft:netherite_block": ("Netheritblock", "Netherite Block"),
    "minecraft:netherite_chestplate": ("Netheritbrustplatte", "Netherite Chestplate"),
    "minecraft:netherite_leggings": ("Netheritbeinschienen", "Netherite Leggings"),
    "minecraft:oak_planks": ("Eichenholzbretter", "Oak Planks"),
    "minecraft:poplar_standing_sign": ("Pappelschild", "Poplar Standing Sign"),
    "minecraft:redstone": ("Redstone-Staub", "Redstone"),
    "minecraft:redstone_block": ("Redstone-Block", "Redstone Block"),
    "minecraft:warped_fungus_on_a_stick": ("Wirrpilzrute", "Warped Fungus on a Stick"),
    # Reviewed Bedrock names and previously untranslated catalog fallbacks.
    "minecraft:axolotl_bucket": ("Axolotl Bucket", "Axolotl Bucket"),
    "minecraft:camera": ("Camera", "Camera"),
    "minecraft:cod_bucket": ("Cod Bucket", "Cod Bucket"),
    "minecraft:infested_chiseled_stone_bricks": ("Infested Chiseled Stone Bricks", "Infested Chiseled Stone Bricks"),
    "minecraft:infested_cracked_stone_bricks": ("Infested Cracked Stone Bricks", "Infested Cracked Stone Bricks"),
    "minecraft:infested_mossy_stone_bricks": ("Infested Mossy Stone Bricks", "Infested Mossy Stone Bricks"),
    "minecraft:lily_of_the_valley": ("Maiglöckchen", "Lily Of The Valley"),
    "minecraft:lingering_potion": ("Lingering Potion", "Lingering Potion"),
    "minecraft:music_disc_11": ("Music Disc 11", "Music Disc 11"),
    "minecraft:music_disc_13": ("Music Disc 13", "Music Disc 13"),
    "minecraft:music_disc_bounce": ("Music Disc Bounce", "Music Disc Bounce"),
    "minecraft:music_disc_creator": ("Music Disc Creator", "Music Disc Creator"),
    "minecraft:music_disc_creator_music_box": ("Music Disc Creator Music Box", "Music Disc Creator Music Box"),
    "minecraft:music_disc_precipice": ("Music Disc Precipice", "Music Disc Precipice"),
    "minecraft:normal_stone_slab": ("Normal Stone Slab", "Normal Stone Slab"),
    "minecraft:npc_spawn_egg": ("NPC-Spawn-Ei", "Npc Spawn Egg"),
    "minecraft:pufferfish_bucket": ("Pufferfish Bucket", "Pufferfish Bucket"),
    "minecraft:record_bounce": ("Fingerspit - Bounce", "Fingerspit - Bounce"),
    "minecraft:salmon_bucket": ("Salmon Bucket", "Salmon Bucket"),
    "minecraft:smooth_quartz": ("Smooth Quartz", "Smooth Quartz"),
    "minecraft:splash_potion": ("Splash Potion", "Splash Potion"),
    "minecraft:stone_brick_slab": ("Stone Brick Slab", "Stone Brick Slab"),
    "minecraft:sulfur_cube_bucket": ("Sulfur Cube Bucket", "Sulfur Cube Bucket"),
    "minecraft:tadpole_bucket": ("Tadpole Bucket", "Tadpole Bucket"),
    "minecraft:trip_wire": ("Trip Wire", "Trip Wire"),
    "minecraft:silver_glazed_terracotta": ("Silver Glazed Terracotta", "Silver Glazed Terracotta"),
    "minecraft:tropical_fish_bucket": ("Tropical Fish Bucket", "Tropical Fish Bucket"),
    "minecraft:undyed_shulker_box": ("Undyed Shulker Box", "Undyed Shulker Box"),
    "minecraft:zombie_pigman_spawn_egg": ("Zombifizierter-Piglin-Spawn-Ei", "Zombie Pigman Spawn Egg"),
    **{f"minecraft:light_block_{level}": (f"Light Block {level}", f"Light Block {level}") for level in range(16)},
}


# Exact inherited labels for reviewed German translations. Values are only
# migration inputs; replacement text belongs to the bundled catalog.
GERMAN_LABEL_MIGRATIONS = {
    "minecraft:brick_double_slab": ("Brick Double Slab", "Brick Double Slab"),
    "minecraft:chemical_heat": ("Chemical Heat", "Chemical Heat"),
    "minecraft:chemistry_table": ("Chemistry Table", "Chemistry Table"),
    "minecraft:client_request_placeholder_block": ("Client Request Placeholder Block", "Client Request Placeholder Block"),
    "minecraft:cobblestone_double_slab": ("Cobblestone Double Slab", "Cobblestone Double Slab"),
    "minecraft:colored_torch_blue": ("Colored Torch Blue", "Colored Torch Blue"),
    "minecraft:colored_torch_bp": ("Colored Torch Bp", "Colored Torch Bp"),
    "minecraft:colored_torch_green": ("Colored Torch Green", "Colored Torch Green"),
    "minecraft:colored_torch_purple": ("Colored Torch Purple", "Colored Torch Purple"),
    "minecraft:colored_torch_red": ("Colored Torch Red", "Colored Torch Red"),
    "minecraft:colored_torch_rg": ("Colored Torch Rg", "Colored Torch Rg"),
    "minecraft:compound_creator": ("Compound Creator", "Compound Creator"),
    "minecraft:concrete_powder": ("Concrete Powder", "Concrete Powder"),
    "minecraft:debug_stick": ("Debug Stick", "Debug Stick"),
    "minecraft:deprecated_anvil": ("Deprecated Anvil", "Deprecated Anvil"),
    "minecraft:deprecated_purpur_block_1": ("Deprecated Purpur Block 1", "Deprecated Purpur Block 1"),
    "minecraft:deprecated_purpur_block_2": ("Deprecated Purpur Block 2", "Deprecated Purpur Block 2"),
    "minecraft:double_stone_block_slab": ("Double Stone Block Slab", "Double Stone Block Slab"),
    "minecraft:double_stone_block_slab2": ("Double Stone Block Slab2", "Double Stone Block Slab2"),
    "minecraft:double_stone_block_slab3": ("Double Stone Block Slab3", "Double Stone Block Slab3"),
    "minecraft:double_stone_block_slab4": ("Double Stone Block Slab4", "Double Stone Block Slab4"),
    "minecraft:element_constructor": ("Element Constructor", "Element Constructor"),
    "minecraft:glow_stick": ("Glow Stick", "Glow Stick"),
    "minecraft:hard_black_stained_glass": ("Hard Black Stained Glass", "Hard Black Stained Glass"),
    "minecraft:hard_black_stained_glass_pane": ("Hard Black Stained Glass Pane", "Hard Black Stained Glass Pane"),
    "minecraft:hard_blue_stained_glass": ("Hard Blue Stained Glass", "Hard Blue Stained Glass"),
    "minecraft:hard_blue_stained_glass_pane": ("Hard Blue Stained Glass Pane", "Hard Blue Stained Glass Pane"),
    "minecraft:hard_brown_stained_glass": ("Hard Brown Stained Glass", "Hard Brown Stained Glass"),
    "minecraft:hard_brown_stained_glass_pane": ("Hard Brown Stained Glass Pane", "Hard Brown Stained Glass Pane"),
    "minecraft:hard_cyan_stained_glass": ("Hard Cyan Stained Glass", "Hard Cyan Stained Glass"),
    "minecraft:hard_cyan_stained_glass_pane": ("Hard Cyan Stained Glass Pane", "Hard Cyan Stained Glass Pane"),
    "minecraft:hard_glass": ("Hard Glass", "Hard Glass"),
    "minecraft:hard_glass_pane": ("Hard Glass Pane", "Hard Glass Pane"),
    "minecraft:hard_gray_stained_glass": ("Hard Gray Stained Glass", "Hard Gray Stained Glass"),
    "minecraft:hard_gray_stained_glass_pane": ("Hard Gray Stained Glass Pane", "Hard Gray Stained Glass Pane"),
    "minecraft:hard_green_stained_glass": ("Hard Green Stained Glass", "Hard Green Stained Glass"),
    "minecraft:hard_green_stained_glass_pane": ("Hard Green Stained Glass Pane", "Hard Green Stained Glass Pane"),
    "minecraft:hard_light_blue_stained_glass": ("Hard Light Blue Stained Glass", "Hard Light Blue Stained Glass"),
    "minecraft:hard_light_blue_stained_glass_pane": ("Hard Light Blue Stained Glass Pane", "Hard Light Blue Stained Glass Pane"),
    "minecraft:hard_light_gray_stained_glass": ("Hard Light Gray Stained Glass", "Hard Light Gray Stained Glass"),
    "minecraft:hard_light_gray_stained_glass_pane": ("Hard Light Gray Stained Glass Pane", "Hard Light Gray Stained Glass Pane"),
    "minecraft:hard_lime_stained_glass": ("Hard Lime Stained Glass", "Hard Lime Stained Glass"),
    "minecraft:hard_lime_stained_glass_pane": ("Hard Lime Stained Glass Pane", "Hard Lime Stained Glass Pane"),
    "minecraft:hard_magenta_stained_glass": ("Hard Magenta Stained Glass", "Hard Magenta Stained Glass"),
    "minecraft:hard_magenta_stained_glass_pane": ("Hard Magenta Stained Glass Pane", "Hard Magenta Stained Glass Pane"),
    "minecraft:hard_orange_stained_glass": ("Hard Orange Stained Glass", "Hard Orange Stained Glass"),
    "minecraft:hard_orange_stained_glass_pane": ("Hard Orange Stained Glass Pane", "Hard Orange Stained Glass Pane"),
    "minecraft:hard_pink_stained_glass": ("Hard Pink Stained Glass", "Hard Pink Stained Glass"),
    "minecraft:hard_pink_stained_glass_pane": ("Hard Pink Stained Glass Pane", "Hard Pink Stained Glass Pane"),
    "minecraft:hard_purple_stained_glass": ("Hard Purple Stained Glass", "Hard Purple Stained Glass"),
    "minecraft:hard_purple_stained_glass_pane": ("Hard Purple Stained Glass Pane", "Hard Purple Stained Glass Pane"),
    "minecraft:hard_red_stained_glass": ("Hard Red Stained Glass", "Hard Red Stained Glass"),
    "minecraft:hard_red_stained_glass_pane": ("Hard Red Stained Glass Pane", "Hard Red Stained Glass Pane"),
    "minecraft:hard_stained_glass": ("Hard Stained Glass", "Hard Stained Glass"),
    "minecraft:hard_stained_glass_pane": ("Hard Stained Glass Pane", "Hard Stained Glass Pane"),
    "minecraft:hard_white_stained_glass": ("Hard White Stained Glass", "Hard White Stained Glass"),
    "minecraft:hard_white_stained_glass_pane": ("Hard White Stained Glass Pane", "Hard White Stained Glass Pane"),
    "minecraft:hard_yellow_stained_glass": ("Hard Yellow Stained Glass", "Hard Yellow Stained Glass"),
    "minecraft:hard_yellow_stained_glass_pane": ("Hard Yellow Stained Glass Pane", "Hard Yellow Stained Glass Pane"),
    "minecraft:ice_bomb": ("Ice Bomb", "Ice Bomb"),
    "minecraft:info_update": ("Info Update", "Info Update"),
    "minecraft:info_update2": ("Info Update2", "Info Update2"),
    "minecraft:lab_table": ("Lab Table", "Lab Table"),
    "minecraft:material_reducer": ("Material Reducer", "Material Reducer"),
    "minecraft:moving_block": ("Moving Block", "Moving Block"),
    "minecraft:nether_brick_double_slab": ("Nether Brick Double Slab", "Nether Brick Double Slab"),
    "minecraft:normal_stone_double_slab": ("Normal Stone Double Slab", "Normal Stone Double Slab"),
    "minecraft:petrified_oak_double_slab": ("Petrified Oak Double Slab", "Petrified Oak Double Slab"),
    "minecraft:petrified_oak_slab": ("Petrified Oak Slab", "Petrified Oak Slab"),
    "minecraft:photo_item": ("Photo Item", "Photo Item"),
    "minecraft:prismarine_double_slab": ("Prismarine Double Slab", "Prismarine Double Slab"),
    "minecraft:quartz_double_slab": ("Quartz Double Slab", "Quartz Double Slab"),
    "minecraft:rapid_fertilizer": ("Rapid Fertilizer", "Rapid Fertilizer"),
    "minecraft:red_sandstone_double_slab": ("Red Sandstone Double Slab", "Red Sandstone Double Slab"),
    "minecraft:sandstone_double_slab": ("Sandstone Double Slab", "Sandstone Double Slab"),
    "minecraft:smooth_stone_double_slab": ("Smooth Stone Double Slab", "Smooth Stone Double Slab"),
    "minecraft:stone_block_slab": ("Stone Block Slab", "Stone Block Slab"),
    "minecraft:stone_block_slab2": ("Stone Block Slab2", "Stone Block Slab2"),
    "minecraft:stone_block_slab3": ("Stone Block Slab3", "Stone Block Slab3"),
    "minecraft:stone_block_slab4": ("Stone Block Slab4", "Stone Block Slab4"),
    "minecraft:stone_brick_double_slab": ("Stone Brick Double Slab", "Stone Brick Double Slab"),
    "minecraft:underwater_tnt": ("Underwater Tnt", "Underwater Tnt"),
    "minecraft:underwater_torch": ("Underwater Torch", "Underwater Torch"),
    "minecraft:frostbite_spawn_egg": ("Frostbite Spawn Egg", "Frostbite Spawn Egg"),
    "minecraft:ice_ball": ("Ice Ball", "Ice Ball"),
    "minecraft:ice_crystal": ("Ice Crystal", "Ice Crystal"),
    "minecraft:icicle": ("Icicle", "Icicle"),
}
SUPERSEDED_ITEM_LABELS.update(GERMAN_LABEL_MIGRATIONS)

# These two labels are quoted from exact Mojang language keys. All other
# German translations in this group are explicitly editorial, not Mojang text.
REVIEWED_MOJANG_GERMAN_KEYS = {
    "minecraft:normal_stone_double_slab": "tile.double_stone_slab4.stone.name",
    "minecraft:prismarine_double_slab": "tile.double_stone_slab2.prismarine.rough.name",
}
EDITORIAL_GERMAN_ITEM_IDS = frozenset(GERMAN_LABEL_MIGRATIONS.keys() - REVIEWED_MOJANG_GERMAN_KEYS.keys())
# Exact inherited pairs from catalogs with reviewed German labels. The older
# English-only pairs above remain supported; no single-language wildcard is used.
ENGLISH_LABEL_MIGRATIONS = {
    "minecraft:acacia_chest_boat": ("Akazien-Truhenboot", "Acacia Chest Boat"),
    "minecraft:bamboo_chest_raft": ("Bambus-Truhenfloß", "Bamboo Chest Raft"),
    "minecraft:birch_chest_boat": ("Birken-Truhenboot", "Birch Chest Boat"),
    "minecraft:chemical_heat": ("Hitzeblock", "Chemical Heat"),
    "minecraft:cherry_chest_boat": ("Kirschholz-Truhenboot", "Cherry Chest Boat"),
    "minecraft:colored_torch_blue": ("Blaue Fackel", "Colored Torch Blue"),
    "minecraft:colored_torch_bp": ("Gefärbte Fackel (blau/violett)", "Colored Torch Bp"),
    "minecraft:colored_torch_green": ("Grüne Fackel", "Colored Torch Green"),
    "minecraft:colored_torch_purple": ("Violette Fackel", "Colored Torch Purple"),
    "minecraft:colored_torch_red": ("Rote Fackel", "Colored Torch Red"),
    "minecraft:colored_torch_rg": ("Gefärbte Fackel (rot/grün)", "Colored Torch Rg"),
    "minecraft:dark_oak_chest_boat": ("Schwarzeichenholz-Truhenboot", "Dark Oak Chest Boat"),
    "minecraft:double_stone_block_slab": ("Stein-Doppelstufe (alt, Typ 1)", "Double Stone Block Slab"),
    "minecraft:double_stone_block_slab2": ("Stein-Doppelstufe (alt, Typ 2)", "Double Stone Block Slab2"),
    "minecraft:double_stone_block_slab3": ("Stein-Doppelstufe (alt, Typ 3)", "Double Stone Block Slab3"),
    "minecraft:double_stone_block_slab4": ("Stein-Doppelstufe (alt, Typ 4)", "Double Stone Block Slab4"),
    "minecraft:hard_black_stained_glass": ("Gehärtetes schwarzes Glas", "Hard Black Stained Glass"),
    "minecraft:hard_black_stained_glass_pane": ("Gehärtete schwarze Glasscheibe", "Hard Black Stained Glass Pane"),
    "minecraft:hard_blue_stained_glass": ("Gehärtetes blaues Glas", "Hard Blue Stained Glass"),
    "minecraft:hard_blue_stained_glass_pane": ("Gehärtete blaue Glasscheibe", "Hard Blue Stained Glass Pane"),
    "minecraft:hard_brown_stained_glass": ("Gehärtetes braunes Glas", "Hard Brown Stained Glass"),
    "minecraft:hard_brown_stained_glass_pane": ("Gehärtete braune Glasscheibe", "Hard Brown Stained Glass Pane"),
    "minecraft:hard_cyan_stained_glass": ("Gehärtetes türkises Glas", "Hard Cyan Stained Glass"),
    "minecraft:hard_cyan_stained_glass_pane": ("Gehärtete türkise Glasscheibe", "Hard Cyan Stained Glass Pane"),
    "minecraft:hard_glass": ("Gehärtetes Glas", "Hard Glass"),
    "minecraft:hard_glass_pane": ("Gehärtete Glasscheibe", "Hard Glass Pane"),
    "minecraft:hard_gray_stained_glass": ("Gehärtetes graues Glas", "Hard Gray Stained Glass"),
    "minecraft:hard_gray_stained_glass_pane": ("Gehärtete graue Glasscheibe", "Hard Gray Stained Glass Pane"),
    "minecraft:hard_green_stained_glass": ("Gehärtetes grünes Glas", "Hard Green Stained Glass"),
    "minecraft:hard_green_stained_glass_pane": ("Gehärtete grüne Glasscheibe", "Hard Green Stained Glass Pane"),
    "minecraft:hard_light_blue_stained_glass": ("Gehärtetes hellblaues Glas", "Hard Light Blue Stained Glass"),
    "minecraft:hard_light_blue_stained_glass_pane": ("Gehärtete hellblaue Glasscheibe", "Hard Light Blue Stained Glass Pane"),
    "minecraft:hard_light_gray_stained_glass": ("Gehärtetes hellgraues Glas", "Hard Light Gray Stained Glass"),
    "minecraft:hard_light_gray_stained_glass_pane": ("Gehärtete hellgraue Glasscheibe", "Hard Light Gray Stained Glass Pane"),
    "minecraft:hard_lime_stained_glass": ("Gehärtetes hellgrünes Glas", "Hard Lime Stained Glass"),
    "minecraft:hard_lime_stained_glass_pane": ("Gehärtete hellgrüne Glasscheibe", "Hard Lime Stained Glass Pane"),
    "minecraft:hard_magenta_stained_glass": ("Gehärtetes magentafarbenes Glas", "Hard Magenta Stained Glass"),
    "minecraft:hard_magenta_stained_glass_pane": ("Gehärtete magentafarbene Glasscheibe", "Hard Magenta Stained Glass Pane"),
    "minecraft:hard_orange_stained_glass": ("Gehärtetes orangefarbenes Glas", "Hard Orange Stained Glass"),
    "minecraft:hard_orange_stained_glass_pane": ("Gehärtete orangefarbene Glasscheibe", "Hard Orange Stained Glass Pane"),
    "minecraft:hard_pink_stained_glass": ("Gehärtetes rosa Glas", "Hard Pink Stained Glass"),
    "minecraft:hard_pink_stained_glass_pane": ("Gehärtete rosa Glasscheibe", "Hard Pink Stained Glass Pane"),
    "minecraft:hard_purple_stained_glass": ("Gehärtetes violettes Glas", "Hard Purple Stained Glass"),
    "minecraft:hard_purple_stained_glass_pane": ("Gehärtete violette Glasscheibe", "Hard Purple Stained Glass Pane"),
    "minecraft:hard_red_stained_glass": ("Gehärtetes rotes Glas", "Hard Red Stained Glass"),
    "minecraft:hard_red_stained_glass_pane": ("Gehärtete rote Glasscheibe", "Hard Red Stained Glass Pane"),
    "minecraft:hard_stained_glass": ("Gefärbtes gehärtetes Glas", "Hard Stained Glass"),
    "minecraft:hard_stained_glass_pane": ("Gefärbte gehärtete Glasscheibe", "Hard Stained Glass Pane"),
    "minecraft:hard_white_stained_glass": ("Gehärtetes weißes Glas", "Hard White Stained Glass"),
    "minecraft:hard_white_stained_glass_pane": ("Gehärtete weiße Glasscheibe", "Hard White Stained Glass Pane"),
    "minecraft:hard_yellow_stained_glass": ("Gehärtetes gelbes Glas", "Hard Yellow Stained Glass"),
    "minecraft:hard_yellow_stained_glass_pane": ("Gehärtete gelbe Glasscheibe", "Hard Yellow Stained Glass Pane"),
    "minecraft:info_update": ("Aktualisierungsblock", "Info Update"),
    "minecraft:info_update2": ("Aktualisierungsblock 2", "Info Update2"),
    "minecraft:jungle_chest_boat": ("Tropenholz-Truhenboot", "Jungle Chest Boat"),
    "minecraft:mangrove_chest_boat": ("Mangroven-Truhenboot", "Mangrove Chest Boat"),
    "minecraft:normal_stone_double_slab": ("Stein-Doppelstufe", "Normal Stone Double Slab"),
    "minecraft:oak_chest_boat": ("Eichenholz-Truhenboot", "Oak Chest Boat"),
    "minecraft:pale_oak_chest_boat": ("Blasseichenholz-Truhenboot", "Pale Oak Chest Boat"),
    "minecraft:photo_item": ("Foto", "Photo Item"),
    "minecraft:poplar_chest_boat": ("Pappel-Truhenboot", "Poplar Chest Boat"),
    "minecraft:rapid_fertilizer": ("Superdünger", "Rapid Fertilizer"),
    "minecraft:spruce_chest_boat": ("Fichten-Truhenboot", "Spruce Chest Boat"),
    "minecraft:stone_block_slab": ("Steinstufe (alt, Typ 1)", "Stone Block Slab"),
    "minecraft:stone_block_slab2": ("Steinstufe (alt, Typ 2)", "Stone Block Slab2"),
    "minecraft:stone_block_slab3": ("Steinstufe (alt, Typ 3)", "Stone Block Slab3"),
    "minecraft:stone_block_slab4": ("Steinstufe (alt, Typ 4)", "Stone Block Slab4"),
    "minecraft:underwater_tnt": ("Unterwasser-TNT", "Underwater Tnt"),
}
for _item_id, _pair in ENGLISH_LABEL_MIGRATIONS.items():
    SUPERSEDED_ITEM_LABELS.setdefault(_item_id, _pair)

REVIEWED_MOJANG_ENGLISH_KEYS = {
    "minecraft:acacia_chest_boat": "item.chest_boat.acacia.name",
    "minecraft:bamboo_chest_raft": "item.chest_boat.bamboo.name",
    "minecraft:birch_chest_boat": "item.chest_boat.birch.name",
    "minecraft:cherry_chest_boat": "item.chest_boat.cherry.name",
    "minecraft:dark_oak_chest_boat": "item.chest_boat.big_oak.name",
    "minecraft:jungle_chest_boat": "item.chest_boat.jungle.name",
    "minecraft:mangrove_chest_boat": "item.chest_boat.mangrove.name",
    "minecraft:normal_stone_double_slab": "tile.double_stone_slab4.stone.name",
    "minecraft:oak_chest_boat": "item.chest_boat.oak.name",
    "minecraft:pale_oak_chest_boat": "item.chest_boat.pale_oak.name",
    "minecraft:poplar_chest_boat": "item.chest_boat.poplar.name",
    "minecraft:spruce_chest_boat": "item.chest_boat.spruce.name",
}
DOCUMENTED_ENGLISH_ITEM_IDS = frozenset(
    {
        "minecraft:chemical_heat",
        "minecraft:hard_glass",
        "minecraft:hard_glass_pane",
        "minecraft:rapid_fertilizer",
        "minecraft:underwater_tnt",
    }
)
EDITORIAL_ITEM_IDS_BY_LOCALE = {
    "de": EDITORIAL_GERMAN_ITEM_IDS,
    "en": frozenset(ENGLISH_LABEL_MIGRATIONS.keys() - REVIEWED_MOJANG_ENGLISH_KEYS.keys() - DOCUMENTED_ENGLISH_ITEM_IDS),
}
# These IDs name groups or double slabs whose catalog qualifiers distinguish
# them from individual colors, other legacy types or a single slab.
LEGACY_VARIANT_GROUP_IDS = {item_id for item_id in GERMAN_LABEL_MIGRATIONS if "stone_block_slab" in item_id or item_id.endswith("_double_slab")} | {
    "minecraft:colored_torch_rg",
    "minecraft:colored_torch_bp",
}
REPLACEABLE_CATALOG_ITEM_IDS = (GERMAN_LABEL_MIGRATIONS.keys() | ENGLISH_LABEL_MIGRATIONS.keys()) - EXPECTED_ITEM_NAME_DIFFERENCES.keys()


def _shipped_pairs(item_id, superseded_pair):
    return (superseded_pair, (superseded_pair[1], superseded_pair[1]), ENGLISH_LABEL_MIGRATIONS.get(item_id))


def confirmed_item_label_pair(record) -> list[str | None] | None:
    """Read automatic comparison values. A null locale has no proven automatic value."""
    if isinstance(record, dict):
        if record.get("borrowed") not in ("de", "en"):
            return None
        record = record.get("names")
    if isinstance(record, (tuple, list)) and len(record) == 2 and all(value is None or (isinstance(value, str) and value.strip()) for value in record):
        return list(record)
    return None


def item_label_reference(item_id, current, previous, reviewed, official, composed, learned):
    """Track automatic names per language without adopting an edited value as the new baseline."""
    prior = confirmed_item_label_pair(previous)
    catalog_pair = reviewed.get(item_id, ())
    if item_id in EXPECTED_ITEM_NAME_DIFFERENCES and tuple(prior or current or ()) == EXPECTED_ITEM_NAME_DIFFERENCES[item_id][0] == tuple(catalog_pair):
        return previous
    if not any(official.values()) and not composed and (prior or catalog_pair or not learned):
        return previous
    if not any(official.values()) and catalog_pair and not prior and current:
        # Existing reviewed disc titles can intentionally differ from a composition.
        return None
    baseline = list(prior or catalog_pair)
    if isinstance(previous, dict):
        baseline[("de", "en").index(previous["borrowed"])] = ""
    pair, sources = resolve_names(item_id, official, baseline, catalog_pair, {"en": learned}, composed=composed)
    overrides = reviewed_variant_name_overrides(item_id, reviewed, official)
    names = []
    borrowed = None
    for index, locale in enumerate(("de", "en")):
        value = prior[index] if prior and current[index] != prior[index] else overrides.get(locale, pair[index])
        if not prior and current and current[index] == value and not official.get(locale) and (not catalog_pair or value != catalog_pair[index]):
            # Seeing the same text as a proposed fallback does not establish
            # that the updater wrote this locale in an older installation.
            value = None
        names.append(value)
        if value is not None and sources[index] == "other_language" and locale not in overrides:
            borrowed = locale
    return {"names": names, "borrowed": borrowed} if borrowed else names


def reviewed_item_label_repairs(current: Mapping, reviewed: Mapping, confirmed: Mapping | None = None) -> dict[str, tuple[str, str]]:
    repairs = {}
    for item_id, superseded_pair in SUPERSEDED_ITEM_LABELS.items():
        names = current.get(item_id)
        replacement = reviewed.get(item_id)
        # Generators without the German key shipped the old English name twice.
        known_pairs = _shipped_pairs(item_id, superseded_pair)
        if not _complete_pair(names) or not _complete_pair(replacement):
            continue
        if confirmed and confirmed_item_label_pair(confirmed.get(item_id)) == list(names):
            continue
        # A literal ID is a generated missing value. Match the surviving half
        # against the shipped pairs before introducing a newer translation.
        if item_id in names:
            known_pairs += (replacement, (replacement[1], replacement[1]))
            known = any(pair and all(value in (item_id, prior) for value, prior in zip(names, pair, strict=True)) for pair in known_pairs)
        else:
            known = tuple(names) in known_pairs
        if not known:
            continue
        if tuple(replacement) != superseded_pair:
            repairs[item_id] = tuple(replacement)
    return repairs
