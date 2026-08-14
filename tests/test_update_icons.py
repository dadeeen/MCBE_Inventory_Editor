import hashlib
import json
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from mcbe_editor.block_icon_renderer import decode_png, encode_rgba_png
from scripts.update_icons import (
    _decode_tga_to_png,
    _read_json_member,
    _texture_paths_from_entry,
    bed_variant_texture_keys,
    block_face_texture_keys,
    build_data_driven_texture_aliases,
    build_icon_cache,
    candidate_texture_keys,
    parse_texture_data,
    potion_variant_texture_keys,
)


def _opaque_checker_png() -> bytes:
    rgba = bytearray()
    for y in range(16):
        for x in range(16):
            rgba.extend((186 if (x // 4 + y // 4) % 2 else 112, 86, 48, 255))
    return encode_rgba_png(16, 16, bytes(rgba))


def _solid_png(red: int, green: int, blue: int) -> bytes:
    return encode_rgba_png(16, 16, bytes((red, green, blue, 255)) * (16 * 16))


def _shield_model_json() -> str:
    return json.dumps(
        {
            "format_version": "1.16.0",
            "minecraft:geometry": [
                {
                    "description": {
                        "identifier": "geometry.shield",
                        "texture_width": 64,
                        "texture_height": 64,
                    },
                    "bones": [
                        {
                            "name": "shield",
                            "cubes": [
                                {"origin": [0, 25, 0], "size": [2, 6, 6], "uv": [26, 0]},
                                {"origin": [-5, 17, -1], "size": [12, 22, 1], "uv": [0, 0]},
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _shield_atlas_png() -> bytes:
    rgba = bytearray(bytes((255, 255, 255, 255)) * (64 * 64))
    for y in range(23):
        for x in range(26):
            offset = (y * 64 + x) * 4
            rgba[offset : offset + 4] = bytes((132, 91, 47, 255))
    for y in range(12):
        for x in range(26, 42):
            offset = (y * 64 + x) * 4
            rgba[offset : offset + 4] = bytes((92, 98, 104, 255))
    return encode_rgba_png(64, 64, bytes(rgba))


def _copper_golem_model_json() -> str:
    return json.dumps(
        {
            "format_version": "1.12.0",
            "minecraft:geometry": [
                {
                    "description": {
                        "identifier": "geometry.copper_golem",
                        "texture_width": 64,
                        "texture_height": 64,
                    },
                    "bones": [
                        {
                            "name": "body",
                            "cubes": [
                                {
                                    "origin": [-4, 12, -2],
                                    "size": [8, 12, 4],
                                    "uv": [0, 0],
                                    "inflate": -0.01,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _copper_golem_entity_json() -> str:
    return json.dumps(
        {
            "minecraft:client_entity": {
                "description": {
                    "textures": {
                        "default": "textures/entity/copper_golem/copper_golem",
                        "exposed": "textures/entity/copper_golem/copper_golem_exposed",
                        "weathered": "textures/entity/copper_golem/copper_golem_weathered",
                        "oxidized": "textures/entity/copper_golem/copper_golem_oxidized",
                    },
                    "geometry": {
                        "standing": "geometry.copper_golem",
                    },
                }
            }
        }
    )


def _legacy_head_model_json(geometry_identifier: str) -> str:
    return json.dumps(
        {
            geometry_identifier: {
                "texturewidth": 64,
                "textureheight": 32,
                "bones": [
                    {
                        "name": "head",
                        "cubes": [
                            {
                                "origin": [-4, 24, -4],
                                "size": [8, 8, 8],
                                "uv": [0, 0],
                            }
                        ],
                    }
                ],
            }
        }
    )


def _skull_entity_json(variant: str, geometry_identifier: str, texture_path: str) -> str:
    return json.dumps(
        {
            "minecraft:client_entity": {
                "description": {
                    "textures": {variant: f"textures/{texture_path}"},
                    "geometry": {variant: geometry_identifier},
                }
            }
        }
    )


def _head_atlas_png() -> bytes:
    rgba = bytearray(bytes((255, 255, 255, 255)) * (64 * 32))
    for y in range(16):
        for x in range(32):
            offset = (y * 64 + x) * 4
            rgba[offset : offset + 4] = bytes((42 + x, 96 + y * 2, 54, 255))
    return encode_rgba_png(64, 32, bytes(rgba))


@pytest.mark.parametrize(
    ("item_id", "texture_key"),
    [
        ("minecraft:black_dye", "dye_powder_black_new"),
        ("minecraft:blue_dye", "dye_powder_blue_new"),
        ("minecraft:brown_dye", "dye_powder_brown_new"),
        ("minecraft:cocoa_beans", "dye_powder_brown"),
        ("minecraft:empty_map", "map_empty"),
        ("minecraft:enchanted_golden_apple", "apple_golden"),
        ("minecraft:firework_star", "fireworks_charge"),
        ("minecraft:glow_ink_sac", "dye_powder_glow"),
        ("minecraft:ink_sac", "dye_powder_black"),
        ("minecraft:lapis_lazuli", "dye_powder_blue"),
        ("minecraft:lodestone_compass", "lodestonecompass_item"),
        ("minecraft:sugar_cane", "reeds"),
        ("minecraft:tripwire_hook", "trip_wire_source"),
        ("minecraft:tuff_brick_stairs", "tuff_bricks"),
        ("minecraft:tuff_brick_slab", "tuff_bricks"),
        ("minecraft:tuff_brick_wall", "tuff_bricks"),
        ("minecraft:turtle_scute", "turtle_shell_piece"),
        ("minecraft:white_dye", "dye_powder_white_new"),
        ("minecraft:zombie_pigman_spawn_egg", "spawn_egg_zombified_piglin"),
    ],
)
def test_candidate_texture_keys_cover_verified_bedrock_legacy_names(item_id, texture_key):
    assert texture_key in candidate_texture_keys(item_id)


def test_candidate_texture_keys_cover_verified_block_aliases():
    expected = {
        "minecraft:allow": "build_allow",
        "minecraft:deny": "build_deny",
        "minecraft:brown_mushroom_block": "mushroom_block_skin_brown",
        "minecraft:cinnabar_brick_slab": "cinnabar_bricks",
        "minecraft:cinnabar_brick_stairs": "cinnabar_bricks",
        "minecraft:cinnabar_brick_wall": "cinnabar_bricks",
        "minecraft:crimson_fence": "crimson_planks",
        "minecraft:crimson_fence_gate": "crimson_planks",
        "minecraft:crimson_hyphae": "crimson_log_side",
        "minecraft:crimson_pressure_plate": "crimson_planks",
        "minecraft:crimson_slab": "crimson_planks",
        "minecraft:crimson_stairs": "crimson_planks",
        "minecraft:crimson_stem": "crimson_log_side",
        "minecraft:deepslate_brick_slab": "deepslate_bricks",
        "minecraft:deepslate_brick_stairs": "deepslate_bricks",
        "minecraft:deepslate_brick_wall": "deepslate_bricks",
        "minecraft:deepslate_tile_slab": "deepslate_tiles",
        "minecraft:deepslate_tile_stairs": "deepslate_tiles",
        "minecraft:deepslate_tile_wall": "deepslate_tiles",
        "minecraft:end_brick_stairs": "end_bricks",
        "minecraft:end_portal_frame": "endframe_top",
        "minecraft:fence_gate": "planks_oak",
        "minecraft:glow_frame": "glow_item_frame",
        "minecraft:heavy_weighted_pressure_plate": "iron_block",
        "minecraft:honey_block": "honey_side",
        "minecraft:infested_deepslate": "deepslate",
        "minecraft:iron_chain": "chain",
        "minecraft:light_gray_carpet": "wool_colored_silver",
        "minecraft:light_gray_wool": "wool_colored_silver",
        "minecraft:light_weighted_pressure_plate": "gold_block",
        "minecraft:lit_pumpkin": "pumpkin_face_on",
        "minecraft:melon_block": "melon_side",
        "minecraft:moss_carpet": "moss_block",
        "minecraft:mossy_cobblestone": "cobblestone_mossy",
        "minecraft:mossy_cobblestone_stairs": "cobblestone_mossy",
        "minecraft:mud_brick_slab": "mud_bricks",
        "minecraft:mud_brick_stairs": "mud_bricks",
        "minecraft:mud_brick_wall": "mud_bricks",
        "minecraft:normal_stone_stairs": "stone",
        "minecraft:packed_ice": "ice_packed",
        "minecraft:pointed_dripstone": "pointed_dripstone_up_tip",
        "minecraft:polished_blackstone_brick_slab": "polished_blackstone_bricks",
        "minecraft:polished_blackstone_brick_stairs": "polished_blackstone_bricks",
        "minecraft:polished_blackstone_brick_wall": "polished_blackstone_bricks",
        "minecraft:rail": "rail_normal",
        "minecraft:red_mushroom_block": "mushroom_block_skin_red",
        "minecraft:small_dripleaf_block": "small_dripleaf_top",
        "minecraft:snow_layer": "snow",
        "minecraft:sticky_piston": "piston_top_sticky",
        "minecraft:stone_brick_stairs": "stone_bricks",
        "minecraft:stripped_cherry_wood": "stripped_cherry_log_side",
        "minecraft:stripped_crimson_hyphae": "stripped_crimson_stem_side",
        "minecraft:stripped_mangrove_wood": "stripped_mangrove_log_side",
        "minecraft:stripped_pale_oak_wood": "stripped_pale_oak_log_side",
        "minecraft:stripped_warped_hyphae": "stripped_warped_stem_side",
        "minecraft:sulfur_brick_slab": "sulfur_bricks",
        "minecraft:sulfur_brick_stairs": "sulfur_bricks",
        "minecraft:sulfur_brick_wall": "sulfur_bricks",
        "minecraft:sulfur_spike": "sulfur_spike_up_tip",
        "minecraft:warped_fence": "warped_planks",
        "minecraft:warped_fence_gate": "warped_planks",
        "minecraft:warped_hyphae": "warped_stem_side",
        "minecraft:warped_pressure_plate": "warped_planks",
        "minecraft:warped_slab": "warped_planks",
        "minecraft:warped_stairs": "warped_planks",
        "minecraft:waxed_copper": "copper_block",
        "minecraft:waxed_copper_chest": "copper_chest_inventory_front",
        "minecraft:waxed_exposed_copper_chest": "exposed_copper_chest_inventory_front",
        "minecraft:waxed_oxidized_copper_chest": "oxidized_copper_chest_inventory_front",
        "minecraft:waxed_weathered_copper_chest": "weathered_copper_chest_inventory_front",
        "minecraft:wooden_pressure_plate": "planks_oak",
        # Bark variants of the newer woods carry no texture key of their own.
        "minecraft:cherry_wood": "cherry_log_side",
        "minecraft:mangrove_wood": "mangrove_log_side",
        "minecraft:pale_oak_wood": "pale_oak_log_side",
        # Dark oak is spelled ``big_oak`` in the leaf textures.
        "minecraft:dark_oak_leaves": "big_oak_leaves_carried",
        # ``stone_stairs`` is Bedrock's historical cobblestone staircase.
        "minecraft:stone_stairs": "cobblestone",
        "minecraft:bamboo_mosaic_slab": "bamboo_mosaic",
        "minecraft:bamboo_mosaic_stairs": "bamboo_mosaic",
        "minecraft:cut_sandstone_slab": "cut_sandstone",
        "minecraft:cut_red_sandstone_slab": "cut_red_sandstone",
        "minecraft:pale_moss_carpet": "pale_moss_block",
        "minecraft:red_sandstone": "red_sandstone_normal",
        "minecraft:red_sandstone_stairs": "red_sandstone_normal",
    }
    for item_id, texture_key in expected.items():
        assert texture_key in candidate_texture_keys(item_id), item_id


def test_block_face_texture_keys_recover_log_side_from_selected_top_texture():
    side_keys = block_face_texture_keys("acacia_log", "blocks/log_acacia_top", "side")

    assert "log_acacia" in side_keys
    assert "log_acacia_top" not in side_keys


@pytest.mark.parametrize(
    ("item_id", "texture_path", "face", "expected_first"),
    [
        ("dispenser", "blocks/furnace_top", "front", "dispenser_front_horizontal"),
        ("dropper", "blocks/furnace_top", "front", "dropper_front_horizontal"),
        ("piston", "blocks/piston_side", "top", "piston_top_normal"),
        ("sticky_piston", "blocks/piston_top_sticky", "side", "piston_side"),
        # The crafter names its faces after compass directions and has no
        # ``crafter_side`` at all, so the side would fall back to the top grid.
        ("crafter", "blocks/crafter_top", "side", "crafter_east"),
        ("crafter", "blocks/crafter_top", "front", "crafter_north"),
        ("crafter", "blocks/crafter_top", "top", "crafter_top"),
        # Without these the carved face ends up on the lid and the flanks too.
        ("carved_pumpkin", "blocks/pumpkin_face_off", "side", "pumpkin_side"),
        ("carved_pumpkin", "blocks/pumpkin_face_off", "top", "pumpkin_top"),
        ("carved_pumpkin", "blocks/pumpkin_face_off", "front", "pumpkin_face_off"),
        ("lit_pumpkin", "blocks/pumpkin_face_on", "front", "pumpkin_face_on"),
    ],
)
def test_block_face_texture_keys_prioritize_verified_bedrock_names(item_id, texture_path, face, expected_first):
    assert block_face_texture_keys(item_id, texture_path, face)[0] == expected_first


@pytest.mark.parametrize(
    "item_id",
    ["oak_wood", "dark_oak_wood", "stripped_birch_wood", "crimson_hyphae", "stripped_warped_hyphae"],
)
def test_bark_blocks_wear_their_side_texture_on_every_face(item_id):
    side = block_face_texture_keys(item_id, "blocks/log_oak", "side")

    assert block_face_texture_keys(item_id, "blocks/log_oak", "top") == side
    assert block_face_texture_keys(item_id, "blocks/log_oak", "front") == side
    # The cross-section must not sneak back in as a lid; that would make the
    # all-bark block look like the log of the same wood.
    assert not any(key.endswith(("_top", "_end")) for key in side)


def test_log_blocks_keep_their_cross_section_on_top():
    keys = block_face_texture_keys("oak_log", "blocks/log_oak", "top")

    assert "log_oak_top" in keys


def _tiny_tga(red: int = 255, green: int = 0, blue: int = 0, alpha: int = 255) -> bytes:
    return bytes(
        [
            0,
            0,
            2,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
            1,
            0,
            32,
            0,
            blue,
            green,
            red,
            alpha,
        ]
    )


def test_tga_decoder_honors_right_to_left_image_origin():
    # Descriptor 0x30 means top-to-bottom and right-to-left. File order is
    # therefore the blue right pixel followed by the red left pixel.
    header = bytes([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 0, 24, 0x30])
    raw = header + bytes([255, 0, 0, 0, 0, 255])

    texture = decode_png(_decode_tga_to_png(raw))

    assert texture.rgba == bytes([255, 0, 0, 255, 0, 0, 255, 255])


def test_read_json_member_accepts_mojang_json_comments(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '// Mojang reference comment\n{"texture_data": {"apple": {"textures": "textures/items/apple"}}}',
        )

    with zipfile.ZipFile(archive) as zf:
        data = _read_json_member(zf, "textures/item_texture.json")

    assert data["texture_data"]["apple"]["textures"] == "textures/items/apple"


def test_read_json_member_keeps_comment_markers_inside_strings(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    payload = {"texture_data": {"test": {"textures": "textures/items/http://kept"}}}
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", json.dumps(payload))

    with zipfile.ZipFile(archive) as zf:
        data = _read_json_member(zf, "textures/item_texture.json")

    assert data == payload


def test_texture_paths_support_terrain_path_entries():
    assert _texture_paths_from_entry({"path": "textures/blocks/grass_side", "overlay_color": "#79c05a"}) == ["textures/blocks/grass_side"]


def test_build_icon_cache_maps_commented_texture_json_to_png(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '// Mojang reference comment\n{"texture_data": {"apple": {"textures": "textures/items/apple"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/apple.png", b"\x89PNG\r\n\x1a\n")

    manifest = build_icon_cache(
        archive,
        ["apple"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["mapped_items"] == 1
    assert manifest["items"]["minecraft:apple"] == "items/apple"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "apple.png").exists()


def test_build_icon_cache_never_copies_model_atlas_when_geometry_is_missing(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '{"texture_data": {"shield": {"textures": "textures/entity/shield"}, "apple": {"textures": "textures/items/apple"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/entity/shield.png", _shield_atlas_png())
        zf.writestr("resource_pack/textures/items/apple.png", b"\x89PNG\r\n\x1a\n")

    manifest = build_icon_cache(
        archive,
        ["shield", "apple"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["items"]["minecraft:apple"] == "items/apple"
    assert "minecraft:shield" not in manifest["items"]
    assert "minecraft:shield" in manifest["missing_items"]
    assert manifest["render_failure_count"] == 1
    assert "geometry.shield" in manifest["render_failures"]["minecraft:shield"]
    assert not (tmp_path / "icons" / "vanilla" / "textures" / "items" / "shield.png").exists()


def test_build_icon_cache_renders_explicit_model_atlas_with_authoritative_geometry(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '{"texture_data": {"shield": {"textures": "textures/entity/shield"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/entity/shield.png", _shield_atlas_png())
        zf.writestr("resource_pack/models/entity/shield.geo.json", _shield_model_json())

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["shield"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["schema_version"] == 5
    assert manifest["items"]["minecraft:shield"] == "entity/shield"
    assert manifest["generated_model_icon_count"] == 1
    assert manifest["generated_model_icons"]["minecraft:shield"] == {
        "geometry": "models/entity/shield.geo.json",
        "geometry_identifier": "geometry.shield",
        "texture": "entity/shield",
    }
    assert not manifest["missing_items"]
    rendered = (target / "textures" / "items" / "shield.png").read_bytes()
    assert rendered != _shield_atlas_png()
    assert (decode_png(rendered).width, decode_png(rendered).height) == (64, 64)


def test_build_icon_cache_renders_all_copper_golem_statue_oxidation_and_waxed_variants(tmp_path):
    states = {
        "copper_golem_statue": ("default", "copper_block", ""),
        "exposed_copper_golem_statue": ("exposed", "exposed_copper", "_exposed"),
        "weathered_copper_golem_statue": ("weathered", "weathered_copper", "_weathered"),
        "oxidized_copper_golem_statue": ("oxidized", "oxidized_copper", "_oxidized"),
    }
    block_definitions = {}
    known_items = []
    for item_id, (_variant, block_texture, _suffix) in states.items():
        for candidate in (item_id, f"waxed_{item_id}"):
            known_items.append(candidate)
            block_definitions[candidate] = {"textures": block_texture}

    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/blocks.json", json.dumps(block_definitions))
        zf.writestr("resource_pack/entity/copper_golem.entity.json", _copper_golem_entity_json())
        zf.writestr("resource_pack/models/entity/copper_golem.geo.json", _copper_golem_model_json())
        for _item_id, (_variant, _block_texture, suffix) in states.items():
            zf.writestr(
                f"resource_pack/textures/entity/copper_golem/copper_golem{suffix}.png",
                _solid_png(184, 115, 83),
            )

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        known_items,
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["mapped_items"] == 8
    assert manifest["generated_model_icon_count"] == 8
    assert not manifest["missing_items"]
    for item_id, (variant, block_texture, suffix) in states.items():
        texture_path = f"entity/copper_golem/copper_golem{suffix}"
        for candidate in (item_id, f"waxed_{item_id}"):
            namespaced_id = f"minecraft:{candidate}"
            assert manifest["items"][namespaced_id] == texture_path
            assert manifest["generated_model_icons"][namespaced_id] == {
                "block_texture": block_texture,
                "definition": "entity/copper_golem.entity.json",
                "geometry": "models/entity/copper_golem.geo.json",
                "geometry_identifier": "geometry.copper_golem",
                "geometry_variant": "standing",
                "texture": texture_path,
                "variant": variant,
            }
            rendered = target / "textures" / "items" / f"{candidate}.png"
            assert rendered.is_file()
            assert (decode_png(rendered.read_bytes()).width, decode_png(rendered.read_bytes()).height) == (64, 64)


def test_build_icon_cache_rejects_copper_golem_statue_when_official_block_mapping_changes(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/blocks.json",
            '{"copper_golem_statue": {"textures": "unexpected_texture"}}',
        )
        zf.writestr("resource_pack/entity/copper_golem.entity.json", _copper_golem_entity_json())
        zf.writestr("resource_pack/models/entity/copper_golem.geo.json", _copper_golem_model_json())
        zf.writestr(
            "resource_pack/textures/entity/copper_golem/copper_golem.png",
            _solid_png(184, 115, 83),
        )

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["copper_golem_statue"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["missing_items"] == ["minecraft:copper_golem_statue"]
    assert "Block-Definition" in manifest["render_failures"]["minecraft:copper_golem_statue"]
    assert not (target / "textures" / "items" / "copper_golem_statue.png").exists()


@pytest.mark.parametrize(
    ("item_id", "variant", "geometry_identifier", "texture_path"),
    [
        ("creeper_head", "creeper", "geometry.mob_head", "entity/skulls/creeper"),
        ("dragon_head", "dragon", "geometry.dragon_head", "entity/dragon/dragon"),
        ("skeleton_skull", "skeleton", "geometry.mob_head", "entity/skulls/skeleton"),
        ("wither_skeleton_skull", "wither", "geometry.mob_head", "entity/skulls/wither_skeleton"),
        ("zombie_head", "zombie", "geometry.mob_head", "entity/skulls/zombie"),
    ],
)
def test_build_icon_cache_renders_static_heads_from_authoritative_entity_definition(
    tmp_path,
    item_id,
    variant,
    geometry_identifier,
    texture_path,
):
    archive = tmp_path / f"{item_id}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/entity/skull.entity.json",
            _skull_entity_json(variant, geometry_identifier, texture_path),
        )
        zf.writestr("resource_pack/models/mobs.json", _legacy_head_model_json(geometry_identifier))
        zf.writestr(f"resource_pack/textures/{texture_path}.png", _head_atlas_png())

    target = tmp_path / "icons" / item_id
    manifest = build_icon_cache(
        archive,
        [item_id],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    namespaced_id = f"minecraft:{item_id}"
    assert manifest["items"][namespaced_id] == texture_path
    assert manifest["generated_model_icons"][namespaced_id] == {
        "definition": "entity/skull.entity.json",
        "geometry": "models/mobs.json",
        "geometry_identifier": geometry_identifier,
        "texture": texture_path,
        "variant": variant,
    }
    assert not manifest["missing_items"]
    rendered = (target / "textures" / "items" / f"{item_id}.png").read_bytes()
    assert rendered != _head_atlas_png()
    assert (decode_png(rendered).width, decode_png(rendered).height) == (64, 64)


def test_build_icon_cache_rejects_head_when_entity_definition_does_not_match_whitelist(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/entity/skull.entity.json",
            _skull_entity_json("skeleton", "geometry.wrong", "entity/skulls/skeleton"),
        )
        zf.writestr("resource_pack/models/mobs.json", _legacy_head_model_json("geometry.mob_head"))
        zf.writestr("resource_pack/textures/entity/skulls/skeleton.png", _head_atlas_png())

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["skeleton_skull"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert "minecraft:skeleton_skull" not in manifest["items"]
    assert manifest["missing_items"] == ["minecraft:skeleton_skull"]
    assert "Entity-Definition" in manifest["render_failures"]["minecraft:skeleton_skull"]
    assert not (target / "textures" / "items" / "skeleton_skull.png").exists()


def test_build_icon_cache_keeps_unconfigured_entity_atlases_blocked(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '{"texture_data": {"custom_model": {"textures": "textures/entity/custom_model"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/entity/custom_model.png", _solid_png(255, 255, 255))

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["custom_model"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert "minecraft:custom_model" not in manifest["items"]
    assert manifest["missing_items"] == ["minecraft:custom_model"]
    assert manifest["generated_model_icon_count"] == 0
    assert not (target / "textures" / "items" / "custom_model.png").exists()


def test_build_icon_cache_accepts_relative_target_root(monkeypatch, tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '{"texture_data": {"apple": {"textures": "textures/items/apple"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/apple.png", _solid_png(255, 0, 0))
    monkeypatch.chdir(tmp_path)

    manifest = build_icon_cache(
        archive,
        ["apple"],
        Path("icons") / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["items"]["minecraft:apple"] == "items/apple"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "apple.png").is_file()


def test_build_icon_cache_maps_semantic_item_texture_alias(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '{"texture_data": {"redstone_dust": {"textures": "textures/items/redstone_dust"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/redstone_dust.png", b"redstone dust")

    manifest = build_icon_cache(
        archive,
        ["redstone", "redstone_wire"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["items"]["minecraft:redstone"] == "items/redstone_dust"
    assert manifest["items"]["minecraft:redstone_wire"] == "items/redstone_dust"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "redstone.png").read_bytes() == b"redstone dust"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "redstone_wire.png").read_bytes() == b"redstone dust"


def test_build_icon_cache_distinguishes_dye_sources_from_separate_dye_items(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    expected = {
        "lapis_lazuli": "dye_powder_blue",
        "blue_dye": "dye_powder_blue_new",
        "ink_sac": "dye_powder_black",
        "black_dye": "dye_powder_black_new",
        "cocoa_beans": "dye_powder_brown",
        "brown_dye": "dye_powder_brown_new",
        "bone_meal": "dye_powder_white",
        "white_dye": "dye_powder_white_new",
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps({"texture_data": {"dye_powder": {"textures": [f"textures/items/{texture}" for texture in expected.values()]}}}),
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        for texture in expected.values():
            zf.writestr(f"resource_pack/textures/items/{texture}.png", texture.encode())

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(archive, list(expected), target, {"resource_pack_release": "test"})

    for item_id, texture in expected.items():
        assert manifest["items"][f"minecraft:{item_id}"] == f"items/{texture}"
        assert (target / "textures" / "items" / f"{item_id}.png").read_bytes() == texture.encode()


def test_build_icon_cache_prefers_specific_bucket_and_spawn_egg_frames(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "bucket": {
                            "textures": [
                                "textures/items/bucket_empty",
                                "textures/items/bucket_powder_snow",
                            ]
                        },
                        "spawn_egg": {
                            "textures": [
                                "textures/items/egg_chicken",
                                "textures/items/egg_zombie",
                            ]
                        },
                        "spawn_egg_zombie": {"textures": "textures/items/spawn_eggs/spawn_egg_zombie"},
                        "spawn_egg_zombified_piglin": {"textures": "textures/items/spawn_eggs/spawn_egg_zombified_piglin"},
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        for path, content in {
            "items/bucket_empty": b"empty bucket",
            "items/bucket_powder_snow": b"powder snow bucket",
            "items/egg_chicken": b"chicken egg",
            "items/egg_zombie": b"legacy zombie egg",
            "items/spawn_eggs/spawn_egg_zombie": b"current zombie egg",
            "items/spawn_eggs/spawn_egg_zombified_piglin": b"current zombified piglin egg",
        }.items():
            zf.writestr(f"resource_pack/textures/{path}.png", content)

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["powder_snow_bucket", "zombie_spawn_egg", "zombie_pigman_spawn_egg"],
        target,
        {"resource_pack_release": "test"},
    )

    assert manifest["items"]["minecraft:powder_snow_bucket"] == "items/bucket_powder_snow"
    assert manifest["items"]["minecraft:zombie_spawn_egg"] == "items/spawn_eggs/spawn_egg_zombie"
    assert manifest["items"]["minecraft:zombie_pigman_spawn_egg"] == "items/spawn_eggs/spawn_egg_zombified_piglin"
    assert (target / "textures" / "items" / "powder_snow_bucket.png").read_bytes() == b"powder snow bucket"
    assert (target / "textures" / "items" / "zombie_spawn_egg.png").read_bytes() == b"current zombie egg"
    assert (target / "textures" / "items" / "zombie_pigman_spawn_egg.png").read_bytes() == b"current zombified piglin egg"


def test_build_icon_cache_prefers_specific_non_block_item_over_generic_variant_array(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "boat": {
                            "textures": [
                                "textures/items/boat_oak",
                                "textures/items/boat_acacia",
                            ]
                        }
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/boat_oak.png", b"oak boat")
        zf.writestr("resource_pack/textures/items/boat_acacia.png", b"acacia boat")

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["acacia_boat"],
        target,
        {"resource_pack_release": "test"},
    )

    assert manifest["items"]["minecraft:acacia_boat"] == "items/boat_acacia"
    assert (target / "textures" / "items" / "acacia_boat.png").read_bytes() == b"acacia boat"


def test_build_icon_cache_maps_tripwire_hook_to_verified_source_sprite(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    source_sprite = _solid_png(156, 126, 72)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            '{"texture_data": {"trip_wire_source": {"textures": "textures/blocks/trip_wire_source"}}}',
        )
        zf.writestr("resource_pack/textures/blocks/trip_wire_source.png", source_sprite)

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["tripwire_hook"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
        block_item_ids={"tripwire_hook"},
    )

    assert manifest["items"]["minecraft:tripwire_hook"] == "blocks/trip_wire_source"
    assert not manifest["missing_items"]
    assert (target / "textures" / "items" / "tripwire_hook.png").read_bytes() == source_sprite


def test_build_icon_cache_maps_button_materials_explicitly(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "planks_oak": {"textures": "textures/blocks/planks_oak"},
                        "crimson_planks": {"textures": "textures/blocks/crimson_planks"},
                        "warped_planks": {"textures": "textures/blocks/warped_planks"},
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/blocks/planks_oak.png", b"oak")
        zf.writestr("resource_pack/textures/blocks/crimson_planks.png", b"crimson")
        zf.writestr("resource_pack/textures/blocks/warped_planks.png", b"warped")

    manifest = build_icon_cache(
        archive,
        ["wooden_button", "crimson_button", "warped_button"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["items"]["minecraft:wooden_button"] == "blocks/planks_oak"
    assert manifest["items"]["minecraft:crimson_button"] == "blocks/crimson_planks"
    assert manifest["items"]["minecraft:warped_button"] == "blocks/warped_planks"


def test_build_icon_cache_model_renders_common_wood_shapes_but_keeps_native_item_sprites(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    native_boat = _opaque_checker_png()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps({"texture_data": {"boat_acacia": {"textures": "textures/items/boat_acacia"}}}),
        )
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps({"texture_data": {"planks_acacia": {"textures": "textures/blocks/planks_acacia"}}}),
        )
        zf.writestr("resource_pack/textures/items/boat_acacia.png", native_boat)
        zf.writestr("resource_pack/textures/blocks/planks_acacia.png", _opaque_checker_png())

    target = tmp_path / "icons" / "vanilla"
    items = ["acacia_boat", "acacia_button", "acacia_fence", "acacia_fence_gate", "acacia_planks", "acacia_pressure_plate", "acacia_sign", "acacia_slab"]
    manifest = build_icon_cache(
        archive,
        items,
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
        block_item_ids=set(items) - {"acacia_boat"},
    )

    assert manifest["generated_block_icon_count"] == 7
    assert set(manifest["generated_block_icons"]) == {f"minecraft:{item}" for item in items if item != "acacia_boat"}
    generated = [(target / "textures" / "items" / f"{item}.png").read_bytes() for item in items if item != "acacia_boat"]
    assert len({hashlib.sha256(value).hexdigest() for value in generated}) == len(generated)
    assert (target / "textures" / "items" / "acacia_boat.png").read_bytes() == native_boat


def test_build_icon_cache_uses_bedrock_dispenser_front_texture(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "dispenser_top": {"textures": "textures/blocks/furnace_top"},
                        "dispenser_side": {"textures": "textures/blocks/furnace_side"},
                        "dispenser_front_horizontal": {"textures": "textures/blocks/dispenser_front_horizontal"},
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/blocks/furnace_top.png", _solid_png(0, 0, 255))
        zf.writestr("resource_pack/textures/blocks/furnace_side.png", _solid_png(255, 0, 0))
        zf.writestr("resource_pack/textures/blocks/dispenser_front_horizontal.png", _solid_png(0, 255, 0))

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["dispenser"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
        block_item_ids={"dispenser"},
    )

    assert manifest["generated_block_icons"]["minecraft:dispenser"]["shape"] == "cube"
    rgba = decode_png((target / "textures" / "items" / "dispenser.png").read_bytes()).rgba
    colors = {tuple(rgba[offset : offset + 4]) for offset in range(0, len(rgba), 4)}
    assert any(red > green and red > blue and alpha for red, green, blue, alpha in colors)
    assert any(green > red and green > blue and alpha for red, green, blue, alpha in colors)
    assert any(blue > red and blue > green and alpha for red, green, blue, alpha in colors)


def test_build_icon_cache_model_renders_tga_block_textures(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps({"texture_data": {"grass_block": {"textures": "textures/blocks/grass_block"}}}),
        )
        zf.writestr("resource_pack/textures/blocks/grass_block.tga", _tiny_tga(40, 180, 60))

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["grass_block"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
        block_item_ids={"grass_block"},
    )

    assert manifest["generated_block_icons"]["minecraft:grass_block"]["shape"] == "cube"
    assert manifest["render_failure_count"] == 0
    assert (target / "textures" / "items" / "grass_block.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_build_icon_cache_reports_model_render_failures_and_keeps_original(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps({"texture_data": {"planks_acacia": {"textures": "textures/blocks/planks_acacia"}}}),
        )
        zf.writestr("resource_pack/textures/blocks/planks_acacia.png", b"invalid png")

    target = tmp_path / "icons" / "vanilla"
    manifest = build_icon_cache(
        archive,
        ["acacia_slab"],
        target,
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
        block_item_ids={"acacia_slab"},
    )

    assert manifest["render_failure_count"] == 1
    assert "Keine PNG-Datei" in manifest["render_failures"]["minecraft:acacia_slab"]
    assert (target / "textures" / "items" / "acacia_slab.png").read_bytes() == b"invalid png"


def test_build_icon_cache_prefers_carried_inventory_texture(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "turtle_egg": {"textures": "textures/blocks/turtle_egg_not_cracked"},
                        "turtle_egg_carried": {"textures": "textures/items/turtle_egg"},
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/blocks/turtle_egg_not_cracked.png", b"block texture")
        zf.writestr("resource_pack/textures/items/turtle_egg.png", b"inventory texture")

    manifest = build_icon_cache(
        archive,
        ["turtle_egg"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["items"]["minecraft:turtle_egg"] == "items/turtle_egg"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "turtle_egg.png").read_bytes() == b"inventory texture"


def test_build_icon_cache_maps_common_vanilla_aliases(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            """
            {
              "texture_data": {
                "bow_standby": {"textures": "textures/items/bow_standby"},
                "crossbow_standby": {"textures": "textures/items/crossbow_standby"},
                "shield": {"textures": "textures/entity/shield"},
                "egg_agent": {"textures": "textures/items/egg_agent"},
                "axolotl_bucket": {"textures": "textures/items/bucket_empty"},
                "bucket_axolotl": {"textures": "textures/items/bucket_axolotl"},
                "bucket_tropical": {"textures": "textures/items/bucket_tropical"},
                "book_normal": {"textures": "textures/items/book_normal"},
                "book_enchanted": {"textures": "textures/items/book_enchanted"},
                "clock_item": {"textures": "textures/items/clock_item"},
                "cooked_fish": {"textures": "textures/items/fish_cooked"},
                "dye_powder_black": {"textures": "textures/items/dye_powder_black"},
                "dye_powder_silver": {"textures": "textures/items/dye_powder_silver"},
                "map_filled": {"textures": "textures/items/map_filled"},
                "minecart_chest": {"textures": "textures/items/minecart_chest"},
                "potion_bottle_drinkable": {"textures": "textures/items/potion_bottle_drinkable"},
                "seeds_beetroot": {"textures": "textures/items/seeds_beetroot"},
                "wood_sword": {"textures": "textures/items/wood_sword"},
                "gold_axe": {"textures": "textures/items/gold_axe"},
                "carrot_golden": {"textures": "textures/items/carrot_golden"},
                "rail_activator": {"textures": "textures/blocks/rail_activator"},
                "planks_acacia": {"textures": "textures/blocks/planks_acacia"}
              }
            }
            """,
        )
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            """
            {
              "texture_data": {
                "ancient_debris_top": {"textures": "textures/blocks/ancient_debris_top"},
                "black_candle_cake": {"textures": "textures/blocks/cake"},
                "cactus_side": {"textures": "textures/blocks/cactus_side"},
                "cut_copper": {"textures": "textures/blocks/cut_copper"},
                "copper_chest": {"textures": "textures/blocks/copper_chest_inventory_front"}
              }
            }
            """,
        )
        zf.writestr("resource_pack/textures/items/bow_standby.png", b"bow")
        zf.writestr("resource_pack/textures/items/crossbow_standby.png", b"crossbow")
        zf.writestr("resource_pack/textures/entity/shield.png", _shield_atlas_png())
        zf.writestr("resource_pack/models/entity/shield.geo.json", _shield_model_json())
        zf.writestr("resource_pack/textures/items/egg_agent.png", b"egg")
        zf.writestr("resource_pack/textures/items/bucket_empty.png", b"empty bucket")
        zf.writestr("resource_pack/textures/items/bucket_axolotl.png", b"bucket")
        zf.writestr("resource_pack/textures/items/bucket_tropical.png", b"tropical bucket")
        zf.writestr("resource_pack/textures/items/book_normal.png", b"book")
        zf.writestr("resource_pack/textures/items/book_enchanted.png", b"enchanted book")
        zf.writestr("resource_pack/textures/items/clock_item.png", b"clock")
        zf.writestr("resource_pack/textures/items/dye_powder_black.png", b"black dye")
        zf.writestr("resource_pack/textures/items/dye_powder_black_new.png", b"new black dye")
        zf.writestr("resource_pack/textures/items/dye_powder_silver.png", b"light gray dye")
        zf.writestr("resource_pack/textures/items/fish_cooked.png", b"cooked fish")
        zf.writestr("resource_pack/textures/items/map_filled.png", b"map")
        zf.writestr("resource_pack/textures/items/minecart_chest.png", b"minecart chest")
        zf.writestr("resource_pack/textures/items/potion_bottle_drinkable.png", b"potion")
        zf.writestr("resource_pack/textures/items/seeds_beetroot.png", b"seeds")
        zf.writestr("resource_pack/textures/items/wood_sword.png", b"wood sword")
        zf.writestr("resource_pack/textures/items/gold_axe.png", b"gold axe")
        zf.writestr("resource_pack/textures/items/carrot_golden.png", b"golden carrot")
        zf.writestr("resource_pack/textures/blocks/rail_activator.png", b"rail")
        zf.writestr("resource_pack/textures/blocks/planks_acacia.png", b"planks")
        zf.writestr("resource_pack/textures/blocks/ancient_debris_top.png", b"debris")
        zf.writestr("resource_pack/textures/blocks/cake_top.png", b"cake")
        zf.writestr("resource_pack/textures/blocks/cactus_side.tga", _tiny_tga())
        zf.writestr("resource_pack/textures/blocks/cut_copper.png", b"copper")
        zf.writestr("resource_pack/textures/blocks/copper_chest_inventory_front.png", b"copper chest")
        zf.writestr("resource_pack/textures/items/leather_boots.tga", _tiny_tga(80, 40, 20))

    manifest = build_icon_cache(
        archive,
        [
            "bow",
            "crossbow",
            "shield",
            "agent_spawn_egg",
            "axolotl_bucket",
            "buckettropical",
            "tropical_fish_bucket",
            "book",
            "enchanted_book",
            "clock",
            "cooked_cod",
            "black_dye",
            "light_gray_dye",
            "filled_map",
            "chest_minecart",
            "potion",
            "beetroot_seeds",
            "wooden_sword",
            "golden_axe",
            "golden_carrot",
            "activator_rail",
            "acacia_fence",
            "acaciafence",
            "black_candle_cake",
            "waxed_cut_copper",
            "copper_chest",
            "cactus",
            "leather_boots",
            "ancient_debris",
        ],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["mapped_items"] == 29
    assert manifest["items"]["minecraft:bow"] == "items/bow_standby"
    assert manifest["items"]["minecraft:crossbow"] == "items/crossbow_standby"
    assert manifest["items"]["minecraft:shield"] == "entity/shield"
    assert manifest["generated_model_icons"]["minecraft:shield"]["geometry"] == "models/entity/shield.geo.json"
    assert "minecraft:shield" not in manifest["missing_items"]
    assert manifest["items"]["minecraft:agent_spawn_egg"] == "items/egg_agent"
    assert manifest["items"]["minecraft:axolotl_bucket"] == "items/bucket_axolotl"
    assert manifest["items"]["minecraft:buckettropical"] == "items/bucket_tropical"
    assert manifest["items"]["minecraft:tropical_fish_bucket"] == "items/bucket_tropical"
    assert manifest["items"]["minecraft:book"] == "items/book_normal"
    assert manifest["items"]["minecraft:enchanted_book"] == "items/book_enchanted"
    assert manifest["items"]["minecraft:clock"] == "items/clock_item"
    assert manifest["items"]["minecraft:cooked_cod"] == "items/fish_cooked"
    assert manifest["items"]["minecraft:black_dye"] == "items/dye_powder_black_new"
    assert manifest["items"]["minecraft:light_gray_dye"] == "items/dye_powder_silver"
    assert manifest["items"]["minecraft:filled_map"] == "items/map_filled"
    assert manifest["items"]["minecraft:chest_minecart"] == "items/minecart_chest"
    assert manifest["items"]["minecraft:potion"] == "items/potion_bottle_drinkable"
    assert manifest["items"]["minecraft:beetroot_seeds"] == "items/seeds_beetroot"
    assert manifest["items"]["minecraft:wooden_sword"] == "items/wood_sword"
    assert manifest["items"]["minecraft:golden_axe"] == "items/gold_axe"
    assert manifest["items"]["minecraft:golden_carrot"] == "items/carrot_golden"
    assert manifest["items"]["minecraft:activator_rail"] == "blocks/rail_activator"
    assert manifest["items"]["minecraft:acacia_fence"] == "blocks/planks_acacia"
    assert manifest["items"]["minecraft:acaciafence"] == "blocks/planks_acacia"
    assert manifest["items"]["minecraft:black_candle_cake"] == "blocks/cake_top"
    assert manifest["items"]["minecraft:waxed_cut_copper"] == "blocks/cut_copper"
    assert manifest["items"]["minecraft:copper_chest"] == "blocks/copper_chest_inventory_front"
    assert manifest["items"]["minecraft:cactus"] == "blocks/cactus_side"
    assert manifest["items"]["minecraft:leather_boots"] == "items/leather_boots"
    assert manifest["items"]["minecraft:ancient_debris"] == "blocks/ancient_debris_top"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "cactus.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "leather_boots.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_build_icon_cache_prefers_axolotl_bucket_sprite_over_generic_bucket_texture(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "bucket": {
                            "textures": [
                                "textures/items/bucket_empty",
                                "textures/items/bucket_axolotl",
                            ]
                        }
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/bucket_empty.png", b"empty bucket")
        zf.writestr("resource_pack/textures/items/bucket_axolotl.png", b"axolotl bucket")

    manifest = build_icon_cache(
        archive,
        ["axolotl_bucket"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["items"]["minecraft:axolotl_bucket"] == "items/bucket_axolotl"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "axolotl_bucket.png").read_bytes() == b"axolotl bucket"


def test_build_icon_cache_extracts_axolotl_entity_variant_preview_icons(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/entity/axolotl/axolotl_gold.png", b"gold axolotl")
        zf.writestr("resource_pack/textures/entity/axolotl/axolotl_gold_baby.png", b"baby gold axolotl")

    manifest = build_icon_cache(
        archive,
        [],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["display_assets"]["mcbe:axolotl_gold"] == "entity/axolotl/axolotl_gold"
    assert manifest["display_assets"]["mcbe:axolotl_gold_baby"] == "entity/axolotl/axolotl_gold_baby"
    assert "minecraft:entity_axolotl_gold" not in manifest["items"]
    assert (tmp_path / "icons" / "vanilla" / "textures" / "display" / "axolotl_gold.png").read_bytes() == b"gold axolotl"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "display" / "axolotl_gold_baby.png").read_bytes() == b"baby gold axolotl"


def test_build_icon_cache_extracts_bedrock_potion_variant_icons(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "potion_bottle_drinkable": {"textures": "textures/items/potion_bottle_drinkable"},
                        "potion_bottle_splash": {"textures": "textures/items/potion_bottle_splash"},
                        "potion_bottle_lingering": {"textures": "textures/items/potion_bottle_lingering"},
                        "tipped_arrow": {"textures": "textures/items/tipped_arrow"},
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/potion_bottle_drinkable.png", b"base potion")
        zf.writestr("resource_pack/textures/items/potion_bottle_empty.png", b"water bottle")
        zf.writestr("resource_pack/textures/items/potion_bottle_fireResistance.png", b"fire resistance")
        zf.writestr("resource_pack/textures/items/potion_bottle_splash.png", b"base splash potion")
        zf.writestr("resource_pack/textures/items/potion_bottle_splash_poison.png", b"splash poison")
        zf.writestr("resource_pack/textures/items/potion_bottle_lingering_empty.png", b"lingering water")
        zf.writestr("resource_pack/textures/items/potion_bottle_lingering_nightVision.png", b"lingering night vision")
        zf.writestr("resource_pack/textures/items/tipped_arrow.png", b"tipped arrow")
        zf.writestr("resource_pack/textures/items/tipped_arrow_swift.png", b"swift arrow")

    manifest = build_icon_cache(
        archive,
        ["potion", "splash_potion", "lingering_potion", "tipped_arrow"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert potion_variant_texture_keys("potion")[0] == "potion_bottle_empty"
    assert manifest["items"]["minecraft:potion#0"] == "items/potion_bottle_empty"
    for damage in range(5):
        assert potion_variant_texture_keys("splash_potion")[damage] == "potion_bottle_splash"
        assert manifest["items"][f"minecraft:splash_potion#{damage}"] == "items/potion_bottle_splash"
        assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / f"splash_potion#{damage}.png").read_bytes() == b"base splash potion"
    assert potion_variant_texture_keys("potion")[12] == "potion_bottle_fireResistance"
    assert manifest["items"]["minecraft:potion#12"] == "items/potion_bottle_fireResistance"
    assert manifest["items"]["minecraft:lingering_potion#0"] == "items/potion_bottle_lingering_empty"
    assert manifest["items"]["minecraft:splash_potion#25"] == "items/potion_bottle_splash_poison"
    assert manifest["items"]["minecraft:lingering_potion#5"] == "items/potion_bottle_lingering_nightVision"
    assert manifest["items"]["minecraft:tipped_arrow#14"] == "items/tipped_arrow_swift"
    assert manifest["mapped_items"] == 3
    assert manifest["mapped_icons"] == 20
    assert manifest["potion_variant_icons"] == 17
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "potion#0.png").read_bytes() == b"water bottle"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "potion#12.png").read_bytes() == b"fire resistance"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "splash_potion#25.png").read_bytes() == b"splash poison"


def test_build_icon_cache_extracts_all_bed_data_value_icons(tmp_path):
    colors = [
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
    ]
    texture_paths = [f"textures/items/bed_{color}" for color in colors]
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps({"texture_data": {"bed": {"textures": texture_paths}}}),
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        for color, texture_path in zip(colors, texture_paths, strict=True):
            zf.writestr(f"resource_pack/{texture_path}.png", color.encode("ascii"))

    manifest = build_icon_cache(
        archive,
        ["bed"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    parsed = parse_texture_data({"texture_data": {"bed": {"textures": texture_paths}}})
    assert bed_variant_texture_keys("bed", parsed)[0] == "items/bed_white"
    assert bed_variant_texture_keys("minecraft:bed", parsed)[15] == "items/bed_black"
    assert manifest["bed_variant_icons"] == 16
    for damage, color in enumerate(colors):
        assert manifest["items"][f"minecraft:bed#{damage}"] == f"items/bed_{color}"
        assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / f"bed#{damage}.png").read_bytes() == color.encode("ascii")


def test_bed_variant_texture_mapping_fails_closed_when_mojang_order_changes():
    expected = [
        f"items/bed_{color}"
        for color in (
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
    ]
    reordered = list(expected)
    reordered[0], reordered[15] = reordered[15], reordered[0]

    assert bed_variant_texture_keys("bed", {"bed": expected}) == dict(enumerate(expected))
    assert bed_variant_texture_keys("bed", {"bed": reordered}) == {}
    assert bed_variant_texture_keys("bed", {"bed": expected[:-1]}) == {}


def test_build_icon_cache_maps_bedrock_flower_variant_textures(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps({"texture_data": {"red_flower": {"textures": ["textures/blocks/flower_rose", "textures/blocks/flower_cornflower"]}}}),
        )
        zf.writestr("resource_pack/textures/blocks/flower_cornflower.png", b"cornflower")

    manifest = build_icon_cache(
        archive,
        ["cornflower"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["mapped_items"] == 1
    assert manifest["items"]["minecraft:cornflower"] == "blocks/flower_cornflower"
    assert (tmp_path / "icons" / "vanilla" / "textures" / "items" / "cornflower.png").exists()


def test_builds_data_driven_aliases_from_texture_path_variants():
    texture_data = parse_texture_data(
        {
            "texture_data": {
                "red_flower": {
                    "textures": [
                        "textures/blocks/flower_tulip_red",
                        "textures/blocks/flower_lily_of_the_valley",
                    ]
                },
                "double_plant": {"textures": "textures/blocks/double_plant_sunflower_front"},
            }
        }
    )

    aliases = build_data_driven_texture_aliases(texture_data, ["red_tulip", "lily_of_the_valley", "sunflower"])

    assert aliases["red_tulip"] == ["flower_tulip_red"]
    assert aliases["lily_of_the_valley"] == ["flower_lily_of_the_valley"]
    assert aliases["sunflower"] == ["double_plant_sunflower_front"]


def test_data_driven_aliases_rank_the_underside_behind_every_other_face():
    texture_data = parse_texture_data(
        {
            "texture_data": {
                "enchanting_table_bottom": {"textures": "textures/blocks/enchanting_table_bottom"},
                "enchanting_table_side": {"textures": "textures/blocks/enchanting_table_side"},
                "enchanting_table_top": {"textures": "textures/blocks/enchanting_table_top"},
                "smooth_quartz_bottom": {"textures": "textures/blocks/smooth_quartz_bottom"},
            }
        }
    )

    aliases = build_data_driven_texture_aliases(texture_data, ["enchanting_table", "smooth_quartz"])

    # The enchanting table's underside is plain obsidian and must not win the
    # flat icon merely because terrain_texture.json lists it first.
    assert aliases["enchanting_table"] == ["enchanting_table_side", "enchanting_table_top", "enchanting_table_bottom"]
    # When the underside is the only face, it stays the source.
    assert aliases["smooth_quartz"] == ["smooth_quartz_bottom"]


def test_build_icon_cache_uses_data_driven_texture_aliases(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps(
                {
                    "texture_data": {
                        "red_flower": {"textures": ["textures/blocks/flower_tulip_red"]},
                        "double_plant": {"textures": "textures/blocks/double_plant_sunflower_front"},
                    }
                }
            ),
        )
        zf.writestr("resource_pack/textures/blocks/flower_tulip_red.png", b"red tulip")
        zf.writestr("resource_pack/textures/blocks/double_plant_sunflower_front.png", b"sunflower")

    manifest = build_icon_cache(
        archive,
        ["red_tulip", "sunflower"],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["mapped_items"] == 2
    assert manifest["items"]["minecraft:red_tulip"] == "blocks/flower_tulip_red"
    assert manifest["items"]["minecraft:sunflower"] == "blocks/double_plant_sunflower_front"
    assert manifest["data_driven_texture_aliases"] >= 2


def test_build_icon_cache_generates_extra_legacy_item_targets(tmp_path):
    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/item_texture.json", '{"texture_data": {}}')
        zf.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps({"texture_data": {"sunflower_carried": {"textures": "textures/blocks/double_plant_sunflower_front"}}}),
        )
        zf.writestr("resource_pack/textures/blocks/double_plant_sunflower_front.png", b"sunflower")

    manifest = build_icon_cache(
        archive,
        [],
        tmp_path / "icons" / "vanilla",
        {"resource_pack_release": "test", "resource_pack_asset": "test.zip"},
    )

    assert manifest["known_items"] == 0
    assert manifest["extra_item_icon_targets"] >= 1
    assert manifest["items"]["minecraft:sunflower"] == "blocks/double_plant_sunflower_front"
    assert not manifest["missing_items"]


def _write_complete_icon_cache(path, marker):
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(
        json.dumps({"items": {"minecraft:apple": "items/apple"}}),
        encoding="utf-8",
    )
    icon_path = path / "textures" / "items" / "apple.png"
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    icon_path.write_bytes(marker.encode("utf-8"))
    (path / "marker.txt").write_text(marker, encoding="utf-8")


def test_publish_icon_cache_restores_previous_cache_when_publish_fails(monkeypatch, tmp_path):
    from mcbe_editor import icon_cache as icon_cache_module

    target = tmp_path / "vanilla"
    staging = tmp_path / ".vanilla.staging-test"
    _write_complete_icon_cache(target, "old")
    _write_complete_icon_cache(staging, "new")
    real_replace = icon_cache_module.os.replace

    def fail_new_publish(source, destination):
        if Path(source) == staging and Path(destination) == target:
            raise OSError("publish failed")
        return real_replace(source, destination)

    monkeypatch.setattr(icon_cache_module.os, "replace", fail_new_publish)

    with pytest.raises(OSError, match="publish failed"):
        icon_cache_module.publish_icon_cache(staging, target)

    assert (target / "marker.txt").read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".vanilla.rollback-*"))


def test_recover_icon_cache_restores_complete_rollback_over_partial_target(tmp_path):
    from mcbe_editor.icon_cache import recover_icon_cache

    target = tmp_path / "vanilla"
    target.mkdir()
    (target / "partial.txt").write_text("partial", encoding="utf-8")
    rollback = tmp_path / ".vanilla.rollback-test"
    _write_complete_icon_cache(rollback, "old")

    recover_icon_cache(target)

    assert (target / "marker.txt").read_text(encoding="utf-8") == "old"
    assert not rollback.exists()


def test_parallel_icon_cache_builds_use_independent_staging_directories(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '{"texture_data": {"apple": {"textures": "textures/items/apple"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/apple.png", b"apple")
    target = tmp_path / "icons" / "vanilla"

    def build(index):
        return build_icon_cache(
            archive,
            ["apple"],
            target,
            {"resource_pack_release": f"test-{index}", "resource_pack_asset": "test.zip"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        manifests = list(executor.map(build, range(2)))

    assert len(manifests) == 2
    final_manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert final_manifest["items"]["minecraft:apple"] == "items/apple"
    assert not list(target.parent.glob(".vanilla.staging-*"))


def test_failed_icon_cache_build_removes_unique_staging_directory(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    archive = tmp_path / "bedrock-samples.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "resource_pack/textures/item_texture.json",
            '{"texture_data": {"apple": {"textures": "textures/items/apple"}}}',
        )
        zf.writestr("resource_pack/textures/terrain_texture.json", '{"texture_data": {}}')
        zf.writestr("resource_pack/textures/items/apple.png", b"apple")
    target = tmp_path / "icons" / "vanilla"
    monkeypatch.setattr(
        update_icons_module,
        "_write_texture_as_png",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        update_icons_module.build_icon_cache(archive, ["apple"], target, {})

    assert not list(target.parent.glob(".vanilla.staging-*"))
    assert not target.exists()


class _IconDownloadResponse:
    def __init__(self, payload):
        import io

        self._payload = io.BytesIO(payload)
        self.url = "https://release-assets.githubusercontent.com/example.zip"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self._payload.read(size)


class _IconDownloadOpener:
    def __init__(self, payload):
        self.payload = payload
        self.addheaders = []

    def open(self, _url, timeout=None):
        return _IconDownloadResponse(self.payload)


def _icon_zip_bytes(filename="file.txt", content=b"ok"):
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, content)
    return buffer.getvalue()


def test_icon_updater_rejects_malformed_allowlisted_url():
    import scripts.update_icons as update_icons_module

    with pytest.raises(RuntimeError, match="Unsichere Resource-Pack-URL"):
        update_icons_module._validate_https_url(
            "https://[github.com/asset.zip",
            update_icons_module.ALLOWED_RESOURCE_PACK_HOSTS,
            label="Resource-Pack",
        )


def test_icon_updater_rejects_untrusted_redirect_before_following_it():
    import scripts.update_icons as update_icons_module

    handler = update_icons_module._AllowlistedRedirectHandler(
        update_icons_module.ALLOWED_RESOURCE_PACK_HOSTS,
        label="Resource-Pack",
    )
    request = update_icons_module.urllib.request.Request("https://github.com/Mojang/bedrock-samples/releases/download/v1/asset.zip")

    with pytest.raises(RuntimeError, match="Unsichere Resource-Pack-URL"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1:8080/internal",
        )


def test_icon_download_rejects_path_traversal_asset_name(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    monkeypatch.setattr(update_icons_module, "CACHE_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="Assetname"):
        update_icons_module.download_release_zip(
            {
                "resource_pack_asset": "../outside.zip",
                "resource_pack_asset_size": 10,
                "resource_pack_url": "https://release-assets.githubusercontent.com/example.zip",
            },
            use_cache=False,
        )


def test_icon_zip_validation_limits_member_size(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    archive_path = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.bin", b"1234")

    monkeypatch.setattr(update_icons_module, "MAX_RESOURCE_PACK_MEMBER_BYTES", 3)

    with pytest.raises(RuntimeError, match="unerwartet großen ZIP-Eintrag"):
        update_icons_module._validate_downloaded_zip(archive_path)


def test_icon_download_failure_preserves_existing_cache(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    old_payload = _icon_zip_bytes("old.txt", b"old")
    new_payload = _icon_zip_bytes("new.txt", b"new")
    destination = tmp_path / "bedrock-samples.zip"
    destination.write_bytes(old_payload)
    monkeypatch.setattr(update_icons_module, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        update_icons_module.urllib.request,
        "build_opener",
        lambda *_handlers: _IconDownloadOpener(new_payload),
    )

    with pytest.raises(RuntimeError, match="unvollständig"):
        update_icons_module.download_release_zip(
            {
                "resource_pack_asset": destination.name,
                "resource_pack_asset_size": len(new_payload) + 1,
                "resource_pack_url": "https://release-assets.githubusercontent.com/example.zip",
            },
            use_cache=False,
        )

    assert destination.read_bytes() == old_payload
    assert not list(tmp_path.glob(".bedrock-samples.zip.*.part"))


def test_icon_release_cache_retention_keeps_only_current_managed_full_release(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    current = tmp_path / "bedrock-samples-1.21.100.1.zip"
    old = tmp_path / "bedrock-samples-1.21.90.1.zip"
    generic_item_db_cache = tmp_path / "bedrock_resource_pack.zip"
    min_release = tmp_path / "bedrock-samples-1.21.100.1-min.zip"
    unrelated = tmp_path / "operator-backup.zip"
    current.write_bytes(b"current")
    old.write_bytes(b"old-release")
    generic_item_db_cache.write_bytes(b"item-db")
    min_release.write_bytes(b"min")
    unrelated.write_bytes(b"operator")
    monkeypatch.setattr(update_icons_module, "CACHE_DIR", tmp_path)

    result = update_icons_module.prune_cached_icon_release_zips(current)

    assert result == {"removed_count": 1, "removed_bytes": len(b"old-release"), "warnings": []}
    assert current.exists()
    assert not old.exists()
    assert generic_item_db_cache.exists()
    assert min_release.exists()
    assert unrelated.exists()


def test_icon_release_cache_retention_does_not_fail_update_when_cleanup_is_blocked(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    current = tmp_path / "bedrock-samples-1.21.100.1.zip"
    old = tmp_path / "bedrock-samples-1.21.90.1.zip"
    current.write_bytes(b"current")
    old.write_bytes(b"old")
    monkeypatch.setattr(update_icons_module, "CACHE_DIR", tmp_path)
    real_unlink = Path.unlink

    def blocked_unlink(path, *args, **kwargs):
        if path == old:
            raise PermissionError("locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked_unlink)

    result = update_icons_module.prune_cached_icon_release_zips(current)

    assert result["removed_count"] == 0
    assert result["removed_bytes"] == 0
    assert len(result["warnings"]) == 1
    assert "locked" in result["warnings"][0]
    assert current.exists()
    assert old.exists()


def test_icon_release_cache_retention_skips_unverified_current_path(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    old = cache_dir / "bedrock-samples-1.21.90.1.zip"
    old.write_bytes(b"old")
    outside_current = tmp_path / "bedrock-samples-1.21.100.1.zip"
    outside_current.write_bytes(b"current")
    monkeypatch.setattr(update_icons_module, "CACHE_DIR", cache_dir)

    result = update_icons_module.prune_cached_icon_release_zips(outside_current)

    assert result == {"removed_count": 0, "removed_bytes": 0, "warnings": []}
    assert old.exists()


def test_icon_release_metadata_rejects_incomplete_object(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    metadata = tmp_path / "icon_release_metadata.json"
    metadata.write_text('{"resource_pack_release":"only-tag"}', encoding="utf-8")
    monkeypatch.setattr(update_icons_module, "RELEASE_METADATA_PATH", metadata)

    assert update_icons_module.read_release_metadata() == {}


def test_icon_main_commits_source_metadata_before_cache_publication(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    info = {
        "resource_pack_release": "test",
        "resource_pack_asset": "bedrock-samples.zip",
        "resource_pack_asset_size": 100,
        "resource_pack_url": "https://release-assets.githubusercontent.com/example.zip",
    }
    order = []
    monkeypatch.setattr(update_icons_module, "read_release_metadata", lambda: {})
    monkeypatch.setattr(update_icons_module, "get_latest_full_release_info", lambda: info)
    download = mock.Mock(return_value=tmp_path / "download.zip")
    monkeypatch.setattr(update_icons_module, "download_release_zip", download)
    monkeypatch.setattr(update_icons_module, "load_item_icon_targets", lambda: ([], [], 0))
    monkeypatch.setattr(
        update_icons_module,
        "build_icon_cache",
        lambda *_args, **_kwargs: (
            order.append("build") or {"mapped_items": 0, "inventory_item_targets": 0, "excluded_non_addable_items": 0, "missing_count": 0}
        ),
    )
    monkeypatch.setattr(update_icons_module, "write_release_metadata", lambda _value: order.append("metadata"))
    monkeypatch.setattr(
        update_icons_module,
        "prune_cached_icon_release_zips",
        lambda _path: order.append("prune") or {"removed_count": 0, "removed_bytes": 0, "warnings": []},
    )

    assert update_icons_module.main([]) == 0
    assert order == ["metadata", "build", "prune"]
    download.assert_called_once_with(info, use_cache=False)


def test_icon_normal_mode_checks_latest_even_with_cached_metadata(monkeypatch):
    import scripts.update_icons as update_icons_module

    cached = {
        "resource_pack_release": "old",
        "resource_pack_asset": "bedrock-samples-old.zip",
        "resource_pack_asset_size": 100,
        "resource_pack_url": "https://release-assets.githubusercontent.com/old.zip",
    }
    latest = {**cached, "resource_pack_release": "new", "resource_pack_asset": "bedrock-samples-new.zip"}
    latest_lookup = mock.Mock(return_value=latest)
    monkeypatch.setattr(update_icons_module, "read_release_metadata", lambda: cached)
    monkeypatch.setattr(update_icons_module, "get_latest_full_release_info", latest_lookup)

    assert update_icons_module.main(["--dry-run"]) == 0
    latest_lookup.assert_called_once_with()


def test_icon_normal_mode_reuses_download_only_for_matching_release(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    info = {
        "resource_pack_release": "current",
        "resource_pack_asset": "bedrock-samples-current.zip",
        "resource_pack_asset_size": 100,
        "resource_pack_url": "https://release-assets.githubusercontent.com/current.zip",
    }
    download = mock.Mock(return_value=tmp_path / "download.zip")
    monkeypatch.setattr(update_icons_module, "read_release_metadata", lambda: info)
    monkeypatch.setattr(update_icons_module, "get_latest_full_release_info", lambda: info)
    monkeypatch.setattr(update_icons_module, "download_release_zip", download)
    monkeypatch.setattr(update_icons_module, "load_item_icon_targets", lambda: ([], [], 0))
    monkeypatch.setattr(update_icons_module, "load_block_item_targets", lambda: set())
    monkeypatch.setattr(
        update_icons_module,
        "build_icon_cache",
        lambda *_args, **_kwargs: {
            "mapped_items": 0,
            "inventory_item_targets": 0,
            "excluded_non_addable_items": 0,
            "missing_count": 0,
        },
    )
    monkeypatch.setattr(
        update_icons_module,
        "prune_cached_icon_release_zips",
        lambda _path: {"removed_count": 0, "removed_bytes": 0, "warnings": []},
    )

    assert update_icons_module.main([]) == 0
    download.assert_called_once_with(info, use_cache=True)


def test_icon_internal_cache_mode_skips_online_release_lookup(monkeypatch):
    import scripts.update_icons as update_icons_module

    cached = {
        "resource_pack_release": "cached",
        "resource_pack_asset": "bedrock-samples-cached.zip",
        "resource_pack_asset_size": 100,
        "resource_pack_url": "https://release-assets.githubusercontent.com/cached.zip",
    }
    latest_lookup = mock.Mock()
    monkeypatch.setattr(update_icons_module, "read_release_metadata", lambda: cached)
    monkeypatch.setattr(update_icons_module, "get_latest_full_release_info", latest_lookup)

    assert update_icons_module.main(["--cache", "--dry-run"]) == 0
    latest_lookup.assert_not_called()


def test_icon_metadata_failure_does_not_publish_new_cache(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    info = {
        "resource_pack_release": "test",
        "resource_pack_asset": "bedrock-samples.zip",
        "resource_pack_asset_size": 100,
        "resource_pack_url": "https://release-assets.githubusercontent.com/example.zip",
    }
    build = mock.Mock()
    monkeypatch.setattr(update_icons_module, "get_latest_full_release_info", lambda: info)
    monkeypatch.setattr(update_icons_module, "download_release_zip", lambda *_args, **_kwargs: tmp_path / "download.zip")
    monkeypatch.setattr(update_icons_module, "load_item_icon_targets", lambda: ([], [], 0))
    monkeypatch.setattr(update_icons_module, "build_icon_cache", build)
    monkeypatch.setattr(
        update_icons_module,
        "write_release_metadata",
        lambda _value: (_ for _ in ()).throw(OSError("metadata locked")),
    )

    with pytest.raises(OSError, match="metadata locked"):
        update_icons_module.main([])

    build.assert_not_called()


def test_icon_release_metadata_rejects_non_string_asset_name(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    metadata = tmp_path / "icon_release_metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "resource_pack_release": "v1",
                "resource_pack_asset": {"name": "pack.zip"},
                "resource_pack_asset_size": 10,
                "resource_pack_url": "https://release-assets.githubusercontent.com/example.zip",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_icons_module, "RELEASE_METADATA_PATH", metadata)

    assert update_icons_module.read_release_metadata() == {}


def test_get_latest_full_release_info_rejects_invalid_assets_shape(monkeypatch):
    import scripts.update_icons as update_icons_module

    monkeypatch.setattr(
        update_icons_module,
        "fetch_github_json",
        lambda _url: {"tag_name": "v1", "assets": "not-a-list"},
    )

    with pytest.raises(RuntimeError, match="Asset-Liste"):
        update_icons_module.get_latest_full_release_info()


def test_icon_cache_completeness_rejects_non_string_item_mapping(tmp_path):
    from mcbe_editor.icon_cache import _cache_is_complete

    cache = tmp_path / "vanilla"
    cache.mkdir()
    (cache / "manifest.json").write_text(
        json.dumps({"items": {"minecraft:apple": ["items/apple"]}}),
        encoding="utf-8",
    )

    assert _cache_is_complete(cache) is False


def test_icon_download_crc_failure_preserves_existing_cache(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    old_payload = _icon_zip_bytes("old.txt", b"old")
    new_payload = _icon_zip_bytes("new.txt", b"new")
    destination = tmp_path / "bedrock-samples.zip"
    destination.write_bytes(old_payload)
    monkeypatch.setattr(update_icons_module, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        update_icons_module.urllib.request,
        "build_opener",
        lambda *_handlers: _IconDownloadOpener(new_payload),
    )
    monkeypatch.setattr(
        update_icons_module,
        "_validate_downloaded_zip",
        lambda _path: (_ for _ in ()).throw(RuntimeError("CRC failure")),
    )

    with pytest.raises(RuntimeError, match="CRC failure"):
        update_icons_module.download_release_zip(
            {
                "resource_pack_asset": destination.name,
                "resource_pack_asset_size": len(new_payload),
                "resource_pack_url": "https://release-assets.githubusercontent.com/example.zip",
            },
            use_cache=False,
        )

    assert destination.read_bytes() == old_payload
    assert not list(tmp_path.glob(".bedrock-samples.zip.*.part"))


def test_incomplete_icon_cache_with_manifest_but_missing_assets_is_rejected(tmp_path):
    from mcbe_editor.icon_cache import _cache_is_complete

    cache = tmp_path / "vanilla"
    cache.mkdir()
    (cache / "manifest.json").write_text(
        json.dumps({"items": {"minecraft:apple": "items/apple"}}),
        encoding="utf-8",
    )

    assert _cache_is_complete(cache) is False


def test_icon_cache_manifest_cannot_escape_asset_directory(tmp_path):
    from mcbe_editor.icon_cache import _cache_is_complete

    cache = tmp_path / "vanilla"
    cache.mkdir()
    (cache / "manifest.json").write_text(
        json.dumps({"items": {"minecraft:../outside": "items/apple"}}),
        encoding="utf-8",
    )
    outside = cache / "textures" / "outside.png"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"outside")

    assert _cache_is_complete(cache) is False


def test_icon_persistent_metadata_tolerates_invalid_utf8(monkeypatch, tmp_path):
    import scripts.update_icons as update_icons_module

    metadata = tmp_path / "icon_release_metadata.json"
    metadata.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(update_icons_module, "RELEASE_METADATA_PATH", metadata)

    assert update_icons_module.read_release_metadata() == {}


def test_icon_item_database_reports_invalid_utf8(tmp_path):
    import scripts.update_icons as update_icons_module

    item_db = tmp_path / "item_db.json"
    item_db.write_bytes(b"\xff\xfe")

    with pytest.raises(RuntimeError, match="Item-DB JSON ist ungültig"):
        update_icons_module.load_item_icon_targets(item_db)


def test_icon_targets_follow_positive_addable_registry(tmp_path):
    import scripts.update_icons as update_icons_module

    item_db = tmp_path / "item_db.json"
    item_db.write_text(
        json.dumps(
            {
                "items": {
                    "minecraft:apple": ["Apfel", "Apple"],
                    "minecraft:element_32": ["Element 32", "Element 32"],
                    "minecraft:oak_double_slab": ["Eichen-Doppelstufe", "Oak Double Slab"],
                },
                "block_only_items": ["minecraft:element_32", "minecraft:oak_double_slab"],
                "addable_items": ["minecraft:apple", "minecraft:allow"],
            }
        ),
        encoding="utf-8",
    )

    targets, excluded, catalog_count = update_icons_module.load_item_icon_targets(item_db)

    assert targets == ["allow", "apple"]
    assert excluded == ["element_32", "oak_double_slab"]
    assert catalog_count == 3


def test_block_icon_targets_follow_positive_block_registry(tmp_path):
    import scripts.update_icons as update_icons_module

    item_db = tmp_path / "item_db.json"
    item_db.write_text(
        json.dumps({"block_items": ["minecraft:stone", "minecraft:acacia_slab", "invalid:custom-block"]}),
        encoding="utf-8",
    )

    assert update_icons_module.load_block_item_targets(item_db) == {"stone", "acacia_slab", "invalid:custom_block"}
