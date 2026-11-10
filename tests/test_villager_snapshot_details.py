"""Browsing retained scan bytes cannot authorize writes or replace old identities."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask

from mcbe_editor import villager_service
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.villager_directory import VillagerDirectory
from tests.test_villager_workflow import _actor, _records
from tests.test_villager_workflow import villager_client as villager_client
from tests.test_villager_workflow import villager_world as villager_world


def change_resident(world, records):
    key = next(key for key in records if key.startswith(b"actorprefix"))
    with_db = LevelDbWriter(str(Path(world) / "db"))
    try:
        with_db.put(key, _actor(key[len(b"actorprefix") :], 9007199254740993, health=3))
    finally:
        with_db.close()


def test_two_scan_revisions_keep_their_own_details_without_opening_the_database(villager_world, monkeypatch):
    world, records = villager_world
    service = BedrockEditorService({}, {})
    old = villager_service.scan(service, world)
    change_resident(world, records)
    new = villager_service.scan(service, world)
    open_db = Mock(side_effect=AssertionError("Snapshot browsing must not open the live database"))
    monkeypatch.setattr(service, "_open_db_readonly", open_db)
    for scanned, health in [(old, 12), (new, 3)]:
        row = scanned["villagers"][0]
        detail = villager_service.detail(service, world, row["id"], row["revision"], scanned["world_revision"])
        assert detail["health"]["current"] == health
        detail["nbt"]["value"].clear()
        assert villager_service.detail(service, world, row["id"], row["revision"], scanned["world_revision"])["nbt"]["value"]
    open_db.assert_not_called()
    with pytest.raises(ValueError, match="verändert"):
        villager_service.detail(service, world, old["villagers"][0]["id"], "0" * 64, old["world_revision"])


@pytest.mark.parametrize("online", [False, True])
def test_http_details_report_stale_scan_and_never_enable_world_writes(villager_client, villager_world, monkeypatch, online):
    import main

    world, records = villager_world
    scanned = villager_client.post("/api/villagers/scan", json={"world_path": world}).get_json()
    row = scanned["villagers"][0]
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
    else:
        change_resident(world, records)
    before = _records(world)
    opener = Mock(side_effect=AssertionError("Cached HTTP details must not open a database"))
    monkeypatch.setattr(main.editor_service, "_open_db_readonly", opener)
    body = {"world_path": world, "world_revision": scanned["world_revision"], "id": row["id"], "revision": row["revision"]}
    response = villager_client.post("/api/villagers/detail", json=body)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["snapshot_stale"] is True
    assert response.get_json()["villager"]["health"]["current"] == 12
    preview = villager_client.post(
        "/api/villagers/preview",
        json={
            **body,
            "server_guard_token": scanned["server_guard_token"],
            "server_guard_epoch": scanned["server_guard_epoch"],
            "selection": [{"id": row["id"], "revision": row["revision"]}],
            "changes": {"heal": True},
        },
    )
    assert preview.status_code == 409, preview.get_json()
    opener.assert_not_called()
    assert _records(world) == before


@pytest.mark.parametrize("limit", [0, 1])
def test_evicted_scan_never_falls_back_to_newer_world_data(villager_world, monkeypatch, limit):
    world, records = villager_world
    service = BedrockEditorService({}, {})
    service._villager_directory = VillagerDirectory(max_entries=limit)
    old = villager_service.scan(service, world)
    row = old["villagers"][0]
    assert villager_service.detail(service, world, row["id"], row["revision"], old["world_revision"])["health"]["current"] == 12
    change_resident(world, records)
    villager_service.scan(service, world)
    opener = Mock(side_effect=AssertionError("A different world revision must not be read"))
    monkeypatch.setattr(service, "_open_db_readonly", opener)
    with pytest.raises(villager_service.VillagerSnapshotUnavailableError, match="nicht mehr verfügbar"):
        villager_service.detail(service, world, row["id"], row["revision"], old["world_revision"])
    opener.assert_not_called()


def test_http_reports_unavailable_details_after_snapshot_eviction(villager_client, villager_world, monkeypatch):
    import main

    world, records = villager_world
    main.editor_service._villager_directory = VillagerDirectory(max_entries=1)
    old = villager_client.post("/api/villagers/scan", json={"world_path": world}).get_json()
    row = old["villagers"][0]
    change_resident(world, records)
    assert villager_client.post("/api/villagers/scan", json={"world_path": world}).status_code == 200
    opener = Mock(side_effect=AssertionError("An evicted scan cannot reopen a changed database"))
    monkeypatch.setattr(main.editor_service, "_open_db_readonly", opener)
    response = villager_client.post(
        "/api/villagers/detail",
        json={"world_path": world, "world_revision": old["world_revision"], "id": row["id"], "revision": row["revision"]},
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "villager_snapshot_unavailable"
    assert "nicht mehr verfügbar" in response.get_json()["error"]
    opener.assert_not_called()


def test_unfinished_scan_does_not_publish_browsable_details(villager_world, monkeypatch):
    world, _ = villager_world
    service = BedrockEditorService({}, {})
    original = service._villager_directory.snapshot

    def changing_world(db):
        snapshot = original(db)
        (Path(world) / "level.dat").write_bytes(b"changed during scan")
        return snapshot

    monkeypatch.setattr(service._villager_directory, "snapshot", changing_world)
    with pytest.raises(villager_service.VillagerSnapshotStaleError):
        villager_service.scan(service, world)
    assert not service._villager_directory._scans


def test_retained_scan_keys_are_bounded_and_world_and_locale_specific(villager_world):
    world, _ = villager_world
    service = BedrockEditorService({}, {})
    scanned = villager_service.scan(service, world)
    row = scanned["villagers"][0]
    directory = service._villager_directory
    arguments = (scanned["world_revision"], row["id"], row["revision"])
    assert directory.scanned_detail(world + "-other", *arguments) is None
    app = Flask(__name__)
    with app.test_request_context(headers={"Accept-Language": "en"}):
        assert directory.scanned_detail(world, *arguments) is None
    snapshot = next(iter(directory._entries.values()))
    for index in range(100):
        directory.remember_scan(world, str(index), snapshot)
    assert len(directory._scans) == directory._max_entries
    assert len(directory._entries) == 1
