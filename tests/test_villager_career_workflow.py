"""HTTP, disk and transaction checks for villager careers in real world copies."""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import pytest

from mcbe_editor import nbt, villager_service
from mcbe_editor.backup import get_backups_dir
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.villager_career import CAREER_FIELDS
from tests import test_villager_workflow as workflow
from tests import test_workspace_villagers as workspace
from tests.test_villager_career import career_tag

villager_world = workflow.villager_world
villager_client = workflow.villager_client


def write_metadata(world, experiments=None):
    tag = nbt.CompoundTag({"LevelName": nbt.StringTag("Career integration fixture")})
    if experiments is not None:
        tag["experiments"] = experiments
    raw = nbt.NamedTag(tag).save_to(**SAVE_KWARGS)
    Path(world, "level.dat").write_bytes(struct.pack("<II", 10, len(raw)) + raw)


@pytest.fixture
def career_world(villager_world, tmp_path, monkeypatch):
    world, records = villager_world
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "career-backups"))
    updates = {}
    for key, raw in records.items():
        if not key.startswith(b"actorprefix"):
            continue
        actor = nbt.load(raw, **LOAD_KWARGS)
        for name, value in career_tag().items():
            if name not in {"UniqueID", "Pos", "internalComponents"}:
                actor.tag[name] = value
        updates[key] = actor.save_to(**SAVE_KWARGS)
    writer = LevelDbWriter(str(Path(world, "db")))
    try:
        writer.put_batch(updates)
    finally:
        writer.close()
    write_metadata(world)
    return world, workflow._records(world)


def scan_request(client, world):
    response = client.post("/api/villagers/scan", json={"world_path": world})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def preview_body(scanned, world, changes):
    row = scanned["villagers"][0]
    return {
        "world_path": world,
        "world_revision": scanned["world_revision"],
        "selection": [{"id": row["id"], "revision": row["revision"]}],
        "changes": changes,
        "server_guard_epoch": scanned["server_guard_epoch"],
        "server_guard_token": scanned["server_guard_token"],
    }


def career_preview(client, world, changes=None):
    scanned = scan_request(client, world)
    body = preview_body(scanned, world, {"career": changes or {"profession": "farmer", "trade_tier": 2}})
    response = client.post("/api/villagers/preview", json=body)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["change_count"] == 1 and result["preview_token"]
    return result, body


def backups(world):
    return sorted(Path(get_backups_dir(world)).glob("*.zip"))


def staged_request(client, world, *, with_player=False, career_first=False):
    key, request, player = workspace.prepare(client, world)
    preview, _body = career_preview(client, world)
    request["villager_previews"].insert(0 if career_first else len(request["villager_previews"]), preview["preview_token"])
    if with_player:
        request.update(player)
    return key, request


def test_direct_http_career_scan_detail_preview_signed_save_and_reopen(villager_client, career_world):
    world, original = career_world
    scanned = scan_request(villager_client, world)
    row = scanned["villagers"][0]
    assert row["career_editable"] and row["career"]["tier_editable"]
    detail = villager_client.post(
        "/api/villagers/detail",
        json={
            "world_path": world,
            "world_revision": scanned["world_revision"],
            "id": row["id"],
            "revision": row["revision"],
        },
    )
    assert detail.status_code == 200, detail.get_json()
    assert len(detail.get_json()["villager"]["career"]["professions"]) == 14
    assert workflow._records(world) == original
    preview, body = career_preview(villager_client, world)
    assert preview["rows"][0]["kind"] == "career" and preview["rows"][0]["warnings"]
    assert workflow._records(world) == original and not backups(world)

    response = villager_client.post(
        "/api/villagers/save",
        json={
            **body,
            "preview_token": preview["preview_token"],
            "changes": {"career": {"profession": "armorer", "trade_tier": 4}},
        },
    )
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["success"] and result["write_committed"] and result["validation"]["ok"]
    after = workflow._records(world)
    changed = [key for key in after if after[key] != original[key]]
    assert len(changed) == 1
    key = changed[0]
    actor = nbt.load(after[key], **LOAD_KWARGS).tag
    assert actor["Variant"].py_data == 1 and actor["PreferredProfession"].py_data == "farmer"
    assert actor["TradeTier"].py_data == 2 and actor["TradeExperience"].py_data == 70
    assert "Offers" not in actor
    before_actor = nbt.load(original[key], **LOAD_KWARGS).tag
    for name in set(before_actor) - CAREER_FIELDS:
        assert before_actor[name].save_to() == actor[name].save_to(), name
    assert set(after) == set(original)
    assert len(backups(world)) == 1
    with zipfile.ZipFile(backups(world)[0]) as archive:
        assert archive.testzip() is None
        assert any(name.endswith("level.dat") for name in archive.namelist())
    again = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": preview["preview_token"]})
    assert again.status_code == 409
    assert workflow._records(world) == after and len(backups(world)) == 1


@pytest.mark.parametrize("with_player", [False, True])
@pytest.mark.parametrize("career_first", [False, True])
def test_central_save_composes_career_health_name_and_inventory_once(villager_client, career_world, with_player, career_first):
    world, _records = career_world
    key, request = staged_request(villager_client, world, with_player=with_player, career_first=career_first)
    before = workflow._records(world)
    response = villager_client.post("/api/workspace/save", json=request)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["success"] and result["write_committed"] and result["atomic_batch"]
    after = workflow._records(world)
    actor = nbt.load(after[key], **LOAD_KWARGS).tag
    assert actor["Variant"].py_data == 1 and actor["TradeExperience"].py_data == 70
    assert actor["TradeTier"].py_data == 2 and "Offers" not in actor
    assert actor["Attributes"][0]["Current"].py_data == actor["Attributes"][0]["Max"].py_data == 40
    assert actor["CustomName"].py_data == "Egon 🐑"
    assert actor["ChestItems"][0]["Name"].py_data == "minecraft:carrot" and actor["ChestItems"][0]["Count"].py_data == 4
    original_actor = nbt.load(before[key], **LOAD_KWARGS).tag
    for name in set(original_actor) - CAREER_FIELDS - {"Attributes", "CustomName", "ChestItems"}:
        assert actor[name].save_to() == original_actor[name].save_to(), name
    assert set(after) == set(before)
    for other_key in before:
        if not other_key.startswith(b"actorprefix") and other_key != b"~local_player":
            assert after[other_key] == before[other_key]
    assert nbt.load(after[b"~local_player"], **LOAD_KWARGS).tag["Health"].py_data == (30 if with_player else 20)
    assert len(backups(world)) == 1


@pytest.mark.parametrize("with_player", [False, True])
def test_two_career_previews_for_same_actor_are_rejected_without_partial_save(villager_client, career_world, with_player):
    world, _records = career_world
    _key, request = staged_request(villager_client, world, with_player=with_player)
    second, _body = career_preview(villager_client, world, {"trade_tier": 1})
    request["villager_previews"].append(second["preview_token"])
    original = workflow._records(world)
    response = villager_client.post("/api/workspace/save", json=request)
    assert response.status_code >= 400, response.get_json()
    assert workflow._records(world) == original and not backups(world)


@pytest.mark.parametrize("failure", ["signature", "actor", "behavior_pack"])
def test_career_refusal_preserves_staged_player_and_every_other_record(villager_client, career_world, failure):
    world, _records = career_world
    key, request = staged_request(villager_client, world, with_player=True)
    if failure == "signature":
        request["villager_previews"][-1] += "bad"
    elif failure == "actor":
        actor = nbt.load(workflow._records(world)[key], **LOAD_KWARGS)
        actor.tag["UnknownAddonState"] = nbt.LongTag(5)
        writer = LevelDbWriter(str(Path(world, "db")))
        try:
            writer.put_batch({key: actor.save_to(**SAVE_KWARGS)})
        finally:
            writer.close()
    else:
        Path(world, "world_behavior_packs.json").write_text('[{"pack_id":"fixture","version":[1,0,0]}]', encoding="utf-8")
    original = workflow._records(world)
    response = villager_client.post("/api/workspace/save", json=request)
    assert response.status_code >= 400, response.get_json()
    assert workflow._records(world) == original and not backups(world)


@pytest.mark.parametrize(
    "context", ["active_pack", "malformed_packs", "wrong_packs_shape", "deep_packs", "rebalance", "bad_rebalance_type", "bad_experiments", "bad_metadata"]
)
def test_world_context_disables_only_career_and_api_preview_cannot_bypass_it(villager_client, career_world, context):
    world, original = career_world
    if context == "active_pack":
        Path(world, "world_behavior_packs.json").write_text('[{"pack_id":"fixture","version":[1,0,0]}]', encoding="utf-8")
    elif context == "malformed_packs":
        Path(world, "world_behavior_packs.json").write_text("[broken", encoding="utf-8")
    elif context == "wrong_packs_shape":
        Path(world, "world_behavior_packs.json").write_text("{}", encoding="utf-8")
    elif context == "deep_packs":
        Path(world, "world_behavior_packs.json").write_text("[" * 1500 + "]" * 1500, encoding="utf-8")
    elif context == "rebalance":
        write_metadata(world, nbt.CompoundTag({"villager_trades_rebalance": nbt.ByteTag(1)}))
    elif context == "bad_rebalance_type":
        write_metadata(world, nbt.CompoundTag({"villager_trades_rebalance": nbt.StringTag("false")}))
    elif context == "bad_experiments":
        write_metadata(world, nbt.StringTag("unknown"))
    else:
        Path(world, "level.dat").write_bytes(b"invalid metadata")
    scanned = scan_request(villager_client, world)
    row = scanned["villagers"][0]
    assert not row["career_editable"] and not row["career"]["tier_editable"] and row["career"]["reason"]
    assert row["editable"] and row["name_editable"]
    body = preview_body(scanned, world, {"career": {"profession": "farmer"}})
    response = villager_client.post("/api/villagers/preview", json=body)
    assert response.status_code == 400, response.get_json()
    allowed = villager_client.post("/api/villagers/preview", json={**body, "changes": {"name": "Still editable"}})
    assert allowed.status_code == 200 and allowed.get_json()["change_count"] == 1
    assert workflow._records(world) == original and not backups(world)


def test_resource_packs_unrelated_experiments_and_history_flags_allow_vanilla_career(villager_client, career_world):
    world, _records = career_world
    Path(world, "world_resource_packs.json").write_text(json.dumps([{"pack_id": "fixture", "version": [1, 0, 0]}]), encoding="utf-8")
    Path(world, "world_behavior_packs.json").write_text("[]", encoding="utf-8")
    write_metadata(
        world,
        nbt.CompoundTag(
            {
                "villager_trades_rebalance": nbt.ByteTag(0),
                "experiments_ever_used": nbt.ByteTag(1),
                "saved_with_toggled_experiments": nbt.ByteTag(1),
                "upcoming_creator_features": nbt.ByteTag(1),
            }
        ),
    )
    preview, _body = career_preview(villager_client, world)
    assert preview["change_count"] == 1


def test_cached_scan_and_detail_recover_after_behavior_pack_is_removed(career_world):
    world, _records = career_world
    service = BedrockEditorService({}, {})
    initial = villager_service.scan(service, world)
    row = initial["villagers"][0]
    arguments = (service, world, row["id"], row["revision"], initial["world_revision"])
    assert villager_service.detail(*arguments)["career_editable"]
    path = Path(world, "world_behavior_packs.json")
    path.write_text('[{"pack_id":"fixture","version":[1,0,0]}]', encoding="utf-8")
    blocked = villager_service.scan(service, world)
    assert blocked["world_revision"] == initial["world_revision"]
    assert not blocked["villagers"][0]["career_editable"]
    assert not villager_service.detail(*arguments)["career_editable"]
    path.unlink()
    assert villager_service.scan(service, world)["villagers"][0]["career_editable"]
    assert villager_service.detail(*arguments)["career_editable"]
    assert initial["villagers"][0]["career_editable"]


@pytest.mark.parametrize("mode,final_call", [("direct", 3), ("workspace", 3), ("workspace_player", 4)])
def test_context_activated_at_final_gate_prevents_database_batch(villager_client, career_world, monkeypatch, mode, final_call):
    import main

    world, _records = career_world
    if mode == "direct":
        preview, body = career_preview(villager_client, world)
        endpoint = "/api/villagers/save"
        request = {**body, "preview_token": preview["preview_token"]}
        label = "Dorfbewohner speichern"
    else:
        _key, request = staged_request(villager_client, world, with_player=mode == "workspace_player")
        endpoint, label = "/api/workspace/save", "Workspace speichern"
    original = workflow._records(world)
    real_gate = main.require_final_world_write_allowed
    calls = 0

    def gate(action):
        nonlocal calls
        real_gate(action)
        if action == label:
            calls += 1
            if calls == final_call:
                Path(world, "world_behavior_packs.json").write_text('[{"pack_id":"fixture","version":[1,0,0]}]', encoding="utf-8")

    monkeypatch.setattr(main, "require_final_world_write_allowed", gate)
    response = villager_client.post(endpoint, json=request)
    assert response.status_code >= 400, response.get_json()
    assert calls == final_call
    assert workflow._records(world) == original and not backups(world)


@pytest.mark.parametrize("mode", ["direct", "workspace", "workspace_player"])
@pytest.mark.parametrize("changed", ["behavior_pack", "world_metadata"])
def test_context_change_during_adapter_gate_prevents_every_workspace_write(villager_client, career_world, monkeypatch, mode, changed):
    import main

    world, _records = career_world
    if mode == "direct":
        preview, body = career_preview(villager_client, world)
        endpoint = "/api/villagers/save"
        request = {**body, "preview_token": preview["preview_token"]}
    else:
        _key, request = staged_request(villager_client, world, with_player=mode == "workspace_player")
        endpoint = "/api/workspace/save"
    original = workflow._records(world)
    database_files = {path.name: path.read_bytes() for path in Path(world, "db").iterdir()}
    real_gate = main.require_final_world_write_allowed
    adapter_checks = 0

    def gate(action):
        nonlocal adapter_checks
        real_gate(action)
        if action == "LevelDB-Batch-Schreiben":
            # The adapter runs its own server gate after all service checks.
            # LevelDB's writer lock cannot prevent either metadata change.
            adapter_checks += 1
            if changed == "behavior_pack":
                Path(world, "world_behavior_packs.json").write_text('[{"pack_id":"fixture","version":[1,0,0]}]', encoding="utf-8")
            else:
                Path(world, "level.dat").write_bytes(b"world metadata changed during the final adapter gate")

    monkeypatch.setattr(main, "require_final_world_write_allowed", gate)
    response = villager_client.post(endpoint, json=request)
    result = response.get_json()
    assert response.status_code == (400 if changed == "behavior_pack" else 409), result
    assert adapter_checks == 1 and not result.get("write_committed")
    assert workflow._records(world) == original and not backups(world)
    assert {path.name: path.read_bytes() for path in Path(world, "db").iterdir()} == database_files
