"""Placement must inspect the grid columns overlapped by the stored collision box."""

from __future__ import annotations

import pytest

from mcbe_editor import mount_placement
from mcbe_editor.mounts import mount_collision_width
from tests.test_mount_block_probe import (
    FINALIZED_STATE_TAG,
    SUBCHUNK_PREFIX_TAG,
    FakeDb,
    _chunk_base,
    _finalized,
    _single_layer_payload_with_palette_indices,
)


@pytest.mark.parametrize(
    ("x", "z", "expected_x", "expected_z", "center"),
    [
        (8.0, 8.0, {7, 8}, {7, 8}, (8, 8)),
        (8.0, 8.5, {7, 8}, {7, 8, 9}, (8, 8)),
        (8.5, 8.0, {7, 8, 9}, {7, 8}, (8, 8)),
        (8.5, 8.5, {7, 8, 9}, {7, 8, 9}, (8, 8)),
        (-8.5, -8.0, {-10, -9, -8}, {-9, -8}, (-9, -8)),
        (-0.5, -0.5, {-2, -1, 0}, {-2, -1, 0}, (-1, -1)),
    ],
)
def test_footprint_follows_position_instead_of_a_fixed_grid(x, z, expected_x, expected_z, center) -> None:
    columns = mount_placement._candidate_footprint_columns({"x": x, "y": 65.0, "z": z}, half_width=0.7)

    assert {(column["block_x"], column["block_z"]) for column in columns} == {(block_x, block_z) for block_x in expected_x for block_z in expected_z}
    assert [(column["block_x"], column["block_z"]) for column in columns if column["center"]] == [center]


def test_default_footprint_uses_the_same_horse_width_as_live_placement() -> None:
    # This position exposes the former 0.75 default, which unnecessarily read x=9.
    candidate = {"x": 8.27, "y": 65.0, "z": 8.5}
    columns = mount_placement._candidate_footprint_columns(candidate)

    assert {column["block_x"] for column in columns} == {7, 8}
    assert columns == mount_placement._candidate_footprint_columns(candidate, half_width=mount_collision_width("minecraft:horse") / 2)


@pytest.mark.parametrize(
    ("x", "chunk_x", "safe_to_place"),
    [(15.25, 0, True), (15.251, 0, None), (-16.75, -2, True), (-16.749, -2, None)],
)
def test_footprint_requires_neighbor_chunk_only_when_box_overlaps_it(x, chunk_x, safe_to_place) -> None:
    base = _chunk_base(chunk_x, 0)
    floor = {(local_x, 0, local_z) for local_x in (14, 15) for local_z in (7, 8)}
    db = FakeDb(
        {
            base + bytes([SUBCHUNK_PREFIX_TAG, 4]): _single_layer_payload_with_palette_indices(floor),
            base + bytes([FINALIZED_STATE_TAG]): _finalized(2),
        }
    )
    # Use an exactly representable half-width and Float32 position to distinguish
    # touching a block face from even a small real overlap after serialization.
    candidate = {"id": "edge", "x": x, "y": 65.0, "z": 8.25}
    result = mount_placement._candidate_with_footprint_probe(db, candidate, 0, half_width=0.75)

    assert result["safe_to_place"] is safe_to_place
    footprint = result["chunk_probe"]["footprint_check"]
    assert footprint["column_count"] == (4 if safe_to_place else 6)
    assert footprint["all_chunks_finalized"] is (safe_to_place is True)


@pytest.mark.parametrize(
    ("mount_type", "safe_to_place", "column_count", "clearance_blocks"),
    [
        ("minecraft:horse", True, 6, 2),
        ("minecraft:donkey", True, 6, 2),
        ("minecraft:mule", True, 6, 2),
        ("minecraft:skeleton_horse", True, 6, 2),
        ("minecraft:camel", False, 9, 3),
    ],
)
def test_selected_mount_size_controls_the_actual_block_probe(monkeypatch, mount_type, safe_to_place, column_count, clearance_blocks) -> None:
    base = _chunk_base(0, 0)
    floor = {(local_x, 0, local_z) for local_x in range(7, 10) for local_z in range(7, 10)}
    # The side obstacle lies outside a horse's box but inside a camel's box.
    payload = _single_layer_payload_with_palette_indices(floor | {(9, 1, 8)})
    db = FakeDb({base + bytes([SUBCHUNK_PREFIX_TAG, 4]): payload, base + bytes([FINALIZED_STATE_TAG]): _finalized(2)})
    monkeypatch.setattr(mount_placement, "VERTICAL_PLACEMENT_Y_OFFSETS", (0,))
    preview = {
        "mount_type": mount_type,
        "dimension_id": 0,
        "placement_search": {"radius": 2},
        "candidate_positions": [{"id": "east_2", "x": 8.2, "y": 65.0, "z": 8.5, "offset": {"x": 2, "y": 0, "z": 0}}],
    }

    result = mount_placement._adjust_vertical_placement_candidates(db, preview)
    candidate = result["candidate_positions"][0]

    assert candidate["safe_to_place"] is safe_to_place
    assert candidate["chunk_probe"]["footprint_check"]["column_count"] == column_count
    assert candidate["chunk_probe"]["footprint_check"]["clearance_blocks"] == clearance_blocks
