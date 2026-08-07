import binascii
import hashlib
import struct
import zlib

import pytest

from mcbe_editor.block_icon_renderer import ICON_SIZE, crop_png, decode_png, encode_rgba_png, render_bedrock_model_icon, render_block_icon


def _checker_texture(*, transparent: bool = False) -> bytes:
    rgba = bytearray()
    for y in range(16):
        for x in range(16):
            alpha = 0 if transparent and (x + y) % 2 else 255
            rgba.extend((196 if (x // 4 + y // 4) % 2 else 112, 92, 44, alpha))
    return encode_rgba_png(16, 16, bytes(rgba))


def _solid_texture(red: int, green: int, blue: int) -> bytes:
    return encode_rgba_png(16, 16, bytes((red, green, blue, 255)) * (16 * 16))


def _shield_model(*, plate_uv: list[int] | None = None) -> dict:
    return {
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
                            {"origin": [-5, 17, -1], "size": [12, 22, 1], "uv": plate_uv or [0, 0]},
                        ],
                    }
                ],
            }
        ]
    }


def _shield_atlas() -> bytes:
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


def _legacy_head_model(*, mirror: bool = False) -> dict:
    return {
        "geometry.mob_head": {
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
                            "mirror": mirror,
                        }
                    ],
                }
            ],
        }
    }


def _legacy_head_atlas() -> bytes:
    rgba = bytearray(bytes((255, 255, 255, 255)) * (64 * 32))
    for y in range(16):
        for x in range(32):
            offset = (y * 64 + x) * 4
            rgba[offset : offset + 4] = bytes((34 + x * 2, 112 + y * 3, 58, 255))
    return encode_rgba_png(64, 32, bytes(rgba))


def _custom_png(
    width: int,
    height: int,
    bit_depth: int,
    color_type: int,
    scanlines: bytes,
    *,
    interlace: int = 0,
    palette: bytes = b"",
    transparency: bytes = b"",
) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace)
    extra = (chunk(b"PLTE", palette) if palette else b"") + (chunk(b"tRNS", transparency) if transparency else b"")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + extra + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b"")


def test_png_round_trip_preserves_rgba_pixels():
    raw = _checker_texture()
    texture = decode_png(raw)

    assert (texture.width, texture.height) == (16, 16)
    assert texture.rgba[:4] == bytes((112, 92, 44, 255))
    assert encode_rgba_png(texture.width, texture.height, texture.rgba) == raw


def test_png_decoder_supports_packed_palette_and_transparency():
    raw = _custom_png(
        2,
        2,
        4,
        3,
        b"\0\x01\0\x10",
        palette=bytes((255, 0, 0, 0, 255, 0)),
        transparency=bytes((255, 0)),
    )

    texture = decode_png(raw)

    assert texture.rgba == bytes((255, 0, 0, 255, 0, 255, 0, 0, 0, 255, 0, 0, 255, 0, 0, 255))


def test_png_decoder_supports_adam7_interlacing():
    red = bytes((255, 0, 0, 255))
    green = bytes((0, 255, 0, 255))
    blue = bytes((0, 0, 255, 255))
    white = bytes((255, 255, 255, 255))
    # For 2x2 Adam7 uses pass 1 for (0,0), pass 6 for (1,0), and pass 7 for row 1.
    raw = _custom_png(2, 2, 8, 6, b"\0" + red + b"\0" + green + b"\0" + blue + white, interlace=1)

    texture = decode_png(raw)

    assert texture.rgba == red + green + blue + white


def test_common_block_shapes_render_to_distinct_cached_icons():
    texture = _checker_texture()
    rendered = {
        item: render_block_icon(f"minecraft:acacia_{item}", texture, is_block_item=True)
        for item in ["button", "pressure_plate", "slab", "stairs", "fence", "fence_gate", "sign", "hanging_sign", "planks"]
    }

    assert all(result is not None for result in rendered.values())
    hashes = {hashlib.sha256(result[0]).hexdigest() for result in rendered.values() if result}
    assert len(hashes) == len(rendered)
    for result in rendered.values():
        assert result is not None
        decoded = decode_png(result[0])
        assert (decoded.width, decoded.height) == (ICON_SIZE, ICON_SIZE)


def test_sparse_unknown_block_texture_is_not_forced_into_a_cube():
    assert render_block_icon("minecraft:custom_flower", _checker_texture(transparent=True), is_block_item=True) is None


def test_opaque_unknown_geometry_is_not_forced_into_a_cube():
    item_ids = [
        "minecraft:dragon_egg",
        "minecraft:composter",
        "minecraft:lectern",
        "minecraft:chorus_plant",
        "minecraft:farmland",
        "minecraft:small_dripleaf_block",
        "minecraft:stonecutter_block",
    ]
    for item_id in item_ids:
        assert render_block_icon(item_id, _checker_texture(), is_block_item=True) is None


def test_non_block_item_is_never_model_rendered():
    assert render_block_icon("minecraft:apple", _checker_texture(), is_block_item=False) is None


def test_known_model_shape_can_render_when_registry_classifies_it_as_an_item():
    rendered = render_block_icon("minecraft:acacia_sign", _checker_texture(), is_block_item=False)

    assert rendered is not None
    assert rendered[1] == "sign"


def test_special_vanilla_block_shapes_do_not_fall_back_to_full_cubes():
    expected = {
        "minecraft:anvil": "anvil",
        "minecraft:chest": "chest",
        "minecraft:daylight_detector": "low_block",
        "minecraft:enchanting_table": "enchanting_table",
        "minecraft:end_portal_frame": "end_portal_frame",
        "minecraft:glass_pane": "pane",
        "minecraft:heavy_core": "heavy_core",
        # Half-height body; the four tendrils are rotated planes and stay out.
        "minecraft:sculk_sensor": "half_block",
        "minecraft:calibrated_sculk_sensor": "half_block",
        "minecraft:snow_layer": "snow_layer",
    }

    for item_id, shape in expected.items():
        rendered = render_block_icon(item_id, _checker_texture(), is_block_item=True)
        assert rendered is not None
        assert rendered[1] == shape


def test_full_cube_blocks_without_a_derivable_suffix_still_render_as_cubes():
    # Bedrock keys these as plain words or with a suffix the shape heuristic does
    # not recognize, so each one has to be listed explicitly.
    item_ids = [
        "minecraft:azalea_leaves_flowered",
        "minecraft:bamboo_mosaic",
        "minecraft:blast_furnace",
        "minecraft:carved_pumpkin",
        "minecraft:cinnabar",
        "minecraft:crafter",
        "minecraft:dark_prismarine",
        "minecraft:ice",
        "minecraft:lit_pumpkin",
        "minecraft:mangrove_roots",
        "minecraft:mob_spawner",
        "minecraft:muddy_mangrove_roots",
        "minecraft:potent_sulfur",
        "minecraft:purpur_pillar",
        "minecraft:red_nether_brick",
        "minecraft:sandstone",
        "minecraft:slime",
        "minecraft:smooth_quartz",
        "minecraft:sulfur",
        "minecraft:trial_spawner",
        "minecraft:vault",
    ]

    for item_id in item_ids:
        rendered = render_block_icon(item_id, _checker_texture(), is_block_item=True)
        assert rendered is not None, item_id
        assert rendered[1] == "cube", item_id


def test_legacy_bedrock_keys_reach_their_non_cube_shapes():
    expected = {
        # The oak trapdoor's historical key carries no wood prefix.
        "minecraft:trapdoor": "trapdoor",
        "minecraft:copper_bars": "pane",
        "minecraft:waxed_oxidized_copper_bars": "pane",
        "minecraft:iron_bars": "pane",
    }

    for item_id, shape in expected.items():
        rendered = render_block_icon(item_id, _checker_texture(), is_block_item=True)
        assert rendered is not None, item_id
        assert rendered[1] == shape, item_id


def _quadrant_atlas(size: int = 16) -> bytes:
    """A sheet whose four quadrants carry four distinct colours."""

    colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
    rgba = bytearray()
    for y in range(size):
        for x in range(size):
            rgba.extend(colors[(y >= size // 2) * 2 + (x >= size // 2)])
    return encode_rgba_png(size, size, bytes(rgba))


@pytest.mark.parametrize("size", [16, 64])
def test_crop_png_cuts_the_requested_quadrant_at_any_texture_resolution(size):
    # Regions are given in sixteenths, so an HD pack must crop the same quadrant.
    bottom_left = decode_png(crop_png(_quadrant_atlas(size), 0, 8, 8, 8))

    assert (bottom_left.width, bottom_left.height) == (size // 2, size // 2)
    assert set(bytes(bottom_left.rgba[i : i + 4]) for i in range(0, len(bottom_left.rgba), 4)) == {bytes((0, 0, 255, 255))}


@pytest.mark.parametrize("region", [(-1, 0, 8, 8), (0, 0, 0, 8), (12, 0, 8, 8), (0, 12, 8, 8)])
def test_crop_png_rejects_regions_outside_the_texture(region):
    with pytest.raises(ValueError):
        crop_png(_quadrant_atlas(), *region)


def test_renderer_uses_distinct_side_top_and_front_textures():
    rendered = render_block_icon(
        "minecraft:iron_block",
        _solid_texture(255, 0, 0),
        is_block_item=True,
        top_png_bytes=_solid_texture(0, 255, 0),
        front_png_bytes=_solid_texture(0, 0, 255),
    )

    assert rendered is not None
    rgba = decode_png(rendered[0]).rgba
    colors = {tuple(rgba[offset : offset + 4]) for offset in range(0, len(rgba), 4)}
    assert any(g > r and g > b and a for r, g, b, a in colors)
    assert any(b > r and b > g and a for r, g, b, a in colors)
    assert any(r > g and r > b and a for r, g, b, a in colors)


def test_bedrock_box_uv_model_renderer_extracts_geometry_instead_of_copying_atlas():
    rendered = render_bedrock_model_icon(_shield_model(), _shield_atlas(), geometry_identifier="geometry.shield")

    texture = decode_png(rendered)
    assert (texture.width, texture.height) == (ICON_SIZE, ICON_SIZE)
    assert texture.pixel(0, 0)[3] == 0
    opaque_colors = {tuple(texture.rgba[offset : offset + 4]) for offset in range(0, len(texture.rgba), 4) if texture.rgba[offset + 3]}
    assert any(red > green > blue for red, green, blue, _alpha in opaque_colors)
    assert (255, 255, 255, 255) not in opaque_colors


def test_bedrock_model_renderer_supports_finite_cube_inflate_values():
    model = _shield_model()
    model["minecraft:geometry"][0]["bones"][0]["cubes"][0]["inflate"] = -0.01

    rendered = render_bedrock_model_icon(model, _shield_atlas(), geometry_identifier="geometry.shield")

    texture = decode_png(rendered)
    assert (texture.width, texture.height) == (ICON_SIZE, ICON_SIZE)
    assert any(texture.rgba[offset + 3] for offset in range(0, len(texture.rgba), 4))


def test_bedrock_model_renderer_rejects_inflate_that_collapses_a_cube():
    model = _shield_model()
    model["minecraft:geometry"][0]["bones"][0]["cubes"][0]["inflate"] = -2

    with pytest.raises(ValueError, match="nach inflate keine gültige Größe"):
        render_bedrock_model_icon(model, _shield_atlas(), geometry_identifier="geometry.shield")


def test_bedrock_model_renderer_supports_legacy_named_geometry_and_mirrored_cubes():
    regular = render_bedrock_model_icon(
        _legacy_head_model(),
        _legacy_head_atlas(),
        geometry_identifier="geometry.mob_head",
    )
    mirrored = render_bedrock_model_icon(
        _legacy_head_model(mirror=True),
        _legacy_head_atlas(),
        geometry_identifier="geometry.mob_head",
    )

    regular_texture = decode_png(regular)
    assert (regular_texture.width, regular_texture.height) == (ICON_SIZE, ICON_SIZE)
    assert any(regular_texture.rgba[offset + 3] for offset in range(0, len(regular_texture.rgba), 4))
    assert regular != mirrored


def test_bedrock_model_renderer_rejects_missing_legacy_geometry_identifier():
    with pytest.raises(ValueError, match="wurde nicht gefunden"):
        render_bedrock_model_icon(
            _legacy_head_model(),
            _legacy_head_atlas(),
            geometry_identifier="geometry.unknown",
        )


def test_bedrock_model_renderer_rejects_out_of_bounds_uvs():
    with pytest.raises(ValueError, match="UV-Koordinaten außerhalb"):
        render_bedrock_model_icon(_shield_model(plate_uv=[63, 63]), _shield_atlas(), geometry_identifier="geometry.shield")


def test_bedrock_model_renderer_rejects_rotated_geometry_instead_of_rendering_it_incorrectly():
    model = _shield_model()
    model["minecraft:geometry"][0]["bones"][0]["rotation"] = [0, 45, 0]

    with pytest.raises(ValueError, match="Rotierte Bedrock-Bones"):
        render_bedrock_model_icon(model, _shield_atlas(), geometry_identifier="geometry.shield")
