"""Exercise operator recovery against real journals and synthetic world folders."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import backup, restore_recovery, server_status
from mcbe_editor.config import load_config


def _world(path: Path, contents: bytes) -> None:
    (path / "db").mkdir(parents=True)
    (path / "db" / "state.dat").write_bytes(contents)


def _tree_contents(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


@pytest.fixture
def interrupted_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    monkeypatch.setenv("MCBE_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("MCBE_REQUIRE_SERVER_OFFLINE", "true")
    monkeypatch.setenv("MCBE_READ_ONLY", "false")
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "app-data"))
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "app-data" / "backups"))
    root = tmp_path / "worlds"
    world = root / "world"
    transaction_id = "0123456789abcdef"
    rollback = root / f".world_rollback_interrupted_{transaction_id}"
    staging = root / ".world_restoring_interrupted"
    _world(rollback, b"original world")
    _world(staging, b"selected backup")
    journal = Path(backup._write_restore_transaction(str(root), world.name, str(rollback), str(staging), transaction_id))
    return SimpleNamespace(root=root, world=world, rollback=rollback, staging=staging, journal=journal)


def _mock_server_probe(monkeypatch, status: str) -> list[tuple[str, int]]:
    calls = []

    def probe(host, port):
        calls.append((host, port))
        return {"status": status, "message": f"Synthetic server status: {status}"}

    # Keep check_server_status and write_gate real; only replace the UDP probe.
    monkeypatch.setattr(server_status, "_bedrock_unconnected_ping", probe)
    return calls


@pytest.mark.parametrize("status,confirmed,read_only,require_offline,reason", [
    ("unknown", False, False, True, "unbekannt"),
    ("online", True, False, False, "Server läuft noch"),
    ("unknown", True, True, True, "Read-Only-Modus"),
])
def test_recovery_cli_blocked_gate_preserves_every_candidate(
    interrupted_restore, monkeypatch, capsys, status, confirmed, read_only, require_offline, reason,
):
    state = interrupted_restore
    monkeypatch.setenv("MCBE_REQUIRE_SERVER_OFFLINE", str(require_offline).lower())
    monkeypatch.setenv("MCBE_READ_ONLY", str(read_only).lower())
    calls = _mock_server_probe(monkeypatch, status)
    before = _tree_contents(state.root)
    args = [str(state.world)]  # The world itself is absent after the first rename.
    if confirmed:
        args.append("--confirm-server-stopped")

    assert restore_recovery.main(args) == 1

    result, = json.loads(capsys.readouterr().out)
    assert result["status"] == "deferred-write-gate"
    assert reason in result["reason"]
    assert result["world_path"] == str(state.world)
    assert _tree_contents(state.root) == before
    assert not state.world.exists()
    assert len(calls) == 1


@pytest.mark.parametrize("path_kind", ["scan_root", "missing_world", "configured_root"])
def test_recovery_cli_confirmed_unknown_restores_original_and_is_idempotent(interrupted_restore, monkeypatch, capsys, path_kind):
    state = interrupted_restore
    calls = _mock_server_probe(monkeypatch, "unknown")
    monkeypatch.setattr(restore_recovery, "get_configured_scan_roots", lambda **_kwargs: [{"path": str(state.root)}])
    args = ["--confirm-server-stopped"]
    if path_kind != "configured_root":
        args.append(str(state.root if path_kind == "scan_root" else state.world))

    assert restore_recovery.main(args) == 0

    result, = json.loads(capsys.readouterr().out)
    assert result == {"status": "original-restored", "world_path": str(state.world)}
    assert (state.world / "db" / "state.dat").read_bytes() == b"original world"
    assert not state.rollback.exists()
    assert not state.staging.exists()
    assert not state.journal.exists()
    after = _tree_contents(state.root)
    assert restore_recovery.main(args) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert _tree_contents(state.root) == after
    assert len(calls) == 1


def test_recovery_cli_preserves_ambiguous_world_rollback_and_staging(interrupted_restore, monkeypatch, capsys):
    state = interrupted_restore
    _mock_server_probe(monkeypatch, "unknown")
    _world(state.world, b"externally recreated world")
    before = _tree_contents(state.root)

    assert restore_recovery.main([str(state.root), "--confirm-server-stopped"]) == 1

    result, = json.loads(capsys.readouterr().out)
    assert result["status"] == "manual-recovery-required"
    assert "Keine der vorhandenen Weltkopien wurde gelöscht" in result["error"]
    assert _tree_contents(state.root) == before


def test_startup_defers_unknown_until_explicit_cli_confirmation(interrupted_restore, monkeypatch, capsys, caplog):
    import main as application

    state = interrupted_restore
    calls = _mock_server_probe(monkeypatch, "unknown")
    monkeypatch.setattr(application, "APP_CONFIG", load_config())
    monkeypatch.setattr(application, "_BACKGROUND_TASKS_STARTED", False)
    monkeypatch.setattr(application, "get_configured_scan_roots", lambda **_kwargs: [{"path": str(state.root)}])
    monkeypatch.setattr(application, "WORLD_PRESENCE", SimpleNamespace(start_cleanup_thread=lambda: None, stop_cleanup_thread=lambda: None))
    monkeypatch.setattr(application.atexit, "register", lambda _callback: None)
    before = _tree_contents(state.root)

    application.start_background_tasks()

    assert application._BACKGROUND_TASKS_STARTED is True
    assert "deferred-write-gate" in caplog.text
    assert "python -m mcbe_editor.restore_recovery --help" in caplog.text
    assert _tree_contents(state.root) == before
    assert restore_recovery.main([str(state.root), "--confirm-server-stopped"]) == 0
    result, = json.loads(capsys.readouterr().out)
    assert result["status"] == "original-restored"
    assert (state.world / "db" / "state.dat").read_bytes() == b"original world"
    assert not state.journal.exists()
    assert len(calls) == 2
