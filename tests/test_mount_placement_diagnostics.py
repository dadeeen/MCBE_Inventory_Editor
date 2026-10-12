"""Placement explanations retain the actual failure across the full footprint."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from flask import Flask

from mcbe_editor import mount_api_routes
from mcbe_editor.mount_block_probe import CHUNK_VERSION_TAG, FINALIZED_STATE_TAG, SUBCHUNK_PREFIX_TAG, _assess_placement_blocks, probe_candidate_chunk
from mcbe_editor.mount_diagnostics import placement_issue
from mcbe_editor.mount_placement import _candidate_with_footprint_probe, placement_safety_from_preview, refine_preview_placement
from mcbe_editor.mounts import build_mount_preview
from tests.test_mount_block_probe import FakeDb, _block_palette_entry, _chunk_base, _single_layer_payload_with_palette_indices
from tests.test_mount_create_horse_profile_route import _deps, _preview

BASE = _chunk_base(0, 0)
POSITION = {"id": "east_2", "x": 8.5, "y": 65.0, "z": 8.5}


def _world(finalized=2, *, floor_y=0):
    records = {
        BASE + bytes([CHUNK_VERSION_TAG]): b"version",
        BASE + bytes([SUBCHUNK_PREFIX_TAG, 4]): _single_layer_payload_with_palette_indices({(x, floor_y, z) for x in range(16) for z in range(16)}),
    }
    if finalized is not None:
        records[BASE + bytes([FINALIZED_STATE_TAG])] = finalized if isinstance(finalized, bytes) else finalized.to_bytes(4, "little", signed=True)
    return records


def test_missing_chunk_keeps_individual_block_evidence():
    probe = probe_candidate_chunk(FakeDb(), POSITION, dimension_id=0)
    assert probe["safe_to_place"] is None
    assert {block["reason"] for block in probe["placement_check"]["blocks"].values()} == {"subchunk_missing"}


def test_out_of_range_position_explains_why_the_probe_cannot_start():
    result = _candidate_with_footprint_probe(FakeDb(), {**POSITION, "y": 3000.0}, 0)
    assert result["safe_to_place"] is None
    assert [issue["code"] for issue in result["placement_issues"]] == ["position_out_of_range"]


@pytest.mark.parametrize("missing", [False, True])
def test_full_direction_and_height_search_keeps_the_selected_failure_reason(missing):
    preview = build_mount_preview({"player": {"label": "Alex"}, "stats": {"pos": [8.5, 65.0, 8.5], "dimension_id": 0}}, "player")
    result = refine_preview_placement(FakeDb({} if missing else _world(0)), preview)
    selected = next(candidate for candidate in result["candidate_positions"] if candidate["id"] == result["selected_candidate_id"])
    assert selected["safe_to_place"] is None
    assert selected["placement_issues"][0]["code"] == ("chunk_data_missing" if missing else "generation_incomplete")
    assert placement_safety_from_preview(result)["message"] == selected["warning"]
    assert selected["radius_scan_attempts"][0]["warning"] == selected["warning"]


def test_only_missing_neighbor_is_named_when_center_is_readable():
    result = _candidate_with_footprint_probe(FakeDb(_world()), {**POSITION, "x": 15.5}, 0)
    assert result["safe_to_place"] is None
    (issue,) = result["placement_issues"]
    assert issue["code"] == "chunk_data_missing"
    assert issue["chunks"] == [{"x": 1, "z": 0}]
    assert issue["block_count"] == 9
    assert issue["sample_block"] == {"x": 16, "y": 64, "z": 7, "role": "floor"}
    assert result["warning"] == issue["message"]


@pytest.mark.parametrize(
    "finalized,code",
    [
        (0, "generation_incomplete"),
        (1, "generation_incomplete"),
        (None, "generation_unconfirmed"),
        (99, "generation_unconfirmed"),
        (b"\x02\0\0\0extra", "generation_unconfirmed"),
    ],
)
def test_present_chunk_is_not_misreported_as_missing(finalized, code):
    result = _candidate_with_footprint_probe(FakeDb(_world(finalized)), POSITION, 0)
    assert result["safe_to_place"] is None
    (issue,) = result["placement_issues"]
    assert issue["code"] == code
    assert issue["chunks"] == [{"x": 0, "z": 0}]


def test_missing_upper_subchunk_retains_unfinished_generation_cause():
    records = _world(0, floor_y=15)
    result = _candidate_with_footprint_probe(FakeDb(records), {**POSITION, "y": 80.0}, 0)
    assert [issue["code"] for issue in result["placement_issues"]] == ["generation_incomplete"]


@pytest.mark.parametrize(
    "payload,code",
    [(bytes([10, 1, 0]), "unsupported_block_format"), (bytes([8, 2, 0]), "additional_block_layers"), (bytes([8, 1, 2]), "block_data_unreadable")],
)
def test_unreadable_body_layer_above_head_has_its_own_location(payload, code):
    records = _world(floor_y=13)
    records[BASE + bytes([SUBCHUNK_PREFIX_TAG, 5])] = payload
    result = _candidate_with_footprint_probe(FakeDb(records), {**POSITION, "y": 78.0}, 0, clearance_blocks=3)
    assert result["safe_to_place"] is None
    (issue,) = result["placement_issues"]
    assert issue["code"] == code
    assert issue["sample_block"]["y"] == 80
    assert issue["sample_block"]["role"] == "body_2"
    assert issue["block_count"] == 9


def test_confirmed_placement_has_no_stale_diagnostics():
    result = _candidate_with_footprint_probe(FakeDb(_world()), {**POSITION, "placement_issues": [placement_issue("probe_failed")]}, 0)
    assert result["safe_to_place"] is True
    assert result["placement_issues"] == []


@pytest.mark.parametrize("floor,code", [("minecraft:snow_layer", "support_state_unknown"), ("addon:custom_block", "support_shape_unknown")])
def test_unconfirmed_ground_is_named_without_claiming_missing_chunks(floor, code):
    records = _world()
    key = BASE + bytes([SUBCHUNK_PREFIX_TAG, 4])
    records[key] = records[key].replace(_block_palette_entry("minecraft:stone"), _block_palette_entry(floor))
    result = _candidate_with_footprint_probe(FakeDb(records), POSITION, 0)
    assert result["safe_to_place"] is None
    (issue,) = result["placement_issues"]
    assert issue["code"] == code
    assert floor in issue["message"]


def test_missing_chunk_coordinates_are_floored_on_negative_side_of_boundary():
    result = _candidate_with_footprint_probe(FakeDb(_world()), {**POSITION, "x": -0.5}, 0)
    (issue,) = result["placement_issues"]
    assert issue["code"] == "chunk_data_missing"
    assert issue["chunks"] == [{"x": -1, "z": 0}]


@pytest.mark.parametrize("role,block", [("feet", "minecraft:stone"), ("head", "minecraft:stone"), ("floor", "minecraft:water")])
def test_known_collision_is_not_hidden_by_other_missing_blocks(role, block):
    result = _assess_placement_blocks({"floor": {}, "feet": {}, "head": {}, role: {"block_name": block}})
    assert result["safe_to_place"] is False


@pytest.mark.parametrize("phase", ["open", "read", "close"])
def test_optional_probe_failure_is_explained_logged_and_never_leaks_exception(monkeypatch, phase):
    logged = []

    def fail():
        raise OSError("private-world-path must not appear in the UI")

    db = SimpleNamespace(close=fail if phase == "close" else lambda: None)
    service = SimpleNamespace(_open_db_readonly=lambda _path: fail() if phase == "open" else db)
    deps = replace(_deps(), service=service, log_api_exception=lambda label, exc: logged.append((label, exc)))
    monkeypatch.setattr(mount_api_routes, "refine_preview_placement", lambda _db, preview: fail() if phase == "read" else preview)
    result = mount_api_routes._annotate_preview_with_chunk_probe(deps, "world", _preview())
    (candidate,) = result["candidate_positions"]
    assert candidate["safe_to_place"] is None
    assert candidate["placement_issues"][0]["code"] == "probe_failed"
    assert "private-world-path" not in str(result)
    assert len(logged) == 1
    assert result["placement_search"]["placement_safe_count"] == 0


def test_diagnostic_messages_follow_request_language():
    with Flask(__name__).test_request_context(headers={"Accept-Language": "en"}):
        issue = placement_issue("chunk_data_missing")
        assert issue["message"].startswith("Chunk data is missing")
        assert issue["hint"].startswith("Load the area")
