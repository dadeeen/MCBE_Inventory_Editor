from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from mcbe_editor.mount_block_probe import (
    CHUNK_VERSION_TAG,
    DATA_2D_TAG,
    DATA_3D_TAG,
    FINALIZED_STATE_TAG,
    PROBE_INDEX_ORDERS,
    SUBCHUNK_PREFIX_TAG,
    TAG_LIST,
    _assess_placement_blocks,
    _skip_nbt_payload,
    annotate_preview_candidates_with_chunk_probe,
    describe_subchunk_payload,
    is_confirmed_full_support_surface,
    probe_candidate_chunk,
    read_palette_index_from_subchunk,
)
from mcbe_editor.mount_placement import _candidate_with_footprint_probe, _footprint_assessment, _reassess_candidate_space
from mcbe_editor.mounts import build_mount_preview


class FakeDb:
    def __init__(self, items=None) -> None:
        self.items = dict(items or {})

    def get(self, key: bytes) -> bytes:
        if key not in self.items:
            raise KeyError(key)
        return self.items[key]


def _chunk_base(chunk_x: int, chunk_z: int) -> bytes:
    return chunk_x.to_bytes(4, "little", signed=True) + chunk_z.to_bytes(4, "little", signed=True)


def _block_index(local_x: int, local_y: int, local_z: int) -> int:
    """Bedrock's real XZY subchunk index order, as used by every fixture here."""

    return (local_x << 8) | (local_z << 4) | local_y


def _nbt_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return len(raw).to_bytes(2, "little") + raw


def _named_string_tag(name: str, value: str) -> bytes:
    return bytes([8]) + _nbt_string(name) + _nbt_string(value)


def _named_int_tag(name: str, value: int) -> bytes:
    return bytes([3]) + _nbt_string(name) + int(value).to_bytes(4, "little", signed=True)


def _named_compound_tag(name: str, payload: bytes = b"") -> bytes:
    return bytes([10]) + _nbt_string(name) + payload + bytes([0])


def _block_palette_entry(block_name: str) -> bytes:
    payload = _named_string_tag("name", block_name) + _named_int_tag("version", 18165760) + _named_compound_tag("states")
    return _named_compound_tag("", payload)


def _palette_count(count: int, encoding: str = "varint") -> bytes:
    if encoding == "le_i32":
        return count.to_bytes(4, "little", signed=False)
    return bytes([count])


def _word_count(bits_per_block: int) -> int:
    blocks_per_word = 32 // bits_per_block
    return (4096 + blocks_per_word - 1) // blocks_per_word


def _single_layer_payload_with_palette_indices(
    stone_blocks: set[tuple[int, int, int]],
    *,
    count_encoding: str = "varint",
    version: int = 8,
    subchunk_y_index: int = 4,
    bits_per_block: int = 1,
    block_index_func=_block_index,
) -> bytes:
    header = bits_per_block << 1
    blocks_per_word = 32 // bits_per_block
    words = [0] * _word_count(bits_per_block)
    mask = (1 << bits_per_block) - 1
    for local_x, local_y, local_z in stone_blocks:
        index = block_index_func(local_x, local_y, local_z)
        word_index = index // blocks_per_word
        bit_offset = (index % blocks_per_word) * bits_per_block
        words[word_index] |= (1 & mask) << bit_offset
    packed = b"".join(word.to_bytes(4, "little") for word in words)
    palette = _palette_count(2, count_encoding) + _block_palette_entry("minecraft:air") + _block_palette_entry("minecraft:stone")
    if version == 9:
        return bytes([9, 1, subchunk_y_index & 0xFF, header]) + packed + palette
    return bytes([8, 1, header]) + packed + palette


def _single_layer_payload_with_palette_index(
    local_x: int,
    local_y: int,
    local_z: int,
    palette_index: int,
    *,
    count_encoding: str = "varint",
    version: int = 8,
    bits_per_block: int = 1,
) -> bytes:
    stones = {(local_x, local_y, local_z)} if palette_index else set()
    return _single_layer_payload_with_palette_indices(stones, count_encoding=count_encoding, version=version, bits_per_block=bits_per_block)


def test_describe_subchunk_payload_reports_paletted_candidate_shape() -> None:
    info = describe_subchunk_payload(bytes([8, 1, 0x10, 0x20, 0x30]))

    assert info == {
        "payload_length": 5,
        "first_bytes_hex": "0801102030",
        "version": 8,
        "known_version": True,
        "layer_count_candidate": 1,
        "subchunk_y_index_candidate": None,
        "storage_header_offset_candidate": 2,
        "format_hint": "paletted_subchunk_candidate",
    }


def test_describe_subchunk_payload_reports_version9_y_index() -> None:
    info = describe_subchunk_payload(bytes([9, 1, 0xFC, 0x10, 0x20, 0x30]))

    assert info["version"] == 9
    assert info["known_version"] is True
    assert info["layer_count_candidate"] == 1
    assert info["subchunk_y_index_candidate"] == -4
    assert info["storage_header_offset_candidate"] == 3
    assert info["format_hint"] == "paletted_subchunk_candidate"


def test_describe_subchunk_payload_reports_unknown_version() -> None:
    info = describe_subchunk_payload(bytes([42, 1, 2, 3]))

    assert info["version"] == 42
    assert info["known_version"] is False
    assert info["format_hint"] == "unknown_subchunk_version"
    assert info["layer_count_candidate"] is None


def test_skip_nbt_list_rejects_non_progressing_end_elements() -> None:
    raw = bytes([0]) + (2_147_483_647).to_bytes(4, "little", signed=True)

    assert _skip_nbt_payload(raw, 0, TAG_LIST) is None


def test_skip_nbt_list_rejects_unreasonably_large_container() -> None:
    raw = bytes([1]) + (65_537).to_bytes(4, "little", signed=True) + b"\x00"

    assert _skip_nbt_payload(raw, 0, TAG_LIST) is None


def test_read_palette_index_from_subchunk_reads_single_target_index_and_block_name() -> None:
    payload = _single_layer_payload_with_palette_index(7, 9, 14, 1)

    target = read_palette_index_from_subchunk(payload, 7, 9, 14)

    assert target["ok"] is True
    assert target["reason"] == "ok"
    assert target["version"] == 8
    assert target["layer_count"] == 1
    assert target["subchunk_y_index"] is None
    assert target["bits_per_block"] == 1
    assert target["blocks_per_word"] == 32
    assert target["block_index"] == _block_index(7, 9, 14)
    assert target["palette_index"] == 1
    assert target["palette_offset"] == 515
    assert target["palette_count_candidate"] == 2
    assert target["palette_count_encoding"] == "varint"
    assert target["block_name"] == "minecraft:stone"
    assert target["palette_entry"]["ok"] is True
    assert target["palette_entry"]["block_name"] == "minecraft:stone"
    assert target["palette_entry"]["keys"] == ["name", "states", "version"]
    assert target["palette_parse_quality"] == {"parsed_count": 2, "named_count": 2}


def test_read_palette_index_from_subchunk_uses_padded_words_for_width_five() -> None:
    payload = _single_layer_payload_with_palette_index(6, 0, 0, 1, bits_per_block=5)

    target = read_palette_index_from_subchunk(payload, 6, 0, 0)

    assert target["ok"] is True
    assert target["reason"] == "ok"
    assert target["bits_per_block"] == 5
    assert target["blocks_per_word"] == 6
    assert target["word_count"] == 683
    assert target["block_index"] == _block_index(6, 0, 0)
    assert target["palette_index"] == 1
    assert target["palette_offset"] == 2735
    assert target["block_name"] == "minecraft:stone"


def test_read_palette_index_from_subchunk_reads_int32_palette_count() -> None:
    payload = _single_layer_payload_with_palette_index(7, 9, 14, 1, count_encoding="le_i32")

    target = read_palette_index_from_subchunk(payload, 7, 9, 14)

    assert target["ok"] is True
    assert target["reason"] == "ok"
    assert target["palette_index"] == 1
    assert target["palette_count_candidate"] == 2
    assert target["palette_count_encoding"] == "le_i32"
    assert target["block_name"] == "minecraft:stone"
    assert target["palette_entry"]["ok"] is True
    assert target["palette_parse_quality"] == {"parsed_count": 2, "named_count": 2}


def test_read_palette_index_from_subchunk_reads_version9_with_y_index() -> None:
    payload = _single_layer_payload_with_palette_index(7, 9, 14, 1, version=9)

    target = read_palette_index_from_subchunk(payload, 7, 9, 14)

    assert target["ok"] is True
    assert target["version"] == 9
    assert target["subchunk_y_index"] == 4
    assert target["bits_per_block"] == 1
    assert target["palette_index"] == 1
    assert target["palette_offset"] == 516
    assert target["block_name"] == "minecraft:stone"


def test_read_palette_index_uses_request_local_index_order_without_global_race() -> None:
    coords = (1, 2, 3)

    def legacy_yzx(x: int, y: int, z: int) -> int:
        return (y << 8) | (z << 4) | x

    def bedrock_xzy(x: int, y: int, z: int) -> int:
        return (x << 8) | (z << 4) | y

    legacy_payload = _single_layer_payload_with_palette_indices({coords}, block_index_func=legacy_yzx)
    bedrock_payload = _single_layer_payload_with_palette_indices({coords}, block_index_func=bedrock_xzy)

    def read_legacy() -> str | None:
        return read_palette_index_from_subchunk(
            legacy_payload,
            *coords,
            block_index_func=legacy_yzx,
        )["block_name"]

    def read_bedrock() -> str | None:
        return read_palette_index_from_subchunk(
            bedrock_payload,
            *coords,
            block_index_func=bedrock_xzy,
        )["block_name"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read_legacy if index % 2 == 0 else read_bedrock) for index in range(200)]

    assert [future.result() for future in futures] == ["minecraft:stone"] * len(futures)


def test_read_palette_index_from_subchunk_reports_unsupported_version() -> None:
    target = read_palette_index_from_subchunk(bytes([42, 1, 2, 3]), 0, 0, 0)

    assert target["ok"] is False
    assert target["reason"] == "unsupported_subchunk_version"
    assert target["version"] == 42


def test_probe_candidate_chunk_marks_blocked_feet_unsafe() -> None:
    # Position x=23.77/z=-289.38 is chunk 1/-19. Y=73 is subchunk 4 and local y=9.
    base = _chunk_base(1, -19)
    payload = _single_layer_payload_with_palette_index(7, 9, 14, 1)
    db = FakeDb({base + bytes([SUBCHUNK_PREFIX_TAG, 4]): payload})

    probe = probe_candidate_chunk(
        db,
        {"x": 23.77, "y": 73.0, "z": -289.38},
        dimension_id=0,
        block_index_func=_block_index,
    )

    assert probe["block_check"] == "chunk_probe_found"
    assert probe["chunk_key_found"] is True
    assert probe["subchunk_key_found"] is True
    assert probe["chunk_x"] == 1
    assert probe["chunk_z"] == -19
    assert probe["subchunk_y"] == 4
    assert probe["local_block"] == {"block_x": 23, "block_y": 73, "block_z": -290, "local_x": 7, "local_y": 9, "local_z": 14}
    assert probe["subchunk_payload_length"] == len(payload)
    assert probe["subchunk_format"]["format_hint"] == "paletted_subchunk_candidate"
    assert probe["subchunk_format"]["version"] == 8
    assert probe["target_block"]["ok"] is True
    assert probe["target_block"]["palette_index"] == 1
    assert probe["target_block"]["block_name"] == "minecraft:stone"
    assert probe["safe_to_place"] is False
    assert probe["placement_check"]["status"] == "unsafe"
    assert probe["placement_check"]["block_names"] == {"floor": "minecraft:air", "feet": "minecraft:stone", "head": "minecraft:air"}
    assert "Fußraum" in probe["warning"]


def test_probe_candidate_chunk_marks_clear_space_over_support_safe() -> None:
    base = _chunk_base(1, -19)
    payload = _single_layer_payload_with_palette_indices({(7, 8, 14)})
    db = FakeDb(
        {
            base + bytes([SUBCHUNK_PREFIX_TAG, 4]): payload,
            base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
        }
    )

    probe = probe_candidate_chunk(db, {"x": 23.77, "y": 73.0, "z": -289.38}, dimension_id=0)

    assert probe["block_check"] == "chunk_probe_found"
    assert probe["safe_to_place"] is True
    assert probe["target_block"]["block_name"] == "minecraft:air"
    assert probe["placement_check"]["status"] == "safe"
    assert probe["placement_check"]["block_names"] == {"floor": "minecraft:stone", "feet": "minecraft:air", "head": "minecraft:air"}
    assert probe["probe_index_order"] == "bedrock_xzy"
    assert probe["placement_check"]["probe_index_order"] == "bedrock_xzy"
    assert "Boden/Fuß-/Kopfraum geprüft" in probe["warning"]


def test_candidate_footprint_allows_edge_overhang_when_center_is_supported() -> None:
    base = _chunk_base(1, -19)
    payload = _single_layer_payload_with_palette_indices({(7, 8, 14)})
    db = FakeDb(
        {
            base + bytes([SUBCHUNK_PREFIX_TAG, 4]): payload,
            base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
        }
    )

    candidate = {"id": "test", "x": 23.77, "y": 73.0, "z": -289.38, "offset": {"x": 0, "y": 0, "z": 0}}
    probed = _candidate_with_footprint_probe(db, candidate, dimension_id=0)

    assert probed["block_check"] == "footprint_probe"
    assert probed["safe_to_place"] is True
    assert probed["chunk_probe"]["footprint_check"]["column_count"] == 6
    assert probed["chunk_probe"]["footprint_check"]["edge_overhang_count"] >= 1
    assert "Körperraum frei" in probed["warning"]


def test_candidate_footprint_reads_both_chunks_at_boundary() -> None:
    left_base = _chunk_base(0, 0)
    right_base = _chunk_base(1, 0)
    left_floor = {(15, 0, local_z) for local_z in (7, 8, 9)}
    right_floor = {(0, 0, local_z) for local_z in (7, 8, 9)}
    db = FakeDb(
        {
            left_base + bytes([SUBCHUNK_PREFIX_TAG, 4]): _single_layer_payload_with_palette_indices(left_floor),
            right_base + bytes([SUBCHUNK_PREFIX_TAG, 4]): _single_layer_payload_with_palette_indices(right_floor),
            left_base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
            right_base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
        }
    )
    candidate = {"id": "chunk_boundary", "x": 15.8, "y": 65.0, "z": 8.5, "offset": {"x": 0, "y": 0, "z": 0}}

    probed = _candidate_with_footprint_probe(db, candidate, dimension_id=0)
    columns = probed["chunk_probe"]["footprint_check"]["columns"]

    assert probed["safe_to_place"] is True
    assert probed["chunk_probe"]["footprint_check"]["column_count"] == 6
    assert {column["block_x"] for column in columns} == {15, 16}
    assert all(column["block_names"]["floor"] == "minecraft:stone" for column in columns)


def test_candidate_footprint_requires_every_touched_chunk_to_be_finalized() -> None:
    left_base = _chunk_base(0, 0)
    right_base = _chunk_base(1, 0)
    left_floor = {(15, 0, local_z) for local_z in (7, 8, 9)}
    right_floor = {(0, 0, local_z) for local_z in (7, 8, 9)}
    db = FakeDb(
        {
            left_base + bytes([SUBCHUNK_PREFIX_TAG, 4]): _single_layer_payload_with_palette_indices(left_floor),
            right_base + bytes([SUBCHUNK_PREFIX_TAG, 4]): _single_layer_payload_with_palette_indices(right_floor),
            left_base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
            right_base + bytes([FINALIZED_STATE_TAG]): _finalized(0),
        }
    )
    candidate = {"id": "chunk_boundary", "x": 15.8, "y": 65.0, "z": 8.5, "offset": {"x": 0, "y": 0, "z": 0}}

    probed = _candidate_with_footprint_probe(db, candidate, dimension_id=0)
    footprint = probed["chunk_probe"]["footprint_check"]

    assert probed["safe_to_place"] is None
    assert footprint["all_chunks_finalized"] is False
    assert {column["chunk_finalized"] for column in footprint["columns"]} == {0, 2}


def test_candidate_footprint_does_not_mark_boundary_safe_when_neighbor_chunk_is_missing() -> None:
    left_base = _chunk_base(0, 0)
    left_floor = {(15, 0, local_z) for local_z in (7, 8, 9)}
    db = FakeDb(
        {
            left_base + bytes([SUBCHUNK_PREFIX_TAG, 4]): _single_layer_payload_with_palette_indices(left_floor),
            left_base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
        }
    )
    candidate = {"id": "chunk_boundary", "x": 15.8, "y": 65.0, "z": 8.5, "offset": {"x": 0, "y": 0, "z": 0}}

    probed = _candidate_with_footprint_probe(db, candidate, dimension_id=0)

    assert probed["safe_to_place"] is None
    assert probed["chunk_probe"]["footprint_check"]["status"] == "unchecked"
    assert "nicht vollständig gelesen" in probed["warning"]


def test_candidate_footprint_rejects_side_head_block() -> None:
    base = _chunk_base(1, -19)
    payload = _single_layer_payload_with_palette_indices({(7, 8, 14), (8, 10, 14)})
    db = FakeDb({base + bytes([SUBCHUNK_PREFIX_TAG, 4]): payload})

    candidate = {"id": "test", "x": 23.77, "y": 73.0, "z": -289.38, "offset": {"x": 0, "y": 0, "z": 0}}
    probed = _candidate_with_footprint_probe(db, candidate, dimension_id=0)

    assert probed["block_check"] == "footprint_probe"
    assert probed["safe_to_place"] is False
    assert probed["chunk_probe"]["probe_index_order"] == "bedrock_xzy"
    assert probed["chunk_probe"]["footprint_check"]["column_count"] == 6
    assert "Footprint-Kopfraum" in probed["warning"]


def test_camel_footprint_checks_third_body_block() -> None:
    base = _chunk_base(1, -19)
    payload = _single_layer_payload_with_palette_indices({(7, 8, 14), (7, 11, 14)})
    db = FakeDb({base + bytes([SUBCHUNK_PREFIX_TAG, 4]): payload})
    candidate = {"id": "test", "x": 23.5, "y": 73.0, "z": -289.5, "offset": {"x": 0, "y": 0, "z": 0}}

    probed = _candidate_with_footprint_probe(db, candidate, dimension_id=0, half_width=0.85, clearance_blocks=3)

    assert probed["safe_to_place"] is False
    assert probed["chunk_probe"]["footprint_check"]["clearance_blocks"] == 3
    center = next(column for column in probed["chunk_probe"]["footprint_check"]["columns"] if column["center"])
    assert center["block_names"]["body_2"] == "minecraft:stone"
    assert "Körperraum" in probed["warning"]


def test_footprint_rejects_partial_height_support_without_shape_data() -> None:
    columns = [
        {
            "block_x": 1,
            "block_z": 2,
            "center": True,
            "block_names": {"floor": "minecraft:oak_slab", "feet": "minecraft:air", "head": "minecraft:air"},
        }
    ]

    result = _footprint_assessment(columns)

    assert result["safe_to_place"] is False
    assert "keine bestätigte Vollblock-Oberfläche" in result["message"]


def test_is_confirmed_full_support_surface_uses_positive_list_not_negative_list() -> None:
    # Confirmed full cubes: explicit terrain, plus large suffix families.
    assert is_confirmed_full_support_surface("minecraft:stone")
    assert is_confirmed_full_support_surface("minecraft:grass_block")
    assert is_confirmed_full_support_surface("minecraft:iron_block")
    assert is_confirmed_full_support_surface("minecraft:oak_planks")
    assert is_confirmed_full_support_surface("minecraft:deepslate_gold_ore")
    assert is_confirmed_full_support_surface("minecraft:white_wool")
    assert is_confirmed_full_support_surface("minecraft:oak_double_slab")
    assert is_confirmed_full_support_surface("minecraft:double_stone_block_slab")
    # Namespaced add-on blocks may define arbitrary geometry/collision and must
    # never inherit a Vanilla full-cube classification from their suffix.
    assert not is_confirmed_full_support_surface("addon:paper_planks")
    assert not is_confirmed_full_support_surface("custom:ghost_ore")
    assert not is_confirmed_full_support_surface("addon:oak_double_slab")
    # Non-cube blocks that a short negative list would have missed must NOT pass.
    for non_cube in (
        "minecraft:torch",
        "minecraft:rail",
        "minecraft:ladder",
        "minecraft:oak_trapdoor",
        "minecraft:stone_pressure_plate",
        "minecraft:cake",
        "minecraft:cauldron",
        "minecraft:piston",
        "minecraft:sticky_piston",
        "minecraft:mud",
        "minecraft:oak_slab",
        "minecraft:cobblestone_wall",
        "minecraft:some_future_block_we_have_not_seen",
    ):
        assert not is_confirmed_full_support_surface(non_cube), non_cube


def test_footprint_marks_unknown_non_full_block_center_unchecked() -> None:
    # A block that is neither air/liquid nor on the partial-height list used to
    # "fail open" as safe ground.  It must now stay unchecked, not safe.
    columns = [
        {
            "block_x": 1,
            "block_z": 2,
            "center": True,
            "block_names": {"floor": "minecraft:cauldron", "feet": "minecraft:air", "head": "minecraft:air"},
        }
    ]

    result = _footprint_assessment(columns)

    assert result["safe_to_place"] is None
    assert result["status"] == "unchecked"
    assert "kein bestätigter Vollblock" in result["message"]


def test_footprint_keeps_confirmed_full_block_center_safe() -> None:
    columns = [
        {
            "block_x": 1,
            "block_z": 2,
            "center": True,
            "block_names": {"floor": "minecraft:iron_block", "feet": "minecraft:air", "head": "minecraft:air"},
        }
    ]

    result = _footprint_assessment(columns)

    assert result["safe_to_place"] is True
    assert result["status"] == "safe"


def test_assess_placement_blocks_marks_unknown_floor_unchecked() -> None:
    # First-stage assessment must no longer fail open for a named non-cube floor.
    result = _assess_placement_blocks(
        {
            "floor": {"block_name": "minecraft:torch"},
            "feet": {"block_name": "minecraft:air"},
            "head": {"block_name": "minecraft:air"},
        }
    )

    assert result["safe_to_place"] is None
    assert result["status"] == "unchecked"
    assert "kein bestätigter Vollblock" in result["message"]


def test_assess_placement_blocks_keeps_confirmed_cube_floor_safe() -> None:
    result = _assess_placement_blocks(
        {
            "floor": {"block_name": "minecraft:stone"},
            "feet": {"block_name": "minecraft:air"},
            "head": {"block_name": "minecraft:air"},
        }
    )

    assert result["safe_to_place"] is True
    assert result["status"] == "safe"


def test_probe_candidate_chunk_reports_missing_subchunk_without_marking_safe() -> None:
    probe = probe_candidate_chunk(FakeDb(), {"x": 23.77, "y": 73.0, "z": -289.38}, dimension_id=0)

    assert probe["block_check"] == "chunk_probe_missing"
    assert probe["chunk_key_found"] is False
    assert probe["subchunk_key_found"] is False
    assert probe["subchunk_format"] is None
    assert probe["target_block"] is None
    assert probe["safe_to_place"] is None
    assert "nicht sicher" in probe["warning"]


def test_generated_chunk_without_subchunk_is_air_and_therefore_unsupported() -> None:
    """Bedrock omits an all-air subchunk, so this is a known answer, not a gap."""

    base = _chunk_base(1, -19)
    db = FakeDb({base + bytes([DATA_2D_TAG]): b"height-and-biome-data", base + bytes([FINALIZED_STATE_TAG]): _finalized(2)})

    probe = probe_candidate_chunk(db, {"x": 23.77, "y": 73.0, "z": -289.38}, dimension_id=0)

    assert probe["block_check"] == "chunk_probe_found"
    assert probe["chunk_key_found"] is True
    assert probe["biome_key_found"] is True
    assert probe["chunk_generated"] is True
    assert probe["subchunk_key_found"] is False
    assert probe["placement_check"]["block_names"] == {
        "floor": "minecraft:air",
        "feet": "minecraft:air",
        "head": "minecraft:air",
    }
    # Mid-air is not "unknown" -- it is a definite lack of ground.
    assert probe["safe_to_place"] is False


def _finalized(state: int) -> bytes:
    return state.to_bytes(4, "little", signed=True)


def test_missing_subchunk_only_means_air_inside_a_finalized_chunk() -> None:
    """A chunk record exists long before terrain generation is complete.

    FinalizedState 0/1 mean the chunk still needs ticking or population, so an
    absent subchunk does not prove air -- blocks may still be written there.
    """

    base = _chunk_base(1, -19)
    position = {"x": 23.77, "y": 73.0, "z": -289.38}

    for state in (0, 1):
        db = FakeDb({base + bytes([CHUNK_VERSION_TAG]): b"chunk-record", base + bytes([FINALIZED_STATE_TAG]): _finalized(state)})

        probe = probe_candidate_chunk(db, position, dimension_id=0)

        assert probe["chunk_generated"] is True, state
        assert probe["chunk_finalized"] == state
        assert probe["safe_to_place"] is None, f"FinalizedState {state} darf keine Aussage erlauben"
        assert probe["block_check"] == "chunk_probe_missing", state

    done = FakeDb({base + bytes([CHUNK_VERSION_TAG]): b"chunk-record", base + bytes([FINALIZED_STATE_TAG]): _finalized(2)})
    finished = probe_candidate_chunk(done, position, dimension_id=0)
    assert finished["chunk_finalized"] == 2
    assert finished["safe_to_place"] is False, "fertiger Chunk ohne Subchunk ist Luft, also kein Boden"

    # Kein FinalizedState-Eintrag: unbewiesen, also nicht als fertig behandeln.
    without = FakeDb({base + bytes([CHUNK_VERSION_TAG]): b"chunk-record"})
    unknown = probe_candidate_chunk(without, position, dimension_id=0)
    assert unknown["chunk_finalized"] is None
    assert unknown["safe_to_place"] is None


def test_unfinalized_chunk_cannot_reach_safe_through_the_footprint() -> None:
    """Die gemeldete Reproduktion: Boden vorhanden, Subchunk darüber fehlt."""

    base = _chunk_base(1, -19)
    floor_payload = _single_layer_payload_with_palette_indices({(x, 15, z) for x in range(16) for z in range(16)})
    records = {
        base + bytes([CHUNK_VERSION_TAG]): b"chunk-record",
        # Boden bei Y=79 vorhanden, Subchunk ab Y=80 fehlt.
        base + bytes([SUBCHUNK_PREFIX_TAG, 4]): floor_payload,
    }

    candidate = {"x": 23.5, "y": 80.0, "z": -289.5}
    unfinished = probe_candidate_chunk(FakeDb({**records, base + bytes([FINALIZED_STATE_TAG]): _finalized(0)}), candidate, dimension_id=0)
    assert unfinished["safe_to_place"] is not True, "unfertiger Chunk wurde als sicher gemeldet"

    footprint = _candidate_with_footprint_probe(
        FakeDb({**records, base + bytes([FINALIZED_STATE_TAG]): _finalized(0)}), {"id": "c", **candidate}, dimension_id=0
    )
    assert footprint.get("safe_to_place") is not True, "Footprint wurde im unfertigen Chunk als sicher gemeldet"

    # Auch vollständig lesbare Blöcke dürfen einen unfertigen Chunk nicht zu
    # "safe" hochstufen: Population kann diese Blöcke beim nächsten Laden noch
    # verändern. Die frühere Korrektur prüfte FinalizedState nur dann, wenn der
    # Subchunk fehlte, und übersah genau diesen Pfad.
    readable_payload = _single_layer_payload_with_palette_indices({(7, 8, 14)})
    readable_records = {
        base + bytes([SUBCHUNK_PREFIX_TAG, 4]): readable_payload,
        base + bytes([CHUNK_VERSION_TAG]): b"chunk-record",
        base + bytes([FINALIZED_STATE_TAG]): _finalized(0),
    }
    readable_candidate = {"x": 23.77, "y": 73.0, "z": -289.38}

    direct = probe_candidate_chunk(FakeDb(readable_records), readable_candidate, dimension_id=0)
    assert direct["chunk_finalized"] == 0
    assert direct["safe_to_place"] is None
    assert direct["placement_check"]["reason"] == "chunk_not_finalized"

    readable_footprint = _candidate_with_footprint_probe(
        FakeDb(readable_records), {"id": "readable", **readable_candidate}, dimension_id=0
    )
    assert readable_footprint["safe_to_place"] is None
    assert readable_footprint["chunk_probe"]["footprint_check"]["all_chunks_finalized"] is False


def test_modern_chunk_version_and_data3d_tags_are_recognised() -> None:
    for tag in (CHUNK_VERSION_TAG, DATA_3D_TAG):
        base = _chunk_base(1, -19)
        db = FakeDb({base + bytes([tag]): b"chunk-record", base + bytes([FINALIZED_STATE_TAG]): _finalized(2)})

        probe = probe_candidate_chunk(db, {"x": 23.77, "y": 73.0, "z": -289.38}, dimension_id=0)

        assert probe["chunk_generated"] is True, f"tag 0x{tag:02x} must mark the chunk as generated"
        assert probe["safe_to_place"] is False


def test_ungenerated_chunk_stays_unchecked_instead_of_assuming_air() -> None:
    probe = probe_candidate_chunk(FakeDb(), {"x": 23.77, "y": 73.0, "z": -289.38}, dimension_id=0)

    assert probe["chunk_generated"] is False
    assert probe["block_check"] == "chunk_probe_missing"
    assert probe["safe_to_place"] is None


def test_non_overworld_probe_never_falls_back_to_the_overworld_chunk() -> None:
    """The bare chunk key is the Overworld chunk at the same coordinates.

    Falling back to it would answer a missing Nether chunk with Overworld
    terrain, i.e. a confident verdict about the wrong dimension.
    """

    overworld_only = FakeDb({_chunk_base(1, -19) + bytes([CHUNK_VERSION_TAG]): b"chunk-record"})
    position = {"x": 23.77, "y": 73.0, "z": -289.38}

    nether = probe_candidate_chunk(overworld_only, position, dimension_id=1)
    assert nether["chunk_generated"] is False
    assert nether["safe_to_place"] is None

    # The same coordinates in the Overworld still resolve normally.
    assert probe_candidate_chunk(overworld_only, position, dimension_id=0)["chunk_generated"] is True

    # A real Nether chunk carries the dimension component and is found.
    nether_db = FakeDb({_chunk_base(1, -19) + (1).to_bytes(4, "little", signed=True) + bytes([CHUNK_VERSION_TAG]): b"chunk-record"})
    assert probe_candidate_chunk(nether_db, position, dimension_id=1)["chunk_generated"] is True


def test_state_dependent_floor_is_unchecked_rather_than_rejected() -> None:
    """Snow depth and piston extension decide whether the block carries.

    The probe does not read block states, so the honest answer is "unknown"
    (the user may confirm), not "unsafe" (rejected server-side).
    """

    for floor in ("minecraft:snow_layer", "minecraft:piston", "minecraft:sticky_piston"):
        columns = [
            {
                "block_x": 1,
                "block_z": 2,
                "center": True,
                "block_names": {"floor": floor, "feet": "minecraft:air", "head": "minecraft:air"},
            }
        ]

        footprint = _footprint_assessment(columns)
        assert footprint["safe_to_place"] is None, floor
        assert footprint["status"] == "unchecked", floor
        assert "Blockzustand" in footprint["message"], floor

        reassessed = _reassess_candidate_space(
            {"chunk_probe": {"placement_check": {"block_names": {"floor": floor, "feet": "minecraft:air", "head": "minecraft:air"}}}}
        )
        assert reassessed["chunk_probe"]["placement_check"]["status"] == "unchecked", floor
        assert reassessed["safe_to_place"] is None, floor

        # Still never confirmed support: it cannot silently become safe ground.
        assert not is_confirmed_full_support_surface(floor), floor

    # A genuinely partial shape stays a hard rejection.
    slab = _footprint_assessment(
        [
            {
                "block_x": 1,
                "block_z": 2,
                "center": True,
                "block_names": {"floor": "minecraft:oak_slab", "feet": "minecraft:air", "head": "minecraft:air"},
            }
        ]
    )
    assert slab["safe_to_place"] is False


def test_state_dependent_block_at_a_footprint_edge_counts_as_tolerated_overhang() -> None:
    columns = [
        {"block_x": 1, "block_z": 2, "center": True, "block_names": {"floor": "minecraft:stone", "feet": "minecraft:air", "head": "minecraft:air"}},
        {"block_x": 2, "block_z": 2, "center": False, "block_names": {"floor": "minecraft:snow_layer", "feet": "minecraft:air", "head": "minecraft:air"}},
    ]

    result = _footprint_assessment(columns)

    assert result["safe_to_place"] is True
    assert result["edge_overhang_count"] == 1


def test_placement_never_uses_an_alternative_index_order_to_reach_safe() -> None:
    """A payload written in a non-Bedrock order must not decode into a safe spot.

    This is the regression that matters: scoring six orderings and keeping the
    most placeable-looking one reported positions inside solid rock as `safe`.
    """

    # Distinct local x/y/z, so the six orderings really do address different blocks.
    local_x, floor_y, local_z = 3, 8, 14
    for order_name, order_func in PROBE_INDEX_ORDERS:
        if order_name == "bedrock_xzy":
            continue
        # Ground under the feet, free space above -- but encoded the wrong way.
        payload = _single_layer_payload_with_palette_indices(
            {(local_x, floor_y, local_z)},
            block_index_func=order_func,
        )
        db = FakeDb({_chunk_base(1, -19) + bytes([SUBCHUNK_PREFIX_TAG, 4]): payload})

        probe = probe_candidate_chunk(db, {"x": 19.5, "y": 73.0, "z": -289.5}, dimension_id=0)

        assert probe["probe_index_order"] == "bedrock_xzy"
        assert probe["safe_to_place"] is not True, f"{order_name} payload must not decode into a safe placement"


def test_annotate_preview_candidates_with_chunk_probe_adds_probe_summary() -> None:
    preview = build_mount_preview(
        {"player": {"label": "Alex"}, "stats": {"pos": [17.77, 74.62, -289.38], "dimension_id": 0, "rotation": [-90.0, 0.0]}},
        "player-key",
        placement_radius=6,
    )
    selected = preview["selected_position"]
    chunk_x = int(selected["x"] // 16)
    chunk_z = -19
    subchunk_y = int(selected["y"] // 16)
    local_x = int(selected["x"] // 1) & 0x0F
    local_y = int(selected["y"] // 1) & 0x0F
    local_z = int(selected["z"] // 1) & 0x0F
    base = _chunk_base(chunk_x, chunk_z)
    payload = _single_layer_payload_with_palette_indices({(local_x, local_y - 1, local_z)})
    db = FakeDb(
        {
            base + bytes([SUBCHUNK_PREFIX_TAG, subchunk_y & 0xFF]): payload,
            base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
        }
    )

    annotated = annotate_preview_candidates_with_chunk_probe(db, preview)
    first = annotated["candidate_positions"][0]
    found_candidates = [candidate for candidate in annotated["candidate_positions"] if candidate.get("block_check") == "chunk_probe_found"]
    target_names = annotated["placement_search"]["chunk_probe_target_block_names"]

    assert annotated["placement_search"]["block_check"] == "chunk_probe"
    assert annotated["placement_search"]["chunk_probe_candidate_count"] == len(preview["candidate_positions"])
    assert annotated["placement_search"]["chunk_probe_found_count"] == len(found_candidates)
    assert annotated["placement_search"]["chunk_probe_found_count"] >= 1
    assert annotated["placement_search"]["chunk_probe_format_hints"] == ["paletted_subchunk_candidate"]
    assert annotated["placement_search"]["chunk_probe_target_read_count"] >= 1
    assert annotated["placement_search"]["placement_safe_count"] >= 1
    assert annotated["placement_search"]["placement_unsafe_count"] >= 1
    assert target_names == ["minecraft:air"]
    assert first["block_check"] == "chunk_probe_found"
    assert first["safe_to_place"] is True
    assert first["chunk_probe"]["subchunk_key_found"] is True
    assert first["chunk_probe"]["subchunk_format"]["layer_count_candidate"] == 1
    assert first["chunk_probe"]["target_block"]["ok"] is True
    assert first["chunk_probe"]["target_block"]["block_name"] == "minecraft:air"
    assert first["chunk_probe"]["probe_index_order"] == "bedrock_xzy"
    assert first["chunk_probe"]["placement_check"]["status"] == "safe"
