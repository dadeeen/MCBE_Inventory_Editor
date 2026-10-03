"""Restore errors must distinguish untouched/rolled-back worlds from unresolved swaps."""

import errno
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from mcbe_editor import backup, restore_recovery
from mcbe_editor.backup_api_routes import RESTORE_OUTCOME_UNKNOWN, BackupRouteDeps, restore_backup
from mcbe_editor.services import BedrockEditorService
from tests.node_runner import run_node


def _recovery_command(world):
    return restore_recovery.recovery_command(str(world), "--confirm-server-stopped")


@pytest.fixture
def restore_case(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    # Without a server host the status is unknown, as in a local installation.
    monkeypatch.delenv("MCBE_SERVER_HOST", raising=False)
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_bytes(b"archived database")
    service = BedrockEditorService({}, {})
    created = service.create_manual_backup(str(world))
    preview = service.preview_backup_restore(str(world), created["backup_file"])
    (world / "db" / "CURRENT").write_bytes(b"current database")
    request = {"world_path": str(world), "backup_file": created["backup_file"], "backup_token": preview["backup_token"]}
    deps = BackupRouteDeps(
        service=service, jsonify=lambda payload: payload, api_error=Mock(), log_api_exception=Mock(),
        json_string=lambda data, key: data[key], require_world_write_allowed=lambda: None,
        require_final_world_write_allowed=lambda operation: None, presence_conflict_response=lambda *args, **kwargs: None,
        audit_event=Mock(), final_write_gate_blocked_error=type("GateError", (Exception,), {}),
    )
    return world, request, deps


@pytest.mark.parametrize("phase", ["original-renamed", "replacement-renamed"])
def test_restore_sync_failure_reports_unknown_outcome_and_retains_recovery(restore_case, monkeypatch, phase):
    world, request, deps = restore_case
    real_sync = backup._fsync_directory
    injected = False

    def sync(directory):
        nonlocal injected
        rollback = list(world.parent.glob(".world_rollback_*"))
        after_rename = not world.exists() if phase == "original-renamed" else world.exists()
        if not injected and Path(directory) == world.parent and rollback and after_rename:
            injected = True
            raise OSError(errno.EIO, "synthetic post-rename sync failure")
        return real_sync(directory)

    with monkeypatch.context() as faults:
        faults.setattr(backup, "_fsync_directory", sync)
        payload, status = restore_backup(request, deps)
    assert injected
    assert status == 500
    assert payload["success"] is False
    assert payload["code"] == "restore_outcome_unknown"
    assert payload["write_outcome_unknown"] is True
    assert payload["reload_required"] is True
    assert "write_committed" not in payload
    assert "rolled_back" not in payload
    # The answer keeps the cause and names the recovery command for the world.
    assert payload["message_key"] == RESTORE_OUTCOME_UNKNOWN
    assert _recovery_command(world) in payload["message"]
    assert "synthetic post-rename sync failure" in payload["message"]
    assert Path(backup.resolve_backup_path(str(world), payload["pre_restore_backup"])).is_file()
    journals = list(world.parent.glob(".mcbe_restore_*.json"))
    rollbacks = list(world.parent.glob(".world_rollback_*"))
    assert len(journals) == len(rollbacks) == 1
    assert (rollbacks[0] / "db" / "CURRENT").read_bytes() == b"current database"
    if phase == "replacement-renamed":
        assert (world / "db" / "CURRENT").read_bytes() == b"archived database"
    else:
        assert not world.exists()
    result = backup.recover_restore_transaction(str(journals[0]))
    assert result["status"] == ("original-restored" if phase == "original-renamed" else "committed-cleaned")
    assert not journals[0].exists()
    assert not rollbacks[0].exists()


@pytest.mark.parametrize("phase", ["first-rename", "replacement-rename", "rollback-rename"])
def test_restore_rename_failures_only_require_reload_when_rollback_is_unresolved(restore_case, monkeypatch, phase):
    world, request, deps = restore_case
    real_replace = os.replace

    def replace(source, target):
        source_path = Path(source)
        if phase == "first-rename" and source_path == world:
            raise OSError(errno.EACCES, "synthetic first rename failure")
        if phase != "first-rename" and source_path.name.startswith(".world_restoring_"):
            raise OSError(errno.EACCES, "synthetic replacement failure")
        if phase == "rollback-rename" and source_path.name.startswith(".world_rollback_"):
            raise OSError(errno.EACCES, "synthetic rollback failure")
        return real_replace(source, target)

    with monkeypatch.context() as faults:
        faults.setattr(backup.os, "replace", replace)
        payload, status = restore_backup(request, deps)
    assert status == 500
    assert Path(backup.resolve_backup_path(str(world), payload["pre_restore_backup"])).is_file()
    if phase == "rollback-rename":
        assert payload["write_outcome_unknown"] is True
        assert payload["reload_required"] is True
        assert list(world.parent.glob(".mcbe_restore_*.json"))
        rollbacks = list(world.parent.glob(".world_rollback_*"))
        assert len(rollbacks) == 1
        # The original world lies in the rollback folder; the answer names it
        # and the command that moves it back.
        assert rollbacks[0].name in payload["message"]
        assert _recovery_command(world) in payload["message"]
        assert restore_recovery.main([str(world), "--confirm-server-stopped"]) == 0
        assert (world / "db" / "CURRENT").read_bytes() == b"current database"
        assert not rollbacks[0].exists()
    else:
        assert "write_outcome_unknown" not in payload
        assert "reload_required" not in payload
        assert (world / "db" / "CURRENT").read_bytes() == b"current database"
        assert not list(world.parent.glob(".mcbe_restore_*.json"))
        assert not list(world.parent.glob(".world_rollback_*"))


@pytest.mark.parametrize(("locale", "opening"), [("de", "Wiederherstellung unterbrochen."), ("en", "Restore interrupted.")])
def test_unknown_restore_value_error_is_not_reported_as_prewrite_rejection(restore_case, locale, opening):
    import main

    _world, request, deps = restore_case
    error = ValueError("post-rename failure")
    error.write_outcome_unknown = True
    error.pre_restore_backup = "safety.zip"
    error.cleanup_warning = "recovery state retained"
    error.source_snapshot_path = "snapshot.zip"
    deps.service.restore_backup = Mock(side_effect=error)
    with main.app.test_request_context("/", headers={"Accept-Language": locale}):
        payload, status = restore_backup(request, deps)
    assert status == 500
    assert payload["code"] == "restore_outcome_unknown"
    assert payload["message"].startswith(opening)
    assert payload["message"].endswith("post-rename failure")
    assert _recovery_command(request["world_path"]) in payload["message"]
    assert payload["write_outcome_unknown"] is True
    assert payload["reload_required"] is True
    assert payload["pre_restore_backup"] == "safety.zip"
    assert payload["cleanup_warning"] == "recovery state retained"
    assert payload["source_snapshot_path"] == "snapshot.zip"


def test_restore_client_invalidates_only_the_matching_uncertain_context():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/api_client.js');
require('./static/backup_restore_logic.js');
async function scenario({ unknown = false, changeWorld = false, changePlayer = false, conflict = false } = {}) {
    let world = 'world-a', player = 'player-a', resets = 0, loads = 0, posts = 0;
    let players = [{ player_key: player }];
    const messages = [], renders = [];
    global.fetch = async url => {
        if (url.endsWith('restore_preview')) return { success: true, backup_token: {} };
        posts++;
        if (conflict && posts === 1) return { success: false, presence_conflict: true };
        if (changeWorld) world = 'world-b';
        if (changePlayer) player = 'player-b';
        return {
            success: false, error: 'Restore failed', pre_restore_backup: 'safety.zip',
            ...(unknown ? { write_outcome_unknown: true, reload_required: true } : {}),
        };
    };
    const controller = MCBEBackupRestoreLogic.createBackupRestoreController({
        getWorldPath: () => world, getCurrentPlayerKey: () => player, getPlayers: () => players,
        setPlayers: value => { players = value; }, parseJsonResponse: async value => value,
        resetLoadedPlayerState: () => { resets++; player = ''; }, confirmPresenceConflict: async () => true,
        loadPlayersList: async () => { loads++; return true; },
        renderPlayersList: () => renders.push('players'), renderPlayerToolOptions: () => renders.push('tools'),
        renderWorldAnalysis: () => renders.push('world'), logStatus: (message, type) => messages.push({ message, type }),
    });
    await controller.restoreBackup('backup.zip');
    assert.equal(posts, conflict ? 2 : 1);
    assert.equal(loads, 0); // An uncertain result is not auto-reloaded as a successful restore.
    assert.equal(resets, unknown && !changeWorld && !changePlayer ? 1 : 0);
    assert.ok(messages.every(entry => entry.type !== 'success'));
    if (resets) {
        assert.equal(player, ''); assert.deepEqual(players, []);
        assert.deepEqual(renders, ['players', 'tools', 'world']);
        assert.equal(messages.at(-1).type, 'error');
    } else {
        assert.equal(player, changePlayer ? 'player-b' : 'player-a');
    }
}
(async () => {
    await scenario();
    await scenario({ unknown: true });
    await scenario({ unknown: true, conflict: true });
    await scenario({ unknown: true, changeWorld: true });
    await scenario({ unknown: true, changePlayer: true });
})().catch(error => { console.error(error); process.exitCode = 1; });
""")
