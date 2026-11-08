"""Independent byte-level and HTTP lifecycle checks for villager changes."""

from __future__ import annotations

import base64
import hashlib
import struct
import time
from threading import Event
from unittest.mock import Mock

from itsdangerous.timed import TimestampSigner

from mcbe_editor import read_operation, villager_api_routes, villager_service
from mcbe_editor.villagers import prepare_health_changes, scan_villagers
from mcbe_editor.world_locks import world_lock_if_free
from mcbe_editor.world_read_jobs import READ_ID_HEADER, WorldReadJobs
from tests.test_villager_workflow import (
    _prepare,
    _preview_request,
    _records,
    villager_client as villager_client,
    villager_world as villager_world,
)


def _string(value):
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack("<H", len(raw)) + raw


def _tag(kind, name, payload):
    return bytes([kind]) + _string(name) + payload


def _integer(name, value, kind=3):
    return _tag(kind, name, struct.pack({1: "<b", 2: "<h", 3: "<i", 4: "<q"}[kind], value))


def _float(name, value):
    return _tag(5, name, struct.pack("<f", value))


def _text(name, value):
    return _tag(8, name, _string(value))


def _compound(name, *children):
    return _tag(10, name, b"".join(children) + b"\x00")


def _list(name, kind, *payloads):
    return _tag(9, name, bytes([kind]) + struct.pack("<i", len(payloads)) + b"".join(payloads))


class _BinaryDb:
    def __init__(self, values):
        self.values = dict(values)

    def iter_items(self):
        return iter(self.values.items())

    def get(self, key):
        return self.values[key]


def _binary_actor(unique_id=-(2**62) + 37, identifier="minecraft:villager_v2"):
    """Encode the test input without using the application's NBT serializer."""
    key = b"actorprefix" + bytes.fromhex("0000000200000001")
    health = b"".join(
        [
            _float("Max", 20),
            _float("Base", 20),
            _text("Name", "minecraft:health"),
            _float("DefaultMax", 20),
            _float("Current", 12),
            _float("DefaultMin", 0),
            _float("Min", 0),
            _text("future_attribute_metadata", b"\xff\\x80\x00"),
            b"\x00",
        ]
    )
    luck = b"".join([_text("Name", "minecraft:luck"), _float("Current", 0), _float("Max", 1024), _float("Base", 0), b"\x00"])
    raw = _compound(
        "",
        _text("identifier", identifier),
        _integer("UniqueID", unique_id, 4),
        _list("Pos", 5, struct.pack("<f", 1.25), struct.pack("<f", 64.5), struct.pack("<f", -1.25)),
        _integer("Variant", 5),
        _integer("TradeTier", 4),
        _integer("TradeExperience", 250),
        _integer("IsBaby", 0, 1),
        _integer("Dead", 0, 1),
        _integer("DeathTime", 0, 2),
        _text("CustomName", "Prüfdorfbewohner"),
        _compound("Offers", _list("Recipes", 10, _compound("", _text("buyA", "opaque-original-trade"), _integer("tier", 4), _integer("uses", 3))[3:])),
        _list("Armor", 10, _compound("", _integer("Count", 1, 1), _text("Name", "minecraft:iron_helmet"))[3:]),
        _compound("internalComponents", _compound("EntityStorageKeyComponent", _text("StorageKey", key[-8:]))),
        _list("Attributes", 10, luck, health),
        _tag(5, "FutureNaN", bytes.fromhex("0100c07f")),
        _text(b"future_\xff_name", b"\xfe\xff\x00\\x80"),
        _tag(7, "FutureBytes", struct.pack("<i", 8) + b"\x00\xff\x05Max\x00\x00"),
    )
    index = b"digp" + struct.pack("<ii", 0, -1)
    record_id = "actor:" + base64.urlsafe_b64encode(key).decode().rstrip("=")
    return key, index, record_id, raw, health


def test_health_patch_matches_independent_binary_offsets_and_keeps_opaque_bytes():
    key, index, record_id, raw, health = _binary_actor()
    original = {key: raw, index: key[-8:], b"unrelated-world-record": b"opaque\xff\x00"}
    db = _BinaryDb(original)
    plan = prepare_health_changes(
        db,
        [{"id": record_id, "revision": hashlib.sha256(raw).hexdigest()}],
        {
            "max_health": 40,
            "current_health": 40,
        },
    )
    assert set(plan.writes) == {key}
    expected = bytearray(raw)
    start = raw.index(health)
    for name in ("Current", "Max", "DefaultMax"):
        needle = bytes([5]) + _string(name)
        offset = start + health.index(needle) + len(needle)
        expected[offset : offset + 4] = struct.pack("<f", 40)
    assert plan.writes[key] == bytes(expected)
    assert db.values == original


def test_binary_scan_keeps_exact_large_identity_and_checks_other_entity_types():
    key, index, record_id, raw, _ = _binary_actor()
    db = _BinaryDb({key: raw, index: key[-8:]})
    row = scan_villagers(db)["villagers"][0]
    assert row["id"] == record_id
    assert row["unique_id"] == str(-(2**62) + 37)
    assert row["profession"]["id"] == "librarian"
    assert row["trade_tier"] == 4 and row["editable"] is True
    db.values[b"actorprefix" + bytes.fromhex("0000000200000002")] = _binary_actor(identifier="minecraft:cow")[3]
    row = scan_villagers(db)["villagers"][0]
    assert row["editable"] is False
    assert "duplicate_unique_id" in {issue["code"] for issue in row["issues"]}


def test_expired_signed_preview_cannot_write(villager_client, villager_world, monkeypatch):
    import main

    world, original = villager_world
    preview, _ = _preview_request(villager_client, world)
    serializer = villager_api_routes._serializer(main.villager_route_deps())
    payload = serializer.loads(preview["preview_token"])
    old_time = int(time.time()) - villager_api_routes.PREVIEW_MAX_AGE - 2
    with monkeypatch.context() as clock:
        clock.setattr(TimestampSigner, "get_timestamp", lambda _self: old_time)
        expired = serializer.dumps(payload)
    result = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": expired})
    assert result.status_code == 409
    assert result.get_json()["code"] == "villager_preview_stale"
    assert _records(world) == original


def test_new_client_guard_cannot_bless_an_old_signed_preview(villager_client, villager_world, monkeypatch):
    import main

    world, original = villager_world
    current = {"token": "guard-at-scan"}
    monkeypatch.setattr(
        main,
        "world_db_access_gate",
        lambda: {
            "allowed": True,
            "read_allowed": True,
            "server_guard_epoch": 1,
            "server_guard_token": current["token"],
        },
    )
    observed = []

    def guard(data):
        observed.append(data.get("server_guard_token"))
        if data.get("server_guard_token") != current["token"]:
            return main.jsonify({"success": False, "code": "server_guard_stale"}), 409
        return None

    monkeypatch.setattr(main, "require_server_guard_current", guard)
    preview, _ = _preview_request(villager_client, world)
    current["token"] = "guard-after-restart"
    result = villager_client.post(
        "/api/villagers/save",
        json={
            "world_path": world,
            "preview_token": preview["preview_token"],
            "server_guard_token": current["token"],
            "server_guard_epoch": 2,
        },
    )
    assert result.status_code == 409
    assert observed[-1] == "guard-at-scan"
    assert _records(world) == original


def test_cancelled_villager_read_closes_reader_and_releases_world_lock(villager_client, villager_world, monkeypatch, tmp_path):
    import main

    world, original = villager_world
    monkeypatch.setattr(main, "WORLD_READ_JOBS", WorldReadJobs(tmp_path / "read-jobs"))
    started, release, closed = Event(), Event(), Event()
    original_scan = villager_service.scan_villagers
    original_open = main.editor_service._open_db_readonly

    def open_reader(path):
        db = original_open(path)
        real_close = db.close

        def close():
            try:
                real_close()
            finally:
                closed.set()

        db.close = close
        return db

    def paused_scan(db):
        started.set()
        while not release.wait(0.02):
            read_operation.checkpoint("entities", current=1)
        return original_scan(db)

    monkeypatch.setattr(main.editor_service, "_open_db_readonly", open_reader)
    monkeypatch.setattr(villager_service, "scan_villagers", paused_scan)
    identifier = "d" * 32
    try:
        response = villager_client.post("/api/villagers/scan", json={"world_path": world}, headers={READ_ID_HEADER: identifier})
        assert response.status_code == 202
        assert started.wait(5)
        cancelled = villager_client.delete(f"/api/world_reads/{identifier}")
        assert cancelled.status_code == 408
        assert cancelled.get_json()["code"] == "read_cancelled"
        assert closed.wait(5)
        result = villager_client.get(f"/api/world_reads/{identifier}")
        assert result.status_code == 408
        assert "villagers" not in result.get_json()
    finally:
        release.set()
        assert closed.wait(5)
    with world_lock_if_free(world) as acquired:
        assert acquired
    assert _records(world) == original


def test_background_detail_and_preview_keep_request_session_and_can_commit(villager_client, villager_world, monkeypatch, tmp_path):
    import main

    world, _ = villager_world
    monkeypatch.setattr(main, "WORLD_READ_JOBS", WorldReadJobs(tmp_path / "read-jobs"))

    def completed_read(endpoint, payload, identifier):
        response = villager_client.post(endpoint, json=payload, headers={READ_ID_HEADER: identifier})
        assert response.status_code == 202
        deadline = time.monotonic() + 5
        while response.status_code == 202 and time.monotonic() < deadline:
            Event().wait(0.01)
            response = villager_client.get(f"/api/world_reads/{identifier}")
        assert response.status_code == 200, response.get_json()
        return response.get_json()

    scanned = completed_read("/api/villagers/scan", {"world_path": world}, "a" * 32)
    row = scanned["villagers"][0]
    detailed = completed_read(
        "/api/villagers/detail",
        {
            "world_path": world,
            "world_revision": scanned["world_revision"],
            "id": row["id"],
            "revision": row["revision"],
        },
        "b" * 32,
    )
    assert detailed["villager"]["id"] == row["id"]
    preview = completed_read(
        "/api/villagers/preview",
        {
            "world_path": world,
            "world_revision": scanned["world_revision"],
            "selection": [{"id": row["id"], "revision": row["revision"]}],
            "changes": {"max_health": 40, "heal": True},
            "server_guard_token": scanned["server_guard_token"],
            "server_guard_epoch": scanned["server_guard_epoch"],
        },
        "c" * 32,
    )
    response = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": preview["preview_token"]})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["changed_count"] == 1
    assert response.get_json()["validation"]["ok"] is True


def test_backup_pruning_failure_retains_committed_outcome_and_verified_data(villager_world, monkeypatch):
    world, _ = villager_world
    service, arguments, plan = _prepare(world)
    monkeypatch.setattr(villager_service, "prune_backups", Mock(side_effect=OSError("backup retention unavailable")))
    result = villager_service.save(service, world, **arguments, pre_write_check=lambda: None)
    assert result["success"] is False and result["write_committed"] is True
    assert result["reload_required"] is True and result["error_phase"] == "post_write"
    assert result["validation"]["ok"] is True
    assert result["validation"]["errors"]
    saved = _records(world)
    assert all(saved[key] == value for key, value in plan.writes.items())


def test_audit_error_cannot_change_successful_commit_to_retryable_failure(villager_client, villager_world, monkeypatch):
    import main

    world, _ = villager_world
    preview, _ = _preview_request(villager_client, world)
    monkeypatch.setattr(main, "audit_event", Mock(side_effect=OSError("audit unavailable")))
    monkeypatch.setattr(main, "log_api_exception", Mock())
    response = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": preview["preview_token"]})
    result = response.get_json()
    assert response.status_code == 200
    assert result["write_committed"] is True and result["success"] is True
    assert result["validation"]["ok"] is True
