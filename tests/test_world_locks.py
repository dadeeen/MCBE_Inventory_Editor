import importlib
import threading

import pytest


def test_world_lock_registry_survives_services_module_reload(tmp_path):
    import mcbe_editor.services as services

    world_path = str(tmp_path / "world")
    old_lock = services.BedrockEditorService._get_world_lock(world_path)
    reloaded = importlib.reload(services)
    new_lock = reloaded.BedrockEditorService._get_world_lock(world_path)

    assert new_lock is old_lock


def test_reloaded_service_cannot_enter_world_lock_held_by_old_service(tmp_path):
    import mcbe_editor.services as services

    world_path = str(tmp_path / "world")
    old_service = services.BedrockEditorService({}, {})
    old_lock = old_service._get_world_lock(world_path)
    reloaded = importlib.reload(services)
    new_lock = reloaded.BedrockEditorService._get_world_lock(world_path)
    entered = threading.Event()

    old_lock.acquire()
    try:
        worker = threading.Thread(target=lambda: (new_lock.acquire(), entered.set(), new_lock.release()))
        worker.start()
        assert not entered.wait(0.1)
    finally:
        old_lock.release()
    worker.join(timeout=2)
    assert entered.is_set()


def test_player_import_errors_survive_services_reload():
    import mcbe_editor.player_api_routes as player_api_routes
    import mcbe_editor.services as services

    original_rollback = services.PlayerImportRecordRollbackError
    original_rolled_back = services.PlayerImportRolledBackError
    reloaded = importlib.reload(services)

    assert reloaded.PlayerImportRecordRollbackError is original_rollback
    assert reloaded.PlayerImportRolledBackError is original_rolled_back
    assert player_api_routes.PlayerImportRecordRollbackError is original_rollback
    assert player_api_routes.PlayerImportRolledBackError is original_rolled_back


def test_player_import_preview_stale_error_identity_survives_services_reload():
    import mcbe_editor.player_api_routes as player_api_routes
    import mcbe_editor.services as services

    original = services.PlayerImportPreviewStaleError
    reloaded = importlib.reload(services)

    assert reloaded.PlayerImportPreviewStaleError is original
    assert player_api_routes.PlayerImportPreviewStaleError is original


def test_player_state_transfer_errors_survive_services_reload():
    import mcbe_editor.player_api_routes as player_api_routes
    import mcbe_editor.services as services

    original_rollback = services.PlayerStateTransferRollbackError
    original_rolled_back = services.PlayerStateTransferRolledBackError
    original_stale = services.PlayerStateTransferPreviewStaleError
    reloaded = importlib.reload(services)

    assert reloaded.PlayerStateTransferRollbackError is original_rollback
    assert reloaded.PlayerStateTransferRolledBackError is original_rolled_back
    assert reloaded.PlayerStateTransferPreviewStaleError is original_stale
    assert player_api_routes.PlayerStateTransferRollbackError is original_rollback
    assert player_api_routes.PlayerStateTransferRolledBackError is original_rolled_back
    assert player_api_routes.PlayerStateTransferPreviewStaleError is original_stale


def test_unused_world_locks_do_not_accumulate_forever(tmp_path):
    import gc
    import weakref

    from mcbe_editor import world_locks

    world_path = str(tmp_path / "one-off-world")
    key = world_locks.lock_key(world_path)
    lock = world_locks.get_world_lock(world_path)
    lock_ref = weakref.ref(lock)
    assert world_locks._WORLD_LOCKS.get(key) is lock

    del lock
    gc.collect()

    assert lock_ref() is None
    assert key not in world_locks._WORLD_LOCKS


def test_file_lock_state_is_removed_even_when_handle_close_fails(monkeypatch):
    from mcbe_editor import world_locks

    class FailingCloseHandle:
        def close(self):
            raise OSError("simulated close failure")

    key = "close-failure"
    world_locks._FILE_LOCK_STATES[key] = world_locks._FileLockState(
        handle=FailingCloseHandle(),
        pid=world_locks.os.getpid(),
    )
    monkeypatch.setattr(world_locks, "_release_os_lock", lambda _handle: None)

    with pytest.raises(OSError, match="close failure"):
        world_locks._exit_file_lock(key)

    assert key not in world_locks._FILE_LOCK_STATES


def test_locked_world_serializes_across_processes(tmp_path):
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path
    from unittest.mock import patch

    from mcbe_editor.world_locks import locked_world

    world = tmp_path / "world"
    world.mkdir()
    started = tmp_path / "child-started"
    entered = tmp_path / "child-entered"
    backup_root = tmp_path / "backups"
    data_root = tmp_path / "data"
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["MCBE_BACKUP_ROOT"] = str(backup_root)
    env["MCBE_DATA_ROOT"] = str(data_root)
    env["PYTHONPATH"] = str(root)
    code = (
        "from pathlib import Path\n"
        "from mcbe_editor.world_locks import locked_world\n"
        f"world = {str(world)!r}\n"
        f"started = Path({str(started)!r})\n"
        f"entered = Path({str(entered)!r})\n"
        "started.write_text('ready', encoding='utf-8')\n"
        "with locked_world(world):\n"
        "    entered.write_text('entered', encoding='utf-8')\n"
    )

    with (
        patch.dict(
            os.environ,
            {
                "MCBE_BACKUP_ROOT": str(backup_root),
                "MCBE_DATA_ROOT": str(data_root),
            },
            clear=False,
        ),
        locked_world(str(world)),
    ):
        process = subprocess.Popen([sys.executable, "-c", code], cwd=root, env=env)
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists()
        time.sleep(0.2)
        assert not entered.exists()

    process.wait(timeout=5)
    assert process.returncode == 0
    assert entered.exists()


def test_locked_operation_serializes_across_processes(tmp_path):
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    from mcbe_editor.world_locks import locked_operation

    started = tmp_path / "child-started"
    entered = tmp_path / "child-entered"
    lock_root = tmp_path / "locks"
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    code = (
        "from pathlib import Path\n"
        "from mcbe_editor.world_locks import locked_operation\n"
        f"root = {str(lock_root)!r}\n"
        f"started = Path({str(started)!r})\n"
        f"entered = Path({str(entered)!r})\n"
        "started.write_text('ready', encoding='utf-8')\n"
        "with locked_operation('shared-update', root=root):\n"
        "    entered.write_text('entered', encoding='utf-8')\n"
    )

    with locked_operation("shared-update", root=str(lock_root)):
        process = subprocess.Popen([sys.executable, "-c", code], cwd=root, env=env)
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists()
        time.sleep(0.2)
        assert not entered.exists()

    process.wait(timeout=5)
    assert process.returncode == 0
    assert entered.exists()
