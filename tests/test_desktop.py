from __future__ import annotations

import os
import contextlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import desktop_app, desktop_worker, gui_dialogs, update_script_runner
from scripts.build_desktop import verify_bundle

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("version,available", [("139.0.3405.125", True), ("0.0.0.0", False), ("", False), ("invalid", False)])
def test_webview2_requires_registered_runtime(monkeypatch, version, available):
    registry = SimpleNamespace(
        HKEY_CURRENT_USER=1,
        HKEY_LOCAL_MACHINE=2,
        KEY_READ=1,
        KEY_WOW64_32KEY=2,
        OpenKey=lambda *args: contextlib.nullcontext("key"),
        QueryValueEx=lambda *args: (version, 1),
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert desktop_app.webview2_available() is available


def test_startup_error_does_not_blame_webview_for_another_failure():
    message = desktop_app.startup_error_message(RuntimeError("Already open"), Path("custom-data/desktop.log"))
    assert "Already open" in message
    assert "custom-data" in message
    assert "WebView2" not in message


@pytest.mark.skipif(sys.platform != "win32", reason="Windows instance lock")
def test_desktop_lock_rejects_duplicate_and_releases_on_exit(tmp_path):
    with desktop_app.desktop_instance(tmp_path), pytest.raises(RuntimeError, match="bereits geöffnet|already open"), desktop_app.desktop_instance(tmp_path):
        pytest.fail("Second host acquired the lock")
    with desktop_app.desktop_instance(tmp_path):
        pass


def test_desktop_environment_forces_loopback_but_preserves_write_guards(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_EDITOR_HOST", "0.0.0.0")
    monkeypatch.setenv("MCBE_REQUIRE_SERVER_OFFLINE", "true")
    monkeypatch.setenv("MCBE_READ_ONLY", "true")
    # prepare_environment writes a few process settings; restore them after this test.
    for name in ("MCBE_EDITOR_PORT", "MCBE_OPEN_BROWSER", "MCBE_LOCAL_HEARTBEAT_SHUTDOWN", "MCBE_DATA_ROOT"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    data = desktop_app.prepare_environment(tmp_path / "Daten ü", 5001)
    assert data == tmp_path / "Daten ü"
    assert os.environ["MCBE_EDITOR_HOST"] == "127.0.0.1"
    assert os.environ["MCBE_EDITOR_MODE"] == "local"
    assert os.environ["MCBE_OPEN_BROWSER"] == "false"
    assert os.environ["MCBE_LOCAL_HEARTBEAT_SHUTDOWN"] == "false"
    assert os.environ["MCBE_REQUIRE_SERVER_OFFLINE"] == "true"
    assert os.environ["MCBE_READ_ONLY"] == "true"


@pytest.mark.parametrize("module", sorted(desktop_worker.WORKERS))
def test_desktop_worker_runs_without_starting_the_application(tmp_path, module):
    output = tmp_path / "Ausgabe ü.txt"
    result = subprocess.run(
        [sys.executable, str(ROOT / "desktop.py"), "--worker", module, "--worker-output", str(output), "--", "--help"],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in output.read_text(encoding="utf-8").lower()
    assert not (tmp_path / "data").exists()


def test_desktop_worker_refuses_arbitrary_module(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        desktop_worker.worker_main("os", tmp_path / "output", [])
    assert not (tmp_path / "output").exists()


def test_frozen_updater_uses_explicit_worker_and_utf8_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        Path(command[command.index("--worker-output") + 1]).write_text("Überprüfung ✓", encoding="utf-8")
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(desktop_worker.subprocess, "run", run)
    result = update_script_runner._run_update([sys.executable, "-m", "scripts.update_db", "--help"], cwd=str(tmp_path), env={}, timeout=12)
    assert result.returncode == 7
    assert result.stdout == "Überprüfung ✓"
    assert seen["command"][1:3] == ["--worker", "scripts.update_db"]
    assert "-m" not in seen["command"]
    assert seen["timeout"] == 12
    assert not Path(seen["command"][4]).exists()


@pytest.mark.parametrize("dirty,accept,closes", [(False, False, True), (True, False, False), (True, True, True)])
def test_close_guard_preserves_unsaved_edits(dirty, accept, closes):
    window = Mock()
    window.evaluate_js.return_value = {"dirty": dirty, "title": "Unsaved", "message": "Discard?"}
    window.create_confirmation_dialog.return_value = accept
    guard = desktop_app.CloseGuard(window, lambda: False)
    guard._confirming.acquire()
    guard._confirm()
    assert guard.allowed is closes
    assert window.destroy.called is closes
    assert window.create_confirmation_dialog.called is dirty


def test_close_guard_does_not_assume_failed_renderer_is_clean():
    window = Mock()
    window.evaluate_js.side_effect = RuntimeError("renderer stopped")
    window.create_confirmation_dialog.return_value = False
    guard = desktop_app.CloseGuard(window, lambda: False)
    guard._confirming.acquire()
    guard._confirm()
    window.create_confirmation_dialog.assert_called_once()
    window.destroy.assert_not_called()


def test_close_guard_waits_for_write_before_closing(monkeypatch):
    window = Mock()
    window.evaluate_js.return_value = {"dirty": False}
    pending = Mock(side_effect=[True, True, False])
    monkeypatch.setattr(desktop_app.time, "sleep", Mock())
    guard = desktop_app.CloseGuard(window, pending)
    guard._confirming.acquire()
    guard._confirm()
    desktop_app.time.sleep.assert_called_once()
    window.destroy.assert_called_once()


def test_native_dialog_adapter_bypasses_python_cli(monkeypatch):
    provider = Mock(return_value="C:/Welten/Überwelt")
    monkeypatch.setattr(gui_dialogs, "_desktop_dialog", provider)
    monkeypatch.setattr(gui_dialogs, "run_gui_script", Mock(side_effect=AssertionError("Python CLI must not run")))
    assert gui_dialogs.select_folder("C:/Welten") == "C:/Welten/Überwelt"
    assert provider.call_args.kwargs == {"folder": True, "initial_dir": "C:/Welten"}
    gui_dialogs.select_player_export()
    assert "*.mcbe-player.zip" in provider.call_args.kwargs["file_types"][0]


@pytest.mark.parametrize("extra", ["data/settings.json", "fixtures/private/world", ".env.local", "setup.bat", "a.mcbe-player.zip"])
def test_desktop_bundle_rejects_private_or_unrelated_files(tmp_path, extra):
    path = tmp_path / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    with pytest.raises(ValueError, match="Unexpected"):
        verify_bundle(tmp_path)


def test_desktop_bundle_requires_embedded_python_and_assets(tmp_path):
    with pytest.raises(ValueError, match="Missing"):
        verify_bundle(tmp_path)
