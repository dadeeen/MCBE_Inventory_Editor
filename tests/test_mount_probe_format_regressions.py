"""Conservative mount placement for incomplete or unsupported terrain formats."""
from __future__ import annotations

import struct

import pytest

from mcbe_editor.mount_block_probe import (
    FINALIZED_STATE_TAG,
    SUBCHUNK_PREFIX_TAG,
    probe_candidate_chunk,
    read_palette_index_from_subchunk,
)
from mcbe_editor.mount_placement import _candidate_with_footprint_probe
from tests.test_mount_block_probe import (
    FakeDb,
    _block_palette_entry,
    _chunk_base,
    _named_compound_tag,
    _named_string_tag,
    _single_layer_payload_with_palette_indices,
)

BASE = _chunk_base(1, -19)
POSITION = {"x": 23.77, "y": 73.0, "z": -289.38}


def _uniform_payload(name: str, version: int, y: int = 4, prefix: bytes = b"") -> bytes:
    header = bytes([8, 1, 0]) if version == 8 else bytes([9, 1, y & 0xFF, 0])
    return header + prefix + _block_palette_entry(name)


def _floor_payload(version: int) -> bytes:
    return _single_layer_payload_with_palette_indices({(7, 8, 14)}, version=version, count_encoding="le_i32")


def _db(payload: bytes, subchunk_y: int = 4) -> FakeDb:
    return FakeDb({
        BASE + bytes([SUBCHUNK_PREFIX_TAG, subchunk_y & 0xFF]): payload,
        BASE + bytes([FINALIZED_STATE_TAG]): struct.pack("<i", 2),
    })


def _probe(db: FakeDb, mode: str, position=None):
    position = POSITION if position is None else position
    if mode == "footprint":
        return _candidate_with_footprint_probe(db, position, 0)
    return probe_candidate_chunk(db, position, dimension_id=0)


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("name", ["minecraft:air", "minecraft:stone", "minecraft:water"])
def test_zero_bit_storage_has_one_implicit_palette_entry(version, name):
    payload = _uniform_payload(name, version)
    for coords in ((0, 0, 0), (7, 9, 14), (15, 15, 15)):
        result = read_palette_index_from_subchunk(payload, *coords)
        assert result["block_name"] == name
        assert result["palette_count_candidate"] == 1
        assert result["palette_index"] == 0
        assert result["palette_entry"]["ok"] is True
        assert result["palette_parse_quality"] == {"parsed_count": 1, "named_count": 1}


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("prefix", [b"\x01", struct.pack("<I", 1)])
def test_existing_prefixed_singleton_compatibility_is_retained(version, prefix):
    result = read_palette_index_from_subchunk(_uniform_payload("minecraft:air", version, prefix=prefix), 7, 9, 14)
    assert result["block_name"] == "minecraft:air"
    assert result["palette_count_candidate"] == 1


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("mode", ["column", "footprint"])
def test_uniform_subchunks_allow_a_proven_clear_surface(version, mode):
    db = _db(_uniform_payload("minecraft:air", version))
    db.items[BASE + bytes([SUBCHUNK_PREFIX_TAG, 3])] = _uniform_payload("minecraft:stone", version, y=3)
    position = {**POSITION, "y": 64.0}
    assert _probe(db, mode, position)["safe_to_place"] is True


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("mode", ["column", "footprint"])
@pytest.mark.parametrize("extra_layer", ["missing", "water", "air"])
def test_unread_secondary_layers_cannot_be_confirmed_safe(version, mode, extra_layer):
    first = _floor_payload(version)
    payload = first[:1] + b"\x02" + first[2:]
    if extra_layer != "missing":
        # Real zero-bit secondary storage: header, then the sole NBT entry.
        payload += b"\x00" + _block_palette_entry("minecraft:" + extra_layer)
    result = _probe(_db(payload), mode)
    assert result["safe_to_place"] is None
    if mode == "column":
        assert result["target_block"]["reason"] == "additional_block_layers_unchecked"


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("mode", ["column", "footprint"])
def test_runtime_palette_flag_cannot_be_interpreted_as_persistent_nbt(version, mode):
    payload = bytearray(_floor_payload(version))
    payload[2 if version == 8 else 3] |= 1
    assert _probe(_db(bytes(payload)), mode)["safe_to_place"] is None


@pytest.mark.parametrize("subchunk_y", [-4, 4])
@pytest.mark.parametrize("mode", ["column", "footprint"])
def test_subchunk_key_and_version9_height_must_agree(subchunk_y, mode):
    payload = bytearray(_floor_payload(9))
    payload[2] = (subchunk_y + 1) & 0xFF
    position = {**POSITION, "y": float(subchunk_y * 16 + 9)}
    assert _probe(_db(bytes(payload), subchunk_y), mode, position)["safe_to_place"] is None


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("mode", ["column", "footprint"])
def test_truncated_unused_palette_entry_cannot_certify_a_safe_surface(version, mode):
    payload = _floor_payload(version)
    offset = (3 if version == 8 else 4) + 512
    payload = payload[:offset] + struct.pack("<I", 3) + payload[offset + 4:] + b"\x0a"
    assert _probe(_db(payload), mode)["safe_to_place"] is None


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("duplicate", ["name", "unused"])
def test_ambiguous_palette_compounds_do_not_silently_use_the_last_value(version, duplicate):
    if duplicate == "name":
        fields = _named_string_tag("name", "minecraft:water") + _named_string_tag("name", "minecraft:stone")
    else:
        fields = (_named_string_tag("name", "minecraft:stone")
                  + _named_string_tag("unused", "first") + _named_string_tag("unused", "last"))
    payload = _floor_payload(version).replace(_block_palette_entry("minecraft:stone"), _named_compound_tag("", fields))
    assert probe_candidate_chunk(_db(payload), POSITION, dimension_id=0)["safe_to_place"] is None


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("bits", [1, 2, 3, 4, 5, 6, 8, 16])
def test_supported_padded_storage_still_reads_each_target(version, bits):
    stones = {(0, 0, 0), (6, 0, 0), (7, 9, 14), (15, 15, 15)}
    payload = _single_layer_payload_with_palette_indices(stones, version=version, count_encoding="le_i32", bits_per_block=bits)
    for coords in (*sorted(stones), (1, 2, 3), (14, 15, 15)):
        result = read_palette_index_from_subchunk(payload, *coords)
        assert result["block_name"] == ("minecraft:stone" if coords in stones else "minecraft:air")
