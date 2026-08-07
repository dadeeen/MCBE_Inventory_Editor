from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from flask import Flask

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.bedrock_nbt import save_player_nbt
from mcbe_editor.mount_api_routes import MountRouteDeps, _preview_from_request
from mcbe_editor.mount_placement import _distance_candidates, placement_safety_from_preview
from mcbe_editor.mounts import (
    MIN_PLACEMENT_RADIUS,
    build_mount_preview,
    horizontal_block_offset,
    mount_type_options,
    normalize_mount_type,
)
from mcbe_editor.players import encode_player_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _player_snapshot(pos=None, dimension_id=0, rotation=None):
    stats = {"pos": pos or [10.5, 64.0, -20.25]}
    if dimension_id is not None:
        stats["dimension_id"] = dimension_id
    if rotation is not None:
        stats["rotation"] = rotation
    return {
        "player": {"label": "Alex"},
        "stats": stats,
    }


class _FakeMountDb:
    def __init__(self, player_key: bytes, player_bytes: bytes) -> None:
        self.player_key = player_key
        self.player_bytes = player_bytes
        self.closed = False

    def get(self, key: bytes) -> bytes:
        if key != self.player_key:
            raise KeyError(key)
        return self.player_bytes

    def close(self) -> None:
        self.closed = True


class _FakeMountService:
    def __init__(self, player_key: bytes, player_bytes: bytes) -> None:
        self.player_key = player_key
        self.player_bytes = player_bytes

    def load_player(self, _world_path: str, _encoded_player_key: str):
        return _player_snapshot([0.0, 70.0, 0.0])

    def _open_db_readonly(self, _world_path: str):
        return _FakeMountDb(self.player_key, self.player_bytes)

    def _read_player(self, db, player_key: bytes):
        return db.get(player_key)


def _mount_route_deps(service) -> MountRouteDeps:
    return MountRouteDeps(
        service=service,
        jsonify=lambda value: value,
        api_error=lambda value, _status=400: value,
        log_api_exception=lambda _label, _exc: None,
        json_string=lambda data, key, default=None: str(data.get(key, default)),
        require_world_db_access_allowed=lambda: None,
        audit_event=lambda *_args, **_kwargs: None,
        server_online_epoch=lambda: 123,
    )


def test_mount_preview_uses_player_position_as_reference_and_places_mount_at_feet() -> None:
    preview = build_mount_preview(_player_snapshot(), "player-key")

    assert preview["success"] is True
    assert preview["mount_type"] == "minecraft:horse"
    assert preview["mount_label"] == "Pferd"
    assert preview["player_reference"] == {"player_key": "player-key", "player_label": "Alex"}
    assert preview["player_position"] == {"x": 10.5, "y": 64.0, "z": -20.25}
    assert preview["placement_search"]["radius"] == 6
    assert preview["placement_search"]["candidate_count"] == 4
    assert preview["placement_search"]["block_check"] == "not_implemented"
    assert preview["placement_search"]["search_shape"] == "four_direction_lines"
    assert preview["placement_search"]["full_area_scan"] is False
    assert preview["placement_search"]["radius_scan_min_distance"] == 2
    assert preview["placement_search"]["radius_scan_max_distance"] == 6
    assert preview["selected_candidate_id"] == "east_6"
    assert preview["selected_position"] == {"x": 16.5, "y": 62.38, "z": -20.25}
    assert preview["candidate_positions"][0]["offset"] == {"x": 6.0, "y": 0.0, "z": 0.0}
    assert [candidate["id"] for candidate in preview["candidate_positions"]] == ["east_6", "west_6", "south_6", "north_6"]
    assert preview["candidate_positions"][0]["safe_to_place"] is None
    assert any("minus 1,62" in warning and "eingerastet" in warning for warning in preview["warnings"])
    assert any("kein vollständiger Flächenscan" in warning for warning in preview["warnings"])
    assert preview["can_create"] is True
    assert preview["create_available"] is True


def test_mount_preview_localizes_display_payload_for_english_request() -> None:
    app = Flask(__name__)

    with app.test_request_context(headers={"Accept-Language": "en"}):
        preview = build_mount_preview(
            _player_snapshot(dimension_id=0, rotation=[-90.0, 0.0]),
            "player-key",
            preferred_offset={"x": 2, "y": 0, "z": 0},
        )

    assert preview["mount_label"] == "Horse"
    assert preview["mount_options"][0]["label"] == "Horse"
    assert preview["mount_options"][0]["notes"] == [
        "Create has been validated in-game; colors and markings now follow actual storage records (Variant/definitions)."
    ]
    assert "The starting height is estimated from the player position minus 1.62 and then snapped to a verified full-block surface." in preview["warnings"]
    assert "View direction was read from the player rotation and prioritized for candidate ordering." in preview["warnings"]
    assert (
        "Create writes actorprefix + digp, generates complete mount NBT, and creates a backup first. Initially, test only with copies of worlds."
        in preview["warnings"]
    )
    assert preview["candidate_positions"][0]["warning"] == (
        "Candidate offset selected by the client; limited server-side, but clearance has not yet been checked."
    )
    assert preview["candidate_positions"][1]["warning"] == (
        "Safety status: clearance has not been checked yet. Do not consider this position safe for placement."
    )


def test_mount_preview_matches_observed_player_to_horse_y_delta() -> None:
    preview = build_mount_preview(_player_snapshot([316.58, 68.62, 217.44]), "player-key", placement_radius=2)

    assert preview["selected_position"] == {"x": 318.58, "y": 67.0, "z": 217.44}


def test_mount_preview_prefers_view_direction_when_rotation_is_available() -> None:
    preview = build_mount_preview(_player_snapshot(rotation=[-90.0, 0.0]), "player-key", placement_radius=4)

    assert preview["placement_search"]["prefers_view_direction"] is True
    assert preview["placement_search"]["candidate_count"] == 4
    assert preview["player_yaw"] == -90.0
    assert preview["selected_candidate_id"] == "blickrichtung_4"
    assert preview["selected_position"] == {"x": 14.5, "y": 62.38, "z": -20.25}
    assert preview["candidate_positions"][0]["offset"] == {"x": 4.0, "y": 0.0, "z": 0.0}
    assert [candidate["id"] for candidate in preview["candidate_positions"]] == ["blickrichtung_4", "rechts_4", "links_4", "hinter_dir_4"]


def test_mount_radius_scan_builds_inner_distance_candidates() -> None:
    preview = build_mount_preview(_player_snapshot(rotation=[-90.0, 0.0]), "player-key", placement_radius=6)
    candidates = _distance_candidates(preview["candidate_positions"][0], 6)

    assert [candidate["id"] for candidate in candidates] == ["blickrichtung_2", "blickrichtung_3", "blickrichtung_4", "blickrichtung_5", "blickrichtung_6"]
    assert [candidate["offset"]["x"] for candidate in candidates] == [2.0, 3.0, 4.0, 5.0, 6.0]
    assert [candidate["distance"] for candidate in candidates] == [2.0, 3.0, 4.0, 5.0, 6.0]


def test_diagonal_candidates_stay_between_the_minimum_and_the_chosen_radius() -> None:
    """Whole-block offsets must respect both ends of the placement contract.

    Nearest rounding shortens diagonals -- yaw 45 at distance 2 rounds to (-1, 1),
    which is 1.41 blocks and undercuts MIN_PLACEMENT_RADIUS.  Pushing every
    diagonal outward instead breaks the other end: the user's search radius stops
    holding.  Only the innermost step may overshoot, because no integer diagonal
    sits between 1.41 and 2.83 blocks.
    """

    for yaw in range(0, 360, 5):
        for radius in (MIN_PLACEMENT_RADIUS, 6, 16):
            preview = build_mount_preview(_player_snapshot(rotation=[float(yaw), 0.0]), "player-key", placement_radius=radius)
            candidates = preview["candidate_positions"]
            assert len(candidates) == 4, (yaw, radius, "a direction collapsed into another")

            for candidate in [*candidates, *_distance_candidates(candidates[0], radius)]:
                distance = candidate["distance"]
                context = (yaw, radius, candidate["id"], distance)
                assert distance >= MIN_PLACEMENT_RADIUS, context
                # Nearest rounding on a block grid can sit up to half a block off
                # per axis; beyond that slack the radius is no longer being
                # honoured, which is what pushing every diagonal outward caused.
                limit = max(radius + math.sqrt(2) / 2, MIN_PLACEMENT_RADIUS * math.sqrt(2))
                assert distance <= limit, context


def test_horizontal_block_offset_rounds_to_the_nearest_block_above_the_floor() -> None:
    # Cardinal directions are already exact and must not be inflated.
    assert horizontal_block_offset(0.0, 1.0, 2) == (0, 2)
    assert horizontal_block_offset(-1.0, 0.0, 6) == (-6, 0)
    # The 45° case that used to fall short: nearest is (1, 1) at 1.41, below the
    # floor, so it is pushed out.
    assert horizontal_block_offset(-0.7071, 0.7071, 2) == (-2, 2)
    # Further out, nearest already clears the floor and must stay nearest rather
    # than inflating past the requested radius: (11, 11) is 15.56, (12, 12) is 17.0.
    assert horizontal_block_offset(-0.7071, 0.7071, 16) == (-11, 11)
    # Degenerate input has no direction to preserve.
    assert horizontal_block_offset(0.0, 0.0, 4) == (0, 0)
    # A caller asking below the floor still gets a legal offset, not a too-close one.
    assert math.hypot(*horizontal_block_offset(-0.7071, 0.7071, 1)) >= MIN_PLACEMENT_RADIUS


def test_mount_route_enriches_preview_with_player_rotation_and_dimension() -> None:
    player_key = b"local_player"
    encoded_key = encode_player_key(player_key)
    player_tag = nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.FloatTag(0.0), nbt.FloatTag(70.0), nbt.FloatTag(0.0)]),
            "Rotation": nbt.ListTag([nbt.FloatTag(-90.0), nbt.FloatTag(0.0)]),
            "DimensionId": nbt.IntTag(0),
        }
    )
    service = _FakeMountService(player_key, save_player_nbt(nbt.NamedTag(player_tag)))

    _world_path, _player_key, preview = _preview_from_request(
        {
            "world_path": "world",
            "player_key": encoded_key,
            "mount_type": "minecraft:horse",
            "placement_radius": 4,
        },
        _mount_route_deps(service),
    )

    assert preview["server_guard_epoch"] == 123
    assert preview["dimension_id"] == 0
    assert preview["player_rotation"] == [-90.0, 0.0]
    assert preview["placement_search"]["prefers_view_direction"] is True
    assert preview["placement_search"]["radius_scan"] == "enabled"
    assert preview["selected_candidate_id"] == "blickrichtung_2"


def test_mount_route_rejects_missing_authoritative_player_position() -> None:
    player_key = b"local_player"
    encoded_key = encode_player_key(player_key)
    player_tag = nbt.CompoundTag({"DimensionId": nbt.IntTag(0)})
    service = _FakeMountService(player_key, save_player_nbt(nbt.NamedTag(player_tag)))

    with pytest.raises(ValueError, match="Spielerposition fehlt oder ist ungültig"):
        _preview_from_request(
            {
                "world_path": "world",
                "player_key": encoded_key,
                "mount_type": "minecraft:horse",
            },
            _mount_route_deps(service),
        )


def test_mount_route_reports_unchecked_placement_safety_until_block_probe_exists() -> None:
    preview = build_mount_preview(_player_snapshot(), "player-key")

    safety = placement_safety_from_preview(preview)

    assert safety["status"] == "unchecked"
    assert safety["safe_to_place"] is None
    assert safety["block_check"] == "not_checked"
    assert safety["candidate_id"] == "east_6"
    assert "nicht" in safety["message"]


def test_mount_route_reports_unsafe_placement_safety() -> None:
    preview = build_mount_preview(_player_snapshot(), "player-key")
    candidate = dict(preview["candidate_positions"][0])
    candidate["safe_to_place"] = False
    candidate["block_check"] = "checked"
    candidate["warning"] = "Pferd kann hier nicht sicher platziert werden."
    preview = {**preview, "candidate_positions": [candidate], "selected_candidate_id": candidate["id"]}

    safety = placement_safety_from_preview(preview)

    assert safety == {
        "status": "unsafe",
        "safe_to_place": False,
        "block_check": "checked",
        "candidate_id": "east_6",
        "message": "Pferd kann hier nicht sicher platziert werden.",
    }


def test_mount_preview_accepts_supported_mount_types() -> None:
    for mount_type, label in {
        "minecraft:horse": "Pferd",
        "minecraft:donkey": "Esel",
        "minecraft:mule": "Maultier",
        "minecraft:camel": "Kamel",
        "minecraft:skeleton_horse": "Skelettpferd",
    }.items():
        preview = build_mount_preview(_player_snapshot(), "player-key", mount_type=mount_type)

        assert preview["success"] is True
        assert preview["mount_type"] == mount_type
        assert preview["mount_label"] == label
        assert preview["create_available"] is True
        assert preview["can_create"] is True


def test_mount_preview_marks_non_overworld_context_as_preview_only() -> None:
    preview = build_mount_preview(_player_snapshot(dimension_id=1), "player-key")

    assert preview["create_available"] is False
    assert preview["can_create"] is False
    assert any("Overworld" in warning for warning in preview["warnings"])


def test_mount_preview_blocks_unknown_dimension_with_guard_warning() -> None:
    preview = build_mount_preview(_player_snapshot(dimension_id=None), "player-key")

    assert preview["create_available"] is False
    assert preview["can_create"] is False
    assert any("DimensionId" in warning for warning in preview["warnings"])


def test_mount_preview_uses_custom_placement_radius() -> None:
    preview = build_mount_preview(_player_snapshot(), "player-key", placement_radius=3)

    assert preview["placement_search"]["radius"] == 3
    assert preview["placement_search"]["candidate_count"] == 4
    assert preview["selected_candidate_id"] == "east_3"
    assert preview["selected_position"] == {"x": 13.5, "y": 62.38, "z": -20.25}


def test_mount_preview_normalizes_float_placement_radius() -> None:
    preview = build_mount_preview(_player_snapshot(), "player-key", placement_radius="7.6")

    assert preview["placement_search"]["radius"] == 8
    assert preview["selected_position"] == {"x": 18.5, "y": 62.38, "z": -20.25}


def test_mount_preview_rejects_small_placement_radius() -> None:
    with pytest.raises(ValueError, match="placement_radius"):
        build_mount_preview(_player_snapshot(), "player-key", placement_radius=1)


def test_mount_preview_prefers_view_direction_for_custom_radius() -> None:
    preview = build_mount_preview(_player_snapshot(rotation=[180.0, 0.0]), "player-key", placement_radius=5)

    assert preview["placement_search"]["prefers_view_direction"] is True
    assert [candidate["id"] for candidate in preview["candidate_positions"]] == ["blickrichtung_5", "rechts_5", "links_5", "hinter_dir_5"]
    assert preview["selected_position"] == {"x": 10.5, "y": 62.38, "z": -25.25}


def test_mount_create_availability_exposed_to_ui() -> None:
    preview = build_mount_preview(_player_snapshot(), "player-key")

    assert preview["mount_options"][0]["id"] == "minecraft:horse"
    assert preview["mount_options"][0]["create_available"] is True
    assert preview["create_available"] is True
    assert preview["can_create"] is True


def test_mount_type_options_for_ui_include_known_labels_and_notes() -> None:
    options = mount_type_options()

    assert [option["id"] for option in options] == [
        "minecraft:horse",
        "minecraft:donkey",
        "minecraft:mule",
        "minecraft:camel",
        "minecraft:skeleton_horse",
    ]
    assert [option["label"] for option in options] == ["Pferd", "Esel", "Maultier", "Kamel", "Skelettpferd"]
    assert all(option["notes"] for option in options)
    assert all(option["label"] for option in options)
    assert [option["create_available"] for option in options] == [True, True, True, True, True]


def test_mount_view_fallback_options_match_backend_options() -> None:
    # The UI keeps a small fallback list so the dropdown is useful before the
    # first preview response. Keep that list synchronized with the server-side
    # mount metadata until a dedicated /api/mount/options endpoint exists.
    view_js = (PROJECT_ROOT / "static" / "mount_view.js").read_text(encoding="utf-8")
    client_options = re.findall(r'\{\s*id:\s*"(minecraft:[^"]+)",\s*label:\s*t\("([^"]+)"\)\s*\}', view_js)
    server_options = [(option["id"], option["label"]) for option in mount_type_options()]

    assert client_options == server_options


def test_mount_preview_accepts_bounded_preferred_offset() -> None:
    preview = build_mount_preview(
        _player_snapshot([0, 70, 0]),
        "player-key",
        preferred_offset={"x": -3, "y": 0, "z": 4},
    )

    assert preview["selected_candidate_id"] == "preferred_offset"
    assert preview["selected_position"] == {"x": -3.0, "y": 68.38, "z": 4.0}
    assert preview["candidate_positions"][0]["id"] == "preferred_offset"


def test_mount_preview_rejects_unsupported_mount_type() -> None:
    with pytest.raises(ValueError, match="wird noch nicht unterstützt"):
        normalize_mount_type("minecraft:pig")


def test_mount_preview_rejects_large_preferred_offset() -> None:
    with pytest.raises(ValueError, match="preferred_offset ist zu groß"):
        build_mount_preview(_player_snapshot(), "player-key", preferred_offset={"x": 17, "y": 0, "z": 0})


def test_mount_preview_rejects_large_placement_radius() -> None:
    with pytest.raises(ValueError, match="placement_radius"):
        build_mount_preview(_player_snapshot(), "player-key", placement_radius=17)


def test_mount_preview_rejects_missing_player_position() -> None:
    with pytest.raises(ValueError, match="Spielerposition fehlt"):
        build_mount_preview({"player": {"label": "Alex"}, "stats": {}}, "player-key")
