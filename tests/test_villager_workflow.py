"""Exercise the villager workflow on real temporary LevelDB files and backups."""

from __future__ import annotations

import os
import struct
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from mcbe_editor import nbt, villager_service
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.service_errors import WriteNotAttemptedError, WriteOutcomeUnknownError
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.villager_preferences import VillagerPreferences


def _actor(suffix: bytes, unique_id: int, health: float = 12) -> bytes:
    # Independent minimal saved-record fixture. The UniqueID deliberately has
    # no numerical relationship to its opaque actor storage key.
    tag = nbt.CompoundTag(
        {
            "identifier": nbt.StringTag("minecraft:villager_v2"),
            "UniqueID": nbt.LongTag(unique_id),
            "Variant": nbt.IntTag(5),
            "TradeTier": nbt.IntTag(4),
            "TradeExperience": nbt.IntTag(250),
            "CustomName": nbt.StringTag("Bibliothekar"),
            "IsBaby": nbt.ByteTag(0),
            "Pos": nbt.ListTag([nbt.FloatTag(1), nbt.FloatTag(64), nbt.FloatTag(1)]),
            "Attributes": nbt.ListTag(
                [
                    nbt.CompoundTag(
                        {
                            "Name": nbt.StringTag("minecraft:health"),
                            "Current": nbt.FloatTag(health),
                            "Max": nbt.FloatTag(20),
                            "Base": nbt.FloatTag(20),
                            "Min": nbt.FloatTag(0),
                            "DefaultMax": nbt.FloatTag(20),
                            "DefaultMin": nbt.FloatTag(0),
                        }
                    )
                ]
            ),
            "internalComponents": nbt.CompoundTag(
                {
                    "EntityStorageKeyComponent": nbt.CompoundTag(
                        {
                            "StorageKey": nbt.StringTag(nbt.utf8_escape_decoder(suffix)),
                        }
                    )
                }
            ),
            "Offers": nbt.CompoundTag(
                {
                    "Recipes": nbt.ListTag(
                        [
                            nbt.CompoundTag(
                                {
                                    "buyA": nbt.CompoundTag({"Name": nbt.StringTag("minecraft:emerald"), "Count": nbt.ByteTag(3)}),
                                    "sell": nbt.CompoundTag({"Name": nbt.StringTag("minecraft:book"), "Count": nbt.ByteTag(1)}),
                                }
                            )
                        ]
                    )
                }
            ),
            "UnknownAddonState": nbt.LongTag(9223372036854775807),
        }
    )
    return nbt.NamedTag(tag, "Entity").save_to(**SAVE_KWARGS)


@pytest.fixture
def villager_world(tmp_path):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text("Villager workflow fixture", encoding="utf-8")
    (world / "level.dat").write_bytes(b"fixture world metadata")
    suffixes = [bytes.fromhex("00000002ff000001"), bytes.fromhex("00000002ff000002")]
    records = {b"actorprefix" + suffix: _actor(suffix, 9007199254740993 + index) for index, suffix in enumerate(suffixes)}
    records[b"digp" + struct.pack("<ii", 0, 0)] = b"".join(suffixes)
    records[b"unrelated-world-record"] = b"opaque bytes\xff\x00"
    db = LevelDbWriter(str(world / "db"))
    db.put_batch(records)
    db.close()
    return str(world), records


def _records(world):
    db = ReadonlyLevelDbAdapter(os.path.join(world, "db"))
    try:
        return dict(db.iter_items())
    finally:
        db.close()


def _prepare(world, service=None):
    service = service or BedrockEditorService({}, {})
    result = villager_service.scan(service, world)
    selection = [{"id": row["id"], "revision": row["revision"]} for row in result["villagers"]]
    changes = {"max_health": 40, "heal": True}
    plan = villager_service.preview(service, world, result["world_revision"], selection, changes)
    assert len(plan.writes) == 2
    return (
        service,
        {"world_revision": result["world_revision"], "selection": selection, "changes": changes, "expected_plan_digest": villager_service.plan_digest(plan)},
        plan,
    )


def test_scan_and_preview_are_read_only_and_batch_preserves_every_other_tag(villager_world):
    world, original = villager_world
    files_before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in (Path(world) / "db").iterdir()}
    service, arguments, plan = _prepare(world)
    files_after = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in (Path(world) / "db").iterdir()}
    assert files_before == files_after
    gates = Mock()
    result = villager_service.save(service, world, **arguments, pre_write_check=gates)
    assert result["success"] is True and result["write_committed"] is True
    assert result["validation"]["ok"] is True
    assert result["changed_count"] == 2
    assert gates.call_count == 3
    after = _records(world)
    assert set(after) == set(original)
    for key in original:
        if not key.startswith(b"actorprefix"):
            assert after[key] == original[key]
            continue
        before_tag = nbt.load(original[key], **LOAD_KWARGS).tag
        after_tag = nbt.load(after[key], **LOAD_KWARGS).tag
        attr = after_tag["Attributes"][0]
        assert attr["Current"].py_data == 40 and attr["Max"].py_data == 40
        assert after[key] == plan.writes[key]
        del before_tag["Attributes"]
        del after_tag["Attributes"]
        assert nbt.NamedTag(before_tag).save_to(**SAVE_KWARGS) == nbt.NamedTag(after_tag).save_to(**SAVE_KWARGS)

    from mcbe_editor.backup import get_backups_dir

    backup = os.path.join(get_backups_dir(world), result["backup_file"])
    with zipfile.ZipFile(backup) as archive:
        assert archive.testzip() is None
        assert any(name.endswith("level.dat") for name in archive.namelist())
    with pytest.raises(villager_service.VillagerSnapshotStaleError):
        villager_service.save(service, world, **arguments, pre_write_check=gates)


def test_backup_failure_never_opens_writer(villager_world, monkeypatch):
    world, original = villager_world
    service, arguments, _ = _prepare(world)
    monkeypatch.setattr(villager_service, "create_backup", Mock(side_effect=OSError("disk full")))
    writer = Mock(side_effect=AssertionError("must not open"))
    monkeypatch.setattr(service, "_open_db", writer)
    with pytest.raises(OSError, match="disk full"):
        villager_service.save(service, world, **arguments, pre_write_check=lambda: None)
    writer.assert_not_called()
    assert _records(world) == original


@pytest.mark.parametrize("stop_at", [1, 2, 3])
def test_final_gate_rejection_never_writes_batch(villager_world, stop_at):
    world, original = villager_world
    service, arguments, _ = _prepare(world)
    calls = 0

    def gate():
        nonlocal calls
        calls += 1
        if calls == stop_at:
            raise WriteNotAttemptedError("server restarted")

    with pytest.raises(WriteNotAttemptedError):
        villager_service.save(service, world, **arguments, pre_write_check=gate)
    assert _records(world) == original


def test_world_change_during_backup_is_rejected(villager_world, monkeypatch):
    world, original = villager_world
    service, arguments, _ = _prepare(world)
    real_backup = villager_service.create_backup

    def changing_backup(*args, **kwargs):
        path = real_backup(*args, **kwargs)
        writer = LevelDbWriter(os.path.join(world, "db"))
        writer.put_batch({b"external-change": b"new"})
        writer.close()
        return path

    monkeypatch.setattr(villager_service, "create_backup", changing_backup)
    with pytest.raises(villager_service.VillagerSnapshotStaleError):
        villager_service.save(service, world, **arguments, pre_write_check=lambda: None)
    assert _records(world) == {**original, b"external-change": b"new"}


def test_revisions_are_rechecked_inside_writer_lock(villager_world, monkeypatch):
    world, original = villager_world
    service, arguments, _ = _prepare(world)
    original_open = service._open_db

    def changed_open(path):
        writer = LevelDbWriter(os.path.join(path, "db"))
        key = next(key for key in original if key.startswith(b"actorprefix"))
        writer.put_batch({key: _actor(key[len(b"actorprefix") :], 9007199254740993, health=11)})
        writer.close()
        return original_open(path)

    monkeypatch.setattr(service, "_open_db", changed_open)
    with pytest.raises(ValueError):
        villager_service.save(service, world, **arguments, pre_write_check=lambda: None)
    for value in _records(world).values():
        if b"minecraft:villager_v2" in value:
            assert nbt.load(value, **LOAD_KWARGS).tag["Attributes"][0]["Max"].py_data == 20


@pytest.mark.parametrize("failure", ["write", "close", "verify"])
def test_errors_after_storage_change_retain_recovery_and_terminal_outcome(villager_world, monkeypatch, failure):
    world, _ = villager_world
    service, arguments, _ = _prepare(world)

    class FailingWriter(LevelDbAdapter):
        def put_batch(self, data):
            super().put_batch(data)
            if failure == "write":
                raise OSError("write response lost")

        def close(self):
            super().close()
            if failure == "close":
                raise OSError("close failed")

    service.db_factory = FailingWriter
    if failure == "verify":
        real_open = service._open_db_readonly
        read_count = 0

        def open_read(path):
            nonlocal read_count
            read_count += 1
            if read_count > 1:
                raise OSError("reopen failed")
            return real_open(path)

        monkeypatch.setattr(service, "_open_db_readonly", open_read)
    if failure == "write":
        with pytest.raises(WriteOutcomeUnknownError) as caught:
            villager_service.save(service, world, **arguments, pre_write_check=lambda: None)
        assert os.path.isfile(caught.value.backup_file)
    else:
        result = villager_service.save(service, world, **arguments, pre_write_check=lambda: None)
        assert result["success"] is False
        assert result["write_committed"] is True
        assert result["error_phase"] == "post_write"
        assert result["reload_required"] is True
        from mcbe_editor.backup import get_backups_dir

        assert os.path.isfile(os.path.join(get_backups_dir(world), result["backup_file"]))


@pytest.fixture
def villager_client(monkeypatch, tmp_path):
    import main

    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, require_server_offline=False, read_only=False))
    monkeypatch.setattr(main, "VILLAGER_PREFERENCES", VillagerPreferences(tmp_path / "preferences"))
    monkeypatch.setattr(main, "CSRF_TOKEN", "villager-test-session")
    monkeypatch.setattr(
        main,
        "write_gate",
        lambda *_args, **_kwargs: {
            "allowed": True,
            "read_allowed": True,
            "server_status": {"status": "offline"},
            "config": {"require_server_offline": False},
        },
    )
    client = main.app.test_client()
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "villager-test-session"
    return client


def _preview_request(client, world):
    response = client.post("/api/villagers/scan", json={"world_path": world})
    assert response.status_code == 200, response.get_json()
    scanned = response.get_json()
    assert {row["unique_id"] for row in scanned["villagers"]} == {"9007199254740993", "9007199254740994"}
    body = {
        "world_path": world,
        "world_revision": scanned["world_revision"],
        "selection": [{"id": row["id"], "revision": row["revision"]} for row in scanned["villagers"]],
        "changes": {"max_health": 40, "heal": True},
        "server_guard_epoch": scanned["server_guard_epoch"],
        "server_guard_token": scanned["server_guard_token"],
    }
    previewed = client.post("/api/villagers/preview", json=body)
    assert previewed.status_code == 200, previewed.get_json()
    return previewed.get_json(), body


def test_real_http_scan_preview_save_and_single_use(villager_client, villager_world):
    world, _ = villager_world
    previewed, body = _preview_request(villager_client, world)
    assert previewed["change_count"] == 2
    assert len(previewed["rows"]) == 2
    response = villager_client.post("/api/villagers/save", json={**body, "preview_token": previewed["preview_token"], "changes": {"max_health": 1}})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["validation"]["ok"] is True
    again = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": previewed["preview_token"]})
    assert again.status_code == 409
    assert again.get_json()["code"] == "villager_snapshot_stale"
    for key, value in _records(world).items():
        if key.startswith(b"actorprefix"):
            assert nbt.load(value, **LOAD_KWARGS).tag["Attributes"][0]["Max"].py_data == 40


@pytest.mark.parametrize("tamper", ["token", "world", "session"])
def test_signed_preview_cannot_cross_world_or_session(villager_client, villager_world, monkeypatch, tmp_path, tamper):
    import main

    world, original = villager_world
    previewed, _ = _preview_request(villager_client, world)
    token = previewed["preview_token"]
    target = world
    if tamper == "token":
        token = "X" + token[1:]
    elif tamper == "world":
        import shutil

        target = str(tmp_path / "copy")
        shutil.copytree(world, target)
    else:
        monkeypatch.setattr(main, "CSRF_TOKEN", "different-session")
        villager_client.environ_base["HTTP_X_CSRF_TOKEN"] = "different-session"
    result = villager_client.post("/api/villagers/save", json={"world_path": target, "preview_token": token})
    assert result.status_code == 409
    assert result.get_json()["code"] == "villager_preview_stale"
    assert _records(world) == original


@pytest.mark.parametrize("endpoint", ["save", "preferences"])
def test_readonly_mode_rejects_villager_mutations(villager_client, monkeypatch, endpoint):
    import main

    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, read_only=True))
    response = villager_client.post(f"/api/villagers/{endpoint}", json={})
    assert response.status_code == 403
    assert response.get_json()["code"] == "read_only"


@pytest.mark.parametrize("endpoint", ["scan", "detail", "preview", "save", "preferences"])
def test_villager_routes_require_csrf(villager_client, endpoint):
    response = villager_client.post(f"/api/villagers/{endpoint}", json={}, headers={"X-CSRF-Token": "wrong"})
    assert response.status_code == 403
