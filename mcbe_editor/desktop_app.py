"""Thin Windows window host for the shared Flask editor.

Only this entry point imports pywebview. No GUI dependency enters browser or
Docker startup. The bound port is stable so WebView local storage survives restarts.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcbe_editor.desktop_navigation import DesktopNavigation
from mcbe_editor.desktop_worker import WORKERS, run_frozen_update, worker_main

TITLE = "MCBE Inventory Editor"
DEFAULT_PORT = 5001
CLOSE_STATE_TIMEOUT = 5.0
SERVER_START_TIMEOUT = 10.0
LOGGER = logging.getLogger(__name__)


class _LogStream:
    """File-like redirect for the windowed bootloader's missing standard streams."""

    encoding = "utf-8"

    def __init__(self, handler: RotatingFileHandler):
        self.handler = handler

    def write(self, text: str) -> int:
        if text:
            self.handler.handle(logging.LogRecord("desktop", logging.INFO, __file__, 0, text, (), None))
        return len(text)

    def flush(self) -> None:
        self.handler.flush()

    def isatty(self) -> bool:
        return False


@contextlib.contextmanager
def desktop_log(path: Path):
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.terminator = ""
    # A logging I/O failure must not report back into the redirected stderr and
    # recursively try to write to the same failed log (e.g. a full disk).
    previous_raise_exceptions = logging.raiseExceptions
    logging.raiseExceptions = False
    try:
        yield _LogStream(handler)
    finally:
        handler.close()
        logging.raiseExceptions = previous_raise_exceptions


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
        MCBE_TRUST_PROXY_HEADERS="false",
        MCBE_TRUSTED_HOSTS="localhost,127.0.0.1,[::1]",
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

    def __init__(self, window, pending_operation, document_allowed=lambda: True):
        self.window = window
        self.pending_operation = pending_operation
        self.document_allowed = document_allowed
        self.allowed = False
        self._confirming = threading.Lock()
        self._querying = threading.Lock()

    def closing(self):
        if self.allowed:
            return True
        if self._confirming.acquire(blocking=False):
            try:
                threading.Thread(target=self._confirm, name="desktop-close", daemon=True).start()
            except Exception:
                self._confirming.release()
                LOGGER.exception("Could not start desktop close confirmation")
        return False

    def _close_state(self):
        if not self.document_allowed():
            return None
        # A dead renderer can leave evaluate_js waiting indefinitely. Keep at
        # most one such daemon query per window; a late answer never closes it.
        if not self._querying.acquire(blocking=False):
            return None
        done = threading.Event()
        result = {}

        def query():
            try:
                result["state"] = self.window.evaluate_js("window.MCBEDesktop?.closeState()")
            except Exception:
                LOGGER.warning("Desktop close state unavailable", exc_info=True)
            finally:
                self._querying.release()
                done.set()

        try:
            threading.Thread(target=query, name="desktop-close-state", daemon=True).start()
        except Exception:
            self._querying.release()
            raise
        if not done.wait(CLOSE_STATE_TIMEOUT):
            LOGGER.warning("Desktop close state timed out")
            return None
        state = result.get("state")
        # Missing frontend code is unknown, not proof that the document is clean.
        if not self.document_allowed() or not isinstance(state, dict) or not isinstance(state.get("dirty"), bool):
            return None
        return state

    def _wait_for_operations(self):
        from mcbe_editor.i18n import t

        if self.pending_operation():
            self.window.set_title(t("Laufender Vorgang wird abgeschlossen …"))
            # This is deliberately not timed out: never interrupt a world write.
            while self.pending_operation():
                time.sleep(0.1)
            self.window.set_title(TITLE)

    def _confirm(self):
        from mcbe_editor.i18n import t

        try:
            self._wait_for_operations()
            state = self._close_state()
            if state is None or state["dirty"]:
                title = t("Editor schließen")
                message = t("Der Bearbeitungsstand kann nicht geprüft werden. Editor trotzdem schließen?")
                if state is not None and isinstance(state.get("title"), str) and isinstance(state.get("message"), str):
                    title, message = state["title"], state["message"]
                if not self.window.create_confirmation_dialog(title, message):
                    return
            # A write may have started while JavaScript or the dialog was active.
            self._wait_for_operations()
            self.allowed = True
            self.window.destroy()
        except Exception:
            self.allowed = False
            LOGGER.exception("Desktop close failed; keeping the window open")
        finally:
            self._confirming.release()


def run_recovery(args: list[str], report: Path) -> int:
    """Run the existing recovery CLI, including its gates, without Flask/WebView.

    Windowed executables have no console. Save help, validation errors and the
    recovery result in one explicit report rather than silently losing output.
    """
    from mcbe_editor.restore_recovery import main as recover
    from mcbe_editor.runtime_data import atomic_write_private_text

    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            result = recover(args)
        except SystemExit as exc:
            result = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
        except Exception:
            traceback.print_exc()
            result = 1
    atomic_write_private_text(report, output.getvalue())
    return result


def _diagnose(application, server) -> dict:
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
    return {"ok": True, "checks": checks, "data_root": application.APP_CONFIG.data_root}


def _wait_for_server(server, finished: threading.Event) -> None:
    """Require a bounded, proxy-free health response before creating a window."""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + SERVER_START_TIMEOUT
    while not finished.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with opener.open(f"http://127.0.0.1:{server.port}/healthz", timeout=min(1.0, remaining)) as response:
                payload = json.loads(response.read(4096))
                if response.status != 200 or payload != {"success": True, "status": "ok"}:
                    raise RuntimeError("Unexpected desktop health response")
            if not finished.is_set():
                return
        except OSError:
            finished.wait(min(0.1, max(0.0, deadline - time.monotonic())))
    raise RuntimeError("Desktop HTTP server stopped or did not become ready in time")


def run_desktop(data: Path, port: int, *, diagnose: Path | None = None, with_window: bool = False, debug: bool = False) -> int:
    import main as application

    server = application.create_local_server("127.0.0.1", port)
    stopping = threading.Event()
    finished = threading.Event()
    failures: list[BaseException] = []
    window_failures: list[Exception] = []
    failure_reported = threading.Event()

    def serve():
        try:
            server.serve_forever()
            if not stopping.is_set():
                raise RuntimeError("Desktop HTTP server exited unexpectedly")
        except BaseException as exc:
            # A worker's SystemExit/KeyboardInterrupt must not silently turn a
            # dead backend into a successful GUI process either.
            failures.append(exc)
            LOGGER.exception("Desktop HTTP server failed")
        finally:
            finished.set()

    thread = threading.Thread(target=serve, name="desktop-http")
    report = None
    try:
        thread.start()
        _wait_for_server(server, finished)
        report = _diagnose(application, server) if diagnose is not None else None
        if report is None or with_window:
            import webview

            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.settings["ALLOW_FILE_URLS"] = False
            webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
            window = webview.create_window(TITLE, "about:blank", width=1440, height=920, min_size=(800, 600), text_select=True)
            navigation = DesktopNavigation(window, f"http://127.0.0.1:{server.port}/")
            window.events.before_show += navigation.install
            window.events.loaded += navigation.prepare_links

            def pick(*, folder, initial_dir=None, file_types=()):
                result = window.create_file_dialog(
                    webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN,
                    directory=initial_dir or "",
                    allow_multiple=False,
                    file_types=file_types,
                )
                return str(result[0]) if result else ""

            application.gui_dialogs.set_desktop_dialog(pick)
            guard = CloseGuard(window, application.has_pending_operations, lambda: navigation.allows(window.get_current_url()))
            window.events.closing += guard.closing

            def check_window():
                # The packaged smoke check uses the real engine and close callback,
                # not a mock WebView. Its caller supplies a fresh synthetic profile.
                try:
                    if not window.events.loaded.wait(30):
                        raise RuntimeError("Native desktop page did not load")
                    state = guard._close_state()
                    if state is None or state["dirty"]:
                        raise RuntimeError("Native desktop close-state roundtrip failed")
                    report["checks"]["native_window"] = True
                except Exception as exc:
                    report.update(ok=False, error=str(exc))
                    # A diagnostic failure must not wait for an interactive dialog.
                    guard.allowed = True
                finally:
                    window.destroy()

            def watch_server():
                from mcbe_editor.i18n import t

                try:
                    navigation.wait_ready()
                except Exception as exc:
                    window_failures.append(exc)
                    guard.allowed = True
                    window.destroy()
                    return
                if report is not None:
                    check_window()
                    return
                finished.wait()
                if stopping.is_set():
                    return
                try:
                    window.set_title(t("Lokaler Server nicht verfügbar"))
                    close = window.create_confirmation_dialog(
                        t("Lokaler Server nicht verfügbar"),
                        t(
                            "Der lokale Server wurde unerwartet beendet. Speichern ist nicht mehr möglich. "
                            "Nicht gespeicherte Änderungen bleiben nur im geöffneten Fenster. "
                            "Abbrechen lässt das Fenster zum Notieren der Änderungen offen. Editor jetzt schließen?"
                        ),
                    )
                    failure_reported.set()
                    if close:
                        # Keep the ordinary close guard: never silently discard a
                        # dirty/unknown document or bypass pending write protection.
                        window.destroy()
                except Exception:
                    LOGGER.exception("Could not display desktop server failure")

            def window_closed():
                stopping.set()
                server.shutdown()

            window.events.closed += window_closed
            webview.start(
                func=watch_server,
                gui="edgechromium",
                private_mode=False,
                storage_path=str(data / "webview"),
                debug=debug,
            )
            if report is not None:
                if report["checks"].get("native_window") is not True or not guard.allowed:
                    report.update(ok=False, error=report.get("error", "Native desktop closed before validation completed"))
                report["checks"]["native_close"] = report["ok"] and guard.allowed
    finally:
        stopping.set()
        application.gui_dialogs.set_desktop_dialog(None)
        server.shutdown()
        if thread.ident is None:
            # Even Thread.start failure must release the already-bound socket
            # and Waitress workers. shutdown marks the loop as stopped first.
            server.serve_forever()
        else:
            thread.join()
    if window_failures:
        if report is not None:
            report.update(ok=False, error=str(window_failures[0]))
        else:
            raise window_failures[0]
    if failures:
        if report is not None:
            report.update(ok=False, error=str(failures[0]))
        elif not failure_reported.is_set():
            raise RuntimeError("Desktop HTTP server failed; see desktop.log") from failures[0]
    if report is not None:
        diagnose.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return int(not report["ok"])
    return int(bool(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCBE Inventory Editor desktop", allow_abbrev=False)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--diagnose", type=Path, help="Write an offline startup/worker report and exit without a window")
    parser.add_argument("--with-window", action="store_true", help="Also test the native WebView window during --diagnose")
    parser.add_argument("--debug", action="store_true", help="Enable WebView developer tools for local troubleshooting")
    parser.add_argument("--recovery-report", type=Path, help="Write recovery output here without a result dialog; place before --recover")
    parser.add_argument("--recover", nargs=argparse.REMAINDER, help="Run restore recovery without the editor; remaining arguments go to recovery")
    parser.add_argument("--worker", choices=sorted(WORKERS), help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args, remaining = parser.parse_known_args(argv)
    if args.worker:
        if args.worker_output is None or not remaining or remaining[0] != "--" or args.recover is not None:
            parser.error("worker requires an output path and -- before its arguments")
        return worker_main(args.worker, args.worker_output, remaining[1:])
    if remaining or args.worker_output is not None:
        parser.error("unexpected desktop arguments")
    if args.recovery_report is not None and args.recover is None:
        parser.error("--recovery-report requires --recover")
    if args.with_window and args.diagnose is None:
        parser.error("--with-window requires --diagnose")
    if args.recover is not None and (args.diagnose is not None or args.debug):
        parser.error("recovery cannot be combined with desktop diagnostics or debugging")
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    if sys.platform != "win32":
        parser.error("The desktop host requires Windows. Use main.py for the browser application.")
    log_path = None
    windowed = sys.stdout is None
    try:
        data = prepare_environment(args.data_dir, args.port)
        # Take the instance lock before opening/rotating a log shared by hosts.
        with desktop_instance(data), desktop_log(data / "desktop.log") as log, contextlib.ExitStack() as stack:
            log_path = data / "desktop.log"
            if sys.stdout is None:
                stack.enter_context(contextlib.redirect_stdout(log))
            if sys.stderr is None:
                stack.enter_context(contextlib.redirect_stderr(log))
            try:
                if args.recover is not None:
                    report = args.recovery_report or data / "restore-recovery.txt"
                    result = run_recovery(args.recover, report)
                    if windowed and args.recovery_report is None:
                        import ctypes

                        from mcbe_editor.i18n import t

                        message = t("Recovery beendet (Exitcode {code}). Details stehen in {path}.", code=result, path=str(report))
                        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10 if result else 0x40)
                    else:
                        print(f"Recovery exit code: {result}. Report: {report}")
                    return result
                if (args.diagnose is None or args.with_window) and not webview2_available():
                    from mcbe_editor.i18n import t

                    raise RuntimeError(
                        t("Microsoft Edge WebView2 Runtime fehlt. Installiere die Runtime von https://go.microsoft.com/fwlink/p/?LinkId=2124703.")
                    )
                return run_desktop(data, args.port, diagnose=args.diagnose, with_window=args.with_window, debug=args.debug)
            except Exception:
                traceback.print_exc(file=log)
                raise
    except Exception as exc:
        if args.diagnose is not None:
            with contextlib.suppress(OSError):
                args.diagnose.write_text(json.dumps({"ok": False, "error": str(exc)}), encoding="utf-8")
        elif args.recovery_report is not None:
            from mcbe_editor.runtime_data import atomic_write_private_text

            with contextlib.suppress(OSError):
                atomic_write_private_text(args.recovery_report, f"Recovery failed or could not be reported: {exc}\n")
        else:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, startup_error_message(exc, log_path), TITLE, 0x10)
        return 1
