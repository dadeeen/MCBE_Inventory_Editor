from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcbe_editor import mount_api_routes, mount_write, nbt, services
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.mount_api_routes import MountRouteDeps
from mcbe_editor.mount_placement import placement_safety_from_preview
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from tests.test_mount_block_probe import _single_layer_payload_with_palette_indices


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


def _synthetic_mount_workspace(tmp_path, monkeypatch, owner_tag=None, position=(0, 65.62, 0)):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text("Synthetic mount test", encoding="utf-8")
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([]),
            "Health": nbt.FloatTag(20),
            "PlayerGameType": nbt.IntTag(0),
            "DimensionId": nbt.IntTag(0),
            "Pos": nbt.ListTag([nbt.FloatTag(value) for value in position]),
        }
    )
    if owner_tag is not None:
        player["UniqueID"] = owner_tag
    values = {b"~local_player": nbt.NamedTag(player).save_to(**SAVE_KWARGS)}
    batches = []
    backups = []

    class Db:
        def __init__(self, _path):
            pass

        def get(self, key):
            return values[key]

        def iter_items(self):
            return list(values.items())

        def close(self):
            pass

        def put_batch(self, writes):
            batches.append(dict(writes))
            values.update(writes)

    def create_backup(_world_path, **_kwargs):
        backups.append(True)
        return str(tmp_path / "synthetic-backup.zip")

    for module in (services, mount_write):
        monkeypatch.setattr(module, "create_backup", create_backup)
        monkeypatch.setattr(module, "prune_backups", lambda *_args, **_kwargs: None)
    service = BedrockEditorService({}, {}, db_factory=Db, readonly_db_factory=Db)
    key = encode_player_key(b"~local_player")
    loaded = service.load_player(str(world), key)
    assert loaded["player"]["editable"] is True
    deps = MountRouteDeps(
        service=service,
        jsonify=lambda value: value,
        api_error=lambda error, status=400: {"success": False, "error": str(error), "status": status},
        log_api_exception=lambda *_args: None,
        json_string=lambda data, name, default="": str(data.get(name, default)),
        require_world_db_access_allowed=lambda: None,
        audit_event=lambda *_args, **_kwargs: None,
        server_online_epoch=lambda: 0,
    )
    player_deps = SimpleNamespace(service=service, json_string=deps.json_string, json_bool=lambda data, name, default=False: data.get(name, default))
    request = {"world_path": str(world), "player_key": key, "base_revision": loaded["player_revision"], "stats": {}}
    return SimpleNamespace(values=values, batches=batches, backups=backups, deps=deps, player_deps=player_deps, request=request)


def _refusal(result):
    """Return payload and status from the stubbed api_error or from jsonify."""

    if isinstance(result, tuple):
        return result
    return result, result.get("status", 200)


@pytest.mark.parametrize("owner_tag", [None, nbt.IntTag(42), nbt.FloatTag(42), nbt.StringTag("42"), nbt.LongTag(-1)])
@pytest.mark.parametrize("workspace_save", [False, True])
def test_tamed_mount_without_player_owner_is_rejected_before_backup(tmp_path, monkeypatch, owner_tag, workspace_save) -> None:
    fixture = _synthetic_mount_workspace(tmp_path, monkeypatch, owner_tag)
    original_player = fixture.values[b"~local_player"]
    mount = {"mount_type": "minecraft:donkey", "create_mode": "synthetic_full", "tamed": True, "allow_unchecked_placement": True}
    if workspace_save:
        result = mount_api_routes.save_workspace({**fixture.request, "mounts": [mount]}, fixture.deps, fixture.player_deps)
    else:
        result = mount_api_routes.create_mount({**fixture.request, **mount}, fixture.deps)
    result, status = _refusal(result)
    assert result["success"] is False
    assert status == 400
    assert "UniqueID des Referenzspielers" in result["error"]
    assert fixture.batches == []
    assert fixture.backups == []
    assert fixture.values[b"~local_player"] == original_player


@pytest.mark.parametrize("tamed", [False, True])
def test_workspace_mounts_preserve_owner_and_shared_chunk_references(tmp_path, monkeypatch, tamed) -> None:
    owner = -4294967295
    fixture = _synthetic_mount_workspace(tmp_path, monkeypatch, nbt.LongTag(owner) if tamed else None)
    mounts = [
        {
            "mount_type": mount_type,
            "create_mode": "synthetic_full",
            "tamed": tamed,
            "allow_unchecked_placement": True,
            "preferred_offset": {"x": 2, "z": offset},
        }
        for mount_type, offset in [("minecraft:donkey", 2), ("minecraft:mule", 6)]
    ]
    result = mount_api_routes.save_workspace({**fixture.request, "mounts": mounts}, fixture.deps, fixture.player_deps)
    assert result["success"] is True
    assert len(fixture.batches) == 1
    assert len(fixture.backups) == 1
    assert len(result["mounts"]) == 2
    assert all(mount["post_create_validation"]["ok"] for mount in result["mounts"])
    actor_keys = [key for key in fixture.values if key.startswith(b"actorprefix")]
    assert len(actor_keys) == 2
    for key in actor_keys:
        actor = nbt.load(fixture.values[key], **LOAD_KWARGS).tag
        assert actor["IsTamed"].py_data == int(tamed)
        assert actor["OwnerNew"].py_data == (owner if tamed else -1)
    digp_values = [value for key, value in fixture.values.items() if key.startswith(b"digp")]
    assert len(digp_values) == 1
    assert len(digp_values[0]) == 16
    assert all(mount_write.digp_entry_for_actor_key(key) in digp_values[0] for key in actor_keys)


@pytest.mark.parametrize("workspace_save", [False, True])
def test_missing_neighbor_chunk_does_not_allow_mount_in_known_stone(tmp_path, monkeypatch, workspace_save) -> None:
    fixture = _synthetic_mount_workspace(tmp_path, monkeypatch, position=(13.8, 65.62, 8.5))
    base = bytes(8)
    solid = {(x, y, z) for x in range(16) for y in range(16) for z in range(16)}
    fixture.values.update(
        {
            base + b"\x2c": b"\x29",
            base + b"\x36": (2).to_bytes(4, "little"),
            base + b"\x2f\x03": _single_layer_payload_with_palette_indices(solid),
            base + b"\x2f\x04": _single_layer_payload_with_palette_indices(solid - {(13, 0, 8), (13, 1, 8)}),
        }
    )
    mount = {
        "mount_type": "minecraft:horse",
        "create_mode": "synthetic_full",
        "placement_radius": 2,
        "preferred_offset": {"x": 2, "z": 0},
        "allow_unchecked_placement": True,
    }
    preview = mount_api_routes._preview_from_request({**fixture.request, **mount}, fixture.deps)[2]
    assert placement_safety_from_preview(preview)["safe_to_place"] is False
    assert any(candidate["id"] == preview["selected_candidate_id"] for candidate in preview["candidate_positions"])
    if workspace_save:
        result = mount_api_routes.save_workspace({**fixture.request, "mounts": [mount]}, fixture.deps, fixture.player_deps)
    else:
        result = mount_api_routes.create_mount({**fixture.request, **mount}, fixture.deps)
    result, status = _refusal(result)
    assert result["success"] is False
    assert status == 400
    assert fixture.batches == []
    assert fixture.backups == []


@pytest.mark.parametrize("workspace_save", [False, True])
@pytest.mark.parametrize(
    "terrain_change,allow_unchecked,expected_status",
    [("blocked", False, 400), ("blocked", True, 400), ("unfinalized", False, 400), ("unfinalized", True, 200), ("unchanged", False, 200)],
)
def test_mount_rechecks_terrain_changed_after_preview_before_writing(
    tmp_path, monkeypatch, workspace_save, terrain_change, allow_unchecked, expected_status
) -> None:
    fixture = _synthetic_mount_workspace(tmp_path, monkeypatch, position=(8.5, 65.62, 8.5))
    base = bytes(8)
    solid = {(x, y, z) for x in range(16) for y in range(16) for z in range(16)}
    fixture.values.update(
        {
            base + b"\x2c": b"\x29",
            base + b"\x36": (2).to_bytes(4, "little"),
            base + b"\x2f\x03": _single_layer_payload_with_palette_indices(solid),
            base + b"\x2f\x04": _single_layer_payload_with_palette_indices(set()),
        }
    )
    mount = {
        "mount_type": "minecraft:horse",
        "create_mode": "synthetic_full",
        "placement_radius": 2,
        "preferred_offset": {"x": 2, "z": 0},
        "allow_unchecked_placement": allow_unchecked,
    }
    preview = mount_api_routes._preview_from_request({**fixture.request, **mount}, fixture.deps)[2]
    assert placement_safety_from_preview(preview)["safe_to_place"] is True
    original_player = fixture.values[b"~local_player"]
    backup_path = tmp_path / "before-mount.zip"

    def change_terrain_before_backup(_path, **_kwargs):
        # A world edit leaves player bytes intact after the route's read-only
        # placement check. The backup captures the newer terrain.
        if terrain_change == "blocked":
            fixture.values[base + b"\x2f\x04"] = _single_layer_payload_with_palette_indices(solid)
        elif terrain_change == "unfinalized":
            fixture.values[base + b"\x36"] = (0).to_bytes(4, "little")
        backup_path.write_bytes(b"test backup")
        fixture.backups.append(True)
        return str(backup_path)

    for module in (services, mount_write):
        monkeypatch.setattr(module, "create_backup", change_terrain_before_backup)
    if workspace_save:
        result = mount_api_routes.save_workspace({**fixture.request, "mounts": [mount]}, fixture.deps, fixture.player_deps)
    else:
        result = mount_api_routes.create_mount({**fixture.request, **mount}, fixture.deps)
    payload, status = _refusal(result)
    assert status == expected_status
    assert fixture.values[b"~local_player"] == original_player
    if expected_status == 400:
        assert payload["success"] is False
        assert fixture.batches == []
        assert not any(key.startswith((b"actorprefix", b"digp")) for key in fixture.values)
        assert not backup_path.exists()
    else:
        assert payload["success"] is True
        assert len(fixture.batches) == 1
        created = payload["mounts"][0] if workspace_save else payload
        assert created["selected_position"] == preview["selected_position"]
        assert created["placement_safety"]["safe_to_place"] is (None if terrain_change == "unfinalized" else True)
        assert backup_path.exists()


def test_workspace_terrain_refusal_keeps_player_and_other_mount_unwritten(tmp_path, monkeypatch) -> None:
    fixture = _synthetic_mount_workspace(tmp_path, monkeypatch, position=(8.5, 65.62, 8.5))
    base = bytes(8)
    solid = {(x, y, z) for x in range(16) for y in range(16) for z in range(16)}
    fixture.values.update(
        {
            base + b"\x2c": b"\x29",
            base + b"\x36": (2).to_bytes(4, "little"),
            base + b"\x2f\x03": _single_layer_payload_with_palette_indices(solid),
            base + b"\x2f\x04": _single_layer_payload_with_palette_indices(set()),
        }
    )
    mounts = [
        {"mount_type": "minecraft:horse", "create_mode": "synthetic_full", "placement_radius": 2, "preferred_offset": offset}
        for offset in [{"x": 2, "z": 0}, {"x": 0, "z": 2}]
    ]
    previews = [mount_api_routes._preview_from_request({**fixture.request, **mount}, fixture.deps)[2] for mount in mounts]
    assert all(placement_safety_from_preview(preview)["safe_to_place"] is True for preview in previews)
    original = dict(fixture.values)
    position = previews[1]["selected_position"]
    obstruction = _single_layer_payload_with_palette_indices({(int(position["x"]), int(position["y"]) % 16, int(position["z"]))})
    backup_path = tmp_path / "before-workspace.zip"

    def change_second_placement(_path, **_kwargs):
        fixture.values[base + b"\x2f\x04"] = obstruction
        backup_path.write_bytes(b"test backup")
        return str(backup_path)

    monkeypatch.setattr(services, "create_backup", change_second_placement)
    payload, status = _refusal(
        mount_api_routes.save_workspace({**fixture.request, "stats": {"health": 19}, "mounts": mounts}, fixture.deps, fixture.player_deps)
    )
    assert status == 400
    assert payload["success"] is False
    assert fixture.batches == []
    assert fixture.values == {**original, base + b"\x2f\x04": obstruction}
    assert not backup_path.exists()


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
    monkeypatch.setattr(mount_api_routes, "validate_selected_placement", lambda *_args, **_kwargs: {"safe_to_place": True, "status": "safe"})
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

    location_and_mount, status = mount_api_routes.save_workspace(
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

    assert status == 400
    assert location_and_mount["success"] is False
    assert location_and_mount["error"].startswith("Speichern abgelehnt: ")
    assert "nicht gemeinsam gespeichert" in location_and_mount["error"]
    assert len(service.calls) == 1
