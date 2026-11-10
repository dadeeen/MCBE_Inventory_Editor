"""Map markers use saved player positions from independently validated reads."""

from pathlib import Path

import pytest

from mcbe_editor import nbt, villager_service
from mcbe_editor.bedrock_nbt import SAVE_KWARGS
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.players import classify_player_record, encode_player_key
from mcbe_editor.services import BedrockEditorService
from tests.test_villager_workflow import villager_world as villager_world
from tests.test_villager_workflow import villager_client as villager_client


def _player(*, position=(24.0, 70.0, -40.0), dimension=0):
    return nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([], 10),
            "Pos": nbt.ListTag([nbt.DoubleTag(value) for value in position]),
            "DimensionId": nbt.IntTag(dimension),
        }
    )


def _bytes(tag):
    return nbt.NamedTag(tag).save_to(**SAVE_KWARGS)


def _write(world, records):
    db = LevelDbWriter(str(Path(world) / "db"))
    try:
        db.put_batch(records)
    finally:
        db.close()


@pytest.mark.parametrize("dimension", [0, 1, 2, 7])
def test_player_metadata_exposes_saved_coordinates_without_dimension_conversion(dimension):
    player = classify_player_record(b"player_map_test", _bytes(_player(dimension=dimension)))
    assert player["position"] == {"x": 24.0, "y": 70.0, "z": -40.0}
    assert player["dimension"] == dimension


@pytest.mark.parametrize(
    "position",
    [
        None,
        nbt.StringTag("24 70 -40"),
        nbt.ListTag([nbt.IntTag(24), nbt.IntTag(70), nbt.IntTag(-40)]),
        nbt.ListTag([nbt.DoubleTag(24), nbt.DoubleTag(70)]),
        nbt.ListTag([nbt.DoubleTag(float("nan")), nbt.DoubleTag(70), nbt.DoubleTag(0)]),
        nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(float("inf")), nbt.DoubleTag(0)]),
        nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(70), nbt.DoubleTag(2**36)]),
    ],
)
def test_invalid_player_coordinates_do_not_get_a_default_map_location(position):
    tag = _player()
    if position is None:
        del tag["Pos"]
    else:
        tag["Pos"] = position
    player = classify_player_record(b"player_map_test", _bytes(tag))
    assert player["position"] is None


@pytest.mark.parametrize("dimension", [None, nbt.StringTag("0"), nbt.FloatTag(0), nbt.LongTag(2**40)])
def test_unknown_player_dimension_is_not_assumed_to_be_overworld(dimension):
    tag = _player()
    if dimension is None:
        del tag["DimensionId"]
    else:
        tag["DimensionId"] = dimension
    player = classify_player_record(b"player_map_test", _bytes(tag))
    assert player["dimension"] is None


def test_map_reads_current_player_markers_without_writes_or_requiring_a_villager_rescan(villager_world):
    world, _ = villager_world
    missing_dimension = _player()
    del missing_dimension["DimensionId"]
    _write(
        world,
        {
            b"player_map_main": _bytes(_player()),
            b"player_map_nether": _bytes(_player(position=(-3, 60, 9), dimension=1)),
            b"player_map_unknown": _bytes(missing_dimension),
            b"player_map_corrupt": b"unreadable NBT",
        },
    )
    service = BedrockEditorService({}, {})
    service.list_players(world)  # Prime the normal player discovery cache.
    before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in (Path(world) / "db").iterdir()}
    snapshot = villager_service.scan(service, world)
    assert "map_players" not in snapshot
    first = villager_service.map_players(service, world, snapshot["world_revision"])
    after = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in (Path(world) / "db").iterdir()}
    assert before == after
    markers = {player["player_key"]: player for player in first["map_players"]}
    assert set(markers) == {encode_player_key(b"player_map_main"), encode_player_key(b"player_map_nether")}
    assert all(set(player) == {"player_key", "label", "position", "dimension"} for player in markers.values())
    assert markers[encode_player_key(b"player_map_main")]["position"] == {"x": 24.0, "y": 70.0, "z": -40.0}
    assert markers[encode_player_key(b"player_map_nether")]["dimension"] == 1

    _write(world, {b"player_map_main": _bytes(_player(position=(100, 80, -200), dimension=2))})
    changed = villager_service.map_players(service, world, snapshot["world_revision"])
    assert changed["snapshot_stale"] is True
    assert changed["world_revision"] != snapshot["world_revision"]
    moved = next(player for player in changed["map_players"] if player["player_key"] == encode_player_key(b"player_map_main"))
    assert moved["position"] == {"x": 100.0, "y": 80.0, "z": -200.0}
    assert moved["dimension"] == 2
    snapshot = villager_service.scan(service, world)
    second = villager_service.map_players(service, world, snapshot["world_revision"])
    assert second["snapshot_stale"] is False
    moved = next(player for player in second["map_players"] if player["player_key"] == encode_player_key(b"player_map_main"))
    assert moved["position"] == {"x": 100.0, "y": 80.0, "z": -200.0}
    assert moved["dimension"] == 2
    assert second["world_revision"] != first["world_revision"]


def test_scan_never_discovers_players_and_map_route_keeps_scan_context_and_csrf(villager_client, villager_world, monkeypatch):
    import main
    from unittest.mock import Mock

    world, _ = villager_world
    players = Mock(return_value=[])
    monkeypatch.setattr(main.editor_service, "_scan_players", players)
    scan = villager_client.post("/api/villagers/scan", json={"world_path": world}).get_json()
    players.assert_not_called()
    body = {"world_path": world, "world_revision": scan["world_revision"]}
    response = villager_client.post("/api/villagers/map_players", json=body)
    assert response.status_code == 200 and response.get_json()["map_players"] == []
    assert players.call_count == 1
    assert villager_client.post("/api/villagers/map_players", json={"world_path": world}).status_code == 400
    stale = villager_client.post("/api/villagers/map_players", json={**body, "world_revision": "stale"})
    assert stale.status_code == 200
    assert stale.get_json()["snapshot_stale"] is True
    assert villager_client.post("/api/villagers/map_players", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403


@pytest.mark.parametrize("online", [False, True])
def test_map_loads_after_a_world_change_and_preserves_write_guards(villager_client, villager_world, monkeypatch, online):
    from dataclasses import replace
    from unittest.mock import Mock

    import main

    world, _ = villager_world
    scan = villager_client.post("/api/villagers/scan", json={"world_path": world}).get_json()
    _write(world, {b"player_map_main": _bytes(_player(position=(100, 80, -200), dimension=2))})
    if online:
        monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, require_server_offline=True))
        monkeypatch.setattr(
            main,
            "write_gate",
            lambda *_args, **_kwargs: {
                "allowed": False,
                "read_allowed": True,
                "reason": "Server online",
                "server_status": {"status": "online"},
                "config": {"require_server_offline": True},
            },
        )
    before = {path.name: path.read_bytes() for path in (Path(world) / "db").iterdir()}
    entity_scan = Mock(side_effect=AssertionError("Loading player markers must not scan villagers"))
    monkeypatch.setattr(main.editor_service._villager_directory, "snapshot", entity_scan)
    response = villager_client.post("/api/villagers/map_players", json={"world_path": world, "world_revision": scan["world_revision"]})
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["snapshot_stale"] is True
    assert result["map_players"][0]["position"] == {"x": 100.0, "y": 80.0, "z": -200.0}
    row = scan["villagers"][0]
    preview = villager_client.post(
        "/api/villagers/preview",
        json={
            "world_path": world,
            "world_revision": scan["world_revision"],
            "server_guard_token": scan["server_guard_token"],
            "server_guard_epoch": scan["server_guard_epoch"],
            "selection": [{"id": row["id"], "revision": row["revision"]}],
            "changes": {"heal": True},
        },
    )
    assert preview.status_code == 409, preview.get_json()
    entity_scan.assert_not_called()
    assert {path.name: path.read_bytes() for path in (Path(world) / "db").iterdir()} == before


def test_player_positions_reject_a_world_change_during_the_read(villager_world, monkeypatch):
    world, _ = villager_world
    service = BedrockEditorService({}, {})
    scan = villager_service.scan(service, world)
    original = service._scan_players

    def changed_during_read(db):
        players = original(db)
        (Path(world) / "level.dat").write_bytes(b"changed during player read")
        return players

    monkeypatch.setattr(service, "_scan_players", changed_during_read)
    with pytest.raises(villager_service.VillagerSnapshotStaleError):
        villager_service.map_players(service, world, scan["world_revision"])
