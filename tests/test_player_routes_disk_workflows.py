"""Route orchestration with the real services and synthetic on-disk LevelDB.

The HTTP/authentication boundary and server probes are deliberately controlled;
NBT, the Python database engine, revision checks, exports and backups are real.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import db, nbt
from mcbe_editor import player_api_routes as routes
from mcbe_editor.backup import get_backups_dir
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import ensure_valid_world_path
from tests.test_leveldb_readonly import _write_batch
from tests.test_readonly_format_regressions import _world_db


SOURCE = b"~local_player"
TARGET = b"player_server-player"


class GateBlocked(RuntimeError):
    def __init__(self, label):
        super().__init__(f"{label}: server started")
        self.write_gate = {"allowed": False, "server_status": {"status": "online"}}


def _player(xp: int, identity: int) -> bytes:
    return save_player_nbt(
        nbt.NamedTag(
            nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag([], 10),
                    "PlayerGameType": nbt.IntTag(0),
                    "XPLevel": nbt.IntTag(xp),
                    "Health": nbt.FloatTag(20),
                    "UniqueID": nbt.LongTag(identity),
                    "AddonIdentity": nbt.StringTag(f"keep-{identity}"),
                }
            )
        )
    )


def _read(world: Path) -> dict[bytes, bytes]:
    reader = ReadonlyLevelDbAdapter(str(world / "db"))
    try:
        return dict(reader.iter_items())
    finally:
        reader.close()


def _write(world: Path, values: dict[bytes, bytes]) -> None:
    writer = LevelDbWriter(str(world / "db"))
    try:
        writer.put_batch(values)
    finally:
        writer.close()


def _payload(response, status=200):
    if isinstance(response, tuple):
        payload, actual = response
    else:
        payload, actual = response, 200
    assert actual == status, payload
    assert payload["success"] is (status == 200), payload
    return payload


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    world = tmp_path / "world"
    world.mkdir()
    (world / "levelname.txt").write_text("Synthetic route workflow", encoding="utf-8")
    values = {SOURCE: _player(17, 111), TARGET: _player(3, 999), b"unrelated-chunk": b"opaque data"}
    _world_db(world, manifest=b"\x03\x03\x04\x03", wal=_write_batch(1, list(values.items())))
    service = BedrockEditorService({}, {})
    gate = {"allowed": True, "read_allowed": True, "server_status": {"status": "offline"}, "server_guard_epoch": 2, "server_guard_token": "current"}
    audit = []
    gate_calls = []

    def final_gate(label):
        gate_calls.append(label)
        if not gate["allowed"]:
            raise GateBlocked(label)

    # Use the same controlled final gate at the real adapter boundary as at
    # the service callback, without importing the unavailable web framework.
    monkeypatch.setattr(db, "_run_runtime_leveldb_write_guard", final_gate)
    deps = routes.PlayerRouteDeps(
        app_config=SimpleNamespace(is_docker=False, require_server_offline=True, read_only=False),
        service=service,
        jsonify=lambda value: value,
        api_error=lambda error, status=400, **kw: ({"success": False, "error": str(error), **kw}, status),
        log_api_exception=lambda *_: None,
        world_load_hints=lambda _: [],
        json_string=lambda data, key, default="": data.get(key, default),
        json_bool=lambda data, key, default=False: data.get(key, default),
        ensure_valid_world_path=ensure_valid_world_path,
        player_export_dir_for_world=lambda _: str(tmp_path / "exports"),
        require_world_db_access_allowed=lambda: None,
        world_db_access_gate=lambda: gate,
        db_access_block_response=lambda value: ({"success": False, "write_gate": value}, 409),
        require_world_write_allowed=lambda: None,
        require_server_guard_current=lambda _: None,
        require_final_world_write_allowed=final_gate,
        presence_conflict_response=lambda *_a, **_k: None,
        audit_event=lambda *args, **kw: audit.append((args, kw)),
        server_online_epoch=lambda: 2,
        final_write_gate_blocked_error=GateBlocked,
    )
    return SimpleNamespace(world=world, values=values, deps=deps, gate=gate, gate_calls=gate_calls, audit=audit)


def _request(fixture, key=TARGET):
    return {"world_path": str(fixture.world), "player_key": encode_player_key(key)}


def test_read_save_reload_and_stale_second_tab(workflow):
    fixture = workflow
    before = _read(fixture.world)
    listed = _payload(routes.list_players({"world_path": str(fixture.world)}, fixture.deps))
    assert len(listed["players"]) == 2
    request = _request(fixture)
    loaded = _payload(routes.load_player(request, fixture.deps))
    assert _read(fixture.world) == before
    assert loaded["player_server_guard_token"] == "current"
    save = {**request, "base_revision": loaded["player_revision"], "stats": {"xp_level": 8}}
    result = _payload(routes.save_player(save, fixture.deps))
    assert result["backup_file"]
    assert fixture.gate_calls
    after = _read(fixture.world)
    assert load_player_nbt(after[TARGET]).tag["XPLevel"].py_data == 8
    assert after[SOURCE] == before[SOURCE]
    assert after[b"unrelated-chunk"] == before[b"unrelated-chunk"]
    reloaded = _payload(routes.load_player(request, fixture.deps))
    assert reloaded["player_revision"] != loaded["player_revision"]
    backups = list(Path(get_backups_dir(str(fixture.world))).glob("*.zip"))
    _payload(routes.save_player({**save, "stats": {"xp_level": 12}}, fixture.deps), 409)
    assert _read(fixture.world) == after
    assert list(Path(get_backups_dir(str(fixture.world))).glob("*.zip")) == backups


def _prepare_import(fixture):
    exported = _payload(routes.export_player(_request(fixture, SOURCE), fixture.deps))
    preview = _payload(routes.import_player_preview({"world_path": str(fixture.world), "export_zip": exported["export_path"]}, fixture.deps))
    loaded = _payload(routes.load_player(_request(fixture), fixture.deps))
    return {
        "world_path": str(fixture.world),
        "target_player_key": encode_player_key(TARGET),
        "export_zip": exported["export_path"],
        "import_token": preview["import_token"],
        "base_revision": loaded["player_revision"],
        "confirm_overwrite": True,
    }


def test_export_preview_import_roundtrip_keeps_source_and_unrelated_records(workflow):
    request = _prepare_import(workflow)
    assert _read(workflow.world) == workflow.values
    result = _payload(routes.import_player(request, workflow.deps))
    assert result["post_write_validated"] is True
    after = _read(workflow.world)
    assert after[TARGET] == workflow.values[SOURCE]
    assert after[SOURCE] == workflow.values[SOURCE]
    assert after[b"unrelated-chunk"] == workflow.values[b"unrelated-chunk"]
    assert result["backup_file"]


def _prepare_transfer(fixture):
    request = {"world_path": str(fixture.world), "source_player_key": encode_player_key(SOURCE), "target_player_key": encode_player_key(TARGET)}
    preview = _payload(routes.preview_player_state_transfer(request, fixture.deps))
    return {**request, "transfer_token": preview["transfer_token"], "confirm_transfer": True, "server_guard_token": preview["server_guard_token"]}


def test_migration_keeps_target_identity_source_and_unrelated_records(workflow):
    request = _prepare_transfer(workflow)
    assert _read(workflow.world) == workflow.values
    result = _payload(routes.transfer_player_state(request, workflow.deps))
    assert result["backup_file"]
    after = _read(workflow.world)
    target = load_player_nbt(after[TARGET]).tag
    assert target["XPLevel"].py_data == 17
    assert target["UniqueID"].py_data == 999
    assert target["AddonIdentity"].py_data == "keep-999"
    assert after[SOURCE] == workflow.values[SOURCE]
    assert after[b"unrelated-chunk"] == workflow.values[b"unrelated-chunk"]


@pytest.mark.parametrize("operation", ["import", "migration"])
def test_target_changed_since_preview_is_not_overwritten(workflow, operation):
    request = _prepare_import(workflow) if operation == "import" else _prepare_transfer(workflow)
    changed = _player(25, 999)
    _write(workflow.world, {TARGET: changed})
    before = _read(workflow.world)
    handler = routes.import_player if operation == "import" else routes.transfer_player_state
    result = _payload(handler(request, workflow.deps), 409)
    assert result.get("target_revision_stale") or result.get("preview_stale")
    assert _read(workflow.world) == before
    assert not list(Path(get_backups_dir(str(workflow.world))).glob("*.zip"))


@pytest.mark.parametrize("operation", ["save", "import", "migration"])
def test_server_start_at_final_gate_leaves_player_bytes_unchanged(workflow, operation):
    if operation == "save":
        loaded = _payload(routes.load_player(_request(workflow), workflow.deps))
        request = {**_request(workflow), "base_revision": loaded["player_revision"], "stats": {"xp_level": 22}}
        handler = routes.save_player
    elif operation == "import":
        request, handler = _prepare_import(workflow), routes.import_player
    else:
        request, handler = _prepare_transfer(workflow), routes.transfer_player_state
    workflow.gate["allowed"] = False
    result = _payload(handler(request, workflow.deps), 409)
    assert result["code"] == "final_write_gate_blocked"
    assert _read(workflow.world) == workflow.values
    assert not list(Path(get_backups_dir(str(workflow.world))).glob("*.zip"))


def test_reading_an_online_player_marks_its_snapshot_stale(workflow):
    workflow.gate.update(server_status={"status": "online"}, allowed=False)
    loaded = _payload(routes.load_player(_request(workflow), workflow.deps))
    assert loaded["server_guard_stale"] is True
    assert loaded["player_server_guard_token"] != loaded["server_guard_token"]
    assert _read(workflow.world) == workflow.values


def test_export_import_restore_and_followup_save_keep_current_world_and_revisions(workflow):
    request = _prepare_import(workflow)
    for key, xp in [(SOURCE, 29), (TARGET, 9)]:
        selected = _request(workflow, key)
        loaded = _payload(routes.load_player(selected, workflow.deps))
        _payload(routes.save_player({**selected, "base_revision": loaded["player_revision"], "stats": {"xp_level": xp}}, workflow.deps))
    before_import = _read(workflow.world)
    loaded = _payload(routes.load_player(_request(workflow), workflow.deps))
    request["base_revision"] = loaded["player_revision"]

    imported = _payload(routes.import_player(request, workflow.deps))
    assert _read(workflow.world) == {**before_import, TARGET: workflow.values[SOURCE]}
    imported_player = _payload(routes.load_player(_request(workflow), workflow.deps))
    service = workflow.deps.service
    preview = service.preview_backup_restore(str(workflow.world), imported["backup_file"])
    restored = service.restore_backup(str(workflow.world), imported["backup_file"], backup_token=preview["backup_token"])
    assert restored["success"] is True
    assert _read(workflow.world) == before_import

    backups = set(Path(get_backups_dir(str(workflow.world))).glob("*.zip"))
    stale = {**_request(workflow), "base_revision": imported_player["player_revision"], "stats": {"xp_level": 15}}
    _payload(routes.save_player(stale, workflow.deps), 409)
    assert _read(workflow.world) == before_import
    assert set(Path(get_backups_dir(str(workflow.world))).glob("*.zip")) == backups
    reloaded = _payload(routes.load_player(_request(workflow), workflow.deps))
    assert reloaded["stats"]["xp_level"] == 9
    assert reloaded["player_revision"] == loaded["player_revision"]
    _payload(routes.save_player({**stale, "base_revision": reloaded["player_revision"]}, workflow.deps))
    final = _read(workflow.world)
    assert load_player_nbt(final[TARGET]).tag["XPLevel"].py_data == 15
    assert final[SOURCE] == before_import[SOURCE]
    assert final[b"unrelated-chunk"] == before_import[b"unrelated-chunk"]


def test_import_readback_failure_rolls_back_before_followup_migration(workflow, monkeypatch):
    request = _prepare_import(workflow)
    open_readonly = workflow.deps.service._open_db_readonly
    corrupt_once = True

    def open_with_one_failed_readback(path):
        nonlocal corrupt_once
        reader = open_readonly(path)
        read = reader.get

        def get(key):
            nonlocal corrupt_once
            raw = read(key)
            if corrupt_once and key == TARGET and raw == workflow.values[SOURCE]:
                corrupt_once = False
                return b"incomplete post-write read"
            return raw

        reader.get = get
        return reader

    monkeypatch.setattr(workflow.deps.service, "_open_db_readonly", open_with_one_failed_readback)
    failure = _payload(routes.import_player(request, workflow.deps), 500)
    assert corrupt_once is False
    assert failure["code"] == "player_import_rolled_back"
    assert failure["rolled_back"] is True
    assert failure["write_committed"] is False
    assert _read(workflow.world) == workflow.values
    assert (Path(get_backups_dir(str(workflow.world))) / failure["backup_file"]).is_file()

    migrated = _payload(routes.transfer_player_state(_prepare_transfer(workflow), workflow.deps))
    assert migrated["write_committed"] is True
    after = _read(workflow.world)
    target = load_player_nbt(after[TARGET]).tag
    assert target["XPLevel"].py_data == 17
    assert target["UniqueID"].py_data == 999
    assert target["AddonIdentity"].py_data == "keep-999"
    assert after[SOURCE] == workflow.values[SOURCE]
    assert after[b"unrelated-chunk"] == workflow.values[b"unrelated-chunk"]
