"""Read-only Bedrock chunk/block probes for experimental mount placement.

This module intentionally uses small, conservative decoding steps.  It can find
candidate chunk/subchunk records and, for known paletted subchunk shapes, read
palette indexes and palette block names.  The first placement assessment checks
three blocks only: floor, feet and head.  A candidate is marked safe only when all
three block names are known, feet/head are air-like, and the floor is a confirmed
full-support cube (see ``is_confirmed_full_support_surface``).  Any block that is
not on that positive list stays "unchecked", never silently safe.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

SUBCHUNK_PREFIX_TAG = 0x2F
# Heightmap + biome records.  0x2B (Data3D) replaced 0x2D (Data2D) in 1.18; a
# modern world contains only 0x2B.
DATA_3D_TAG = 0x2B
DATA_2D_TAG = 0x2D
# Chunk version.  0x2C replaced 0x76 in 1.16.100; a modern world contains only
# 0x2C.  Probing 0x76/0x2D alone therefore never detects a present-day chunk.
CHUNK_VERSION_TAG = 0x2C
LEGACY_CHUNK_VERSION_TAG = 0x76
CHUNK_VERSION_TAGS = (CHUNK_VERSION_TAG, LEGACY_CHUNK_VERSION_TAG)
CHUNK_BIOME_TAGS = (DATA_3D_TAG, DATA_2D_TAG)
# How far generation got: 0 needs ticking, 1 needs population, 2 is finished.
# A chunk record can exist long before the terrain is complete, so only state 2
# licenses a confirmed-safe verdict or the "missing subchunk means air" inference.
FINALIZED_STATE_TAG = 0x36
CHUNK_FINALIZED_DONE = 2
KNOWN_SUBCHUNK_VERSIONS = frozenset({0, 1, 8, 9})
# Bedrock omits the subchunk record for a subchunk that is entirely air.  Inside
# a chunk whose generation is known to be finished, an absent record is therefore
# a definite answer ("air"), not missing data.
EMPTY_SUBCHUNK_BLOCK_NAME = "minecraft:air"
CHUNK_NOT_FINALIZED_PLACEMENT_MESSAGE = (
    "Chunk-Generierung ist nicht abgeschlossen oder nicht sicher nachweisbar; Position bleibt ungeprüft."
)
SUPPORTED_PALETTE_INDEX_BITS = frozenset({0, 1, 2, 3, 4, 5, 6, 8, 16})
BLOCKS_PER_SUBCHUNK = 16 * 16 * 16
MAX_PALETTE_ENTRIES_TO_DECODE = 8192
MAX_NBT_DEPTH = 12
MAX_NBT_LIST_ITEMS = 65_536

PASSABLE_SPACE_BLOCKS = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air"})
LIQUID_BLOCKS = frozenset({"minecraft:water", "minecraft:flowing_water", "minecraft:lava", "minecraft:flowing_lava"})

# Blocks whose collision top is not a plain full-height cube.  Their shape is
# known from the ID alone, and it is known to be wrong for standing on: a mount
# would sink, stand at a height the writer cannot compute, or slide off.  They
# are rejected outright.
PARTIAL_SUPPORT_SURFACE_SUFFIXES = ("_slab", "_stairs", "_wall", "_fence", "_fence_gate", "_carpet")
PARTIAL_SUPPORT_SURFACE_BLOCKS = frozenset(
    {
        "minecraft:anvil",
        "minecraft:bed",
        "minecraft:brewing_stand",
        "minecraft:chest",
        "minecraft:dirt_path",
        "minecraft:enchanting_table",
        "minecraft:end_portal_frame",
        "minecraft:farmland",
        "minecraft:hopper",
        # Mud has a lowered collision surface; entities sink slightly into it.
        # Treat it like every other non-full-height support surface instead of
        # confirming the normal block-top Y coordinate as safe.
        "minecraft:mud",
        "minecraft:soul_sand",
        "minecraft:trapped_chest",
    }
)

# Blocks whose collision shape depends on a block state this probe does not
# decode.  Unlike the list above, the ID alone does not say the surface is
# unusable -- a single snow layer is walked over, eight layers form a full cube,
# and a retracted piston is a solid block.  That is missing data, not a failed
# check, so these become "unchecked" (the user may confirm) rather than "unsafe"
# (rejected server-side).  They still never count as *confirmed* support.
STATE_DEPENDENT_SUPPORT_SURFACE_BLOCKS = frozenset(
    {
        # height=0..7 sits below the block top, height=8 is a full cube.
        "minecraft:snow_layer",
        # Der ausgefahrene Zustand verändert die Kollisionsform.
        "minecraft:piston",
        "minecraft:sticky_piston",
    }
)

# Positive list of blocks confirmed to expose a full-height, solid top surface a
# mount can stand on.  This is intentionally a *positive* list: anything not
# matched here is treated as "unchecked" (safe_to_place=None), never silently as
# safe.  A short negative list can never keep pace with the block catalogue, so
# torches, rails, ladders, trapdoors, pressure plates, buttons, cakes, cauldrons
# and every future non-cube block correctly stay unconfirmed instead of passing
# as solid ground.  The suffixes below cover only *closed* full-cube families in
# which every current and plausible future member is a solid cube.  Open suffixes
# are deliberately excluded: "_block" would let light_block and moving_block (no
# solid stand-on surface) and any future "*_block" ID pass, and "_stem" would let
# the passable pumpkin_stem/melon_stem crops pass.  Their genuine full-cube
# members (mineral/storage blocks, nether stems) are enumerated explicitly below
# so an unknown ID can never fail open through a suffix.
FULL_SUPPORT_SURFACE_SUFFIXES = (
    "_ore",
    "_planks",
    "_log",
    "_wood",
    "_hyphae",
    "_wool",
    "_concrete",
    "_terracotta",
    "_bricks",
)
FULL_SUPPORT_SURFACE_BLOCKS = frozenset(
    {
        # Natural stone and its polished/cut variants.
        "minecraft:stone",
        "minecraft:granite",
        "minecraft:polished_granite",
        "minecraft:diorite",
        "minecraft:polished_diorite",
        "minecraft:andesite",
        "minecraft:polished_andesite",
        "minecraft:deepslate",
        "minecraft:cobbled_deepslate",
        "minecraft:polished_deepslate",
        "minecraft:chiseled_deepslate",
        "minecraft:calcite",
        "minecraft:tuff",
        "minecraft:cobblestone",
        "minecraft:mossy_cobblestone",
        "minecraft:smooth_stone",
        "minecraft:stonebrick",
        "minecraft:blackstone",
        "minecraft:polished_blackstone",
        "minecraft:gilded_blackstone",
        "minecraft:basalt",
        "minecraft:smooth_basalt",
        "minecraft:polished_basalt",
        "minecraft:sandstone",
        "minecraft:smooth_sandstone",
        "minecraft:cut_sandstone",
        "minecraft:chiseled_sandstone",
        "minecraft:red_sandstone",
        "minecraft:smooth_red_sandstone",
        "minecraft:cut_red_sandstone",
        "minecraft:chiseled_red_sandstone",
        "minecraft:bedrock",
        "minecraft:obsidian",
        "minecraft:crying_obsidian",
        "minecraft:netherrack",
        "minecraft:soul_soil",
        "minecraft:end_stone",
        "minecraft:nether_brick",
        "minecraft:red_nether_brick",
        "minecraft:quartz_block",
        "minecraft:smooth_quartz",
        "minecraft:chiseled_quartz_block",
        "minecraft:quartz_pillar",
        "minecraft:purpur_block",
        "minecraft:purpur_pillar",
        "minecraft:prismarine",
        "minecraft:dark_prismarine",
        # Natural ground surfaces.
        "minecraft:dirt",
        "minecraft:coarse_dirt",
        "minecraft:rooted_dirt",
        "minecraft:grass_block",
        "minecraft:podzol",
        "minecraft:mycelium",
        "minecraft:packed_mud",
        "minecraft:clay",
        "minecraft:gravel",
        "minecraft:sand",
        "minecraft:red_sand",
        "minecraft:moss_block",
        "minecraft:pale_moss_block",
        "minecraft:sculk",
        "minecraft:dripstone_block",
        "minecraft:packed_ice",
        "minecraft:blue_ice",
        "minecraft:ice",
        "minecraft:snow",
        # Common light sources and utility/build blocks.
        "minecraft:glowstone",
        "minecraft:sea_lantern",
        "minecraft:shroomlight",
        "minecraft:redstone_lamp",
        "minecraft:crafting_table",
        "minecraft:cartography_table",
        "minecraft:fletching_table",
        "minecraft:smithing_table",
        "minecraft:loom",
        "minecraft:barrel",
        "minecraft:furnace",
        "minecraft:lit_furnace",
        "minecraft:blast_furnace",
        "minecraft:smoker",
        "minecraft:bookshelf",
        "minecraft:chiseled_bookshelf",
        "minecraft:dispenser",
        "minecraft:dropper",
        "minecraft:observer",
        "minecraft:noteblock",
        "minecraft:jukebox",
        "minecraft:tnt",
        "minecraft:target",
        "minecraft:lodestone",
        "minecraft:sponge",
        "minecraft:wet_sponge",
        "minecraft:melon_block",
        "minecraft:pumpkin",
        "minecraft:carved_pumpkin",
        "minecraft:lit_pumpkin",
        "minecraft:brick_block",
        "minecraft:mud_bricks",
        "minecraft:end_bricks",
        "minecraft:prismarine_bricks",
        "minecraft:quartz_bricks",
        "minecraft:command_block",
        "minecraft:repeating_command_block",
        "minecraft:chain_command_block",
        "minecraft:structure_block",
        "minecraft:barrier",
        # Mineral- und Lagerblöcke: früher pauschal über das offene Suffix
        # "_block" erfasst.  Das Suffix wurde entfernt (light_block/moving_block
        # sind keine tragfähige Fläche), daher die echten Vollwürfel explizit.
        "minecraft:iron_block",
        "minecraft:gold_block",
        "minecraft:diamond_block",
        "minecraft:emerald_block",
        "minecraft:netherite_block",
        "minecraft:coal_block",
        "minecraft:redstone_block",
        "minecraft:lapis_block",
        "minecraft:copper_block",
        "minecraft:raw_iron_block",
        "minecraft:raw_copper_block",
        "minecraft:raw_gold_block",
        "minecraft:hay_block",
        "minecraft:bone_block",
        "minecraft:dried_kelp_block",
        "minecraft:nether_wart_block",
        "minecraft:warped_wart_block",
        "minecraft:honeycomb_block",
        # Nether-Stämme: früher über das offene Suffix "_stem" erfasst, das aber
        # auch die passierbaren Pflanzen pumpkin_stem/melon_stem einschließt.
        "minecraft:crimson_stem",
        "minecraft:warped_stem",
        "minecraft:stripped_crimson_stem",
        "minecraft:stripped_warped_stem",
    }
)


def _is_vanilla_double_slab(block_name: str) -> bool:
    """Return True for Bedrock's full-height vanilla double-slab IDs."""

    if not block_name.startswith("minecraft:"):
        return False
    local_name = block_name.removeprefix("minecraft:")
    return local_name.endswith("_double_slab") or (local_name.startswith("double_") and "slab" in local_name)


def support_surface_requires_shape_data(block_name: str) -> bool:
    """True when the block's top surface is known not to be a full-height cube."""

    if _is_vanilla_double_slab(block_name):
        return False
    return block_name in PARTIAL_SUPPORT_SURFACE_BLOCKS or block_name.endswith(PARTIAL_SUPPORT_SURFACE_SUFFIXES)


def support_surface_shape_is_state_dependent(block_name: str) -> bool:
    """True when the block's shape hinges on a state this probe does not read.

    Callers must report these as unchecked, not unsafe: the answer is unknown
    rather than negative, so the decision belongs to the user.
    """

    return block_name in STATE_DEPENDENT_SUPPORT_SURFACE_BLOCKS


def is_confirmed_full_support_surface(block_name: str) -> bool:
    """True only for blocks confirmed to be a full solid cube a mount can stand on.

    Unknown blocks return False on purpose so callers treat them as unchecked
    rather than as safe ground.
    """

    if _is_vanilla_double_slab(block_name):
        return True
    if support_surface_requires_shape_data(block_name) or support_surface_shape_is_state_dependent(block_name):
        return False
    if block_name in FULL_SUPPORT_SURFACE_BLOCKS:
        return True
    # Suffix-Familien gelten ausschließlich für Vanilla-IDs. Add-on-Namespaces
    # dürfen frei definierte Geometrien/Kollisionen verwenden und bleiben daher
    # unabhängig von einem vertraut klingenden Namen immer ungeprüft.
    if not block_name.startswith("minecraft:"):
        return False
    return block_name.endswith(FULL_SUPPORT_SURFACE_SUFFIXES)


TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _chunk_coord(value: Any) -> int | None:
    number = _finite_float(value)
    if number is None:
        return None
    coord = math.floor(number / 16)
    if not -(2**31) <= coord < 2**31:
        return None
    return int(coord)


def _block_coord(value: Any) -> int | None:
    number = _finite_float(value)
    if number is None:
        return None
    coord = math.floor(number)
    if not -(2**31) <= coord < 2**31:
        return None
    return int(coord)


def _subchunk_y(value: Any) -> int | None:
    number = _finite_float(value)
    if number is None:
        return None
    coord = math.floor(number / 16)
    if not -128 <= coord <= 127:
        return None
    return int(coord)


def _chunk_key_bases(chunk_x: int, chunk_z: int, dimension_id: int | None) -> list[bytes]:
    base = chunk_x.to_bytes(4, "little", signed=True) + chunk_z.to_bytes(4, "little", signed=True)
    known_dimension = isinstance(dimension_id, int) and not isinstance(dimension_id, bool)
    if known_dimension and dimension_id != 0:
        # Nether/End chunk keys always carry the dimension component, and the
        # bare key is the *Overworld* chunk at the same coordinates.  Falling
        # back to it would answer a missing Nether chunk with Overworld terrain,
        # so a non-Overworld probe deliberately has no fallback: an absent record
        # stays "ungenerated" instead of silently describing another dimension.
        return [base + dimension_id.to_bytes(4, "little", signed=True)]
    bases = [base]
    if known_dimension:
        # Overworld.  Some tools/worlds tolerate an explicit dimension component
        # here, so probe it after the canonical no-dimension key.
        bases.append(base + dimension_id.to_bytes(4, "little", signed=True))
    return bases


def _chunk_finalized_state(db: Any, base: bytes) -> int | None:
    """Read Bedrock's FinalizedState, or None when it is absent or unreadable.

    None is deliberately *not* treated as "finished": worlds without the record
    cannot prove their terrain is complete, and this probe never promotes an
    unproven answer to a placeable one.
    """

    raw = _get_optional(db, base + bytes([FINALIZED_STATE_TAG]))
    if not isinstance(raw, bytes) or len(raw) < 4:
        return None
    return int.from_bytes(raw[:4], "little", signed=True)


def _get_optional(db: Any, key: bytes) -> bytes | None:
    try:
        value = db.get(key)
    except KeyError:
        return None
    if isinstance(value, bytes):
        return value
    return None


def _read_unsigned_varint(raw: bytes, offset: int) -> tuple[int | None, int]:
    value = 0
    shift = 0
    cursor = offset
    while cursor < len(raw) and shift <= 35:
        byte = raw[cursor]
        cursor += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, cursor
        shift += 7
    return None, offset


def _read_i32(raw: bytes, offset: int) -> tuple[int | None, int]:
    if offset + 4 > len(raw):
        return None, offset
    return int.from_bytes(raw[offset : offset + 4], "little", signed=True), offset + 4


def _read_u32(raw: bytes, offset: int) -> tuple[int | None, int]:
    if offset + 4 > len(raw):
        return None, offset
    return int.from_bytes(raw[offset : offset + 4], "little", signed=False), offset + 4


def _read_nbt_string(raw: bytes, offset: int) -> tuple[str | None, int]:
    if offset + 2 > len(raw):
        return None, offset
    length = int.from_bytes(raw[offset : offset + 2], "little", signed=False)
    start = offset + 2
    end = start + length
    if end > len(raw):
        return None, offset
    return raw[start:end].decode("utf-8", errors="replace"), end


def _local_block_coordinates(position: dict[str, Any]) -> dict[str, int] | None:
    block_x = _block_coord(position.get("x"))
    block_y = _block_coord(position.get("y"))
    block_z = _block_coord(position.get("z"))
    if block_x is None or block_y is None or block_z is None:
        return None
    return _local_block_coordinates_from_block(block_x, block_y, block_z)


def _local_block_coordinates_from_block(block_x: int, block_y: int, block_z: int) -> dict[str, int]:
    return {
        "block_x": block_x,
        "block_y": block_y,
        "block_z": block_z,
        "local_x": block_x & 0x0F,
        "local_y": block_y & 0x0F,
        "local_z": block_z & 0x0F,
    }


BEDROCK_SUBCHUNK_INDEX_ORDER = "bedrock_xzy"


def _subchunk_block_index(local_x: int, local_y: int, local_z: int) -> int:
    """Bedrock's block index inside a paletted subchunk.

    The 4096 indexes are stored in XZY order, so y varies fastest:
    ``index = (x << 8) | (z << 4) | y``.  This is a fixed property of the format,
    verified against real worlds two ways: decoding with this order reproduces
    the game's own heightmap (Data3D) exactly, and it is the only order under
    which terrain stays continuous across chunk borders.
    """

    return (local_x << 8) | (local_z << 4) | local_y


def _storage_word_shape(bits_per_block: int) -> tuple[int | None, int | None]:
    """Return blocks-per-word and word-count for Bedrock padded block storage.

    Bedrock packs indexes word by word.  When the bit width does not divide 32
    cleanly, unused padding bits at the end of each 32-bit word are skipped.
    Treating the storage as one continuous bitstream creates invalid palette
    indexes for widths such as 3, 5 or 6.
    """

    if bits_per_block == 0:
        return None, 0
    blocks_per_word = 32 // bits_per_block
    if blocks_per_word <= 0:
        return None, None
    word_count = math.ceil(BLOCKS_PER_SUBCHUNK / blocks_per_word)
    return blocks_per_word, word_count


def _skip_nbt_payload(raw: bytes, offset: int, tag_type: int, depth: int = 0) -> int | None:
    if depth > MAX_NBT_DEPTH:
        return None
    if tag_type == TAG_END:
        return offset
    if tag_type == TAG_BYTE:
        return offset + 1 if offset + 1 <= len(raw) else None
    if tag_type == TAG_SHORT:
        return offset + 2 if offset + 2 <= len(raw) else None
    if tag_type in (TAG_INT, TAG_FLOAT):
        return offset + 4 if offset + 4 <= len(raw) else None
    if tag_type in (TAG_LONG, TAG_DOUBLE):
        return offset + 8 if offset + 8 <= len(raw) else None
    if tag_type == TAG_STRING:
        _value, end = _read_nbt_string(raw, offset)
        return end if end != offset else None
    if tag_type == TAG_BYTE_ARRAY:
        length, cursor = _read_i32(raw, offset)
        if length is None or length < 0:
            return None
        end = cursor + length
        return end if end <= len(raw) else None
    if tag_type == TAG_LIST:
        if offset + 5 > len(raw):
            return None
        element_type = raw[offset]
        length, cursor = _read_i32(raw, offset + 1)
        if length is None or length < 0 or length > MAX_NBT_LIST_ITEMS:
            return None
        if element_type == TAG_END and length:
            return None
        for _ in range(length):
            next_cursor = _skip_nbt_payload(raw, cursor, element_type, depth + 1)
            if next_cursor is None or next_cursor <= cursor:
                return None
            cursor = next_cursor
        return cursor
    if tag_type == TAG_COMPOUND:
        parsed = _parse_nbt_compound_payload(raw, offset, depth + 1)
        return parsed[1] if parsed is not None else None
    if tag_type == TAG_INT_ARRAY:
        length, cursor = _read_i32(raw, offset)
        if length is None or length < 0:
            return None
        end = cursor + length * 4
        return end if end <= len(raw) else None
    if tag_type == TAG_LONG_ARRAY:
        length, cursor = _read_i32(raw, offset)
        if length is None or length < 0:
            return None
        end = cursor + length * 8
        return end if end <= len(raw) else None
    return None


def _parse_nbt_compound_payload(raw: bytes, offset: int, depth: int = 0) -> tuple[dict[str, Any], int] | None:
    if depth > MAX_NBT_DEPTH:
        return None
    cursor = offset
    values: dict[str, Any] = {}
    while cursor < len(raw):
        tag_type = raw[cursor]
        cursor += 1
        if tag_type == TAG_END:
            return values, cursor
        name, cursor_after_name = _read_nbt_string(raw, cursor)
        if name is None:
            return None
        cursor = cursor_after_name
        if tag_type == TAG_STRING:
            value, end = _read_nbt_string(raw, cursor)
            if value is None:
                return None
            values[name] = value
            cursor = end
            continue
        if tag_type == TAG_INT:
            value, end = _read_i32(raw, cursor)
            if value is None:
                return None
            values[name] = value
            cursor = end
            continue
        if tag_type == TAG_BYTE:
            if cursor + 1 > len(raw):
                return None
            values[name] = int.from_bytes(raw[cursor : cursor + 1], "little", signed=True)
            cursor += 1
            continue
        if tag_type == TAG_COMPOUND:
            nested = _parse_nbt_compound_payload(raw, cursor, depth + 1)
            if nested is None:
                return None
            nested_values, cursor = nested
            values[name] = nested_values
            continue
        end = _skip_nbt_payload(raw, cursor, tag_type, depth + 1)
        if end is None:
            return None
        cursor = end
    return None


def _block_name_from_values(values: dict[str, Any]) -> str | None:
    for key in ("name", "Name"):
        value = values.get(key)
        if isinstance(value, str):
            return value
    if len(values) == 1:
        nested = next(iter(values.values()))
        if isinstance(nested, dict):
            return _block_name_from_values(nested)
    return None


def _parse_palette_entry(raw: bytes, offset: int) -> dict[str, Any]:
    base = {
        "ok": False,
        "reason": "unsupported_palette_entry",
        "offset": offset,
        "end_offset": offset,
        "root_name": None,
        "block_name": None,
        "keys": [],
    }
    if offset >= len(raw):
        return {**base, "reason": "palette_entry_offset_out_of_range"}

    attempts: list[tuple[str, int, str | None]] = []
    if raw[offset] == TAG_COMPOUND:
        root_name, payload_offset = _read_nbt_string(raw, offset + 1)
        if root_name is not None:
            attempts.append(("named_compound", payload_offset, root_name))
    attempts.append(("raw_compound", offset, None))

    for encoding, payload_offset, root_name in attempts:
        parsed = _parse_nbt_compound_payload(raw, payload_offset, 0)
        if parsed is None:
            continue
        values, end_offset = parsed
        block_name = _block_name_from_values(values)
        return {
            "ok": True,
            "reason": "ok" if block_name else "block_name_missing",
            "encoding": encoding,
            "offset": offset,
            "end_offset": end_offset,
            "root_name": root_name,
            "block_name": block_name,
            "keys": sorted(str(key) for key in values),
        }
    return base


def _subchunk_storage_header_offset(raw: bytes) -> tuple[int | None, int | None, str | None]:
    if not raw:
        return None, None, "empty_payload"
    version = raw[0]
    if version == 8:
        if len(raw) < 3:
            return None, None, "truncated_subchunk_header"
        return 2, None, None
    if version == 9:
        if len(raw) < 4:
            return None, None, "truncated_subchunk_header"
        return 3, int.from_bytes(raw[2:3], "little", signed=True), None
    if version in (0, 1):
        if len(raw) < 2:
            return None, None, "truncated_subchunk_header"
        return 1, None, None
    return None, None, "unsupported_subchunk_version"


def describe_subchunk_payload(payload: bytes | None) -> dict[str, Any]:
    """Return conservative format hints for a Bedrock subchunk payload."""

    raw = payload or b""
    info: dict[str, Any] = {
        "payload_length": len(raw),
        "first_bytes_hex": raw[:16].hex(),
        "version": None,
        "known_version": False,
        "layer_count_candidate": None,
        "subchunk_y_index_candidate": None,
        "storage_header_offset_candidate": None,
        "format_hint": "empty" if not raw else "unknown",
    }
    if not raw:
        return info

    version = raw[0]
    info["version"] = version
    info["known_version"] = version in KNOWN_SUBCHUNK_VERSIONS

    if version in (8, 9):
        layer_count = raw[1] if len(raw) >= 2 else None
        storage_header_offset, subchunk_y_index, offset_error = _subchunk_storage_header_offset(raw)
        info["layer_count_candidate"] = layer_count
        info["subchunk_y_index_candidate"] = subchunk_y_index
        info["storage_header_offset_candidate"] = storage_header_offset
        info["format_hint"] = "paletted_subchunk_candidate"
        if layer_count is None or offset_error:
            info["format_hint"] = "paletted_subchunk_missing_layer_count"
        elif layer_count == 0 or layer_count > 8:
            info["format_hint"] = "paletted_subchunk_unusual_layer_count"
    elif version in (0, 1):
        storage_header_offset, _subchunk_y_index, _offset_error = _subchunk_storage_header_offset(raw)
        info["storage_header_offset_candidate"] = storage_header_offset
        info["format_hint"] = "legacy_subchunk_candidate"
    else:
        info["format_hint"] = "unknown_subchunk_version"
    return info


def _palette_count_candidates(raw: bytes, palette_offset: int) -> list[dict[str, int | str]]:
    candidates: list[dict[str, int | str]] = []
    seen: set[tuple[int, int]] = set()

    varint_count, varint_end = _read_unsigned_varint(raw, palette_offset)
    if isinstance(varint_count, int) and 0 <= varint_count <= MAX_PALETTE_ENTRIES_TO_DECODE:
        seen.add((varint_count, varint_end))
        candidates.append({"encoding": "varint", "count": varint_count, "end_offset": varint_end})

    int32_count, int32_end = _read_u32(raw, palette_offset)
    if isinstance(int32_count, int) and 0 <= int32_count <= MAX_PALETTE_ENTRIES_TO_DECODE and (int32_count, int32_end) not in seen:
        candidates.append({"encoding": "le_i32", "count": int32_count, "end_offset": int32_end})

    return candidates


def _decode_palette_entry_for_index(raw: bytes, palette_offset: int, palette_index: int) -> dict[str, Any]:
    """Decode the target palette entry using the most plausible count encoding.

    Real Bedrock subchunks may encode the palette count either as a varint or as
    a little-endian int32.  The first byte of an int32 count can itself be a
    plausible varint, so stopping at the first readable target can return a
    shifted, plausible-looking block name.  Score every candidate by how much of
    the palette parses successfully and prefer the strongest complete decode.
    """

    best: dict[str, Any] | None = None
    best_score: int | None = None
    for count_info in _palette_count_candidates(raw, palette_offset):
        palette_count = int(count_info["count"])
        cursor = int(count_info["end_offset"])
        encoding = str(count_info["encoding"])
        parsed_count = 0
        named_count = 0
        target_entry: dict[str, Any] | None = None
        last_entry: dict[str, Any] | None = None

        for entry_index in range(palette_count):
            entry = _parse_palette_entry(raw, cursor)
            if not entry.get("ok") or int(entry.get("end_offset") or cursor) <= cursor:
                break
            parsed_count += 1
            if entry.get("block_name"):
                named_count += 1
            if entry_index == palette_index:
                target_entry = entry
            last_entry = entry
            cursor = int(entry["end_offset"])

        parse_quality = {"parsed_count": parsed_count, "named_count": named_count}
        if palette_index >= palette_count:
            candidate = {
                "palette_count_candidate": palette_count,
                "palette_count_encoding": encoding,
                "palette_entry": {"ok": False, "reason": "palette_index_out_of_range"},
                "block_name": None,
                "palette_parse_quality": parse_quality,
            }
        elif target_entry is not None:
            candidate = {
                "palette_count_candidate": palette_count,
                "palette_count_encoding": encoding,
                "palette_entry": target_entry,
                "block_name": target_entry.get("block_name"),
                "palette_parse_quality": parse_quality,
            }
        else:
            candidate = {
                "palette_count_candidate": palette_count,
                "palette_count_encoding": encoding,
                "palette_entry": last_entry or {"ok": False, "reason": "palette_index_not_reached"},
                "block_name": None,
                "palette_parse_quality": parse_quality,
            }

        score = parsed_count * 2 + named_count * 8
        if candidate.get("block_name"):
            score += 100
        if target_entry is not None:
            score += 20
        if parsed_count < min(palette_count, palette_index + 1):
            score -= 50
        if best_score is None or score > best_score:
            best_score = score
            best = candidate

    return best or {
        "palette_count_candidate": None,
        "palette_count_encoding": None,
        "palette_entry": {"ok": False, "reason": "palette_count_missing"},
        "block_name": None,
        "palette_parse_quality": {"parsed_count": 0, "named_count": 0},
    }


def read_palette_index_from_subchunk(
    payload: bytes | None,
    local_x: int,
    local_y: int,
    local_z: int,
    *,
    layer: int = 0,
    block_index_func: Callable[[int, int, int], int] | None = None,
) -> dict[str, Any]:
    """Read one local block's palette index and block name from a paletted subchunk payload."""

    raw = payload or b""
    result: dict[str, Any] = {
        "ok": False,
        "reason": "empty_payload" if not raw else "unsupported",
        "version": raw[0] if raw else None,
        "layer": layer,
        "layer_count": None,
        "subchunk_y_index": None,
        "bits_per_block": None,
        "blocks_per_word": None,
        "storage_header": None,
        "word_count": None,
        "block_index": None,
        "palette_index": None,
        "palette_offset": None,
        "palette_count_candidate": None,
        "palette_count_encoding": None,
        "palette_entry": None,
        "palette_parse_quality": None,
        "block_name": None,
    }
    if not raw:
        return result
    if not all(0 <= value <= 15 for value in (local_x, local_y, local_z)):
        result["reason"] = "local_coordinate_out_of_range"
        return result
    version = raw[0]
    if version not in (8, 9):
        result["reason"] = "unsupported_subchunk_version"
        return result
    layer_count = raw[1] if len(raw) >= 2 else None
    result["layer_count"] = layer_count
    if layer != 0:
        result["reason"] = "only_layer_zero_supported"
        return result
    if layer_count is None or layer_count < 1:
        result["reason"] = "missing_block_storage_layer"
        return result

    storage_header_offset, subchunk_y_index, offset_error = _subchunk_storage_header_offset(raw)
    result["subchunk_y_index"] = subchunk_y_index
    if storage_header_offset is None:
        result["reason"] = offset_error or "truncated_subchunk_header"
        return result

    storage_header = raw[storage_header_offset]
    bits_per_block = storage_header >> 1
    result["storage_header"] = storage_header
    result["bits_per_block"] = bits_per_block
    if bits_per_block not in SUPPORTED_PALETTE_INDEX_BITS:
        result["reason"] = "unsupported_bits_per_block"
        return result

    blocks_per_word, word_count = _storage_word_shape(bits_per_block)
    if word_count is None:
        result["reason"] = "unsupported_bits_per_block"
        return result
    data_offset = storage_header_offset + 1
    palette_offset = data_offset + word_count * 4
    result["blocks_per_word"] = blocks_per_word
    result["word_count"] = word_count
    result["palette_offset"] = palette_offset
    if len(raw) < palette_offset:
        result["reason"] = "truncated_block_storage"
        return result

    block_index = (block_index_func or _subchunk_block_index)(local_x, local_y, local_z)
    result["block_index"] = block_index
    if bits_per_block == 0:
        palette_index = 0
    else:
        if not blocks_per_word:
            result["reason"] = "unsupported_bits_per_block"
            return result
        word_index = block_index // blocks_per_word
        bit_offset = (block_index % blocks_per_word) * bits_per_block
        word_offset = data_offset + word_index * 4
        if word_offset + 4 > len(raw):
            result["reason"] = "truncated_block_word"
            return result
        word = int.from_bytes(raw[word_offset : word_offset + 4], "little", signed=False)
        palette_index = (word >> bit_offset) & ((1 << bits_per_block) - 1)

    palette_result = _decode_palette_entry_for_index(raw, palette_offset, palette_index)
    result.update(
        {
            "ok": True,
            "reason": "ok",
            "palette_index": palette_index,
            "palette_count_candidate": palette_result.get("palette_count_candidate"),
            "palette_count_encoding": palette_result.get("palette_count_encoding"),
            "palette_entry": palette_result.get("palette_entry"),
            "palette_parse_quality": palette_result.get("palette_parse_quality"),
            "block_name": palette_result.get("block_name"),
        }
    )
    return result


def _probe_block_at(
    db: Any,
    block_x: int,
    block_y: int,
    block_z: int,
    dimension_id: int | None = None,
    *,
    block_index_func: Callable[[int, int, int], int] | None = None,
) -> dict[str, Any]:
    chunk_x = math.floor(block_x / 16)
    chunk_z = math.floor(block_z / 16)
    subchunk_y = math.floor(block_y / 16)
    local = _local_block_coordinates_from_block(block_x, block_y, block_z)
    result: dict[str, Any] = {
        "ok": False,
        "reason": "subchunk_missing",
        "block_x": block_x,
        "block_y": block_y,
        "block_z": block_z,
        "chunk_x": chunk_x,
        "chunk_z": chunk_z,
        "subchunk_y": subchunk_y,
        "local_x": local["local_x"],
        "local_y": local["local_y"],
        "local_z": local["local_z"],
        "chunk_key_found": False,
        "subchunk_key_found": False,
        "biome_key_found": False,
        "version_key_found": False,
        "chunk_generated": False,
        "chunk_finalized": None,
        "assumed_air": False,
        "subchunk_payload_length": None,
        "subchunk_format": None,
        "target_block": None,
        "block_name": None,
        "checked_key_count": 0,
    }
    if not -128 <= subchunk_y <= 127:
        result["reason"] = "subchunk_y_out_of_range"
        return result

    bases = _chunk_key_bases(chunk_x, chunk_z, dimension_id)
    for base in bases:
        subchunk_key = base + bytes([SUBCHUNK_PREFIX_TAG, subchunk_y & 0xFF])
        subchunk = _get_optional(db, subchunk_key)
        result["checked_key_count"] += 1
        if subchunk is None:
            continue

        subchunk_format = describe_subchunk_payload(subchunk)
        target_block = read_palette_index_from_subchunk(
            subchunk,
            local["local_x"],
            local["local_y"],
            local["local_z"],
            block_index_func=block_index_func,
        )
        block_name = target_block.get("block_name") if isinstance(target_block, dict) else None
        result["checked_key_count"] += 1
        chunk_finalized = _chunk_finalized_state(db, base)
        result.update(
            {
                "chunk_key_found": True,
                "chunk_generated": True,
                "chunk_finalized": chunk_finalized,
                "subchunk_key_found": True,
                "subchunk_payload_length": len(subchunk),
                "subchunk_format": subchunk_format,
                "target_block": target_block,
                "block_name": block_name,
            }
        )
        if block_name:
            result.update({"ok": True, "reason": "ok"})
        else:
            palette_entry = target_block.get("palette_entry") if isinstance(target_block, dict) else None
            if isinstance(palette_entry, dict) and palette_entry.get("reason"):
                reason = palette_entry.get("reason")
            elif isinstance(target_block, dict) and target_block.get("reason") and target_block.get("reason") != "ok":
                reason = target_block.get("reason")
            else:
                reason = "block_name_missing"
            result["reason"] = str(reason or "block_name_missing")
        return result

    # No subchunk record anywhere.  Only now is it worth asking whether the chunk
    # exists at all, because that answer decides between "air" and "no data".
    for base in bases:
        for tag in CHUNK_VERSION_TAGS:
            result["checked_key_count"] += 1
            if _get_optional(db, base + bytes([tag])) is not None:
                result["version_key_found"] = True
                break
        for tag in CHUNK_BIOME_TAGS:
            result["checked_key_count"] += 1
            if _get_optional(db, base + bytes([tag])) is not None:
                result["biome_key_found"] = True
                break
        if result["version_key_found"] or result["biome_key_found"]:
            result.update({"chunk_key_found": True, "chunk_generated": True})
            result["checked_key_count"] += 1
            result["chunk_finalized"] = _chunk_finalized_state(db, base)
            break

    if result["chunk_generated"] and result["chunk_finalized"] == CHUNK_FINALIZED_DONE:
        # Finished chunk, no subchunk record: Bedrock stores nothing for an
        # all-air subchunk, so this is a known block, not a gap in the data.
        result.update({"ok": True, "reason": "empty_subchunk_air", "assumed_air": True, "block_name": EMPTY_SUBCHUNK_BLOCK_NAME})
    elif result["chunk_generated"]:
        # Terrain population is unfinished or its state is unreadable, so an
        # absent subchunk does not prove air -- blocks may still be written.
        result["reason"] = "chunk_not_finalized"
    return result


def _assess_placement_blocks(blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    names = {role: block.get("block_name") for role, block in blocks.items()}
    missing = [role for role in ("floor", "feet", "head") if not names.get(role)]
    if missing:
        return {
            "status": "unchecked",
            "safe_to_place": None,
            "block_names": names,
            "message": f"Blocknamen konnten nicht vollständig gelesen werden ({', '.join(missing)}); Platzierung ist nicht sicher bestätigt.",
        }

    floor = str(names["floor"])
    feet = str(names["feet"])
    head = str(names["head"])
    if feet not in PASSABLE_SPACE_BLOCKS:
        return {
            "status": "unsafe",
            "safe_to_place": False,
            "block_names": names,
            "message": f"Fußraum ist blockiert durch {feet}; Pferd kann hier nicht sicher platziert werden.",
        }
    if head not in PASSABLE_SPACE_BLOCKS:
        return {
            "status": "unsafe",
            "safe_to_place": False,
            "block_names": names,
            "message": f"Kopfraum ist blockiert durch {head}; Pferd kann hier nicht sicher platziert werden.",
        }
    if floor in PASSABLE_SPACE_BLOCKS:
        return {
            "status": "unsafe",
            "safe_to_place": False,
            "block_names": names,
            "message": f"Bodenblock ist {floor}; Pferd hätte keinen tragfähigen Boden.",
        }
    if floor in LIQUID_BLOCKS:
        return {
            "status": "unsafe",
            "safe_to_place": False,
            "block_names": names,
            "message": f"Bodenblock ist Flüssigkeit ({floor}); Pferd kann hier nicht sicher platziert werden.",
        }
    if not is_confirmed_full_support_surface(floor):
        return {
            "status": "unchecked",
            "safe_to_place": None,
            "block_names": names,
            "message": f"Bodenblock {floor} ist kein bestätigter Vollblock; die Standfläche ist nicht sicher bestätigt.",
        }
    return {
        "status": "safe",
        "safe_to_place": True,
        "block_names": names,
        "message": f"Boden/Fuß-/Kopfraum geprüft: Boden {floor}, Fußraum {feet}, Kopfraum {head}.",
    }


def _probe_candidate_chunk_with_index_order(
    db: Any,
    position: dict[str, Any],
    dimension_id: int | None = None,
    *,
    block_index_func: Callable[[int, int, int], int],
) -> dict[str, Any]:
    """Probe one candidate with one explicit subchunk index ordering."""

    chunk_x = _chunk_coord(position.get("x"))
    chunk_z = _chunk_coord(position.get("z"))
    subchunk_y = _subchunk_y(position.get("y"))
    local = _local_block_coordinates(position)
    result: dict[str, Any] = {
        "block_check": "chunk_probe_missing",
        "safe_to_place": None,
        "chunk_x": chunk_x,
        "chunk_z": chunk_z,
        "subchunk_y": subchunk_y,
        "local_block": local,
        "chunk_key_found": False,
        "subchunk_key_found": False,
        "biome_key_found": False,
        "version_key_found": False,
        "chunk_generated": False,
        "chunk_finalized": None,
        "subchunk_payload_length": None,
        "subchunk_format": None,
        "target_block": None,
        "placement_check": None,
        "warning": "Chunk-/Subchunk-Daten wurden nicht gefunden oder noch nicht verstanden; Position ist nicht sicher bestätigt.",
    }
    if chunk_x is None or chunk_z is None or subchunk_y is None or local is None:
        result["block_check"] = "invalid_position"
        result["warning"] = "Kandidatenposition ist ungültig; Position ist nicht sicher bestätigbar."
        return result

    block_x = local["block_x"]
    block_y = local["block_y"]
    block_z = local["block_z"]
    blocks = {
        "floor": _probe_block_at(
            db,
            block_x,
            block_y - 1,
            block_z,
            dimension_id=dimension_id,
            block_index_func=block_index_func,
        ),
        "feet": _probe_block_at(
            db,
            block_x,
            block_y,
            block_z,
            dimension_id=dimension_id,
            block_index_func=block_index_func,
        ),
        "head": _probe_block_at(
            db,
            block_x,
            block_y + 1,
            block_z,
            dimension_id=dimension_id,
            block_index_func=block_index_func,
        ),
    }
    finalized_states = [block.get("chunk_finalized") for block in blocks.values()]
    if all(state == CHUNK_FINALIZED_DONE for state in finalized_states):
        chunk_finalized: int | None = CHUNK_FINALIZED_DONE
    else:
        chunk_finalized = next(
            (state for state in finalized_states if isinstance(state, int) and state != CHUNK_FINALIZED_DONE),
            None,
        )
    feet_probe = blocks["feet"]
    result.update(
        {
            "chunk_key_found": feet_probe.get("chunk_key_found", False),
            "subchunk_key_found": feet_probe.get("subchunk_key_found", False),
            "biome_key_found": feet_probe.get("biome_key_found", False),
            "version_key_found": feet_probe.get("version_key_found", False),
            "chunk_generated": any(block.get("chunk_generated") for block in blocks.values()),
            "chunk_finalized": chunk_finalized,
            "subchunk_payload_length": feet_probe.get("subchunk_payload_length"),
            "subchunk_format": feet_probe.get("subchunk_format"),
            "target_block": feet_probe.get("target_block"),
            "checked_key_count": sum(int(block.get("checked_key_count") or 0) for block in blocks.values()),
        }
    )
    # A block resolved as "empty subchunk inside a generated chunk" is as
    # determinate as one read from a stored palette.
    have_block_data = any(block.get("subchunk_key_found") or block.get("assumed_air") for block in blocks.values())
    if have_block_data:
        placement_check = _assess_placement_blocks(blocks)
        if placement_check.get("safe_to_place") is True and chunk_finalized != CHUNK_FINALIZED_DONE:
            placement_check = {
                **placement_check,
                "status": "unchecked",
                "safe_to_place": None,
                "reason": "chunk_not_finalized",
                "message": CHUNK_NOT_FINALIZED_PLACEMENT_MESSAGE,
            }
        result["block_check"] = "chunk_probe_found"
        result["placement_check"] = {**placement_check, "blocks": blocks}
        result["safe_to_place"] = placement_check.get("safe_to_place")
        result["warning"] = str(placement_check.get("message") or result["warning"])
    return result


# Alternative interpretations of the 4096-index array, kept so diagnostics and
# tests can decode a payload deliberately the wrong way.  They must never take
# part in a placement decision: choosing whichever order "looks" most placeable
# means every ambiguous read resolves towards `safe`, which measurably promoted
# positions inside solid rock to "safe" on real worlds.
PROBE_INDEX_ORDERS: tuple[tuple[str, Callable[[int, int, int], int]], ...] = (
    (BEDROCK_SUBCHUNK_INDEX_ORDER, _subchunk_block_index),
    ("legacy_yzx", lambda x, y, z: (y << 8) | (z << 4) | x),
    ("bedrock_zxy", lambda x, y, z: (z << 8) | (x << 4) | y),
    ("legacy_zyx", lambda x, y, z: (z << 8) | (y << 4) | x),
    ("bedrock_xyz", lambda x, y, z: (x << 8) | (y << 4) | z),
    ("legacy_yxz", lambda x, y, z: (y << 8) | (x << 4) | z),
)


def probe_index_order_func(order_name: str | None) -> Callable[[int, int, int], int] | None:
    """Resolve a diagnostic index-order name to its deterministic decoder."""

    for candidate_name, candidate_func in PROBE_INDEX_ORDERS:
        if candidate_name == order_name:
            return candidate_func
    return None


def probe_candidate_chunk(
    db: Any,
    position: dict[str, Any],
    dimension_id: int | None = None,
    *,
    block_index_func: Callable[[int, int, int], int] | None = None,
) -> dict[str, Any]:
    """Probe a candidate using Bedrock's fixed XZY subchunk index order.

    ``block_index_func`` overrides the decoder for diagnostics and tests only;
    it never changes which order production placement uses.
    """

    if block_index_func is not None:
        return _probe_candidate_chunk_with_index_order(
            db,
            position,
            dimension_id=dimension_id,
            block_index_func=block_index_func,
        )

    result = {
        **_probe_candidate_chunk_with_index_order(
            db,
            position,
            dimension_id=dimension_id,
            block_index_func=_subchunk_block_index,
        ),
        "probe_index_order": BEDROCK_SUBCHUNK_INDEX_ORDER,
    }
    placement = result.get("placement_check") if isinstance(result.get("placement_check"), dict) else None
    if placement is not None:
        result["placement_check"] = {**placement, "probe_index_order": BEDROCK_SUBCHUNK_INDEX_ORDER}
    return result


def annotate_preview_candidates_with_chunk_probe(db: Any, preview: dict[str, Any]) -> dict[str, Any]:
    candidates = preview.get("candidate_positions")
    if not isinstance(candidates, list):
        return preview
    dimension_id = preview.get("dimension_id") if isinstance(preview.get("dimension_id"), int) and not isinstance(preview.get("dimension_id"), bool) else None
    annotated_candidates: list[Any] = []
    found_count = 0
    format_hints: set[str] = set()
    target_read_count = 0
    target_block_names: set[str] = set()
    safe_count = 0
    unsafe_count = 0
    unchecked_count = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            annotated_candidates.append(candidate)
            continue
        probe = probe_candidate_chunk(db, candidate, dimension_id=dimension_id)
        if probe.get("block_check") == "chunk_probe_found":
            found_count += 1
        subchunk_format = probe.get("subchunk_format") if isinstance(probe.get("subchunk_format"), dict) else None
        if subchunk_format and subchunk_format.get("format_hint"):
            format_hints.add(str(subchunk_format["format_hint"]))
        target_block = probe.get("target_block") if isinstance(probe.get("target_block"), dict) else None
        if target_block and target_block.get("ok"):
            target_read_count += 1
        if target_block and target_block.get("block_name"):
            target_block_names.add(str(target_block["block_name"]))
        if probe.get("safe_to_place") is True:
            safe_count += 1
        elif probe.get("safe_to_place") is False:
            unsafe_count += 1
        else:
            unchecked_count += 1
        annotated = {
            **candidate,
            "block_check": probe.get("block_check"),
            "safe_to_place": probe.get("safe_to_place"),
            "warning": probe.get("warning"),
            "chunk_probe": probe,
        }
        annotated_candidates.append(annotated)

    placement_search = preview.get("placement_search") if isinstance(preview.get("placement_search"), dict) else {}
    return {
        **preview,
        "placement_search": {
            **placement_search,
            "block_check": "chunk_probe",
            "chunk_probe_found_count": found_count,
            "chunk_probe_candidate_count": len(annotated_candidates),
            "chunk_probe_format_hints": sorted(format_hints),
            "chunk_probe_target_read_count": target_read_count,
            "chunk_probe_target_block_names": sorted(target_block_names),
            "collision_check": "block_name_probe",
            "placement_safe_count": safe_count,
            "placement_unsafe_count": unsafe_count,
            "placement_unchecked_count": unchecked_count,
        },
        "candidate_positions": annotated_candidates,
    }
