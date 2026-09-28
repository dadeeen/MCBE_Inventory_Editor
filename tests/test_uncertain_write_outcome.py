"""Storage failures must not become apparently safe retries at the API boundary.

Failures the writer proves happened before any batch byte was written stay
ordinary rejections with their own cause, such as a denied log creation.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from mcbe_editor import db, leveldb_writer, mount_api_routes, mount_write, nbt, player_api_routes, services
from mcbe_editor.backup import create_backup, get_backups_dir
from mcbe_editor.bedrock_nbt import LOAD_KWARGS
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter
from mcbe_editor.leveldb_writer import LevelDbWriter
from tests.test_workspace_save import _synthetic_mount_workspace


def _response(result):
    # Routes return (payload, status); the fixture's api_error returns a payload.
    if isinstance(result, tuple):
        return result
    return result, result.get("status", 400)


@pytest.mark.parametrize("operation", ["player", "workspace", "mount"])
@pytest.mark.parametrize("failure", ["before-write", "log-denied", "after-memory", "after-permission", "late-gate"])
def test_real_writer_failure_preserves_backup_and_reports_outcome(tmp_path, monkeypatch, operation, failure):
    import main

    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    fixture = _synthetic_mount_workspace(tmp_path, monkeypatch)
    world = fixture.request["world_path"]
    path = str(Path(world) / "db")
    original_player = fixture.values[b"~local_player"]
    writer = LevelDbWriter(path)
    try:
        writer.put_batch(fixture.values)
    finally:
        writer.close()

    class FailingMemtable(dict):
        def __setitem__(self, key, value):
            error = PermissionError if failure == "after-permission" else MemoryError
            raise error("injected bookkeeping failure after durable write")

    class FaultingWriter(LevelDbWriter):
        def put_batch(self, entries):
            if failure == "before-write":
                raise OSError("injected failure before writing")
            if failure == "late-gate":
                raise main.FinalWriteGateBlockedError("Speichern", {"reason": "Server gestartet"})
            self._memtable = FailingMemtable(self._memtable)
            return super().put_batch(entries)

    def log_denied(_self, path):
        raise PermissionError(13, "Permission denied", path)

    if failure == "log-denied":
        # Existing files stay writable, but the db folder refuses a new file.
        monkeypatch.setattr(leveldb_writer._SessionLog, "__init__", log_denied)
    else:
        monkeypatch.setattr(db, "LevelDbWriter", FaultingWriter)
    monkeypatch.setattr(db, "_run_runtime_leveldb_write_guard", lambda *_: None)
    for module in (services, mount_write):
        monkeypatch.setattr(module, "create_backup", create_backup)
    service = fixture.deps.service
    service.db_factory = db.LevelDbAdapter
    service.readonly_db_factory = ReadonlyLevelDbAdapter
    mount_deps = replace(fixture.deps, final_write_gate_blocked_error=main.FinalWriteGateBlockedError)
    player_deps = replace(
        main.player_route_deps(), service=service, jsonify=lambda value: value,
        api_error=fixture.deps.api_error, log_api_exception=lambda *_: None,
        audit_event=lambda *_args, **_kwargs: None,
        require_world_write_allowed=lambda: None,
        require_server_guard_current=lambda _: None,
        require_final_world_write_allowed=lambda _: None,
        presence_conflict_response=lambda *_args, **_kwargs: None,
    )
    request = fixture.request
    mount = {"mount_type": "minecraft:donkey", "create_mode": "synthetic_full", "tamed": False,
             "allow_unchecked_placement": True, "preferred_offset": {"x": 2, "z": 2}}
    if operation == "player":
        result = player_api_routes.save_player({**request, "stats": {"health": 18}}, player_deps)
    elif operation == "workspace":
        result = mount_api_routes.save_workspace({**request, "mounts": [mount]}, mount_deps, player_deps)
    else:
        result = mount_api_routes.create_mount({**request, **mount}, mount_deps)

    payload, status = _response(result)
    backups = list(Path(get_backups_dir(world)).glob("*.zip"))
    assert len(backups) == 1
    assert payload["success"] is False
    assert "write_committed" not in payload
    if failure == "late-gate":
        assert status == 409
        assert payload["code"] == "final_write_gate_blocked"
        assert "write_outcome_unknown" not in payload
    elif failure in {"before-write", "log-denied"}:
        # The writer proves that no batch byte was written: an ordinary,
        # retryable rejection that keeps its actual cause.
        assert "write_outcome_unknown" not in payload
        assert "Nicht erneut speichern" not in payload["error"]
        if failure == "log-denied":
            assert "verweigert Zugriff" in payload["error"]
            # Each route keeps its ordinary status for this rejection.
            assert status == {"player": 409, "workspace": 400, "mount": 500}[operation]
        else:
            assert "injected failure before writing" in payload["error"]
    else:
        assert status == 500
        assert payload["code"] == "write_outcome_unknown"
        assert payload["write_outcome_unknown"] is True
        assert payload["reload_required"] is True
        assert payload["backup_file"] == backups[0].name
        assert "Nicht erneut speichern" in payload["error"]

    reader = ReadonlyLevelDbAdapter(path)
    try:
        values = dict(reader.iter_items())
    finally:
        reader.close()
    # Prove that the failure actually happened after the entire batch reached
    # disk; the API must neither claim a rollback nor a confirmed success.
    persisted = failure.startswith("after-")
    if operation == "player" and persisted:
        assert nbt.load(values[b"~local_player"], **LOAD_KWARGS).tag["Health"].py_data == 18
    else:
        assert values[b"~local_player"] == original_player
    actors = [key for key in values if key.startswith(b"actorprefix")]
    assert len(actors) == int(persisted and operation != "player")

