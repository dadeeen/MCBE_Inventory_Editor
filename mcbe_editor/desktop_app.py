"""Thin Windows window host for the shared Flask editor.

Only this entry point imports pywebview. No GUI dependency enters browser or
Docker startup. The bound port is stable so WebView local storage survives restarts.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from mcbe_editor.desktop_worker import WORKERS, run_frozen_update, worker_main

TITLE = "MCBE Inventory Editor"
DEFAULT_PORT = 5001


def webview2_available() -> bool:
    """Check the Evergreen Runtime registration documented by Microsoft.

    An explicit check prevents pywebview from falling back to legacy MSHTML.
    """
    import winreg

    key = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    locations = ((winreg.HKEY_CURRENT_USER, winreg.KEY_READ), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_32KEY))
    for hive, access in locations:
        try:
            with winreg.OpenKey(hive, key, 0, access) as handle:
                version, _ = winreg.QueryValueEx(handle, "pv")
                parts = tuple(int(part) for part in str(version).split("."))
                if len(parts) == 4 and min(parts) >= 0 and any(parts):
                    return True
        except (OSError, ValueError):
            continue
    return False


def startup_error_message(error: Exception, log_path: Path | None = None) -> str:
    from mcbe_editor.i18n import t

    message = t("Der Editor konnte nicht gestartet werden: {error}", error=str(error))
    if log_path is not None:
        message += "\n\n" + t("Details stehen in {path}.", path=str(log_path))
    return message


def prepare_environment(data_dir: Path | None = None, port: int = DEFAULT_PORT) -> Path:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    data = (data_dir or Path(os.environ.get("MCBE_DATA_ROOT") or root / "data")).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        MCBE_EDITOR_MODE="local",
        MCBE_EDITOR_HOST="127.0.0.1",
        MCBE_EDITOR_PORT=str(port),
        MCBE_OPEN_BROWSER="false",
        MCBE_LOCAL_HEARTBEAT_SHUTDOWN="false",
        MCBE_DATA_ROOT=str(data),
    )
    return data


@contextlib.contextmanager
def desktop_instance(data: Path):
    """Keep one window host per data directory, including during shutdown."""
    import msvcrt

    from mcbe_editor.i18n import t

    with (data / "desktop.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError(t("Der Editor ist für diesen Datenordner bereits geöffnet.")) from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class CloseGuard:
    """Return immediately from the UI close event, then query the live document.

    Waiting for evaluate_js inside the synchronous WinForms close callback would
    deadlock its UI thread. Only the background confirmation may call back into it.
    """

    def __init__(self, window, pending_operation):
        self.window = window
        self.pending_operation = pending_operation
        self.allowed = False
        self._confirming = threading.Lock()

    def closing(self):
        if self.allowed:
            return True
        if self._confirming.acquire(blocking=False):
            threading.Thread(target=self._confirm, name="desktop-close", daemon=True).start()
        return False

    def _confirm(self):
        from mcbe_editor.i18n import t

        try:
            if self.pending_operation():
                self.window.set_title(t("Laufender Vorgang wird abgeschlossen …"))
                while self.pending_operation():
                    time.sleep(0.1)
                self.window.set_title(TITLE)
            try:
                state = self.window.evaluate_js("window.MCBEDesktop?.closeState() || {dirty: false}")
                if not isinstance(state, dict):
                    raise ValueError("Desktop close state unavailable")
            except Exception:
                # An unavailable renderer cannot establish that edits are saved.
                state = {
                    "dirty": True,
                    "title": t("Editor schließen"),
                    "message": t("Der Bearbeitungsstand kann nicht geprüft werden. Editor trotzdem schließen?"),
                }
            if state.get("dirty") and not self.window.create_confirmation_dialog(state["title"], state["message"]):
                return
            self.allowed = True
            self.window.destroy()
        finally:
            self._confirming.release()


def _diagnose(application, server, output: Path) -> None:
    """Offline check of the packaged assets and both updater entry points."""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks = {}
    for path in ("/healthz", "/", "/static/app.js", "/static/i18n/en.json"):
        with opener.open(f"http://127.0.0.1:{server.port}{path}", timeout=30) as response:
            body = response.read()
            if response.status != 200 or not body:
                raise RuntimeError(f"Desktop resource check failed: {path}")
            checks[path] = len(body)
    if getattr(sys, "frozen", False):
        for module in sorted(WORKERS):
            result = run_frozen_update(module, ["--help"], cwd=str(application.APP_ROOT), env=dict(os.environ), timeout=45)
            if result.returncode != 0 or "usage:" not in result.stdout.lower():
                raise RuntimeError(f"Desktop worker check failed: {module}: {result.stdout}")
            checks[module] = True
    output.write_text(json.dumps({"ok": True, "checks": checks, "data_root": application.APP_CONFIG.data_root}, indent=2), encoding="utf-8")


def run_desktop(data: Path, port: int, *, diagnose: Path | None = None, debug: bool = False) -> int:
    import main as application

    server = application.create_local_server("127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, name="desktop-http")
    thread.start()
    try:
        if diagnose is not None:
            _diagnose(application, server, diagnose)
            return 0
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
        window = webview.create_window(TITLE, f"http://127.0.0.1:{server.port}/", width=1440, height=920, min_size=(800, 600), text_select=True)

        def pick(*, folder, initial_dir=None, file_types=()):
            result = window.create_file_dialog(
                webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN,
                directory=initial_dir or "",
                allow_multiple=False,
                file_types=file_types,
            )
            return str(result[0]) if result else ""

        def pending_operation():
            with application._SAVING_LOCK:
                return application._SAVING_COUNTER > 0

        application.gui_dialogs.set_desktop_dialog(pick)
        guard = CloseGuard(window, pending_operation)
        window.events.closing += guard.closing
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(data / "webview"), debug=debug)
        return 0
    finally:
        application.gui_dialogs.set_desktop_dialog(None)
        server.shutdown()
        thread.join()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCBE Inventory Editor desktop")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--diagnose", type=Path, help="Write an offline startup/worker report and exit without a window")
    parser.add_argument("--debug", action="store_true", help="Enable WebView developer tools for local troubleshooting")
    parser.add_argument("--worker", choices=sorted(WORKERS), help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args, remaining = parser.parse_known_args(argv)
    if args.worker:
        if args.worker_output is None or not remaining or remaining[0] != "--":
            parser.error("worker requires an output path and -- before its arguments")
        return worker_main(args.worker, args.worker_output, remaining[1:])
    if remaining or args.worker_output is not None:
        parser.error("unexpected desktop arguments")
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    if sys.platform != "win32":
        parser.error("The desktop host requires Windows. Use main.py for the browser application.")
    log_path = None
    try:
        data = prepare_environment(args.data_dir, args.port)
        with (data / "desktop.log").open("a", encoding="utf-8") as log, contextlib.ExitStack() as stack:
            log_path = data / "desktop.log"
            # PyInstaller's windowed bootloader supplies no standard streams.
            if sys.stdout is None:
                stack.enter_context(contextlib.redirect_stdout(log))
            if sys.stderr is None:
                stack.enter_context(contextlib.redirect_stderr(log))
            try:
                with desktop_instance(data):
                    if args.diagnose is None and not webview2_available():
                        from mcbe_editor.i18n import t

                        raise RuntimeError(
                            t("Microsoft Edge WebView2 Runtime fehlt. Installiere die Runtime von https://go.microsoft.com/fwlink/p/?LinkId=2124703.")
                        )
                    return run_desktop(data, args.port, diagnose=args.diagnose, debug=args.debug)
            except Exception:
                traceback.print_exc(file=log)
                raise
    except Exception as exc:
        if args.diagnose is not None:
            args.diagnose.write_text(json.dumps({"ok": False, "error": str(exc)}), encoding="utf-8")
        else:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, startup_error_message(exc, log_path), TITLE, 0x10)
        return 1
