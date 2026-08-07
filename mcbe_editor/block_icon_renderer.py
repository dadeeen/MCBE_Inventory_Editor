"""Dependency-free previews for block items and explicit Bedrock models.

Minecraft Bedrock renders many inventory icons from block geometry at runtime;
the resource pack therefore contains only the material texture.  This module
turns common deterministic block shapes and explicitly selected model geometry
into small cached PNGs without adding a runtime imaging dependency.
"""

from __future__ import annotations

import binascii
import math
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ICON_SIZE = 64
MAX_TEXTURE_PIXELS = 512 * 512
MAX_MODEL_CUBES = 256
MAX_MODEL_COORDINATE = 4096.0
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_FULL_CUBE_SUFFIXES = (
    "_bricks",
    "_bulb",
    "_command_block",
    "_concrete",
    "_concrete_powder",
    "_copper",
    "_coral_block",
    "_froglight",
    "_glass",
    "_glazed_terracotta",
    "_grate",
    "_hyphae",
    "_ice",
    "_leaves",
    "_log",
    "_mushroom_block",
    "_nylium",
    "_ore",
    "_planks",
    "_sandstone",
    "_shelf",
    "_shulker_box",
    "_stem",
    "_terracotta",
    "_tiles",
    "_wart_block",
    "_wood",
    "_wool",
)
_FULL_CUBE_PREFIXES = ("chiseled_", "cracked_", "cut_", "infested_", "polished_", "stripped_")
_FULL_CUBE_IDS = {
    "allow",
    "amethyst_block",
    "ancient_debris",
    "azalea_leaves_flowered",
    "bamboo_block",
    "bamboo_mosaic",
    "barrel",
    "basalt",
    "beacon",
    "bedrock",
    "bee_nest",
    "beehive",
    "blackstone",
    "blast_furnace",
    "bone_block",
    "bookshelf",
    "border_block",
    "budding_amethyst",
    "calcite",
    "carved_pumpkin",
    "cinnabar",
    "clay",
    "coal_block",
    "coarse_dirt",
    "cobbled_deepslate",
    "cobblestone",
    "command_block",
    "crafter",
    "crafting_table",
    "creaking_heart",
    "crying_obsidian",
    "copper_block",
    "dark_prismarine",
    "deepslate",
    "deny",
    "diamond_block",
    "dirt",
    "dirt_with_roots",
    "dispenser",
    "dried_kelp_block",
    "dripstone_block",
    "dropper",
    "emerald_block",
    "end_stone",
    "fletching_table",
    "furnace",
    "gilded_blackstone",
    "glass",
    "glowstone",
    "gold_block",
    "grass_block",
    "gravel",
    "hardened_clay",
    "hay_block",
    "honey_block",
    "honeycomb_block",
    "ice",
    "iron_block",
    "jigsaw",
    "jukebox",
    "lapis_block",
    "lit_pumpkin",
    "lodestone",
    "loom",
    "magma",
    "mangrove_roots",
    "melon_block",
    "mob_spawner",
    "moss_block",
    "mossy_cobblestone",
    "mossy_stone_bricks",
    "mud",
    "muddy_mangrove_roots",
    "mushroom_stem",
    "mycelium",
    "nether_brick",
    "netherite_block",
    "netherrack",
    "noteblock",
    "observer",
    "obsidian",
    "packed_mud",
    "pale_moss_block",
    "piston",
    "podzol",
    "polished_andesite",
    "polished_basalt",
    "polished_blackstone",
    "polished_deepslate",
    "polished_diorite",
    "polished_granite",
    "polished_tuff",
    "potent_sulfur",
    "prismarine",
    "pumpkin",
    "purpur_block",
    "purpur_pillar",
    "quartz_block",
    "quartz_pillar",
    "raw_copper_block",
    "raw_gold_block",
    "raw_iron_block",
    "red_nether_brick",
    "red_sand",
    "redstone_block",
    "redstone_lamp",
    "reinforced_deepslate",
    "resin_block",
    "respawn_anchor",
    "sand",
    "sandstone",
    "sculk",
    "sculk_catalyst",
    "sea_lantern",
    "shroomlight",
    "slime",
    "smithing_table",
    "smoker",
    "smooth_basalt",
    "smooth_quartz",
    "smooth_stone",
    "snow",
    "soul_sand",
    "soul_soil",
    "sponge",
    "sticky_piston",
    "stone",
    "structure_block",
    "sulfur",
    "suspicious_gravel",
    "suspicious_sand",
    "target",
    "tinted_glass",
    "tnt",
    "trial_spawner",
    "tuff",
    "vault",
    "wet_sponge",
}


@dataclass(frozen=True)
class Texture:
    width: int
    height: int
    rgba: bytes

    def first_square_frame(self) -> Texture:
        """Use the first frame of the usual vertically stacked animations."""

        size = min(self.width, self.height)
        if size == self.width == self.height:
            return self
        rows = []
        stride = self.width * 4
        for y in range(size):
            rows.append(self.rgba[y * stride : y * stride + size * 4])
        return Texture(size, size, b"".join(rows))

    def pixel(self, u: float, v: float) -> tuple[int, int, int, int]:
        x = min(self.width - 1, max(0, int(u * self.width)))
        y = min(self.height - 1, max(0, int(v * self.height)))
        offset = (y * self.width + x) * 4
        return tuple(self.rgba[offset : offset + 4])  # type: ignore[return-value]


@dataclass(frozen=True)
class ModelCube:
    origin: tuple[float, float, float]
    size: tuple[float, float, float]
    uv: tuple[float, float]
    uv_size: tuple[float, float, float] | None = None
    mirror: bool = False


def _png_chunks(raw: bytes):
    if not raw.startswith(_PNG_SIGNATURE):
        raise ValueError("Keine PNG-Datei.")
    offset = len(_PNG_SIGNATURE)
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + 8 + length
        if end + 4 > len(raw):
            raise ValueError("PNG-Chunk ist unvollständig.")
        payload = raw[offset + 8 : end]
        expected_crc = struct.unpack(">I", raw[end : end + 4])[0]
        if (binascii.crc32(kind + payload) & 0xFFFFFFFF) != expected_crc:
            raise ValueError("PNG-Chunk hat eine ungültige Prüfsumme.")
        yield kind, payload
        offset = end + 4
        if kind == b"IEND":
            return
    raise ValueError("PNG-Ende fehlt.")


def _unfilter_scanline(filter_type: int, current: bytearray, previous: bytes, bytes_per_pixel: int) -> bytes:
    for index in range(len(current)):
        left = current[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        above = previous[index] if previous else 0
        upper_left = previous[index - bytes_per_pixel] if previous and index >= bytes_per_pixel else 0
        if filter_type == 1:
            current[index] = (current[index] + left) & 0xFF
        elif filter_type == 2:
            current[index] = (current[index] + above) & 0xFF
        elif filter_type == 3:
            current[index] = (current[index] + ((left + above) // 2)) & 0xFF
        elif filter_type == 4:
            estimate = left + above - upper_left
            distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
            predictor = (left, above, upper_left)[distances.index(min(distances))]
            current[index] = (current[index] + predictor) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"Nicht unterstützter PNG-Filter: {filter_type}")
    return bytes(current)


def _pass_length(total: int, start: int, step: int) -> int:
    return 0 if total <= start else (total - start + step - 1) // step


def _unpack_samples(row: bytes, count: int, bit_depth: int) -> list[int]:
    if bit_depth == 8:
        if len(row) < count:
            raise ValueError("PNG-Scanline ist unvollständig.")
        return list(row[:count])
    mask = (1 << bit_depth) - 1
    samples = []
    for index in range(count):
        bit_offset = index * bit_depth
        byte_index = bit_offset // 8
        shift = 8 - bit_depth - (bit_offset % 8)
        if byte_index >= len(row) or shift < 0:
            raise ValueError("PNG-Scanline ist unvollständig.")
        samples.append((row[byte_index] >> shift) & mask)
    return samples


def _sample_rgba(samples: list[int], offset: int, color_type: int, bit_depth: int, palette: bytes, transparency: bytes) -> tuple[int, int, int, int]:
    if color_type == 0:
        sample = samples[offset]
        maximum = (1 << bit_depth) - 1
        gray = round(sample * 255 / maximum)
        transparent_sample = int.from_bytes(transparency[:2], "big") if len(transparency) >= 2 else None
        return gray, gray, gray, 0 if sample == transparent_sample else 255
    if color_type == 2:
        red, green, blue = samples[offset : offset + 3]
        transparent_rgb = tuple(int.from_bytes(transparency[index : index + 2], "big") for index in range(0, 6, 2)) if len(transparency) >= 6 else None
        return red, green, blue, 0 if (red, green, blue) == transparent_rgb else 255
    if color_type == 3:
        palette_index = samples[offset]
        palette_offset = palette_index * 3
        if palette_offset + 3 > len(palette):
            raise ValueError("PNG-Palettenindex liegt außerhalb der Palette.")
        alpha = transparency[palette_index] if palette_index < len(transparency) else 255
        return *palette[palette_offset : palette_offset + 3], alpha
    if color_type == 4:
        gray, alpha = samples[offset : offset + 2]
        return gray, gray, gray, alpha
    return tuple(samples[offset : offset + 4])  # type: ignore[return-value]


def decode_png(raw: bytes) -> Texture:
    width = height = bit_depth = color_type = interlace = None
    palette = b""
    transparency = b""
    compressed = bytearray()
    for kind, payload in _png_chunks(raw):
        if kind == b"IHDR":
            if len(payload) != 13:
                raise ValueError("PNG-Kopfdaten sind ungültig.")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if compression or filtering:
                raise ValueError("Nicht unterstützte PNG-Kompression.")
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            compressed.extend(payload)
    if not width or not height or width * height > MAX_TEXTURE_PIXELS:
        raise ValueError("PNG-Bildgröße ist unerwartet.")
    allowed_depths = {0: {1, 2, 4, 8}, 2: {8}, 3: {1, 2, 4, 8}, 4: {8}, 6: {8}}
    if color_type not in allowed_depths or bit_depth not in allowed_depths[color_type] or interlace not in {0, 1}:
        raise ValueError("PNG-Farbformat wird für Blockvorschauen nicht unterstützt.")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    passes = [(0, 0, 1, 1)] if interlace == 0 else [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    pass_sizes = [(_pass_length(width, x, dx), _pass_length(height, y, dy)) for x, y, dx, dy in passes]
    expected_size = sum(
        pass_height * (1 + (pass_width * channels * bit_depth + 7) // 8) for pass_width, pass_height in pass_sizes if pass_width and pass_height
    )
    decompressor = zlib.decompressobj()
    decoded = decompressor.decompress(bytes(compressed), expected_size + 1)
    if len(decoded) != expected_size or decompressor.unconsumed_tail or decompressor.unused_data or not decompressor.eof:
        raise ValueError("PNG-Pixeldaten haben eine unerwartete Länge.")
    pixels = [(0, 0, 0, 0)] * (width * height)
    offset = 0
    bytes_per_pixel = max(1, (channels * bit_depth + 7) // 8)
    for (start_x, start_y, step_x, step_y), (pass_width, pass_height) in zip(passes, pass_sizes, strict=True):
        if not pass_width or not pass_height:
            continue
        row_size = (pass_width * channels * bit_depth + 7) // 8
        previous = b""
        for pass_y in range(pass_height):
            filter_type = decoded[offset]
            current = bytearray(decoded[offset + 1 : offset + 1 + row_size])
            previous = _unfilter_scanline(filter_type, current, previous, bytes_per_pixel)
            samples = _unpack_samples(previous, pass_width * channels, bit_depth)
            image_y = start_y + pass_y * step_y
            for pass_x in range(pass_width):
                image_x = start_x + pass_x * step_x
                pixels[image_y * width + image_x] = _sample_rgba(samples, pass_x * channels, color_type, bit_depth, palette, transparency)
            offset += row_size + 1
    return Texture(width, height, b"".join(bytes(pixel) for pixel in pixels))


def encode_rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("Ungültige RGBA-Bilddaten.")
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        rows.extend(rgba[y * stride : (y + 1) * stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return _PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")


def crop_png(png_bytes: bytes, left: int, top: int, width: int, height: int) -> bytes:
    """Cut one face out of a texture that packs several faces into one sheet.

    The region is given in sixteenths of the texture edge, matching how Bedrock
    models address their box UVs, so HD resource packs crop correctly too.
    """

    if min(left, top) < 0 or min(width, height) <= 0 or left + width > 16 or top + height > 16:
        raise ValueError("Atlas-Region liegt außerhalb der Textur.")
    texture = decode_png(png_bytes).first_square_frame()
    scale = texture.width / 16
    x0, y0 = round(left * scale), round(top * scale)
    span_x, span_y = round(width * scale), round(height * scale)
    if span_x <= 0 or span_y <= 0:
        raise ValueError("Atlas-Region ist nach der Skalierung leer.")
    rows = bytearray()
    for y in range(y0, y0 + span_y):
        offset = (y * texture.width + x0) * 4
        rows.extend(texture.rgba[offset : offset + span_x * 4])
    return encode_rgba_png(span_x, span_y, bytes(rows))


def tint_png(png_bytes: bytes, tint: tuple[int, int, int]) -> bytes:
    texture = decode_png(png_bytes).first_square_frame()
    rgba = bytearray(texture.rgba)
    for offset in range(0, len(rgba), 4):
        for channel in range(3):
            rgba[offset + channel] = round(rgba[offset + channel] * tint[channel] / 255)
    return encode_rgba_png(texture.width, texture.height, bytes(rgba))


def composite_png_overlay(background_png: bytes, overlay_png: bytes, *, overlay_tint: tuple[int, int, int] | None = None) -> bytes:
    background = decode_png(background_png).first_square_frame()
    overlay = decode_png(overlay_png).first_square_frame()
    rgba = bytearray()
    for y in range(overlay.height):
        for x in range(overlay.width):
            foreground = list(overlay.pixel(x / overlay.width, y / overlay.height))
            if overlay_tint:
                for channel in range(3):
                    foreground[channel] = round(foreground[channel] * overlay_tint[channel] / 255)
            behind = background.pixel(x / overlay.width, y / overlay.height)
            source_alpha = foreground[3] / 255
            output_alpha = source_alpha + (behind[3] / 255) * (1 - source_alpha)
            if output_alpha <= 0:
                rgba.extend((0, 0, 0, 0))
                continue
            for channel in range(3):
                rgba.append(round((foreground[channel] * source_alpha + behind[channel] * (behind[3] / 255) * (1 - source_alpha)) / output_alpha))
            rgba.append(round(output_alpha * 255))
    return encode_rgba_png(overlay.width, overlay.height, bytes(rgba))


def _shape_name(item_id: str) -> str | None:
    item = item_id.removeprefix("minecraft:").lower()
    ordered_suffixes = (
        ("_hanging_sign", "hanging_sign"),
        ("_fence_gate", "fence_gate"),
        ("_pressure_plate", "pressure_plate"),
        ("_button", "button"),
        ("_stairs", "stairs"),
        ("_double_slab", "cube"),
        ("_slab", "slab"),
        ("_wall", "wall"),
        ("_fence", "fence"),
        ("_standing_sign", "sign"),
        ("_wall_sign", "sign"),
        ("_sign", "sign"),
        ("_trapdoor", "trapdoor"),
        ("_carpet", "carpet"),
        ("_stained_glass_pane", "pane"),
        ("_glass_pane", "pane"),
        # Copper bars share the iron bars' lattice across every oxidation and
        # waxed stage.
        ("_bars", "pane"),
    )
    for suffix, shape in ordered_suffixes:
        if item.endswith(suffix):
            return shape
    exact_shapes = {
        "anvil": "anvil",
        # Both sensors are a plain half-height body; only their four tendrils are
        # rotated planes, and those the renderer deliberately does not attempt.
        "calibrated_sculk_sensor": "half_block",
        "sculk_sensor": "half_block",
        "heavy_core": "heavy_core",
        "chipped_anvil": "anvil",
        "damaged_anvil": "anvil",
        "chest": "chest",
        "cactus": "cactus",
        "daylight_detector": "low_block",
        "daylight_detector_inverted": "low_block",
        "enchanting_table": "enchanting_table",
        "end_portal_frame": "end_portal_frame",
        "ender_chest": "chest",
        "fence": "fence",
        "fence_gate": "fence_gate",
        "glass_pane": "pane",
        "iron_bars": "pane",
        "snow_layer": "snow_layer",
        "stained_glass_pane": "pane",
        # Bedrock's historical key for the oak trapdoor carries no wood prefix.
        "trapdoor": "trapdoor",
        "trapped_chest": "chest",
        "wooden_button": "button",
        "wooden_pressure_plate": "pressure_plate",
    }
    if item in exact_shapes:
        return exact_shapes[item]
    if item in _FULL_CUBE_IDS or item.startswith(_FULL_CUBE_PREFIXES) or item.endswith(_FULL_CUBE_SUFFIXES):
        return "cube"


def _cuboids(shape: str) -> list[tuple[float, float, float, float, float, float]]:
    cube = (0, 0, 0, 16, 16, 16)
    shapes = {
        "cube": [cube],
        "slab": [(0, 0, 0, 16, 8, 16)],
        "stairs": [(0, 0, 0, 16, 8, 16), (0, 8, 8, 16, 16, 16)],
        "button": [(5, 0, 6, 11, 2, 10)],
        "pressure_plate": [(1, 0, 1, 15, 1, 15)],
        "carpet": [(0, 0, 0, 16, 1, 16)],
        "trapdoor": [(0, 0, 0, 16, 3, 16)],
        "low_block": [(0, 0, 0, 16, 6, 16)],
        "half_block": [(0, 0, 0, 16, 8, 16)],
        # The heavy core is a free-floating 8×8×8 cube, not a ground-filling block.
        "heavy_core": [(4, 0, 4, 12, 8, 12)],
        # The enchanting table stands three quarters of a block tall (12/16).
        "enchanting_table": [(0, 0, 0, 16, 12, 16)],
        # The end portal frame is a single 13/16 box; the eye is a separate
        # block state and never part of the item.
        "end_portal_frame": [(0, 0, 0, 16, 13, 16)],
        "snow_layer": [(0, 0, 0, 16, 2, 16)],
        "pane": [(7, 0, 0, 9, 16, 16)],
        "anvil": [(1, 0, 2, 15, 3, 14), (5, 3, 5, 11, 11, 11), (0, 11, 3, 16, 16, 13)],
        "chest": [(1, 0, 1, 15, 14, 15), (7, 6, 15, 9, 10, 16)],
        "cactus": [(1, 0, 1, 15, 16, 15)],
        "fence": [(6, 0, 6, 10, 16, 10), (0, 5, 7, 16, 8, 9), (0, 11, 7, 16, 14, 9)],
        "wall": [(5, 0, 5, 11, 16, 11), (0, 3, 6, 16, 12, 10)],
        "fence_gate": [(0, 0, 6, 3, 16, 10), (13, 0, 6, 16, 16, 10), (3, 5, 7, 13, 8, 9), (3, 11, 7, 13, 14, 9)],
        "sign": [(2, 7, 7, 14, 15, 9), (7, 0, 7, 9, 7, 9)],
        "hanging_sign": [(2, 3, 7, 14, 12, 9), (3, 12, 7, 5, 16, 9), (11, 12, 7, 13, 16, 9)],
    }
    return shapes[shape]


def _projection_for(boxes: list[tuple[float, float, float, float, float, float]]) -> Callable[[float, float, float], tuple[float, float]]:
    projected = []
    for x0, y0, z0, x1, y1, z1 in boxes:
        for x in (x0, x1):
            for y in (y0, y1):
                for z in (z0, z1):
                    projected.append((x - z, -y + (x + z) / 2))
    min_x, max_x = min(value[0] for value in projected), max(value[0] for value in projected)
    min_y, max_y = min(value[1] for value in projected), max(value[1] for value in projected)
    width, height = max(max_x - min_x, 1), max(max_y - min_y, 1)
    # Small shapes receive Minecraft-like GUI enlargement, but remain visibly
    # smaller than a full block instead of filling the entire tile.
    scale = min(48 / width, 48 / height, 3.0)
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        raw_x, raw_y = x - z, -y + (x + z) / 2
        return 32 + (raw_x - center_x) * scale, 32 + (raw_y - center_y) * scale

    return project


def _blend(canvas: bytearray, x: int, y: int, color: tuple[int, int, int, int], shade: float) -> None:
    if x < 0 or y < 0 or x >= ICON_SIZE or y >= ICON_SIZE or color[3] == 0:
        return
    offset = (y * ICON_SIZE + x) * 4
    source_alpha = color[3] / 255
    target_alpha = canvas[offset + 3] / 255
    output_alpha = source_alpha + target_alpha * (1 - source_alpha)
    if output_alpha <= 0:
        return
    for channel in range(3):
        source = min(255, round(color[channel] * shade))
        target = canvas[offset + channel]
        canvas[offset + channel] = round((source * source_alpha + target * target_alpha * (1 - source_alpha)) / output_alpha)
    canvas[offset + 3] = round(output_alpha * 255)


def _draw_triangle(
    canvas: bytearray,
    texture: Texture,
    points: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    uvs: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    shade: float,
) -> None:
    (x0, y0), (x1, y1), (x2, y2) = points
    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denominator) < 1e-9:
        return
    min_x = max(0, int(min(x0, x1, x2)))
    max_x = min(ICON_SIZE - 1, int(max(x0, x1, x2) + 1))
    min_y = max(0, int(min(y0, y1, y2)))
    max_y = min(ICON_SIZE - 1, int(max(y0, y1, y2) + 1))
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            px, py = x + 0.5, y + 0.5
            w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denominator
            w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denominator
            w2 = 1 - w0 - w1
            if min(w0, w1, w2) < -1e-7:
                continue
            u = w0 * uvs[0][0] + w1 * uvs[1][0] + w2 * uvs[2][0]
            v = w0 * uvs[0][1] + w1 * uvs[1][1] + w2 * uvs[2][1]
            _blend(canvas, x, y, texture.pixel(u, v), shade)


def _draw_quad(canvas: bytearray, texture: Texture, points: list[tuple[float, float]], shade: float) -> None:
    uv = [(0.0, 0.0), (1.0 - 1e-9, 0.0), (1.0 - 1e-9, 1.0 - 1e-9), (0.0, 1.0 - 1e-9)]
    _draw_triangle(canvas, texture, (points[0], points[1], points[2]), (uv[0], uv[1], uv[2]), shade)
    _draw_triangle(canvas, texture, (points[0], points[2], points[3]), (uv[0], uv[2], uv[3]), shade)


def _draw_cuboid(
    canvas: bytearray,
    side_texture: Texture,
    top_texture: Texture,
    front_texture: Texture,
    box: tuple[float, float, float, float, float, float],
    project: Callable[[float, float, float], tuple[float, float]],
) -> None:
    x0, y0, z0, x1, y1, z1 = box
    # Visible positive-X and positive-Z faces, followed by the lit top face.
    _draw_quad(canvas, side_texture, [project(x1, y1, z0), project(x1, y1, z1), project(x1, y0, z1), project(x1, y0, z0)], 0.78)
    _draw_quad(canvas, front_texture, [project(x0, y1, z1), project(x1, y1, z1), project(x1, y0, z1), project(x0, y0, z1)], 0.62)
    _draw_quad(canvas, top_texture, [project(x0, y1, z0), project(x1, y1, z0), project(x1, y1, z1), project(x0, y1, z1)], 1.0)


def _model_triplet(value: Any, field_name: str, *, positive: bool = False) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"Bedrock-Modellfeld {field_name!r} muss aus drei Zahlen bestehen.")
    try:
        result = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Bedrock-Modellfeld {field_name!r} enthält keine gültigen Zahlen.") from exc
    if any(not math.isfinite(component) or abs(component) > MAX_MODEL_COORDINATE for component in result):
        raise ValueError(f"Bedrock-Modellfeld {field_name!r} liegt außerhalb des zulässigen Bereichs.")
    if positive and any(component <= 0 for component in result):
        raise ValueError(f"Bedrock-Modellfeld {field_name!r} muss positive Größen enthalten.")
    return result  # type: ignore[return-value]


def _model_uv(value: Any) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Bedrock-Modellwürfel benötigt zweidimensionale Box-UV-Koordinaten.")
    try:
        result = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bedrock-Modellwürfel enthält ungültige UV-Koordinaten.") from exc
    if any(not math.isfinite(component) or component < 0 or component > MAX_MODEL_COORDINATE for component in result):
        raise ValueError("Bedrock-Modellwürfel enthält UV-Koordinaten außerhalb des zulässigen Bereichs.")
    return result  # type: ignore[return-value]


def _has_nonzero_rotation(value: Any) -> bool:
    if value is None:
        return False
    rotation = _model_triplet(value, "rotation")
    return any(abs(component) > 1e-9 for component in rotation)


def _model_geometry(
    model_data: dict[str, Any],
    geometry_identifier: str,
) -> tuple[list[ModelCube], float, float]:
    geometries = model_data.get("minecraft:geometry")
    selected: dict[str, Any] | None = None
    description: dict[str, Any] | None = None
    if isinstance(geometries, list):
        for geometry in geometries:
            if not isinstance(geometry, dict):
                continue
            candidate_description = geometry.get("description")
            if isinstance(candidate_description, dict) and candidate_description.get("identifier") == geometry_identifier:
                selected = geometry
                description = candidate_description
                break
    else:
        # Bedrock's older models/mobs.json format stores geometry objects under
        # their identifier and keeps the texture dimensions on the object.
        legacy_geometry = model_data.get(geometry_identifier)
        if isinstance(legacy_geometry, dict):
            selected = legacy_geometry
    if selected is None:
        raise ValueError(f"Bedrock-Geometrie {geometry_identifier!r} wurde nicht gefunden.")

    try:
        if description is not None:
            texture_width = float(description["texture_width"])
            texture_height = float(description["texture_height"])
        else:
            texture_width = float(selected["texturewidth"])
            texture_height = float(selected["textureheight"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Bedrock-Geometrie enthält keine gültige Texturgröße.") from exc
    if (
        not math.isfinite(texture_width)
        or not math.isfinite(texture_height)
        or texture_width <= 0
        or texture_height <= 0
        or texture_width * texture_height > MAX_TEXTURE_PIXELS
    ):
        raise ValueError("Bedrock-Geometrie enthält eine unerwartete Texturgröße.")

    bones = selected.get("bones")
    if not isinstance(bones, list):
        raise ValueError("Bedrock-Geometrie enthält keine gültige Bone-Liste.")
    cubes: list[ModelCube] = []
    for bone in bones:
        if not isinstance(bone, dict):
            continue
        if _has_nonzero_rotation(bone.get("rotation")):
            raise ValueError("Rotierte Bedrock-Bones werden für Icon-Vorschauen nicht unterstützt.")
        bone_mirror = bone.get("mirror", False)
        if not isinstance(bone_mirror, bool):
            raise ValueError("Bedrock-Bone enthält einen ungültigen mirror-Wert.")
        raw_cubes = bone.get("cubes", [])
        if not isinstance(raw_cubes, list):
            raise ValueError("Bedrock-Bone enthält keine gültige Würfelliste.")
        for raw_cube in raw_cubes:
            if not isinstance(raw_cube, dict):
                continue
            if _has_nonzero_rotation(raw_cube.get("rotation")):
                raise ValueError("Rotierte Bedrock-Würfel werden für Icon-Vorschauen nicht unterstützt.")
            try:
                inflate = float(raw_cube.get("inflate", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError("Bedrock-Modellwürfel enthält einen ungültigen inflate-Wert.") from exc
            if not math.isfinite(inflate) or abs(inflate) > MAX_MODEL_COORDINATE:
                raise ValueError("Bedrock-Modellwürfel enthält einen inflate-Wert außerhalb des zulässigen Bereichs.")
            mirror = raw_cube.get("mirror", bone_mirror)
            if not isinstance(mirror, bool):
                raise ValueError("Bedrock-Modellwürfel enthält einen ungültigen mirror-Wert.")
            origin = _model_triplet(raw_cube.get("origin"), "origin")
            size = _model_triplet(raw_cube.get("size"), "size", positive=True)
            inflated_origin = tuple(component - inflate for component in origin)
            inflated_size = tuple(component + 2 * inflate for component in size)
            if any(component <= 0 or component > MAX_MODEL_COORDINATE for component in inflated_size):
                raise ValueError("Bedrock-Modellwürfel besitzt nach inflate keine gültige Größe.")
            cubes.append(
                ModelCube(
                    origin=inflated_origin,
                    size=inflated_size,
                    uv=_model_uv(raw_cube.get("uv")),
                    uv_size=size,
                    mirror=mirror,
                )
            )
            if len(cubes) > MAX_MODEL_CUBES:
                raise ValueError("Bedrock-Modell enthält zu viele Würfel.")
    if not cubes:
        raise ValueError("Bedrock-Geometrie enthält keine renderbaren Würfel.")
    return cubes, texture_width, texture_height


def _uv_quad(
    left: float,
    top: float,
    right: float,
    bottom: float,
    texture_width: float,
    texture_height: float,
    *,
    flip_x: bool = False,
    flip_y: bool = False,
) -> list[tuple[float, float]]:
    if left < 0 or top < 0 or right > texture_width or bottom > texture_height or right <= left or bottom <= top:
        raise ValueError("Bedrock-Modell verweist auf UV-Koordinaten außerhalb der Textur.")
    # Keep edge samples inside their atlas region instead of touching the next
    # face at an exact integer boundary.
    epsilon = 1e-7
    u0, u1 = (left + epsilon) / texture_width, (right - epsilon) / texture_width
    v0, v1 = (top + epsilon) / texture_height, (bottom - epsilon) / texture_height
    if flip_x:
        u0, u1 = u1, u0
    if flip_y:
        v0, v1 = v1, v0
    return [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]


def _cube_faces(
    cube: ModelCube,
    texture_width: float,
    texture_height: float,
) -> list[tuple[list[tuple[float, float, float]], list[tuple[float, float]], float]]:
    x0, y0, z0 = cube.origin
    width, height, depth = cube.size
    x1, y1, z1 = x0 + width, y0 + height, z0 + depth
    uv_width, uv_height, uv_depth = cube.uv_size or cube.size
    u, v = cube.uv
    west_uv = _uv_quad(
        u,
        v + uv_depth,
        u + uv_depth,
        v + uv_depth + uv_height,
        texture_width,
        texture_height,
        flip_x=not cube.mirror,
    )
    north_uv = _uv_quad(
        u + uv_depth,
        v + uv_depth,
        u + uv_depth + uv_width,
        v + uv_depth + uv_height,
        texture_width,
        texture_height,
        flip_x=cube.mirror,
    )
    east_uv = _uv_quad(
        u + uv_depth + uv_width,
        v + uv_depth,
        u + uv_depth + uv_width + uv_depth,
        v + uv_depth + uv_height,
        texture_width,
        texture_height,
        flip_x=cube.mirror,
    )
    south_uv = _uv_quad(
        u + uv_depth * 2 + uv_width,
        v + uv_depth,
        u + uv_depth * 2 + uv_width * 2,
        v + uv_depth + uv_height,
        texture_width,
        texture_height,
        flip_x=not cube.mirror,
    )
    up_uv = _uv_quad(
        u + uv_depth,
        v,
        u + uv_depth + uv_width,
        v + uv_depth,
        texture_width,
        texture_height,
        flip_x=cube.mirror,
    )
    down_uv = _uv_quad(
        u + uv_depth + uv_width,
        v,
        u + uv_depth + uv_width * 2,
        v + uv_depth,
        texture_width,
        texture_height,
        flip_x=cube.mirror,
        flip_y=True,
    )
    return [
        ([(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)], north_uv, 1.0),
        ([(x1, y1, z1), (x0, y1, z1), (x0, y0, z1), (x1, y0, z1)], south_uv, 0.68),
        ([(x0, y1, z1), (x0, y1, z0), (x0, y0, z0), (x0, y0, z1)], west_uv, 0.74),
        ([(x1, y1, z0), (x1, y1, z1), (x1, y0, z1), (x1, y0, z0)], east_uv, 0.82),
        ([(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)], up_uv, 0.94),
        ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], down_uv, 0.58),
    ]


def _rotate_model_point(
    point: tuple[float, float, float],
    center: tuple[float, float, float],
    *,
    yaw: float,
    pitch: float,
    roll: float,
) -> tuple[float, float, float]:
    x, y, z = (point[index] - center[index] for index in range(3))
    yaw_radians, pitch_radians, roll_radians = (math.radians(value) for value in (yaw, pitch, roll))
    yaw_cos, yaw_sin = math.cos(yaw_radians), math.sin(yaw_radians)
    x, z = x * yaw_cos + z * yaw_sin, -x * yaw_sin + z * yaw_cos
    pitch_cos, pitch_sin = math.cos(pitch_radians), math.sin(pitch_radians)
    y, z = y * pitch_cos - z * pitch_sin, y * pitch_sin + z * pitch_cos
    roll_cos, roll_sin = math.cos(roll_radians), math.sin(roll_radians)
    return x * roll_cos - y * roll_sin, x * roll_sin + y * roll_cos, z


def _draw_model_triangle(
    canvas: bytearray,
    depth_buffer: list[float],
    texture: Texture,
    points: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    uvs: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    shade: float,
) -> None:
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = points
    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denominator) < 1e-9:
        return
    min_x = max(0, int(min(x0, x1, x2)))
    max_x = min(ICON_SIZE - 1, int(max(x0, x1, x2) + 1))
    min_y = max(0, int(min(y0, y1, y2)))
    max_y = min(ICON_SIZE - 1, int(max(y0, y1, y2) + 1))
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            px, py = x + 0.5, y + 0.5
            weight0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denominator
            weight1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denominator
            weight2 = 1 - weight0 - weight1
            if min(weight0, weight1, weight2) < -1e-7:
                continue
            depth = weight0 * z0 + weight1 * z1 + weight2 * z2
            pixel_index = y * ICON_SIZE + x
            if depth > depth_buffer[pixel_index] + 1e-7:
                continue
            u = weight0 * uvs[0][0] + weight1 * uvs[1][0] + weight2 * uvs[2][0]
            v = weight0 * uvs[0][1] + weight1 * uvs[1][1] + weight2 * uvs[2][1]
            color = texture.pixel(u, v)
            if color[3] == 0:
                continue
            _blend(canvas, x, y, color, shade)
            depth_buffer[pixel_index] = depth


def _draw_model_quad(
    canvas: bytearray,
    depth_buffer: list[float],
    texture: Texture,
    points: list[tuple[float, float, float]],
    uvs: list[tuple[float, float]],
    shade: float,
) -> None:
    _draw_model_triangle(canvas, depth_buffer, texture, (points[0], points[1], points[2]), (uvs[0], uvs[1], uvs[2]), shade)
    _draw_model_triangle(canvas, depth_buffer, texture, (points[0], points[2], points[3]), (uvs[0], uvs[2], uvs[3]), shade)


def render_bedrock_model_icon(
    model_data: dict[str, Any],
    png_bytes: bytes,
    *,
    geometry_identifier: str,
    yaw: float = -16.0,
    pitch: float = -7.0,
    roll: float = -4.0,
) -> bytes:
    """Render an explicitly selected, unrotated Bedrock box-UV model."""

    if any(not math.isfinite(value) or abs(value) > 360 for value in (yaw, pitch, roll)):
        raise ValueError("Ungültige Kameradrehung für Bedrock-Modell.")
    texture = decode_png(png_bytes)
    cubes, texture_width, texture_height = _model_geometry(model_data, geometry_identifier)
    all_points = [point for cube in cubes for points, _uvs, _shade in _cube_faces(cube, texture_width, texture_height) for point in points]
    center = tuple((min(point[index] for point in all_points) + max(point[index] for point in all_points)) / 2 for index in range(3))
    transformed = [_rotate_model_point(point, center, yaw=yaw, pitch=pitch, roll=roll) for point in all_points]
    min_x, max_x = min(point[0] for point in transformed), max(point[0] for point in transformed)
    min_y, max_y = min(point[1] for point in transformed), max(point[1] for point in transformed)
    scale = min(48 / max(max_x - min_x, 1e-9), 48 / max(max_y - min_y, 1e-9))
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    def project(point: tuple[float, float, float]) -> tuple[float, float, float]:
        rotated_x, rotated_y, depth = _rotate_model_point(point, center, yaw=yaw, pitch=pitch, roll=roll)
        return 32 + (rotated_x - center_x) * scale, 32 - (rotated_y - center_y) * scale, depth

    canvas = bytearray(ICON_SIZE * ICON_SIZE * 4)
    depth_buffer = [math.inf] * (ICON_SIZE * ICON_SIZE)
    for cube in cubes:
        for points, uvs, shade in _cube_faces(cube, texture_width, texture_height):
            _draw_model_quad(canvas, depth_buffer, texture, [project(point) for point in points], uvs, shade)
    if not any(canvas[offset + 3] for offset in range(0, len(canvas), 4)):
        raise ValueError("Bedrock-Modell erzeugt keine sichtbaren Pixel.")
    return encode_rgba_png(ICON_SIZE, ICON_SIZE, bytes(canvas))


def render_block_icon(
    item_id: str,
    png_bytes: bytes,
    *,
    is_block_item: bool,
    top_png_bytes: bytes | None = None,
    front_png_bytes: bytes | None = None,
) -> tuple[bytes, str] | None:
    """Return ``(png, shape)`` when a source texture is safe to model-render."""

    shape = _shape_name(item_id)
    explicit_shape = shape not in {None, "cube"}
    if shape is None or (not is_block_item and not explicit_shape):
        return None
    texture = decode_png(png_bytes).first_square_frame()
    canvas = bytearray(ICON_SIZE * ICON_SIZE * 4)
    top_texture = decode_png(top_png_bytes).first_square_frame() if top_png_bytes else texture
    front_texture = decode_png(front_png_bytes).first_square_frame() if front_png_bytes else texture
    boxes = sorted(_cuboids(shape), key=lambda box: (box[0] + box[2], box[1]))
    project = _projection_for(boxes)
    for box in boxes:
        _draw_cuboid(canvas, texture, top_texture, front_texture, box, project)
    return encode_rgba_png(ICON_SIZE, ICON_SIZE, bytes(canvas)), shape
