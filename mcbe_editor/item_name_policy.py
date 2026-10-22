"""Shared exact-match migrations for reviewed Vanilla item labels.

Only known shipped pairs are replaced; user-defined names remain unchanged.
Replacement names come from the bundled catalog, never a second name table.
"""

from __future__ import annotations

from collections.abc import Mapping

# Exact reviewed source/catalog pairs, not an exemption for these IDs in general.
# A changed source or catalog label must return to the ordinary comparison.
EXPECTED_ITEM_NAME_DIFFERENCES = {
    "minecraft:bed": (("Weißes Bett", "White Bed"), ("Bett", "Bed")),
    "minecraft:yellow_flower": (("Löwenzahn", "Dandelion"), ("Blume", "Flower")),
    "minecraft:stonecutter": (("Steinsäge (alt, ohne Funktion)", "Stonecutter (Legacy, No Function)"), ("Steinsäge", "Stonecutter")),
}


def is_expected_item_name_difference(item_id: str, names, source_names: Mapping) -> bool:
    expected = EXPECTED_ITEM_NAME_DIFFERENCES.get(item_id)
    if expected is None or not isinstance(names, (list, tuple)):
        return False
    catalog_pair, source_pair = expected
    return tuple(names) == catalog_pair and tuple(source_names.get(locale, {}).get(item_id) for locale in ("de", "en")) == source_pair


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


def reviewed_item_label_repairs(current: Mapping, reviewed: Mapping) -> dict[str, tuple[str, str]]:
    repairs = {}
    for item_id, superseded_pair in SUPERSEDED_ITEM_LABELS.items():
        names = current.get(item_id)
        replacement = reviewed.get(item_id)
        # Generators without the German key shipped the old English name twice.
        known_pairs = (superseded_pair, (superseded_pair[1], superseded_pair[1]))
        if not isinstance(names, (list, tuple)) or tuple(names) not in known_pairs:
            continue
        if not isinstance(replacement, (list, tuple)) or len(replacement) != 2:
            continue
        if not all(isinstance(name, str) and name.strip() for name in replacement):
            continue
        if tuple(replacement) != superseded_pair:
            repairs[item_id] = tuple(replacement)
    return repairs
