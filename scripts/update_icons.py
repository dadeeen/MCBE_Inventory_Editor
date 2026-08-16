#!/usr/bin/env python3
"""Lädt Vanilla-Icons aus dem offiziellen Mojang/bedrock-samples Full-Release."""

from __future__ import annotations

import argparse
import binascii
import contextlib
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_runtime_dependencies():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from mcbe_editor.block_icon_renderer import composite_png_overlay, crop_png, render_bedrock_model_icon, render_block_icon, tint_png
    from mcbe_editor.icon_cache import publish_icon_cache, recover_icon_cache
    from mcbe_editor.item_registry_policy import is_technical_block_only_item_id
    from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON
    from mcbe_editor.update_output_i18n import output_t

    return (
        publish_icon_cache,
        recover_icon_cache,
        render_block_icon,
        render_bedrock_model_icon,
        tint_png,
        composite_png_overlay,
        crop_png,
        BUNDLED_ITEM_DB_JSON,
        is_technical_block_only_item_id,
        output_t,
    )


(
    publish_icon_cache,
    recover_icon_cache,
    render_block_icon,
    render_bedrock_model_icon,
    tint_png,
    composite_png_overlay,
    crop_png,
    BUNDLED_ITEM_DB_JSON,
    is_technical_block_only_item_id,
    tr,
) = _load_runtime_dependencies()
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
DATA_ROOT = Path(os.environ.get("MCBE_DATA_ROOT", DEFAULT_DATA_ROOT)).expanduser()
ICON_ROOT = Path(os.environ.get("MCBE_ICON_CACHE_ROOT", DATA_ROOT / "icons" / "vanilla")).expanduser()
ITEM_DB_PATH = Path(os.environ.get("MCBE_ITEM_DB_PATH", DATA_ROOT / "item_db.json")).expanduser()
if not ITEM_DB_PATH.exists():
    ITEM_DB_PATH = BUNDLED_ITEM_DB_JSON
CACHE_DIR = Path(os.environ.get("MCBE_UPDATE_CACHE_DIR", DATA_ROOT / "cache" / "item_update")).expanduser()
RELEASE_METADATA_PATH = CACHE_DIR / "icon_release_metadata.json"
_MANAGED_ICON_RELEASE_ZIP_RE = re.compile(r"^bedrock-samples(?:-[A-Za-z0-9][A-Za-z0-9._-]*)?\.zip$", re.IGNORECASE)

RP_OWNER = "Mojang"
RP_REPO = "bedrock-samples"
RP_LATEST_API = f"https://api.github.com/repos/{RP_OWNER}/{RP_REPO}/releases/latest"
MAX_RELEASE_JSON_BYTES = 5 * 1024 * 1024
MAX_RESOURCE_PACK_BYTES = 350 * 1024 * 1024
MAX_RESOURCE_PACK_MEMBERS = 100_000
MAX_RESOURCE_PACK_MEMBER_BYTES = 128 * 1024 * 1024
MAX_RESOURCE_PACK_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ICON_BYTES = 2 * 1024 * 1024
MAX_DECODED_ICON_PIXELS = 512 * 512
ALLOWED_GITHUB_API_HOSTS = {"api.github.com"}
ALLOWED_RESOURCE_PACK_HOSTS = {"github.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com", "release-assets.githubusercontent.com"}
GRASS_TINT = (145, 189, 89)
# Einzelne Blöcke liefern statt einer Flächentextur ein Atlas-Blatt mit mehreren
# Flächen. Ohne Zuschnitt landet das komplette Blatt auf jeder Seite. Die
# Regionen stammen aus den Box-UVs des Vanilla-Modells und sind in Sechzehnteln
# der Texturkante angegeben, damit auch HD-Packs korrekt zugeschnitten werden.
ATLAS_FACE_REGIONS = {
    "heavy_core": {"top": (0, 0, 8, 8), "side": (0, 8, 8, 8)},
}
SPECIAL_BLOCK_FACE_TEXTURE_KEYS = {
    # Bedrock verwendet hier historische Namen, die sich nicht zuverlässig
    # aus der Runtime-ID und dem üblichen ``_<face>``-Schema ableiten lassen.
    "dispenser": {"front": ("dispenser_front_horizontal",)},
    "dropper": {"front": ("dropper_front_horizontal",)},
    # Der Crafter benennt seine Flächen nach Himmelsrichtungen und besitzt gar
    # keinen ``_side``-Key. Norden ist die Ausgabeseite, Osten die Holzflanke.
    "crafter": {"side": ("crafter_east",), "top": ("crafter_top",), "front": ("crafter_north",)},
    # Die Kürbisgesichter liegen unter ``pumpkin_face_*``. Ohne diese Zuordnung
    # findet die Flächensuche weder Deckel noch Flanke und klebt das Gesicht
    # auf alle drei sichtbaren Seiten.
    "carved_pumpkin": {"side": ("pumpkin_side",), "top": ("pumpkin_top",), "front": ("pumpkin_face_off",)},
    "lit_pumpkin": {"side": ("pumpkin_side",), "top": ("pumpkin_top",), "front": ("pumpkin_face_on",)},
    # Schnittsandstein ist rundum gleich; die Stufe fände sonst die Deckfläche
    # des ungeschnittenen Sandsteins.
    "cut_red_sandstone_slab": {"top": ("cut_red_sandstone",)},
    "cut_sandstone_slab": {"top": ("cut_sandstone",)},
    # Der Teppich trägt die Blocktextur, nicht seine Kantenblende.
    "pale_moss_carpet": {"side": ("pale_moss_block",), "front": ("pale_moss_block",)},
    "piston": {"top": ("piston_top_normal",)},
    # Der kalibrierte Sensor unterscheidet sich vom normalen nur durch seine
    # Amethyst-Eingangsseite; ohne diese Zuordnung wären beide Icons gleich.
    "calibrated_sculk_sensor": {
        "side": ("sculk_sensor_side",),
        "top": ("calibrated_sculk_sensor_top",),
        "front": ("calibrated_sculk_sensor_input_side",),
    },
    # Flanke und Deckel unterscheiden sich; ohne Zuordnung setzt sich die aus
    # der Grundtextur abgeleitete Fläche auf beide.
    "red_sandstone": {"top": ("red_sandstone_top",)},
    "red_sandstone_stairs": {"top": ("red_sandstone_top",)},
    "sticky_piston": {
        "side": ("piston_side",),
        "top": ("piston_top_sticky",),
        "front": ("piston_side",),
    },
}


@dataclass(frozen=True)
class ModelIconSpec:
    geometry_path: str
    geometry_identifier: str
    texture_path: str
    entity_definition_path: str | None = None
    entity_variant: str | None = None
    geometry_variant: str | None = None
    block_texture_key: str | None = None
    yaw: float = -16.0
    pitch: float = -7.0
    roll: float = -4.0


# Entity atlases remain blocked for normal item selection. Each exception must
# pair an exact atlas with its authoritative Bedrock geometry so a raw atlas can
# never leak into the icon cache.
MODEL_ICON_SPECS = {
    "creeper_head": ModelIconSpec(
        geometry_path="models/mobs.json",
        geometry_identifier="geometry.mob_head",
        texture_path="entity/skulls/creeper",
        entity_definition_path="entity/skull.entity.json",
        entity_variant="creeper",
    ),
    "dragon_head": ModelIconSpec(
        geometry_path="models/mobs.json",
        geometry_identifier="geometry.dragon_head",
        texture_path="entity/dragon/dragon",
        entity_definition_path="entity/skull.entity.json",
        entity_variant="dragon",
    ),
    "shield": ModelIconSpec(
        geometry_path="models/entity/shield.geo.json",
        geometry_identifier="geometry.shield",
        texture_path="entity/shield",
    ),
    "skeleton_skull": ModelIconSpec(
        geometry_path="models/mobs.json",
        geometry_identifier="geometry.mob_head",
        texture_path="entity/skulls/skeleton",
        entity_definition_path="entity/skull.entity.json",
        entity_variant="skeleton",
    ),
    "wither_skeleton_skull": ModelIconSpec(
        geometry_path="models/mobs.json",
        geometry_identifier="geometry.mob_head",
        texture_path="entity/skulls/wither_skeleton",
        entity_definition_path="entity/skull.entity.json",
        entity_variant="wither",
    ),
    "zombie_head": ModelIconSpec(
        geometry_path="models/mobs.json",
        geometry_identifier="geometry.mob_head",
        texture_path="entity/skulls/zombie",
        entity_definition_path="entity/skull.entity.json",
        entity_variant="zombie",
    ),
}
_COPPER_GOLEM_STATUE_STATES = {
    "copper_golem_statue": ("default", "copper_block", ""),
    "exposed_copper_golem_statue": ("exposed", "exposed_copper", "_exposed"),
    "weathered_copper_golem_statue": ("weathered", "weathered_copper", "_weathered"),
    "oxidized_copper_golem_statue": ("oxidized", "oxidized_copper", "_oxidized"),
}
for _statue_id, (_texture_variant, _block_texture_key, _texture_suffix) in tuple(_COPPER_GOLEM_STATUE_STATES.items()):
    _statue_spec = ModelIconSpec(
        geometry_path="models/entity/copper_golem.geo.json",
        geometry_identifier="geometry.copper_golem",
        texture_path=f"entity/copper_golem/copper_golem{_texture_suffix}",
        entity_definition_path="entity/copper_golem.entity.json",
        entity_variant=_texture_variant,
        geometry_variant="standing",
        block_texture_key=_block_texture_key,
        yaw=-18.0,
        pitch=-7.0,
        roll=-3.0,
    )
    MODEL_ICON_SPECS[_statue_id] = _statue_spec
    MODEL_ICON_SPECS[f"waxed_{_statue_id}"] = _statue_spec
TEXTURE_JSON_NAMES = {"textures/item_texture.json", "textures/terrain_texture.json"}
TEXTURE_PREFIXES = ("textures/items/", "textures/blocks/", "textures/entity/")
COLOR_ALIASES = {
    "black",
    "blue",
    "brown",
    "cyan",
    "gray",
    "green",
    "light_blue",
    "light_gray",
    "lime",
    "magenta",
    "orange",
    "pink",
    "purple",
    "red",
    "white",
    "yellow",
}
COMMON_ALIASES = {
    # Mojang verwendet für einzelne Laufzeit-Item-IDs abweichende semantische
    # Texture-Keys. Diese kleine, geprüfte Brücke ist absichtlich explizit:
    # generisches Entfernen von Suffixen wie ``_dust`` würde auch unabhängige
    # Texturen falsch zuordnen.
    "redstone": ["redstone_dust"],
    "redstone_wire": ["redstone_dust"],
    # blocks.json nutzt den historischen Key mit getrenntem ``trip_wire``;
    # dessen transparente Source-Textur ist die brauchbare Itemvorschau.
    "tripwire_hook": ["trip_wire_source"],
    # Moderne Runtime-IDs, deren Vanilla-Texture-Keys aus historischen
    # Bedrock-Namen bestehen. Alle Ziele sind direkt in item_texture.json
    # der bedrock-samples belegt; es findet keine unscharfe Namenssuche statt.
    # Die historischen Dateien ohne ``_new`` sind die ursprünglichen
    # Farbstoffquellen; ``*_new`` sind die seit Village & Pillage getrennten
    # Farbstoff-Items. Diese Paare dürfen nicht vertauscht werden.
    "cocoa_beans": ["dye_powder_brown"],
    "brown_dye": ["dye_powder_brown_new"],
    "empty_map": ["map_empty"],
    "enchanted_golden_apple": ["apple_golden"],
    "fermented_spider_eye": ["spider_eye_fermented"],
    "fire_charge": ["fireball"],
    "firework_rocket": ["fireworks"],
    "firework_star": ["fireworks_charge"],
    "glass_bottle": ["potion_bottle_empty"],
    "glistering_melon_slice": ["melon_speckled"],
    "glow_ink_sac": ["dye_powder_glow"],
    "ink_sac": ["dye_powder_black"],
    "black_dye": ["dye_powder_black_new"],
    "lapis_lazuli": ["dye_powder_blue"],
    "blue_dye": ["dye_powder_blue_new"],
    "white_dye": ["dye_powder_white_new"],
    "lodestone_compass": ["lodestonecompass_item"],
    "melon_slice": ["melon"],
    "poisonous_potato": ["potato_poisonous"],
    "popped_chorus_fruit": ["chorus_fruit_popped"],
    "slime_ball": ["slimeball"],
    "sugar_cane": ["reeds"],
    "totem_of_undying": ["totem"],
    "turtle_scute": ["turtle_shell_piece"],
    # Die Runtime-ID blieb in Bedrock historisch, während das aktuelle
    # Resource-Pack den heutigen Kreaturnamen verwendet.
    "zombie_pigman_spawn_egg": ["spawn_egg_zombified_piglin", "egg_pigzombie"],
    # Bedrock nutzt für diese Schaltflächen keine eigenständigen Item-Sprites.
    # Eine explizite Materialzuordnung ist sicherer als ein generisches
    # Entfernen von ``_button`` (das würde beliebige Mod-Items fehlmappen).
    "wooden_button": ["planks_oak"],
    "crimson_button": ["crimson_planks"],
    "warped_button": ["warped_planks"],
    # Tuffsteinziegel-Varianten teilen sich im Bedrock-Resource-Pack die
    # gemeinsame Inventartextur ``blocks/tuff_bricks.png``.
    "tuff_brick_stairs": ["tuff_bricks"],
    "tuff_brick_slab": ["tuff_bricks"],
    "tuff_brick_wall": ["tuff_bricks"],
    # Diese Runtime-IDs haben im Bedrock-Sample keinen gleichnamigen
    # Texture-Key. Die Ziele sind jeweils konkrete PNGs aus dem offiziellen
    # Resource-Pack; es findet keine unscharfe Namenssuche statt.
    "allow": ["build_allow"],
    "deny": ["build_deny"],
    "brown_mushroom_block": ["mushroom_block_skin_brown"],
    "cinnabar_brick_slab": ["cinnabar_bricks"],
    "cinnabar_brick_stairs": ["cinnabar_bricks"],
    "cinnabar_brick_wall": ["cinnabar_bricks"],
    "bamboo_mosaic_slab": ["bamboo_mosaic"],
    "bamboo_mosaic_stairs": ["bamboo_mosaic"],
    # Ohne Alias greift die allgemeine Holzregel und liefert die Bretter statt
    # der Rinde. Die berindeten Varianten der neueren Hölzer tragen keinen
    # gleichnamigen Texture-Key.
    "cherry_wood": ["cherry_log_side"],
    "crimson_fence": ["crimson_planks"],
    "crimson_fence_gate": ["crimson_planks"],
    "crimson_hyphae": ["crimson_log_side"],
    # Die Stufe erbt den rundum gleichen Schnittsandstein des vollen Blocks
    # statt der Deckfläche des ungeschnittenen Sandsteins.
    "cut_red_sandstone_slab": ["cut_red_sandstone"],
    "cut_sandstone_slab": ["cut_sandstone"],
    # Schwarzeiche heißt in den Laubtexturen ``big_oak``; ohne Alias endet das
    # Laub bei den gleichnamigen Brettern.
    "dark_oak_leaves": ["big_oak_leaves_carried"],
    "crimson_pressure_plate": ["crimson_planks"],
    "crimson_slab": ["crimson_planks"],
    "crimson_stairs": ["crimson_planks"],
    "crimson_stem": ["crimson_log_side"],
    "deepslate_brick_slab": ["deepslate_bricks"],
    "deepslate_brick_stairs": ["deepslate_bricks"],
    "deepslate_brick_wall": ["deepslate_bricks"],
    "deepslate_tile_slab": ["deepslate_tiles"],
    "deepslate_tile_stairs": ["deepslate_tiles"],
    "deepslate_tile_wall": ["deepslate_tiles"],
    "end_brick_stairs": ["end_bricks"],
    "end_portal_frame": ["endframe_top"],
    "fence_gate": ["planks_oak"],
    "glow_frame": ["glow_item_frame"],
    "heavy_weighted_pressure_plate": ["iron_block"],
    "honey_block": ["honey_side"],
    "infested_deepslate": ["deepslate"],
    "iron_chain": ["chain"],
    "light_gray_carpet": ["wool_colored_silver"],
    "light_gray_wool": ["wool_colored_silver"],
    "light_weighted_pressure_plate": ["gold_block"],
    "lit_pumpkin": ["pumpkin_face_on"],
    "mangrove_wood": ["mangrove_log_side"],
    "melon_block": ["melon_side"],
    "moss_carpet": ["moss_block"],
    "mossy_cobblestone": ["cobblestone_mossy"],
    "mossy_cobblestone_stairs": ["cobblestone_mossy"],
    "mud_brick_slab": ["mud_bricks"],
    "mud_brick_stairs": ["mud_bricks"],
    "mud_brick_wall": ["mud_bricks"],
    "normal_stone_stairs": ["stone"],
    "packed_ice": ["ice_packed"],
    "pale_moss_carpet": ["pale_moss_block"],
    "pale_oak_wood": ["pale_oak_log_side"],
    "pointed_dripstone": ["pointed_dripstone_up_tip"],
    "polished_blackstone_brick_slab": ["polished_blackstone_bricks"],
    "polished_blackstone_brick_stairs": ["polished_blackstone_bricks"],
    "polished_blackstone_brick_wall": ["polished_blackstone_bricks"],
    "rail": ["rail_normal"],
    "red_mushroom_block": ["mushroom_block_skin_red"],
    # Der Deckel-Key gewinnt hier sonst auch die Seitenfläche; ``_normal`` ist
    # die Flanke, wie sie Mauer und Stufe bereits verwenden.
    "red_sandstone": ["red_sandstone_normal"],
    "red_sandstone_stairs": ["red_sandstone_normal"],
    "small_dripleaf_block": ["small_dripleaf_top"],
    "snow_layer": ["snow"],
    "sticky_piston": ["piston_top_sticky"],
    "stone_brick_stairs": ["stone_bricks"],
    # ``stone_stairs`` ist in Bedrock historisch die Bruchsteintreppe;
    # ``normal_stone_stairs`` ist die aus glattem Stein.
    "stone_stairs": ["cobblestone"],
    "stripped_cherry_wood": ["stripped_cherry_log_side"],
    "stripped_crimson_hyphae": ["stripped_crimson_stem_side"],
    "stripped_mangrove_wood": ["stripped_mangrove_log_side"],
    "stripped_pale_oak_wood": ["stripped_pale_oak_log_side"],
    "stripped_warped_hyphae": ["stripped_warped_stem_side"],
    "sulfur_brick_slab": ["sulfur_bricks"],
    "sulfur_brick_stairs": ["sulfur_bricks"],
    "sulfur_brick_wall": ["sulfur_bricks"],
    "sulfur_spike": ["sulfur_spike_up_tip"],
    "warped_fence": ["warped_planks"],
    "warped_fence_gate": ["warped_planks"],
    "warped_hyphae": ["warped_stem_side"],
    "warped_pressure_plate": ["warped_planks"],
    "warped_slab": ["warped_planks"],
    "warped_stairs": ["warped_planks"],
    # Wachsen verändert die Farbe nicht; die ungewachste Basis ist deshalb
    # der fachlich korrekte Vorschau-Sprite.
    "waxed_copper": ["copper_block"],
    "waxed_copper_chest": ["copper_chest_inventory_front"],
    "waxed_exposed_copper_chest": ["exposed_copper_chest_inventory_front"],
    "waxed_oxidized_copper_chest": ["oxidized_copper_chest_inventory_front"],
    "waxed_weathered_copper_chest": ["weathered_copper_chest_inventory_front"],
    "wooden_pressure_plate": ["planks_oak"],
    "bow": ["bow_standby"],
    "crossbow": ["crossbow_standby"],
    # Kein normaler Alias für "shield": MODEL_ICON_SPECS koppelt den Atlas
    # explizit mit der Vanilla-Geometrie, statt ihn als flaches PNG zu kopieren.
    "appleenchanted": ["apple_golden"],
    "baked_potato": ["potato_baked"],
    "beef": ["beef_raw"],
    "chicken": ["chicken_raw"],
    "porkchop": ["porkchop_raw"],
    "mutton": ["mutton_raw"],
    "rabbit": ["rabbit_raw"],
    "cod": ["fish_raw"],
    "salmon": ["fish_salmon_raw"],
    "tropical_fish": ["clownfish"],
    "cooked_cod": ["cooked_fish"],
    "cooked_salmon": ["fish_salmon_cooked"],
    "bucketwater": ["bucket_water"],
    "bucketlava": ["bucket_lava"],
    "bucketmilk": ["bucket_milk"],
    "bucketpowdersnow": ["bucket_powder_snow"],
    "buckettadpole": ["bucket_tadpole"],
    "bucketpuffer": ["bucket_pufferfish"],
    "bucketsalmon": ["bucket_salmon"],
    "bucketfish": ["bucket_cod"],
    "bucketaxolotl": ["bucket_axolotl"],
    "bucketcustomfish": ["bucket_tropical"],
    "buckettropical": ["bucket_tropical"],
    "bucketsulfurcube": ["bucket_sulfur_cube"],
    "axolotl_bucket": ["bucket_axolotl"],
    "tropical_fish_bucket": ["bucket_tropical"],
    "tadpole_bucket": ["bucket_tadpole"],
    "pufferfish_bucket": ["bucket_pufferfish"],
    "salmon_bucket": ["bucket_salmon"],
    "cod_bucket": ["bucket_cod"],
    "carrotonastick": ["carrot_on_a_stick"],
    "anvil": ["anvil_base", "anvil_top_damaged_0"],
    "bell": ["villagebell", "bell_top"],
    "book": ["book_normal"],
    "enchanted_book": ["book_enchanted"],
    "writable_book": ["book_writable"],
    "written_book": ["book_written"],
    "clock": ["clock_item"],
    "compass": ["compass_item"],
    # Funktionale Steinsaege: Texturen heissen stonecutter2_*; "stonecutter" ist der Legacy-Block.
    "stonecutter_block": ["stonecutter2_side", "stonecutter2_top"],
    "filled_map": ["map_filled"],
    "petrified_oak_slab": ["planks_oak"],
    "minecart": ["minecart_normal"],
    "minecartfurnace": ["minecart_furnace"],
    "potion": ["potion_bottle_drinkable"],
    "splash_potion": ["potion_bottle_splash"],
    "lingering_potion": ["potion_bottle_lingering"],
    "bone_meal": ["dye_powder_white"],
    "cactus": ["cactus_side", "cactus_top"],
    "carved_pumpkin": ["pumpkin_face", "pumpkin_face_off"],
    "grass_block": ["grass_side_carried", "grass_block_side", "grass_side"],
    "podzol": ["dirt_podzol_side", "podzol_side"],
    "mycelium": ["mycelium_side"],
    "snow": ["snow"],
    "snow_block": ["snow"],
    "bricks": ["brick"],
    "brick_block": ["brick"],
    "nether_bricks": ["nether_brick"],
    "red_nether_bricks": ["red_nether_brick"],
    "bookshelf": ["bookshelf"],
    "crafting_table": ["crafting_table_front", "crafting_table_top"],
    "furnace": ["furnace_front_off", "furnace_front_on"],
    "blast_furnace": ["blast_furnace_front_off", "blast_furnace_front_on"],
    "smoker": ["smoker_front_off", "smoker_front_on"],
    "chest": ["chest_front"],
    "ender_chest": ["ender_chest_front"],
    "torch": ["torch_on", "torch"],
    "soul_torch": ["soul_torch"],
    "redstone_torch": ["redstone_torch_on"],
    "lantern": ["lantern"],
    "soul_lantern": ["soul_lantern"],
    "barrier": ["barrier"],
    "allium": ["flower_allium"],
    "azure_bluet": ["flower_houstonia"],
    "blue_orchid": ["flower_blue_orchid"],
    "cornflower": ["flower_cornflower"],
    "dandelion": ["flower_dandelion", "yellow_flower"],
    "large_fern": ["double_plant_fern_carried", "double_plant_fern_top"],
    "lily_of_the_valley": ["flower_lily_of_the_valley"],
    "lilac": ["double_plant_syringa_top"],
    "orange_tulip": ["flower_tulip_orange"],
    "oxeye_daisy": ["flower_oxeye_daisy"],
    "peony": ["double_plant_paeonia_top"],
    "pink_tulip": ["flower_tulip_pink"],
    "poppy": ["flower_rose", "red_flower"],
    "red_tulip": ["flower_tulip_red"],
    "rose_bush": ["rose_bush_carried", "double_plant_rose_top"],
    "sunflower": ["sunflower_carried", "double_plant_sunflower_front", "sunflower_top"],
    "white_tulip": ["flower_tulip_white"],
    "wooden_slab": ["planks_oak"],
    "wither_rose": ["flower_wither_rose"],
    "entity_axolotl_lucy": ["entity/axolotl/axolotl_lucy"],
    "entity_axolotl_cyan": ["entity/axolotl/axolotl_cyan"],
    "entity_axolotl_gold": ["entity/axolotl/axolotl_gold"],
    "entity_axolotl_wild": ["entity/axolotl/axolotl_wild"],
    "entity_axolotl_blue": ["entity/axolotl/axolotl_blue"],
    "entity_axolotl_lucy_baby": ["entity/axolotl/axolotl_lucy_baby"],
    "entity_axolotl_cyan_baby": ["entity/axolotl/axolotl_cyan_baby"],
    "entity_axolotl_gold_baby": ["entity/axolotl/axolotl_gold_baby"],
    "entity_axolotl_wild_baby": ["entity/axolotl/axolotl_wild_baby"],
    "entity_axolotl_blue_baby": ["entity/axolotl/axolotl_blue_baby"],
}
PREFER_COMMON_ALIAS_ITEMS = {
    # Mojangs current texture data contains some modern *_bucket keys that point
    # to the empty bucket sprite; the actual bucketed mob item sprites are named
    # bucket_<mob>.
    "axolotl_bucket",
    "tropical_fish_bucket",
    # Der aus den Texturnamen abgeleitete Alias liefert hier die Deckfläche und
    # gewinnt sonst auch die Flanke. Stufe und Mauer nutzen bereits ``_normal``.
    "red_sandstone",
}

POTION_DAMAGE_TEXTURE_SUFFIXES = {
    0: "empty",
    5: "nightVision",
    6: "nightVision",
    7: "invisibility",
    8: "invisibility",
    9: "jump",
    10: "jump",
    11: "jump",
    12: "fireResistance",
    13: "fireResistance",
    14: "moveSpeed",
    15: "moveSpeed",
    16: "moveSpeed",
    17: "moveSlowdown",
    18: "moveSlowdown",
    19: "waterBreathing",
    20: "waterBreathing",
    21: "heal",
    22: "heal",
    23: "harm",
    24: "harm",
    25: "poison",
    26: "poison",
    27: "poison",
    28: "regeneration",
    29: "regeneration",
    30: "regeneration",
    31: "damageBoost",
    32: "damageBoost",
    33: "damageBoost",
    34: "weakness",
    35: "weakness",
    36: "wither",
    37: "turtleMaster",
    38: "turtleMaster",
    39: "turtleMaster",
    40: "slowFall",
    41: "slowFall",
    42: "moveSlowdown",
    43: "windCharged",
    44: "weaving",
    45: "oozing",
    46: "infested",
}
BED_VARIANT_TEXTURE_PATHS = [
    "items/bed_white",
    "items/bed_orange",
    "items/bed_magenta",
    "items/bed_light_blue",
    "items/bed_yellow",
    "items/bed_lime",
    "items/bed_pink",
    "items/bed_gray",
    "items/bed_silver",
    "items/bed_cyan",
    "items/bed_purple",
    "items/bed_blue",
    "items/bed_brown",
    "items/bed_green",
    "items/bed_red",
    "items/bed_black",
]
POTION_ITEM_TEXTURE_PREFIXES = {
    "potion": "potion_bottle",
    "splash_potion": "potion_bottle_splash",
    "lingering_potion": "potion_bottle_lingering",
}
# Mojang liefert für die wirkungslosen Bedrock-Wurftränke keine separaten
# Varianten-PNGs. Wasser, Mundan, verlängert Mundan, Dickflüssig und Seltsam
# verwenden alle explizit die blaue Splash-Basistextur.
SPLASH_POTION_BASE_TEXTURE_DAMAGE_VALUES = range(5)
TIPPED_ARROW_DAMAGE_TEXTURE_SUFFIXES = {
    5: "nightvision",
    6: "nightvision",
    7: "invisibility",
    8: "invisibility",
    9: "leaping",
    10: "leaping",
    11: "leaping",
    12: "fireres",
    13: "fireres",
    14: "swift",
    15: "swift",
    16: "swift",
    17: "slow",
    18: "slow",
    19: "waterbreathing",
    20: "waterbreathing",
    21: "healing",
    22: "healing",
    23: "harm",
    24: "harm",
    25: "poison",
    26: "poison",
    27: "poison",
    28: "regen",
    29: "regen",
    30: "regen",
    31: "strength",
    32: "strength",
    33: "strength",
    34: "weakness",
    35: "weakness",
    36: "wither",
    37: "turtlemaster",
    38: "turtlemaster",
    39: "turtlemaster",
    40: "slowfalling",
    41: "slowfalling",
    42: "slow",
    43: "windCharged",
    44: "weaving",
    45: "oozing",
    46: "infested",
}

WOOD_VARIANTS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "bamboo", "pale_oak")
WOOD_TEXTURE_SUFFIX = {
    "oak": "oak",
    "spruce": "spruce",
    "birch": "birch",
    "jungle": "jungle",
    "acacia": "acacia",
    "dark_oak": "darkoak",
    "mangrove": "mangrove",
    "cherry": "cherry",
    "bamboo": "bamboo",
    "pale_oak": "pale_oak",
}
LEGACY_WOOD_ALIASES = {texture: wood for wood, texture in WOOD_TEXTURE_SUFFIX.items()}
DYE_TEXTURE_COLORS = {"light_gray": "silver"}
BASE_BLOCK_SUFFIXES = (
    "_double_slab",
    "_slab",
    "_stairs",
    "_wall",
    "_fence_gate",
    "_fence",
    "_button",
    "_pressure_plate",
    "_standing_sign",
    "_wall_sign",
    "_sign",
)
# ``*_wood`` und ``*_hyphae`` sind die rundum berindeten Stammvarianten: alle
# sechs Flächen tragen die Seitentextur. Ohne diese Regel findet die
# Flächensuche den Stammquerschnitt ``*_top`` und setzt ihn als Deckel auf –
# damit sähe ein Holzblock aus wie der gleichnamige Stamm.
BARK_ON_EVERY_FACE_SUFFIXES = ("_wood", "_hyphae")
TEXTURE_NAME_PREFIXES = ("flower_", "item_", "block_", "double_plant_")
TEXTURE_NAME_SUFFIXES = (
    "_front",
    "_back",
    "_top",
    "_bottom",
    "_side",
    "_end",
    "_on",
    "_off",
)
# Flächen, die ein Item nur als letzte Wahl repräsentieren sollen.
DEPRIORITIZED_FACE_SUFFIXES = ("_bottom",)
EXTRA_ITEM_ICON_IDS = (
    "large_fern",
    "lilac",
    "peony",
    "rose_bush",
    "sunflower",
)
AXOLOTL_DISPLAY_ASSETS = {
    f"mcbe:axolotl_{variant}{suffix}": f"entity_axolotl_{variant}{suffix}" for variant in ("lucy", "cyan", "gold", "wild", "blue") for suffix in ("", "_baby")
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def log(message: str) -> None:
    print(message)


def _validate_https_url(url: str, allowed_hosts: set[str], *, label: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise RuntimeError(tr("Unsichere {label}-URL: {url}", label=label, url=repr(url))) from exc
    if parsed.scheme.lower() != "https" or host not in allowed_hosts or port not in (None, 443) or parsed.username is not None or parsed.password is not None:
        raise RuntimeError(tr("Unsichere {label}-URL: {url}", label=label, url=repr(url)))
    return url


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib contacts a non-allowlisted target."""

    def __init__(self, allowed_hosts: set[str], *, label: str):
        super().__init__()
        self._allowed_hosts = frozenset(allowed_hosts)
        self._label = label

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved_url = urllib.parse.urljoin(req.full_url, newurl)
        _validate_https_url(resolved_url, self._allowed_hosts, label=self._label)
        return super().redirect_request(req, fp, code, msg, headers, resolved_url)


def _build_validating_opener(allowed_hosts: set[str], *, label: str):
    return urllib.request.build_opener(_AllowlistedRedirectHandler(allowed_hosts, label=label))


def _validate_final_response_url(resp, allowed_hosts: set[str], *, label: str) -> None:
    final_url = getattr(resp, "url", None) or resp.geturl()
    _validate_https_url(final_url, allowed_hosts, label=label)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise


def fetch_github_json(url: str) -> dict[str, Any]:
    _validate_https_url(url, ALLOWED_GITHUB_API_HOSTS, label="GitHub-API")
    opener = _build_validating_opener(ALLOWED_GITHUB_API_HOSTS, label="GitHub-API")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Icon-Updater/1.0")]
    with opener.open(url, timeout=30) as resp:
        _validate_final_response_url(resp, ALLOWED_GITHUB_API_HOSTS, label="GitHub-API")
        raw = resp.read(MAX_RELEASE_JSON_BYTES + 1)
    if len(raw) > MAX_RELEASE_JSON_BYTES:
        raise RuntimeError(tr("GitHub-API-Antwort ist unerwartet groß."))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(tr("GitHub-API-Antwort enthält ungültiges JSON: {error}", error=exc)) from exc
    if not isinstance(data, dict):
        raise RuntimeError(tr("GitHub-API-Antwort hat ein unerwartetes JSON-Format."))
    return data


def get_latest_full_release_info() -> dict[str, Any]:
    data = fetch_github_json(RP_LATEST_API)
    tag = str(data.get("tag_name") or "unknown")
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError(tr("GitHub-API-Antwort enthält keine gültige Asset-Liste."))
    candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        size = _safe_int(asset.get("size"), 0)
        if not name.endswith(".zip") or name.endswith("-min.zip"):
            continue
        if "bedrock-samples" not in name:
            continue
        candidates.append((name, size, str(asset.get("browser_download_url") or "")))
    if not candidates:
        raise RuntimeError(tr("Kein Full-Asset im Release {release} gefunden.", release=tag))
    name, size, url = sorted(candidates, key=lambda row: row[1], reverse=True)[0]
    if size <= 0 or size > MAX_RESOURCE_PACK_BYTES:
        raise RuntimeError(tr("Resource-Pack-Asset hat eine unerwartete Größe: {size} Bytes", size=size))
    return {
        "resource_pack_release": tag,
        "resource_pack_asset": name,
        "resource_pack_asset_size": size,
        "resource_pack_url": _validate_https_url(url, ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack"),
        "resource_pack_fetched_at": utc_now(),
    }


def _valid_release_metadata(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("resource_pack_asset"), str):
        return False
    asset_name = data["resource_pack_asset"]
    if not asset_name or Path(asset_name).name != asset_name or any(separator in asset_name for separator in ("/", "\\")):
        return False
    if not isinstance(data.get("resource_pack_release"), str) or not data.get("resource_pack_release"):
        return False
    if not isinstance(data.get("resource_pack_url"), str) or not data.get("resource_pack_url"):
        return False
    size = _safe_int(data.get("resource_pack_asset_size"), 0)
    if size <= 0 or size > MAX_RESOURCE_PACK_BYTES:
        return False
    try:
        _validate_https_url(str(data.get("resource_pack_url") or ""), ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
    except RuntimeError:
        return False
    return True


def read_release_metadata() -> dict[str, Any]:
    try:
        data = json.loads(RELEASE_METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return {}
    return data if _valid_release_metadata(data) else {}


def _same_resource_pack_release(first: dict[str, Any], second: dict[str, Any]) -> bool:
    fields = (
        "resource_pack_release",
        "resource_pack_asset",
        "resource_pack_asset_size",
        "resource_pack_url",
    )
    return bool(first) and bool(second) and all(first.get(field) == second.get(field) for field in fields)


def write_release_metadata(info: dict[str, Any]) -> None:
    atomic_write_text(RELEASE_METADATA_PATH, json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _validate_downloaded_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_RESOURCE_PACK_MEMBERS:
                raise RuntimeError(tr("Resource-Pack-Download enthält unerwartet viele ZIP-Einträge."))
            total_uncompressed = 0
            for member in members:
                if member.file_size < 0 or member.file_size > MAX_RESOURCE_PACK_MEMBER_BYTES:
                    raise RuntimeError(
                        tr("Resource-Pack-Download enthält einen unerwartet großen ZIP-Eintrag: {member}", member=member.filename)
                    )
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_RESOURCE_PACK_UNCOMPRESSED_BYTES:
                    raise RuntimeError(tr("Resource-Pack-Download ist entpackt unerwartet groß."))
            damaged_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(tr("Resource-Pack-Download ist keine gültige ZIP-Datei.")) from exc
    if damaged_member:
        raise RuntimeError(tr("Resource-Pack-Download enthält einen beschädigten ZIP-Eintrag: {member}", member=damaged_member))


def download_release_zip(info: dict[str, Any], *, use_cache: bool) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    asset_name = str(info.get("resource_pack_asset") or "")
    if not asset_name or Path(asset_name).name != asset_name or any(separator in asset_name for separator in ("/", "\\")):
        raise RuntimeError(tr("Resource-Pack-Assetname ist ungültig."))
    expected_size = _safe_int(info.get("resource_pack_asset_size"), 0)
    if expected_size <= 0 or expected_size > MAX_RESOURCE_PACK_BYTES:
        raise RuntimeError(tr("Resource-Pack-Asset hat eine unerwartete Größe: {size} Bytes", size=expected_size))
    zip_path = CACHE_DIR / asset_name
    if use_cache and zip_path.exists() and zip_path.stat().st_size == expected_size:
        try:
            _validate_downloaded_zip(zip_path)
        except RuntimeError:
            pass
        else:
            log(tr("Cache verwendet: {path}", path=zip_path))
            return zip_path

    opener = _build_validating_opener(ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Icon-Updater/1.0")]
    fd, temp_name = tempfile.mkstemp(prefix=f".{asset_name}.", suffix=".part", dir=CACHE_DIR)
    temp_path = Path(temp_name)
    try:
        with opener.open(str(info["resource_pack_url"]), timeout=60) as resp, os.fdopen(fd, "wb") as output:
            fd = -1
            _validate_final_response_url(resp, ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
            total = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESOURCE_PACK_BYTES:
                    raise RuntimeError(tr("Resource-Pack-Download ist größer als erwartet."))
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != expected_size:
            raise RuntimeError(
                tr(
                    "Resource-Pack-Download ist unvollständig: erwartet {expected} Bytes, erhalten {actual} Bytes",
                    expected=expected_size,
                    actual=total,
                )
            )
        _validate_downloaded_zip(temp_path)
        os.replace(temp_path, zip_path)
        return zip_path
    except Exception:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            temp_path.unlink()
        raise


def prune_cached_icon_release_zips(current_zip: Path) -> dict[str, Any]:
    """Keep only the current updater-owned Full-Release ZIP.

    The update cache is shared with the Item-DB updater and can also contain
    operator-managed files. Restrict retention to the official Full-Release
    naming scheme and never follow or remove symlinks.
    """

    current_name = current_zip.name
    if not _MANAGED_ICON_RELEASE_ZIP_RE.fullmatch(current_name) or current_name.lower().endswith("-min.zip"):
        return {"removed_count": 0, "removed_bytes": 0, "warnings": []}
    try:
        if Path(os.path.abspath(current_zip.parent)) != Path(os.path.abspath(CACHE_DIR)):
            return {"removed_count": 0, "removed_bytes": 0, "warnings": []}
        if current_zip.is_symlink() or not current_zip.is_file():
            return {"removed_count": 0, "removed_bytes": 0, "warnings": []}
    except OSError:
        return {"removed_count": 0, "removed_bytes": 0, "warnings": []}

    removed_count = 0
    removed_bytes = 0
    warnings: list[str] = []
    try:
        candidates = list(CACHE_DIR.iterdir())
    except OSError as exc:
        return {
            "removed_count": 0,
            "removed_bytes": 0,
            "warnings": [tr("Icon-Download-Cache konnte nicht geprüft werden: {error}", error=exc)],
        }

    for candidate in candidates:
        name = candidate.name
        if name == current_name or not _MANAGED_ICON_RELEASE_ZIP_RE.fullmatch(name) or name.lower().endswith("-min.zip"):
            continue
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            size = candidate.stat().st_size
            candidate.unlink()
            removed_count += 1
            removed_bytes += max(0, size)
        except OSError as exc:
            warnings.append(tr("Alter Icon-Release-Cache konnte nicht entfernt werden: {name}: {error}", name=name, error=exc))

    return {
        "removed_count": removed_count,
        "removed_bytes": removed_bytes,
        "warnings": warnings,
    }


def _zip_member_key(name: str) -> str:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if "resource_pack" in parts:
        idx = parts.index("resource_pack")
        return "/".join(parts[idx + 1 :])
    if "textures" in parts:
        idx = parts.index("textures")
        return "/".join(parts[idx:])
    return "/".join(parts)


def _read_json_member(zf: zipfile.ZipFile, key: str) -> dict[str, Any]:
    for info in zf.infolist():
        if info.is_dir() or _zip_member_key(info.filename) != key:
            continue
        raw = zf.read(info)
        data = json.loads(_strip_json_comments(raw.decode("utf-8-sig")))
        return data if isinstance(data, dict) else {}
    return {}


def _normalized_texture_reference(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\\", "/").removeprefix("textures/").removesuffix(".png").removesuffix(".tga")


def _validate_model_icon_mapping(
    zf: zipfile.ZipFile,
    item_id: str,
    item_textures: dict[str, list[str]],
    model_spec: ModelIconSpec,
) -> None:
    has_entity_definition = model_spec.entity_definition_path is not None
    has_entity_variant = model_spec.entity_variant is not None
    if has_entity_definition != has_entity_variant:
        raise ValueError(tr("Modell-Icon-Spezifikation enthält eine unvollständige Entity-Zuordnung."))
    if (model_spec.geometry_variant or model_spec.block_texture_key) and not has_entity_definition:
        raise ValueError(tr("Modell-Icon-Spezifikation enthält eine unvollständige Block-/Geometrie-Zuordnung."))
    if not has_entity_definition:
        if model_spec.texture_path not in item_textures.get(item_id, []):
            raise ValueError(tr("Item-Textur verweist nicht auf den freigegebenen Modell-Atlas."))
        return

    entity_data = _read_json_member(zf, model_spec.entity_definition_path or "")
    client_entity = entity_data.get("minecraft:client_entity")
    description = client_entity.get("description") if isinstance(client_entity, dict) else None
    textures = description.get("textures") if isinstance(description, dict) else None
    geometries = description.get("geometry") if isinstance(description, dict) else None
    variant = model_spec.entity_variant or ""
    geometry_variant = model_spec.geometry_variant or variant
    if not isinstance(textures, dict) or _normalized_texture_reference(textures.get(variant)) != model_spec.texture_path:
        raise ValueError(tr("Entity-Definition verweist nicht auf den freigegebenen Modell-Atlas."))
    if not isinstance(geometries, dict) or geometries.get(geometry_variant) != model_spec.geometry_identifier:
        raise ValueError(tr("Entity-Definition verweist nicht auf die freigegebene Modell-Geometrie."))
    if model_spec.block_texture_key:
        blocks = _read_json_member(zf, "blocks.json")
        block_definition = blocks.get(item_id)
        if not isinstance(block_definition, dict) or block_definition.get("textures") != model_spec.block_texture_key:
            raise ValueError(tr("Block-Definition verweist nicht auf die freigegebene Modell-Texturvariante."))


def _strip_json_comments(text: str) -> str:
    """Remove JSONC-style comments from Mojang texture files."""

    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and nxt == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and nxt == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index = min(index + 2, len(text))
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _texture_paths_from_entry(entry: Any) -> list[str]:
    if isinstance(entry, str):
        return [entry]
    if isinstance(entry, list):
        result: list[str] = []
        for item in entry:
            result.extend(_texture_paths_from_entry(item))
        return result
    if isinstance(entry, dict):
        path = entry.get("path")
        if isinstance(path, str):
            return [path]
        textures = entry.get("textures")
        return _texture_paths_from_entry(textures)
    return []


def parse_texture_data(raw: dict[str, Any]) -> dict[str, list[str]]:
    data = raw.get("texture_data") if isinstance(raw, dict) else {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, entry in data.items():
        normalized = normalize_identifier(str(key))
        paths = []
        for value in _texture_paths_from_entry(entry):
            clean = str(value).replace("\\", "/").removeprefix("textures/").removesuffix(".png")
            if clean:
                paths.append(clean)
        if normalized and paths:
            result[normalized] = paths
    return result


def normalize_identifier(value: str) -> str:
    text = value.strip().lower().replace("minecraft:", "", 1)
    text = text.replace(" ", "_").replace("-", "_")
    return re.sub(r"_+", "_", text)


def load_item_icon_targets(path: Path = ITEM_DB_PATH) -> tuple[list[str], list[str], int]:
    """Load addable icon targets and excluded recognition-catalog IDs.

    ``items`` remains the complete recognition catalog for lossless handling of
    existing worlds. The regular icon QA/cache target list follows Mojang's
    positive item registry in ``addable_items`` instead of every known legacy,
    language, or block identifier.
    """

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(tr("Item-DB JSON nicht gefunden: {path}", path=path)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(tr("Item-DB JSON ist ungültig oder nicht lesbar: {path}", path=path)) from exc
    items = data.get("items") if isinstance(data, dict) else {}
    if not isinstance(items, dict):
        return [], [], 0
    addable_raw = data.get("addable_items") if isinstance(data, dict) else None
    block_only_raw = data.get("block_only_items", []) if isinstance(data, dict) else []
    block_only = {normalized for key in (block_only_raw if isinstance(block_only_raw, list) else []) if (normalized := normalize_identifier(str(key)))}
    catalog_items = {normalized for key in items if (normalized := normalize_identifier(str(key)))}
    if isinstance(addable_raw, list):
        targets = {
            normalized
            for key in addable_raw
            if (normalized := normalize_identifier(str(key)))
            and not is_technical_block_only_item_id(f"minecraft:{normalized}")
        }
    else:
        # Rückwärtskompatibilität für ältere externe Item-Datenbanken.
        targets = {
            item_id
            for item_id in catalog_items - block_only
            if not is_technical_block_only_item_id(f"minecraft:{item_id}")
        }
    excluded = sorted(catalog_items - targets)
    return sorted(targets), excluded, len(catalog_items)


def load_block_item_targets(path: Path = ITEM_DB_PATH) -> set[str]:
    """Load the positive block-item registry used to gate model rendering."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(tr("Item-DB JSON nicht gefunden: {path}", path=path)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(tr("Item-DB JSON ist ungültig oder nicht lesbar: {path}", path=path)) from exc
    raw = data.get("block_items", []) if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return set()
    return {normalized for value in raw if (normalized := normalize_identifier(str(value)))}


def candidate_texture_keys(item_id: str, data_driven_aliases: dict[str, list[str]] | None = None) -> list[str]:
    item = normalize_identifier(item_id)
    keys = []
    if item in PREFER_COMMON_ALIAS_ITEMS and item in COMMON_ALIASES:
        keys.extend(COMMON_ALIASES[item])
    # Bedrock kennzeichnet einige speziell für das Inventar gerenderte
    # Block-Items mit ``*_carried`` (z. B. Turtle Egg). Existiert der Key
    # nicht, ist diese Priorität wirkungslos und die normale Auflösung folgt.
    keys.extend([f"{item}_carried", item])
    if data_driven_aliases and item in data_driven_aliases:
        keys.extend(data_driven_aliases[item])
    if item in COMMON_ALIASES and item not in PREFER_COMMON_ALIAS_ITEMS:
        keys.extend(COMMON_ALIASES[item])
    if item.endswith("_spawn_egg"):
        entity = item.removesuffix("_spawn_egg")
        compact_entity = entity.replace("_", "")
        keys.extend(
            [
                f"spawn_egg_{entity}",
                f"spawn_egg_{compact_entity}",
                f"egg_{entity}",
                f"egg_{compact_entity}",
                "spawn_egg",
                "egg",
            ]
        )
    if item.endswith("_bucket") and item not in PREFER_COMMON_ALIAS_ITEMS:
        bucket_entity = item.removesuffix("_bucket")
        keys.extend([f"bucket_{bucket_entity}", "bucket_empty", "bucket"])
    if item.startswith("music_disc_"):
        disc = item.removeprefix("music_disc_")
        keys.extend([f"record_{disc}", f"music_disc_{disc}"])
    if item.startswith("waxed_"):
        unwaxed = item.removeprefix("waxed_")
        keys.extend([unwaxed, f"{unwaxed}_top", f"{unwaxed}_side", f"{unwaxed}_front", f"{unwaxed}_bottom", f"{unwaxed}_end"])
        for suffix in BASE_BLOCK_SUFFIXES:
            if unwaxed.endswith(suffix):
                base = unwaxed.removesuffix(suffix)
                keys.extend([base, f"{base}_top", f"{base}_side", f"{base}_block"])
                break
    if item.startswith("wooden_"):
        wooden_part = item.removeprefix("wooden_")
        keys.extend([f"wood_{wooden_part}"])
    if item.startswith("golden_"):
        golden_part = item.removeprefix("golden_")
        keys.extend([f"gold_{golden_part}", f"{golden_part}_golden"])
    if item.endswith("_seeds"):
        seed_source = item.removesuffix("_seeds")
        keys.extend([f"seeds_{seed_source}"])
    if item.startswith("cooked_"):
        cooked_source = item.removeprefix("cooked_")
        keys.extend([f"{cooked_source}_cooked"])
    if item.endswith("_rail"):
        rail_kind = item.removesuffix("_rail")
        keys.extend([f"rail_{rail_kind}", item])
    if item.endswith("_minecart"):
        minecart_kind = item.removesuffix("_minecart")
        keys.extend([f"minecart_{minecart_kind}"])
    keys.extend([f"{item}_top", f"{item}_side", f"{item}_front", f"{item}_bottom", f"{item}_end"])
    for wood in WOOD_VARIANTS:
        texture_wood = WOOD_TEXTURE_SUFFIX[wood]
        if item == f"{wood}_boat":
            keys.extend([f"boat_{texture_wood}", "boat"])
        if item == f"{wood}_chest_boat":
            keys.extend([f"{texture_wood}_chest_boat", f"chest_boat_{texture_wood}", f"boat_{texture_wood}", "boat"])
        if item in {f"{wood}_standing_sign", f"{wood}_wall_sign"}:
            keys.extend([f"{wood}_sign", f"sign_{texture_wood}", f"planks_{texture_wood}", f"{wood}_planks", "sign"])
        if item.startswith(f"{wood}_"):
            keys.extend([f"{wood}_planks", f"planks_{texture_wood}"])
    for legacy_wood, wood in LEGACY_WOOD_ALIASES.items():
        if item == f"{legacy_wood}fence":
            keys.extend([f"{wood}_fence", f"planks_{legacy_wood}", f"{wood}_planks"])
    if item.endswith("_chest"):
        keys.extend([f"{item}_inventory_front", f"{item}_inventory_top", f"{item}_inventory_side"])
    for suffix in BASE_BLOCK_SUFFIXES:
        if item.endswith(suffix):
            base = item.removesuffix(suffix)
            keys.extend([base, f"{base}_top", f"{base}_side", f"{base}_block"])
            break
    for color in COLOR_ALIASES:
        prefix = f"{color}_"
        if item.startswith(prefix):
            rest = item.removeprefix(prefix)
            keys.extend([f"{rest}_{color}", f"{rest}_colored_{color}", f"{color}_{rest}"])
            if rest == "wool":
                keys.extend([f"wool_colored_{color}", f"{color}_wool"])
            if rest == "stained_glass":
                keys.extend([f"glass_{color}", f"glass_{color}_stained", f"stained_glass_{color}"])
            if rest == "terracotta":
                keys.extend([f"hardened_clay_stained_{color}", f"terracotta_{color}"])
            if rest == "concrete":
                keys.extend([f"concrete_{color}"])
            if rest == "concrete_powder":
                keys.extend([f"concrete_powder_{color}"])
            if rest == "carpet":
                keys.extend([f"wool_colored_{color}", f"carpet_{color}"])
            if rest == "dye":
                keys.extend([f"dye_powder_{DYE_TEXTURE_COLORS.get(color, color)}"])
    if item.endswith("_planks"):
        wood = item.removesuffix("_planks")
        keys.extend([f"planks_{wood}", item])
    if item.endswith("_log"):
        wood = item.removesuffix("_log")
        keys.extend([f"log_{wood}", f"{wood}_log_side"])
    if item.endswith("_leaves"):
        wood = item.removesuffix("_leaves")
        keys.extend([f"leaves_{wood}"])
    if item.endswith("_sapling"):
        wood = item.removesuffix("_sapling")
        keys.extend([f"sapling_{wood}"])
    return list(dict.fromkeys(keys))


def _texture_alias_candidates_from_path(texture_path: str) -> set[str]:
    stem = PurePosixPath(str(texture_path).replace("\\", "/")).name
    stem = normalize_identifier(stem.removesuffix(".png"))
    if not stem:
        return set()
    candidates = {stem}
    for prefix in TEXTURE_NAME_PREFIXES:
        if stem.startswith(prefix):
            candidates.add(stem.removeprefix(prefix))
    for value in list(candidates):
        for suffix in TEXTURE_NAME_SUFFIXES:
            if value.endswith(suffix):
                candidates.add(value.removesuffix(suffix))
    for value in list(candidates):
        for color in COLOR_ALIASES:
            suffix = f"_{color}"
            if value.endswith(suffix):
                base = value.removesuffix(suffix)
                if base:
                    candidates.add(f"{color}_{base}")
    return {candidate for candidate in candidates if candidate}


def build_data_driven_texture_aliases(texture_data: dict[str, list[str]], known_items: list[str]) -> dict[str, list[str]]:
    known = {normalize_identifier(item) for item in known_items}
    aliases: dict[str, list[str]] = {}
    for texture_paths in texture_data.values():
        for texture_path in texture_paths:
            texture_stem = normalize_identifier(PurePosixPath(texture_path).name)
            for alias in _texture_alias_candidates_from_path(texture_path):
                if alias not in known or alias == texture_stem:
                    continue
                aliases.setdefault(alias, []).append(texture_stem)
    return {key: _ordered_texture_aliases(values) for key, values in sorted(aliases.items())}


def _ordered_texture_aliases(texture_stems: list[str]) -> list[str]:
    """Keep the discovery order, but move the underside behind every other face.

    Without this demotion the order inside ``terrain_texture.json`` alone decides
    which block face becomes a flat item icon, and the underside sorts first
    there. The enchanting table therefore showed the plain obsidian of its
    underside instead of its recognizable side face. Where the underside is the
    only candidate (``quartz_block_bottom`` for smooth quartz, for example) the
    resolution still picks it.
    """

    return sorted(dict.fromkeys(texture_stems), key=lambda stem: stem.endswith(DEPRIORITIZED_FACE_SUFFIXES))


def candidate_png_paths(texture_path: str) -> list[str]:
    path = str(texture_path).replace("\\", "/").removesuffix(".png")
    candidates = [path]
    if "/" in path:
        parent, stem = path.rsplit("/", 1)
        candidates.extend(f"{parent}/{stem}{suffix}" for suffix in TEXTURE_NAME_SUFFIXES)
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def block_face_texture_keys(item_id: str, texture_path: str, face: str) -> list[str]:
    """Return exact candidates for an alternate face of a block preview."""

    item = normalize_identifier(item_id)
    stem = normalize_identifier(PurePosixPath(texture_path).name)
    if item.endswith(BARK_ON_EVERY_FACE_SUFFIXES):
        face = "side"
    keys = list(SPECIAL_BLOCK_FACE_TEXTURE_KEYS.get(item, {}).get(face, ()))
    keys.append(f"{item}_{face}")
    removable_suffixes = ("_front_off", "_front_on", "_front", "_side", "_top", "_bottom", "_end")
    bases = [item]
    for value in (item, stem):
        trimmed = value
        for suffix in removable_suffixes:
            if value.endswith(suffix):
                trimmed = value.removesuffix(suffix)
                break
        if trimmed not in bases:
            bases.append(trimmed)
    for base in bases:
        if face == "front":
            keys.extend([f"{base}_front_off", f"{base}_front", f"{base}_side"])
        elif face == "top":
            keys.extend([f"{base}_top", f"{base}_end"])
        else:
            keys.extend([f"{base}_side", base])
    if item.endswith("_log"):
        wood = item.removesuffix("_log")
        texture_wood = WOOD_TEXTURE_SUFFIX.get(wood, wood)
        if face == "top":
            keys.extend([f"log_{texture_wood}_top", f"{wood}_log_top"])
        else:
            keys.extend([f"log_{texture_wood}", f"log_{texture_wood}_side", f"{wood}_log_side"])
    return list(dict.fromkeys(keys))


TextureMember = tuple[str, zipfile.ZipInfo]


def potion_variant_texture_keys(item_id: str) -> dict[int, str]:
    item = normalize_identifier(item_id)
    if item in POTION_ITEM_TEXTURE_PREFIXES:
        prefix = POTION_ITEM_TEXTURE_PREFIXES[item]
        variants = {damage: f"{prefix}_{suffix}" for damage, suffix in POTION_DAMAGE_TEXTURE_SUFFIXES.items()}
        if item == "splash_potion":
            variants.update({damage: prefix for damage in SPLASH_POTION_BASE_TEXTURE_DAMAGE_VALUES})
        return variants
    if item == "tipped_arrow":
        return {damage: f"tipped_arrow_{suffix}" for damage, suffix in TIPPED_ARROW_DAMAGE_TEXTURE_SUFFIXES.items()}
    return {}


def bed_variant_texture_keys(item_id: str, texture_data: dict[str, list[str]]) -> dict[int, str]:
    """Return the 16 Bedrock bed sprites in authoritative data-value order."""

    if normalize_identifier(item_id) != "bed":
        return {}
    paths = texture_data.get("bed", [])
    if paths[: len(BED_VARIANT_TEXTURE_PATHS)] != BED_VARIANT_TEXTURE_PATHS:
        return {}
    return dict(enumerate(BED_VARIANT_TEXTURE_PATHS))


def _texture_members(zf: zipfile.ZipFile) -> dict[str, TextureMember]:
    members: dict[str, TextureMember] = {}
    for info in zf.infolist():
        if info.is_dir() or info.file_size <= 0 or info.file_size > MAX_ICON_BYTES:
            continue
        key = _zip_member_key(info.filename)
        if not key.startswith(TEXTURE_PREFIXES):
            continue
        if key.endswith(".png"):
            normalized = key.removesuffix(".png")
            source: TextureMember = ("png", info)
        elif key.endswith(".tga") and not key.endswith("_mers.tga"):
            normalized = key.removesuffix(".tga")
            source = ("tga", info)
        else:
            continue
        members.setdefault(normalized, source)
        members.setdefault(normalized.removeprefix("textures/"), source)
    return members


def _is_entity_texture_path(path: str) -> bool:
    return str(path).startswith(("textures/entity/", "entity/"))


def _select_texture_source(
    texture_keys: list[str],
    texture_data: dict[str, list[str]],
    texture_members: dict[str, TextureMember],
    *,
    preserve_candidate_order: bool = False,
) -> tuple[str, TextureMember] | None:
    def mapped_source(key: str) -> tuple[str, TextureMember] | None:
        for texture_path in texture_data.get(key, []):
            for png_path in candidate_png_paths(texture_path):
                if _is_entity_texture_path(png_path) and not _is_entity_texture_path(key):
                    # item_texture.json mappt modell-gerenderte Items (z. B. das
                    # Schild) auf ihre Entity-/Modell-Atlas-Textur. Die ist kein
                    # Inventar-Sprite und würde als weiße Fläche erscheinen –
                    # normale Item-Auswahl darf sie deshalb nie direkt kopieren.
                    # MODEL_ICON_SPECS behandelt geprüfte Modell-/Atlas-Paare.
                    # Explizite entity/-Kandidaten (Axolotl-Varianten) bleiben.
                    continue
                source = texture_members.get(png_path)
                if source:
                    return png_path, source
        return None

    def direct_source(key: str) -> tuple[str, TextureMember] | None:
        source = texture_members.get(key)
        if source:
            return key, source
        for fallback in (f"items/{key}", f"blocks/{key}"):
            source = texture_members.get(fallback)
            if source:
                return fallback, source
        return None

    if preserve_candidate_order:
        # Nicht-Block-Items besitzen häufig konkrete PNGs neben einem
        # datenwertabhängigen Sammelschlüssel (bucket, spawn_egg, boat …).
        # Jeder spezifische Kandidat muss vollständig geprüft werden, bevor ein
        # späterer generischer Schlüssel sein erstes Array-Element liefert.
        for key in texture_keys:
            selected = mapped_source(key) or direct_source(key)
            if selected:
                return selected
        return None

    for key in texture_keys:
        selected = mapped_source(key)
        if selected:
            return selected
    for direct_key in texture_keys:
        selected = direct_source(direct_key)
        if selected:
            return selected
    return None


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def _encode_rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError(tr("Ungültige RGBA-Bilddaten."))
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        rows.extend(rgba[y * stride : (y + 1) * stride])
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(bytes(rows))) + _png_chunk(b"IEND", b"")


def _tga_pixel_to_rgba(pixel: bytes, bits_per_pixel: int) -> bytes:
    if bits_per_pixel == 32 and len(pixel) == 4:
        blue, green, red, alpha = pixel
        return bytes((red, green, blue, alpha))
    if bits_per_pixel == 24 and len(pixel) == 3:
        blue, green, red = pixel
        return bytes((red, green, blue, 255))
    raise ValueError(tr("Nicht unterstützte TGA-Farbtiefe: {bits_per_pixel}", bits_per_pixel=bits_per_pixel))


def _decode_tga_to_png(raw: bytes) -> bytes:
    if len(raw) < 18:
        raise ValueError(tr("TGA-Datei ist zu kurz."))
    id_length, color_map_type, image_type = raw[0], raw[1], raw[2]
    color_map_first = raw[3] | (raw[4] << 8)
    color_map_length = raw[5] | (raw[6] << 8)
    color_map_depth = raw[7]
    width = raw[12] | (raw[13] << 8)
    height = raw[14] | (raw[15] << 8)
    bits_per_pixel = raw[16]
    descriptor = raw[17]
    if width <= 0 or height <= 0 or width * height > MAX_DECODED_ICON_PIXELS:
        raise ValueError(tr("TGA-Bildgröße ist unerwartet."))
    offset = 18 + id_length
    palette: list[bytes] = []
    if color_map_type:
        if color_map_depth not in {24, 32}:
            raise ValueError(tr("Nicht unterstützte TGA-Paletten-Farbtiefe: {bits_per_pixel}", bits_per_pixel=color_map_depth))
        color_bytes = color_map_depth // 8
        for _ in range(color_map_length):
            palette.append(_tga_pixel_to_rgba(raw[offset : offset + color_bytes], color_map_depth))
            offset += color_bytes
    pixel_count = width * height
    pixels: list[bytes] = []
    pixel_bytes = max(bits_per_pixel // 8, 1)
    if image_type == 1 and color_map_type:
        if bits_per_pixel != 8:
            raise ValueError(tr("Nicht unterstützte TGA-Index-Farbtiefe: {bits_per_pixel}", bits_per_pixel=bits_per_pixel))
        for value in raw[offset : offset + pixel_count]:
            palette_index = value - color_map_first
            if palette_index < 0 or palette_index >= len(palette):
                raise ValueError(tr("TGA-Palettenindex außerhalb der Palette."))
            pixels.append(palette[palette_index])
    elif image_type == 2 and not color_map_type:
        for _ in range(pixel_count):
            pixels.append(_tga_pixel_to_rgba(raw[offset : offset + pixel_bytes], bits_per_pixel))
            offset += pixel_bytes
    elif image_type == 10 and not color_map_type:
        while len(pixels) < pixel_count and offset < len(raw):
            packet = raw[offset]
            offset += 1
            count = (packet & 0x7F) + 1
            if packet & 0x80:
                pixel = _tga_pixel_to_rgba(raw[offset : offset + pixel_bytes], bits_per_pixel)
                offset += pixel_bytes
                pixels.extend([pixel] * count)
            else:
                for _ in range(count):
                    pixels.append(_tga_pixel_to_rgba(raw[offset : offset + pixel_bytes], bits_per_pixel))
                    offset += pixel_bytes
    else:
        raise ValueError(tr("Nicht unterstützter TGA-Typ: {image_type}", image_type=image_type))
    if len(pixels) != pixel_count:
        raise ValueError(tr("TGA-Pixeldaten sind unvollständig."))
    origin_top = bool(descriptor & 0x20)
    origin_right = bool(descriptor & 0x10)
    rows = []
    for y in range(height):
        row = pixels[y * width : (y + 1) * width]
        if origin_right:
            row.reverse()
        rows.append(b"".join(row))
    if not origin_top:
        rows.reverse()
    return _encode_rgba_png(width, height, b"".join(rows))


def _write_texture_as_png(zf: zipfile.ZipFile, source: TextureMember, target: Path) -> None:
    kind, info = source
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "png":
        with zf.open(info) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        return
    if kind == "tga":
        target.write_bytes(_decode_tga_to_png(zf.read(info)))
        return
    raise ValueError(tr("Nicht unterstützte Texturquelle: {kind}", kind=kind))


def _texture_source_png_bytes(zf: zipfile.ZipFile, source: TextureMember) -> bytes:
    kind, info = source
    raw = zf.read(info)
    if kind == "png":
        return raw
    if kind == "tga":
        return _decode_tga_to_png(raw)
    raise ValueError(tr("Nicht unterstützte Texturquelle: {kind}", kind=kind))


def build_icon_cache(
    zip_path: Path,
    known_items: list[str],
    target_root: Path,
    release_info: dict[str, Any],
    *,
    catalog_item_count: int | None = None,
    excluded_non_addable_count: int = 0,
    block_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    # tempfile returns an absolute staging path even when ``dir`` was relative.
    # Normalize only the working address (without resolving symlinks) so the
    # atomic publisher can compare both parent directories reliably.
    target_root = Path(os.path.abspath(target_root))
    with zipfile.ZipFile(zip_path) as zf:
        item_textures = parse_texture_data(_read_json_member(zf, "textures/item_texture.json"))
        terrain_textures = parse_texture_data(_read_json_member(zf, "textures/terrain_texture.json"))
        texture_data = {**terrain_textures, **item_textures}
        known_item_set = set(known_items)
        icon_targets = sorted(known_item_set | set(EXTRA_ITEM_ICON_IDS))
        display_texture_targets = list(AXOLOTL_DISPLAY_ASSETS.values())
        data_driven_aliases = build_data_driven_texture_aliases(texture_data, icon_targets + display_texture_targets)
        texture_members = _texture_members(zf)
        target_root.parent.mkdir(parents=True, exist_ok=True)
        recover_icon_cache(target_root, warn=log)
        with tempfile.TemporaryDirectory(prefix=f".{target_root.name}.staging-", dir=target_root.parent) as staging_name:
            staging = Path(staging_name)
            extracted = staging / "textures" / "items"
            extracted_display = staging / "textures" / "display"
            mapped: dict[str, str] = {}
            display_assets: dict[str, str] = {}
            missing: list[str] = []
            used_members: set[str] = set()
            mapped_item_icons = 0
            mapped_extra_item_icons = 0
            potion_variant_icons = 0
            bed_variant_icons = 0
            generated_block_icons: dict[str, dict[str, str]] = {}
            generated_model_icons: dict[str, dict[str, str]] = {}
            render_failures: dict[str, str] = {}
            block_items = {normalize_identifier(value) for value in (block_item_ids or set())}
            for item_id in icon_targets:
                model_spec = MODEL_ICON_SPECS.get(item_id)
                model_handled = model_spec is not None
                if model_spec:
                    target = extracted / f"{item_id}.png"
                    try:
                        _validate_model_icon_mapping(zf, item_id, item_textures, model_spec)
                        source = texture_members.get(model_spec.texture_path)
                        if source is None:
                            raise ValueError(tr("Modell-Atlas {path} fehlt.", path=repr(model_spec.texture_path)))
                        rendered_png = render_bedrock_model_icon(
                            _read_json_member(zf, model_spec.geometry_path),
                            _texture_source_png_bytes(zf, source),
                            geometry_identifier=model_spec.geometry_identifier,
                            yaw=model_spec.yaw,
                            pitch=model_spec.pitch,
                            roll=model_spec.roll,
                        )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(rendered_png)
                        namespaced_item_id = f"minecraft:{item_id}"
                        generated_model_icons[namespaced_item_id] = {
                            "geometry": model_spec.geometry_path,
                            "geometry_identifier": model_spec.geometry_identifier,
                            "texture": model_spec.texture_path,
                        }
                        if model_spec.entity_definition_path:
                            generated_model_icons[namespaced_item_id]["definition"] = model_spec.entity_definition_path
                            generated_model_icons[namespaced_item_id]["variant"] = model_spec.entity_variant or ""
                        if model_spec.geometry_variant and model_spec.geometry_variant != model_spec.entity_variant:
                            generated_model_icons[namespaced_item_id]["geometry_variant"] = model_spec.geometry_variant
                        if model_spec.block_texture_key:
                            generated_model_icons[namespaced_item_id]["block_texture"] = model_spec.block_texture_key
                        mapped[namespaced_item_id] = model_spec.texture_path
                        used_members.add(_zip_member_key(source[1].filename))
                        if item_id in known_item_set:
                            mapped_item_icons += 1
                        else:
                            mapped_extra_item_icons += 1
                    except (ValueError, zlib.error, struct.error) as exc:
                        namespaced_item_id = f"minecraft:{item_id}"
                        render_failures[namespaced_item_id] = f"{exc.__class__.__name__}: {exc}"
                        if item_id in known_item_set:
                            missing.append(namespaced_item_id)

                selected = (
                    None
                    if model_handled
                    else _select_texture_source(
                        candidate_texture_keys(item_id, data_driven_aliases),
                        texture_data,
                        texture_members,
                        preserve_candidate_order=item_id not in block_items,
                    )
                )
                if selected:
                    texture_path, source = selected
                    target = extracted / f"{item_id}.png"
                    rendered = None
                    if not texture_path.startswith("items/") and "inventory_" not in texture_path:
                        try:
                            alternate_faces: dict[str, tuple[str, TextureMember]] = {}
                            faces = () if item_id.endswith("_leaves") else ("side", "top", "front")
                            for face in faces:
                                face_source = _select_texture_source(block_face_texture_keys(item_id, texture_path, face), texture_data, texture_members)
                                if face_source:
                                    alternate_faces[face] = face_source
                            side_source = alternate_faces.get("side", (texture_path, source))
                            side_png = _texture_source_png_bytes(zf, side_source[1])
                            top_png = _texture_source_png_bytes(zf, alternate_faces["top"][1]) if "top" in alternate_faces else None
                            front_png = _texture_source_png_bytes(zf, alternate_faces["front"][1]) if "front" in alternate_faces else None
                            if item_id == "grass_block":
                                front_overlay_png = front_png or side_png
                                dirt_source = _select_texture_source(["dirt"], texture_data, texture_members)
                                if dirt_source:
                                    alternate_faces["side_underlay"] = dirt_source
                                    dirt_png = _texture_source_png_bytes(zf, dirt_source[1])
                                    side_png = composite_png_overlay(dirt_png, side_png, overlay_tint=GRASS_TINT)
                                    front_png = composite_png_overlay(dirt_png, front_overlay_png, overlay_tint=GRASS_TINT)
                                else:
                                    side_png = tint_png(side_png, GRASS_TINT)
                                    front_png = tint_png(front_overlay_png, GRASS_TINT)
                                if top_png:
                                    top_png = tint_png(top_png, GRASS_TINT)
                            atlas_regions = ATLAS_FACE_REGIONS.get(item_id)
                            if atlas_regions:
                                side_region = atlas_regions["side"]
                                atlas_png = side_png
                                side_png = crop_png(atlas_png, *side_region)
                                top_png = crop_png(atlas_png, *atlas_regions.get("top", side_region))
                                front_png = crop_png(atlas_png, *atlas_regions.get("front", side_region))
                            rendered = render_block_icon(
                                item_id,
                                side_png,
                                is_block_item=item_id in block_items,
                                top_png_bytes=top_png,
                                front_png_bytes=front_png,
                            )
                        except (ValueError, zlib.error, struct.error) as exc:
                            # Beschädigte oder unerwartete Bilddaten bleiben als
                            # Originaltextur nutzbar; nur die Modellvorschau wird
                            # in diesem Fall übersprungen und diagnostiziert.
                            rendered = None
                            render_failures[f"minecraft:{item_id}"] = f"{exc.__class__.__name__}: {exc}"
                    if rendered:
                        rendered_png, shape = rendered
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(rendered_png)
                        generated_block_icons[f"minecraft:{item_id}"] = {"shape": shape, "texture": texture_path}
                        used_members.update(_zip_member_key(face_source[1][1].filename) for face_source in alternate_faces.values())
                    else:
                        _write_texture_as_png(zf, source, target)
                    mapped[f"minecraft:{item_id}"] = texture_path
                    used_members.add(_zip_member_key(source[1].filename))
                    if item_id in known_item_set:
                        mapped_item_icons += 1
                    else:
                        mapped_extra_item_icons += 1
                elif not model_handled and item_id in known_item_set:
                    missing.append(f"minecraft:{item_id}")
                for damage, texture_key in potion_variant_texture_keys(item_id).items():
                    selected_variant = _select_texture_source([texture_key], texture_data, texture_members)
                    if not selected_variant:
                        continue
                    texture_path, source = selected_variant
                    _write_texture_as_png(zf, source, extracted / f"{item_id}#{damage}.png")
                    mapped[f"minecraft:{item_id}#{damage}"] = texture_path
                    used_members.add(_zip_member_key(source[1].filename))
                    potion_variant_icons += 1
                for damage, texture_path in bed_variant_texture_keys(item_id, texture_data).items():
                    source = texture_members.get(texture_path)
                    if not source:
                        continue
                    _write_texture_as_png(zf, source, extracted / f"{item_id}#{damage}.png")
                    mapped[f"minecraft:{item_id}#{damage}"] = texture_path
                    used_members.add(_zip_member_key(source[1].filename))
                    bed_variant_icons += 1
            for asset_id, texture_target in AXOLOTL_DISPLAY_ASSETS.items():
                selected = _select_texture_source(
                    candidate_texture_keys(texture_target, data_driven_aliases),
                    texture_data,
                    texture_members,
                )
                if not selected:
                    continue
                texture_path, source = selected
                asset_name = asset_id.removeprefix("mcbe:")
                _write_texture_as_png(zf, source, extracted_display / f"{asset_name}.png")
                display_assets[asset_id] = texture_path
                used_members.add(_zip_member_key(source[1].filename))
            manifest = {
                "schema_version": 5,
                "generated_at": utc_now(),
                "source": "Mojang/bedrock-samples full release",
                "release": release_info,
                "catalog_items": catalog_item_count if catalog_item_count is not None else len(known_items),
                "known_items": len(known_items),
                "inventory_item_targets": len(known_items),
                "excluded_non_addable_items": max(0, excluded_non_addable_count),
                "icon_targets": len(icon_targets),
                "extra_item_icon_targets": len(EXTRA_ITEM_ICON_IDS),
                "mapped_extra_item_icons": mapped_extra_item_icons,
                "display_asset_targets": len(AXOLOTL_DISPLAY_ASSETS),
                "mapped_display_assets": len(display_assets),
                "mapped_items": mapped_item_icons,
                "mapped_icons": len(mapped),
                "potion_variant_icons": potion_variant_icons,
                "bed_variant_icons": bed_variant_icons,
                "generated_block_icon_count": len(generated_block_icons),
                "generated_block_icons": generated_block_icons,
                "generated_model_icon_count": len(generated_model_icons),
                "generated_model_icons": generated_model_icons,
                "render_failure_count": len(render_failures),
                "render_failures": render_failures,
                "missing_items": missing,
                "missing_count": len(missing),
                "texture_data_keys": len(texture_data),
                "data_driven_texture_aliases": sum(len(values) for values in data_driven_aliases.values()),
                "png_candidates": len(texture_members),
                "used_png_members": len(used_members),
                "sha256": hashlib.sha256(json.dumps({"items": mapped, "display_assets": display_assets}, sort_keys=True).encode("utf-8")).hexdigest(),
                "items": mapped,
                "display_assets": display_assets,
            }
            atomic_write_text(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            publish_icon_cache(staging, target_root, warn=log)
            return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=tr("Lädt Vanilla-Item-Icons aus dem offiziellen Mojang/bedrock-samples Full-Release."))
    parser.add_argument("--force", action="store_true", help=tr("Release neu abfragen und Cache neu bauen."))
    parser.add_argument(
        "--cache",
        "--reuse-cached-release",
        dest="cache",
        action="store_true",
        help=tr("Vorhandene Release-Metadaten ohne Online-Versionsprüfung erneut verarbeiten."),
    )
    parser.add_argument("--dry-run", action="store_true", help=tr("Nur Quelle prüfen, nichts extrahieren."))
    args = parser.parse_args(argv)

    if args.cache and not args.force:
        info = read_release_metadata()
        if not info:
            raise RuntimeError(tr("Die Metadaten des gecachten Icon-Releases fehlen oder sind ungültig."))
        log(tr("Release ohne Online-Versionsprüfung wiederverwenden: {release}", release=info["resource_pack_release"]))
    else:
        info = get_latest_full_release_info()
    cached_metadata = read_release_metadata()
    metadata_needs_write = info != cached_metadata
    log(tr("Release: {release} · {asset}", release=info["resource_pack_release"], asset=info["resource_pack_asset"]))
    if args.dry_run:
        return 0
    # The latest release metadata is always queried in normal mode.  Reusing a
    # validated ZIP with the exact current asset name and size is then safe and
    # avoids a redundant large download.
    reuse_matching_download = not args.force and _same_resource_pack_release(cached_metadata, info)
    zip_path = download_release_zip(info, use_cache=reuse_matching_download)
    known_items, excluded_non_addable, catalog_item_count = load_item_icon_targets()
    block_item_ids = load_block_item_targets()
    if metadata_needs_write:
        write_release_metadata(info)
    # Release metadata describes the downloaded source cache, while the target
    # manifest inside ICON_ROOT describes the currently published icon set.
    # Commit the source metadata first so a metadata error cannot be reported
    # after a new user-visible icon cache was already published.
    manifest = build_icon_cache(
        zip_path,
        known_items,
        ICON_ROOT,
        info,
        catalog_item_count=catalog_item_count,
        excluded_non_addable_count=len(excluded_non_addable),
        block_item_ids=block_item_ids,
    )
    retention = prune_cached_icon_release_zips(zip_path)
    if retention["removed_count"]:
        log(
            tr(
                "Icon-Download-Cache bereinigt: {count} alte Release-ZIP(s), {bytes} Bytes entfernt",
                count=retention["removed_count"],
                bytes=retention["removed_bytes"],
            )
        )
    for warning in retention["warnings"]:
        log(tr("Warnung: {warning}", warning=warning))
    log(tr("Icons: {mapped}/{targets} Inventaritems gemappt", mapped=manifest["mapped_items"], targets=manifest["inventory_item_targets"]))
    log(tr("Blockmodelle gerendert: {count}", count=manifest.get("generated_block_icon_count", 0)))
    log(tr("Explizite Itemmodelle gerendert: {count}", count=manifest.get("generated_model_icon_count", 0)))
    if manifest.get("render_failure_count", 0):
        log(tr("Modell-Fehler: {count}", count=manifest["render_failure_count"]))
    log(tr("Nicht neu hinzufügbar ausgeschlossen: {count}", count=manifest["excluded_non_addable_items"]))
    log(tr("Ziel: {path}", path=ICON_ROOT))
    if manifest["missing_count"]:
        preview = ", ".join(manifest["missing_items"][:12])
        log(tr("Fehlend: {count} ({preview})", count=manifest["missing_count"], preview=preview))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
