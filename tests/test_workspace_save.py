from __future__ import annotations

from types import SimpleNamespace

from mcbe_editor import mount_api_routes
from mcbe_editor.mount_api_routes import MountRouteDeps


class _FakeDb:
    def get(self, _key: bytes) -> bytes:
        raise KeyError

    def iter_items(self):
        return iter(())


class _FakeWorkspaceService:
    def __init__(self) -> None:
        self.calls = []

    def _read_player(self, _db, _player_key: bytes) -> bytes:
        return b"player"

    def save_player(self, world_path, player_key, inventory, stats, **kwargs):
        self.calls.append((world_path, player_key, inventory, stats, kwargs))
        batch = kwargs["extra_batch_builder"](_FakeDb(), b"player-key")
        kwargs["extra_batch_validator"](_FakeDb(), batch)
        return {
            "success": True,
            "backup_file": "workspace.zip",
            "player_revision": "revision",
            "no_op": False,
            "workspace": batch["result"],
        }


def test_workspace_save_builds_one_atomic_player_and_mount_batch(monkeypatch) -> None:
    service = _FakeWorkspaceService()
    preview = {
        "success": True,
        "create_available": True,
        "mount_type": "minecraft:horse",
        "selected_position": {"x": 1.5, "y": 64.0, "z": 2.5},
        "dimension_id": 0,
    }
    monkeypatch.setattr(mount_api_routes, "_preview_from_request", lambda _data, _deps: ("C:/World", "player", preview))
    monkeypatch.setattr(mount_api_routes, "placement_safety_from_preview", lambda _preview: {"safe_to_place": True, "status": "safe"})
    monkeypatch.setattr(mount_api_routes, "load_player_nbt", lambda _raw: SimpleNamespace(tag={"UniqueID": SimpleNamespace(py_data=42)}))
    record = SimpleNamespace(
        actor_key=b"actorprefix-one",
        actor_value=b"actor",
        digp_key=b"digp-one",
        digp_value=b"digp",
        mount_type="minecraft:horse",
        position=preview["selected_position"],
        horse_profile={"mode": "random_like_game"},
        mount_stats=None,
        tamed=False,
    )
    monkeypatch.setattr(mount_api_routes, "build_horse_mount_record", lambda *_args, **_kwargs: record)

    def raise_during_validation(_db, _record, **_kwargs):
        raise RuntimeError("digp nicht lesbar")

    monkeypatch.setattr(mount_api_routes, "validate_horse_mount_write", raise_during_validation)

    deps = MountRouteDeps(
        service=service,
        jsonify=lambda value: value,
        api_error=lambda value, _status=400: {"success": False, "error": str(value)},
        log_api_exception=lambda _label, _exc: None,
        json_string=lambda data, key, default=None: str(data.get(key, default)),
        require_world_db_access_allowed=lambda: None,
        audit_event=lambda *_args, **_kwargs: None,
        server_online_epoch=lambda: 1,
        require_world_write_allowed=lambda: None,
        require_server_guard_current=lambda _data: None,
        require_final_world_write_allowed=lambda _label: None,
        presence_conflict_response=lambda *_args, **_kwargs: None,
    )
    player_deps = SimpleNamespace(
        service=service,
        json_string=lambda data, key, default=None: str(data.get(key, default)),
        json_bool=lambda data, key, default=False: bool(data.get(key, default)),
    )

    response, status = mount_api_routes.save_workspace(
        {
            "world_path": "C:/World",
            "player_key": "player",
            "inventory": None,
            "stats": {},
            "mounts": [{"mount_type": "minecraft:horse", "preferred_offset": {"x": 1, "y": 0, "z": 2}}],
        },
        deps,
        player_deps,
    )

    result = response
    assert status == 500
    assert result["success"] is False
    assert result["write_committed"] is True
    assert result["validation_failed"] is True
    assert result["atomic_batch"] is True
    assert result["backup_file"] == "workspace.zip"
    assert len(result["mounts"]) == 1
    assert result["mounts"][0]["post_create_validation"]["ok"] is False
    assert result["mounts"][0]["post_create_validation"]["details"]["exception_type"] == "RuntimeError"
    assert "atomar geschrieben" in result["mounts"][0]["validation_warning"]
    assert len(service.calls) == 1
    call_kwargs = service.calls[0][4]
    assert callable(call_kwargs["extra_batch_builder"])
    assert callable(call_kwargs["extra_batch_validator"])

    location_and_mount = mount_api_routes.save_workspace(
        {
            "world_path": "C:/World",
            "player_key": "player",
            "inventory": None,
            "stats": {"pos": [10.0, 70.0, -5.0], "dimension_id": 1},
            "mounts": [{"mount_type": "minecraft:horse"}],
        },
        deps,
        player_deps,
    )

    assert location_and_mount["success"] is False
    assert "nicht gemeinsam gespeichert" in location_and_mount["error"]
    assert len(service.calls) == 1
