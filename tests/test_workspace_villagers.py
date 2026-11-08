"""Black-box checks of the central save using real disk records and backups."""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from mcbe_editor import nbt, services, villager_service
from mcbe_editor.backup import get_backups_dir
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.players import encode_player_key
from tests import test_villager_workflow as workflow_fixtures
from tests.test_villager_workflow import _preview_request, _records

villager_client = workflow_fixtures.villager_client
villager_world = workflow_fixtures.villager_world


def prepare(client, world, *, name="Egon 🐑", name_first=False):
    records = _records(world)
    key = next(key for key in records if key.startswith(b"actorprefix"))
    actor = nbt.load(records[key], **LOAD_KWARGS)
    actor.tag["ChestItems"] = nbt.ListTag(
        [
            nbt.CompoundTag(
                {"Slot": nbt.ByteTag(i), "Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0), "WasPickedUp": nbt.ByteTag(0)}
            )
            for i in range(8)
        ]
    )
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([]),
            "Health": nbt.FloatTag(20),
            "PlayerGameType": nbt.IntTag(0),
            "DimensionId": nbt.IntTag(0),
            "Pos": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(65.62), nbt.FloatTag(0)]),
        }
    )
    writer = LevelDbWriter(os.path.join(world, "db"))
    writer.put_batch({key: actor.save_to(**SAVE_KWARGS), b"~local_player": nbt.NamedTag(player).save_to(**SAVE_KWARGS)})
    writer.close()
    loaded = services.BedrockEditorService({}, {}).load_player(world, encode_player_key(b"~local_player"))
    health, body = _preview_request(client, world)
    supply = client.post(
        "/api/villagers/preview",
        json={**body, "selection": body["selection"][:1], "changes": {"inventory": [{"slot": 0, "item": {"name": "minecraft:carrot", "count": 4}}]}},
    )
    assert supply.status_code == 200, supply.get_json()
    name_preview = client.post("/api/villagers/preview", json={**body, "selection": body["selection"][:1], "changes": {"name": name}})
    assert name_preview.status_code == 200, name_preview.get_json()
    tokens = [health["preview_token"], supply.get_json()["preview_token"]]
    tokens.insert(0 if name_first else len(tokens), name_preview.get_json()["preview_token"])
    request = {
        "world_path": world,
        "villager_previews": tokens,
        "server_guard_epoch": body["server_guard_epoch"],
        "server_guard_token": body["server_guard_token"],
    }
    player_request = {"player_key": encode_player_key(b"~local_player"), "base_revision": loaded["player_revision"], "stats": {"health": 30}}
    return key, request, player_request


@pytest.mark.parametrize("name,name_first", [("Egon 🐑", False), ("", False), ("", True)])
@pytest.mark.parametrize("with_player,with_mount", [(False, False), (True, False), (True, True)])
def test_central_save_preserves_three_fields_and_writes_one_backup(villager_client, villager_world, with_player, with_mount, name, name_first):
    world, _ = villager_world
    key, request, player = prepare(villager_client, world, name=name, name_first=name_first)
    original = _records(world)
    prior_backups = list(Path(get_backups_dir(world)).glob("*.zip"))
    if with_player:
        request.update(player)
    if with_mount:
        request["mounts"] = [
            {
                "mount_type": "minecraft:donkey",
                "create_mode": "synthetic_full",
                "tamed": False,
                "allow_unchecked_placement": True,
                "preferred_offset": {"x": 2, "z": 2},
            }
        ]
    response = villager_client.post("/api/workspace/save", json=request)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["success"] and result["write_committed"] and result["atomic_batch"]
    after = _records(world)
    actor = nbt.load(after[key], **LOAD_KWARGS).tag
    assert actor["Attributes"][0]["Current"].py_data == 40
    assert actor["Attributes"][0]["Max"].py_data == 40
    assert actor["ChestItems"][0]["Count"].py_data == 4
    assert actor["ChestItems"][0]["Name"].py_data == "minecraft:carrot"
    assert actor.get("CustomName", nbt.StringTag("")).py_data == name
    old = nbt.load(original[key], **LOAD_KWARGS).tag
    if "CustomName" in actor:
        del actor["CustomName"]
    del old["CustomName"]
    for field in ("Attributes", "ChestItems"):
        del actor[field], old[field]
    assert nbt.NamedTag(actor).save_to(**SAVE_KWARGS) == nbt.NamedTag(old).save_to(**SAVE_KWARGS)
    assert after[b"unrelated-world-record"] == original[b"unrelated-world-record"]
    assert nbt.load(after[b"~local_player"], **LOAD_KWARGS).tag["Health"].py_data == (30 if with_player else 20)
    backups = list(Path(get_backups_dir(world)).glob("*.zip"))
    assert len(backups) == len(prior_backups) + 1
    again = villager_client.post("/api/workspace/save", json=request)
    assert again.status_code >= 400
    assert _records(world) == after
    assert list(Path(get_backups_dir(world)).glob("*.zip")) == backups


@pytest.mark.parametrize("failure", ["tamper", "overlap", "stale", "backup_race"])
def test_refusal_does_not_partially_save_player(villager_client, villager_world, monkeypatch, failure):
    world, _ = villager_world
    _, request, player = prepare(villager_client, world)
    request.update(player)
    if failure == "tamper":
        request["villager_previews"][0] += "bad"
    elif failure == "overlap":
        request["villager_previews"].append(request["villager_previews"][0])
    elif failure == "stale":
        Path(world, "level.dat").write_bytes(b"externally changed")
    else:
        backup = services.create_backup

        def race(*args, **kwargs):
            result = backup(*args, **kwargs)
            Path(world, "level.dat").write_bytes(b"changed during backup")
            return result

        monkeypatch.setattr(services, "create_backup", race)
    before = _records(world)
    prior_backups = list(Path(get_backups_dir(world)).glob("*.zip"))
    response = villager_client.post("/api/workspace/save", json=request)
    assert response.status_code >= 400, response.get_json()
    assert _records(world) == before
    assert list(Path(get_backups_dir(world)).glob("*.zip")) == prior_backups


@pytest.mark.parametrize("with_player", [False, True])
def test_backup_failure_blocks_all_writes(villager_client, villager_world, monkeypatch, with_player):
    world, _ = villager_world
    _, request, player = prepare(villager_client, world)
    if with_player:
        request.update(player)
    before = _records(world)
    prior_backups = list(Path(get_backups_dir(world)).glob("*.zip"))
    monkeypatch.setattr(services if with_player else villager_service, "create_backup", Mock(side_effect=OSError("disk full")))
    response = villager_client.post("/api/workspace/save", json=request)
    assert response.status_code >= 400
    assert _records(world) == before
    assert list(Path(get_backups_dir(world)).glob("*.zip")) == prior_backups


@pytest.mark.parametrize("with_player", [False, True])
def test_reopen_failure_reports_commit_and_keeps_backup(villager_client, villager_world, monkeypatch, with_player):
    import main

    world, _ = villager_world
    key, request, player = prepare(villager_client, world)
    if with_player:
        request.update(player)
    readonly = main.editor_service._open_db_readonly
    writer = main.editor_service._open_db
    opened = False

    def open_writer(path):
        nonlocal opened
        opened = True
        return writer(path)

    def open_reader(path):
        if opened:
            raise OSError("reopen failed")
        return readonly(path)

    monkeypatch.setattr(main.editor_service, "_open_db", open_writer)
    monkeypatch.setattr(main.editor_service, "_open_db_readonly", open_reader)
    response = villager_client.post("/api/workspace/save", json=request)
    result = response.get_json()
    assert response.status_code == 500 and result["write_committed"] is True
    assert result["success"] is False and result["validation_failed"] is True
    assert Path(get_backups_dir(world), result["backup_file"]).is_file()
    after = _records(world)
    assert nbt.load(after[key], **LOAD_KWARGS).tag["Attributes"][0]["Current"].py_data == 40
    assert nbt.load(after[key], **LOAD_KWARGS).tag["ChestItems"][0]["Count"].py_data == 4


def test_audit_error_does_not_turn_committed_workspace_into_retry(villager_client, villager_world, monkeypatch):
    import main

    world, _ = villager_world
    _, request, player = prepare(villager_client, world)
    request.update(player)
    monkeypatch.setattr(main, "audit_event", Mock(side_effect=OSError("audit storage failed")))
    response = villager_client.post("/api/workspace/save", json=request)
    assert response.status_code == 200 and response.get_json()["write_committed"] is True
