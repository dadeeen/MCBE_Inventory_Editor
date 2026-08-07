from __future__ import annotations

from mcbe_editor import mount_api_routes
from mcbe_editor.mount_api_routes import MountRouteDeps


class _FinalWriteBlocked(ValueError):
    write_gate = {"allowed": False}


def _deps() -> MountRouteDeps:
    return MountRouteDeps(
        service=object(),
        jsonify=lambda value: value,
        api_error=lambda value, _status=400: {"success": False, "error": str(value)},
        log_api_exception=lambda _label, _exc: None,
        json_string=lambda data, key, default=None: str(data.get(key, default)),
        require_world_db_access_allowed=lambda: None,
        audit_event=lambda *_args, **_kwargs: None,
        server_online_epoch=lambda: 7,
        require_world_write_allowed=lambda: None,
        require_server_guard_current=lambda _data: None,
        require_final_world_write_allowed=lambda _label: None,
        presence_conflict_response=lambda *_args, **_kwargs: None,
        final_write_gate_blocked_error=_FinalWriteBlocked,
    )


def _preview(*, safe_to_place=True):
    return {
        "mount_type": "minecraft:horse",
        "create_available": True,
        "can_create": True,
        "selected_candidate_id": "rechts_2",
        "selected_position": {"x": 2.0, "y": 64.0, "z": 0.0},
        "candidate_positions": [
            {
                "id": "rechts_2",
                "x": 2.0,
                "y": 64.0,
                "z": 0.0,
                "safe_to_place": safe_to_place,
                "block_check": "footprint_probe" if safe_to_place is not None else "not_checked",
            }
        ],
        "dimension_id": 0,
        "placement_search": {"radius": 6, "radius_scan": "enabled", "footprint_check": "enabled"},
    }


def _patch_create(monkeypatch, preview, captured):
    def fake_preview_from_request(data, _deps):
        captured["request_data"] = data
        return "world", "player", preview

    def fake_create_horse_mount_with_service(
        service, world_path, player_key, received_preview, *, create_mode, horse_profile, mount_stats=None, tamed=False, pre_write_check
    ):
        captured.update(
            {
                "service": service,
                "world_path": world_path,
                "player_key": player_key,
                "preview": received_preview,
                "create_mode": create_mode,
                "horse_profile": horse_profile,
                "mount_stats": mount_stats,
                "tamed": tamed,
            }
        )
        pre_write_check()
        return {
            "success": True,
            "mount_type": "minecraft:horse",
            "horse_profile": horse_profile,
            "post_create_validation": {"ok": True},
        }

    monkeypatch.setattr(mount_api_routes, "_preview_from_request", fake_preview_from_request)
    monkeypatch.setattr(mount_api_routes, "create_horse_mount_with_service", fake_create_horse_mount_with_service)


def test_mount_create_passes_horse_profile_to_writer(monkeypatch) -> None:
    captured = {}
    profile = {
        "mode": "custom",
        "health": 23,
        "movement": 0.2,
        "jump_strength": 0.7,
        "color": 4,
        "mark_variant": 2,
    }
    preview = _preview(safe_to_place=True)
    _patch_create(monkeypatch, preview, captured)

    result = mount_api_routes.create_mount(
        {
            "world_path": "world",
            "player_key": "player",
            "mount_type": "minecraft:horse",
            "create_mode": "synthetic_full",
            "horse_profile": profile,
        },
        _deps(),
    )

    assert result["success"] is True
    assert result["horse_profile"] == profile
    assert result["placement_safety"]["status"] == "safe"
    assert captured["horse_profile"] == profile
    assert captured["preview"] is preview


def test_mount_create_returns_error_status_after_committed_validation_failure(monkeypatch) -> None:
    captured = {}
    preview = _preview(safe_to_place=True)
    _patch_create(monkeypatch, preview, captured)

    def fake_failed_validation(*_args, **_kwargs):
        return {
            "success": False,
            "write_committed": True,
            "validation_failed": True,
            "error": "Mount geschrieben; Nachvalidierung fehlgeschlagen.",
            "mount_type": "minecraft:horse",
            "post_create_validation": {"ok": False, "errors": ["digp ungültig"]},
        }

    monkeypatch.setattr(mount_api_routes, "create_horse_mount_with_service", fake_failed_validation)

    response, status = mount_api_routes.create_mount(
        {
            "world_path": "world",
            "player_key": "player",
            "mount_type": "minecraft:horse",
            "create_mode": "synthetic_full",
        },
        _deps(),
    )

    assert status == 500
    assert response["success"] is False
    assert response["write_committed"] is True
    assert response["validation_failed"] is True


def test_mount_create_passes_mount_stats_to_writer(monkeypatch) -> None:
    captured = {}
    preview = _preview(safe_to_place=True)
    _patch_create(monkeypatch, preview, captured)

    result = mount_api_routes.create_mount(
        {
            "world_path": "world",
            "player_key": "player",
            "mount_type": "minecraft:donkey",
            "create_mode": "synthetic_full",
            "mount_stats": {"health": 25},
        },
        _deps(),
    )

    assert result["success"] is True
    assert captured["mount_stats"] == {"health": 25}


def test_mount_create_passes_tamed_flag_to_writer(monkeypatch) -> None:
    captured = {}
    preview = _preview(safe_to_place=True)
    _patch_create(monkeypatch, preview, captured)

    result = mount_api_routes.create_mount(
        {
            "world_path": "world",
            "player_key": "player",
            "mount_type": "minecraft:mule",
            "create_mode": "synthetic_full",
            "tamed": True,
        },
        _deps(),
    )

    assert result["success"] is True
    assert captured["tamed"] is True


def test_mount_create_rejects_string_boolean_for_tamed(monkeypatch) -> None:
    captured = {}
    _patch_create(monkeypatch, _preview(safe_to_place=True), captured)

    result = mount_api_routes.create_mount(
        {
            "world_path": "world",
            "player_key": "player",
            "mount_type": "minecraft:mule",
            "create_mode": "synthetic_full",
            "tamed": "false",
        },
        _deps(),
    )

    assert result["success"] is False
    assert "Boolean" in result["error"]
    assert "tamed" not in captured


def test_mount_create_rejects_unchecked_without_explicit_allowance(monkeypatch) -> None:
    captured = {}
    _patch_create(monkeypatch, _preview(safe_to_place=None), captured)

    result = mount_api_routes.create_mount(
        {
            "world_path": "world",
            "player_key": "player",
            "mount_type": "minecraft:horse",
            "create_mode": "synthetic_full",
        },
        _deps(),
    )

    assert result["success"] is False
    assert "ungeprüft" in result["error"]
    assert "horse_profile" not in captured


def test_mount_create_allows_unchecked_when_explicitly_confirmed(monkeypatch) -> None:
    captured = {}
    _patch_create(monkeypatch, _preview(safe_to_place=None), captured)

    result = mount_api_routes.create_mount(
        {
            "world_path": "world",
            "player_key": "player",
            "mount_type": "minecraft:horse",
            "create_mode": "synthetic_full",
            "allow_unchecked_placement": True,
        },
        _deps(),
    )

    assert result["success"] is True
    assert result["placement_safety"]["status"] == "unchecked"
    assert captured["preview"]["selected_candidate_id"] == "rechts_2"
