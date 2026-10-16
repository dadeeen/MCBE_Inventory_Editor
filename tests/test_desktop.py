from __future__ import annotations

import os
import contextlib
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

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
    monkeypatch.setenv("MCBE_TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("MCBE_TRUSTED_HOSTS", ".external.invalid")
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
    assert os.environ["MCBE_TRUST_PROXY_HEADERS"] == "false"
    assert os.environ["MCBE_TRUSTED_HOSTS"] == "localhost,127.0.0.1,[::1]"


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
    pending = Mock(side_effect=[True, True, False, False])
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


@pytest.mark.parametrize(
    "extra",
    [
        "data/settings.json",
        "DATA/settings.json",
        "fixtures/private/world",
        ".env.local",
        ".ENV.local",
        "setup.bat",
        "a.mcbe-player.zip",
        "A.MCBE-PLAYER.ZIP",
        "a.mcbe-player-bundle.zip",
    ],
)
def test_desktop_bundle_rejects_private_or_unrelated_files(tmp_path, extra):
    path = tmp_path / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    with pytest.raises(ValueError, match="Unexpected"):
        verify_bundle(tmp_path)


def test_desktop_bundle_requires_embedded_python_and_assets(tmp_path):
    with pytest.raises(ValueError, match="Missing"):
        verify_bundle(tmp_path)


@pytest.mark.parametrize("state", [None, {}, {"dirty": 0}, {"dirty": "false"}, {"dirty": True}])
def test_close_guard_requires_an_explicit_clean_state(state):
    window = Mock()
    window.evaluate_js.return_value = state
    window.create_confirmation_dialog.return_value = False
    guard = desktop_app.CloseGuard(window, lambda: False)
    guard._confirming.acquire()
    guard._confirm()
    window.create_confirmation_dialog.assert_called_once()
    window.destroy.assert_not_called()
    assert not guard.allowed


def test_close_guard_recovers_from_a_nonreturning_renderer_without_spawning_more_queries(monkeypatch):
    release = threading.Event()
    entered = threading.Event()

    def blocked_query(_script):
        entered.set()
        release.wait()
        return {"dirty": False}

    window = Mock()
    window.evaluate_js.side_effect = blocked_query
    window.create_confirmation_dialog.return_value = False
    monkeypatch.setattr(desktop_app, "CLOSE_STATE_TIMEOUT", 0.02)
    guard = desktop_app.CloseGuard(window, lambda: False)
    try:
        for _ in range(2):
            assert guard._confirming.acquire(blocking=False)
            guard._confirm()
        assert entered.wait(1)
        window.evaluate_js.assert_called_once()
        assert window.create_confirmation_dialog.call_count == 2
        assert not guard.allowed
        window.destroy.assert_not_called()
    finally:
        release.set()
        # Do not let the query outlive the test's patched objects.
        assert guard._querying.acquire(timeout=2)
        guard._querying.release()
    window.destroy.assert_not_called()  # A late clean result cannot close a cancelled window.


def test_close_guard_waits_for_a_write_started_during_confirmation(monkeypatch):
    window = Mock()
    window.evaluate_js.return_value = {"dirty": True, "title": "Unsaved", "message": "Discard?"}
    window.create_confirmation_dialog.return_value = True
    pending = Mock(side_effect=[False, True, True, False])
    monkeypatch.setattr(desktop_app.time, "sleep", lambda _seconds: window.destroy.assert_not_called())
    guard = desktop_app.CloseGuard(window, pending)
    guard._confirming.acquire()
    guard._confirm()
    assert pending.call_count == 4
    window.destroy.assert_called_once()


def test_close_guard_failed_destroy_does_not_bypass_the_next_close():
    window = Mock()
    window.evaluate_js.return_value = {"dirty": False}
    window.destroy.side_effect = RuntimeError("window unavailable")
    guard = desktop_app.CloseGuard(window, lambda: False)
    guard._confirming.acquire()
    guard._confirm()
    assert not guard.allowed
    assert guard._confirming.acquire(blocking=False)
    guard._confirming.release()


def test_windowed_log_rotates_instead_of_growing_without_bound(tmp_path):
    path = tmp_path / "desktop.log"
    with desktop_app.desktop_log(path) as stream:
        stream.handler.maxBytes = 64
        for _ in range(8):
            assert stream.write("x" * 40) == 40
        stream.flush()
        assert not stream.isatty()
    logs = list(tmp_path.iterdir())
    assert len(logs) == 4  # current log plus three backups
    assert all(log.stat().st_size == 40 for log in logs)


@pytest.mark.parametrize("args", [["--with-window"], ["--recovery-report", "out.txt"], ["--diagnose", "out.json", "--recover"], ["--work", "os"]])
def test_desktop_rejects_incompatible_or_abbreviated_modes(args):
    with pytest.raises(SystemExit) as error:
        desktop_app.main(args)
    assert error.value.code == 2


def test_windowed_log_failure_does_not_recurse_into_redirected_stderr(tmp_path, monkeypatch):
    import contextlib
    import logging

    previous = logging.raiseExceptions
    with desktop_app.desktop_log(tmp_path / "desktop.log") as stream:
        fail = Mock(side_effect=OSError("disk full"))
        monkeypatch.setattr(stream.handler, "shouldRollover", fail)
        with contextlib.redirect_stderr(stream):
            assert stream.write("message") == len("message")
        fail.assert_called_once()
    assert logging.raiseExceptions is previous


@pytest.mark.parametrize("outcome", ["normal", "exception", "return", "shutdown_error", "notice_error", "navigation_error"])
def test_desktop_supervises_server_lifecycle(tmp_path, monkeypatch, outcome):
    """A real worker thread; only OS window and application dependencies are doubles."""
    release = threading.Event()
    window = MagicMock()
    window.create_confirmation_dialog.return_value = False
    for name in ("closing", "closed"):
        event = getattr(window.events, name)
        event.__iadd__.return_value = event
    if outcome == "notice_error":
        window.create_confirmation_dialog.side_effect = RuntimeError("dialog unavailable")

    def serve():
        assert release.wait(5), "test host did not shut down its server"
        if outcome in {"exception", "shutdown_error", "notice_error"}:
            raise RuntimeError("injected HTTP failure")

    server = SimpleNamespace(port=5001, serve_forever=serve, shutdown=release.set)
    application = SimpleNamespace(
        create_local_server=Mock(return_value=server),
        gui_dialogs=Mock(),
        has_pending_operations=lambda: False,
    )

    def start(func, **kwargs):
        assert kwargs["gui"] == "edgechromium"
        if outcome in {"exception", "return", "notice_error"}:
            release.set()
            func()  # waits for the real failing worker, then offers a visible error
            window.create_confirmation_dialog.assert_called_once()
            window.destroy.assert_not_called()  # cancellation preserves the document
        else:
            monitor = threading.Thread(target=func)
            monitor.start()
        window.events.closed.__iadd__.call_args.args[0]()
        if outcome in {"normal", "shutdown_error", "navigation_error"}:
            monitor.join(timeout=5)
            assert not monitor.is_alive()

    view = SimpleNamespace(settings={}, create_window=Mock(return_value=window), start=start)
    monkeypatch.setitem(sys.modules, "main", application)
    monkeypatch.setitem(sys.modules, "webview", view)
    navigation = Mock()
    if outcome == "navigation_error":
        navigation.wait_ready.side_effect = RuntimeError("injected navigation failure")
    monkeypatch.setattr(desktop_app, "DesktopNavigation", Mock(return_value=navigation))
    monkeypatch.setattr(desktop_app, "_wait_for_server", Mock())
    if outcome == "navigation_error":
        with pytest.raises(RuntimeError, match="injected navigation failure"):
            desktop_app.run_desktop(tmp_path, 5001)
        window.destroy.assert_called_once()
    elif outcome in {"notice_error", "shutdown_error"}:
        with pytest.raises(RuntimeError, match="HTTP server failed"):
            desktop_app.run_desktop(tmp_path, 5001)
    else:
        assert desktop_app.run_desktop(tmp_path, 5001) == (0 if outcome == "normal" else 1)
    assert application.gui_dialogs.set_desktop_dialog.call_args.args == (None,)
    assert not any(thread.name == "desktop-http" for thread in threading.enumerate())


@pytest.mark.parametrize("allowed", [(False,), (True, False)])
def test_close_state_does_not_trust_a_foreign_document(allowed):
    window = Mock()
    window.evaluate_js.return_value = {"dirty": False}
    guard = desktop_app.CloseGuard(window, lambda: False, Mock(side_effect=allowed))
    assert guard._close_state() is None
    assert window.evaluate_js.called is allowed[0]


@pytest.mark.parametrize("shutdown_error", [False, True])
def test_headless_diagnose_includes_shutdown_failure(tmp_path, monkeypatch, shutdown_error):
    import json

    release = threading.Event()

    def serve():
        assert release.wait(5)
        if shutdown_error:
            raise RuntimeError("shutdown failed")

    server = SimpleNamespace(port=5001, serve_forever=serve, shutdown=release.set)
    application = SimpleNamespace(create_local_server=lambda *args: server, gui_dialogs=Mock())
    monkeypatch.setitem(sys.modules, "main", application)
    monkeypatch.setattr(desktop_app, "_wait_for_server", Mock())
    monkeypatch.setattr(desktop_app, "_diagnose", lambda *args: {"ok": True, "checks": {"/healthz": True}})
    report = tmp_path / "report.json"
    assert desktop_app.run_desktop(tmp_path, 5001, diagnose=report) == int(shutdown_error)
    result = json.loads(report.read_text())
    assert result["ok"] is not shutdown_error
    assert result["checks"]["/healthz"] is True
    if shutdown_error:
        assert result["error"] == "shutdown failed"


@pytest.mark.parametrize("payload", [b'{"success":true,"status":"ok"}', b'{"status":"wrong"}', b"not json"])
def test_desktop_readiness_requires_health_response_and_bypasses_proxy(monkeypatch, payload):
    import urllib.request

    opener = Mock()
    response = SimpleNamespace(status=200, read=lambda _limit: payload)
    opener.open.return_value = contextlib.nullcontext(response)
    build = Mock(return_value=opener)
    monkeypatch.setattr(urllib.request, "build_opener", build)
    if payload == b'{"success":true,"status":"ok"}':
        desktop_app._wait_for_server(SimpleNamespace(port=12345), threading.Event())
    else:
        with pytest.raises((ValueError, RuntimeError)):
            desktop_app._wait_for_server(SimpleNamespace(port=12345), threading.Event())
    assert build.call_args.args[0].proxies == {}
    assert opener.open.call_args.args == ("http://127.0.0.1:12345/healthz",)
    assert 0 < opener.open.call_args.kwargs["timeout"] <= 1


@pytest.mark.parametrize("already_stopped", [False, True])
def test_desktop_readiness_stops_on_failure_or_deadline(monkeypatch, already_stopped):
    import urllib.request

    opener = Mock()
    opener.open.side_effect = OSError("connection refused")
    monkeypatch.setattr(urllib.request, "build_opener", Mock(return_value=opener))
    monkeypatch.setattr(desktop_app, "SERVER_START_TIMEOUT", 0.01)
    finished = threading.Event()
    if already_stopped:
        finished.set()
    with pytest.raises(RuntimeError, match="did not become ready"):
        desktop_app._wait_for_server(SimpleNamespace(port=12345), finished)
    assert opener.open.called is not already_stopped


@pytest.mark.parametrize("failure", ["readiness", "thread_start"])
def test_desktop_startup_failure_cleans_up_without_opening_window(tmp_path, monkeypatch, failure):
    released = threading.Event()
    server = SimpleNamespace(port=5001, serve_forever=lambda: released.wait(5), shutdown=released.set)
    application = SimpleNamespace(create_local_server=lambda *args: server, gui_dialogs=Mock())
    window_factory = Mock()
    monkeypatch.setitem(sys.modules, "main", application)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=window_factory))
    fail = Mock(side_effect=RuntimeError("injected startup failure"))
    if failure == "readiness":
        monkeypatch.setattr(desktop_app, "_wait_for_server", fail)
    else:
        monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(RuntimeError, match="injected startup failure"):
        desktop_app.run_desktop(tmp_path, 5001)
    assert released.is_set()
    assert application.gui_dialogs.set_desktop_dialog.call_args.args == (None,)
    window_factory.assert_not_called()
    assert not any(thread.name == "desktop-http" for thread in threading.enumerate())
