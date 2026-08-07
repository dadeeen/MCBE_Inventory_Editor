#!/usr/bin/env python3
"""Run Playwright browser smoke tests with managed local Flask servers."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    from test_artifacts import prune_stale_test_artifacts, unique_test_artifact_path
else:
    from .test_artifacts import prune_stale_test_artifacts, unique_test_artifact_path

ROOT = Path(__file__).resolve().parents[1]
TMP = unique_test_artifact_path("browser-smoke")
SERVER_HOST = "127.0.0.1"
SERVER_START_TIMEOUT_SECONDS = 30.0
SERVER_STOP_TIMEOUT_SECONDS = 10.0
VENV_REEXEC_ENV = "MCBE_BROWSER_SMOKE_VENV_REEXEC"


@dataclass(frozen=True)
class ServerSpec:
    port: int
    data_root: str
    read_only: str
    require_server_offline: str


SERVER_SPECS = (
    ServerSpec(8765, "data-normal", "false", "false"),
    ServerSpec(8766, "data-viewer", "true", "true"),
)

PROFILE_DIRS = {
    "LOCALAPPDATA": "profiles/localappdata",
    "APPDATA": "profiles/appdata",
    "USERPROFILE": "profiles/userprofile",
}

COMMON_ENV = {
    "MCBE_EDITOR_MODE": "local",
    "MCBE_OPEN_BROWSER": "false",
    "MCBE_LOCAL_HEARTBEAT_SHUTDOWN": "false",
    "MCBE_AUTH_REQUIRED": "false",
    "MCBE_WORLDS_ROOT": "tests/fixtures/worlds",
    "MCBE_AUDIT_LOG_ENABLED": "false",
    "MCBE_STARTUP_NETWORK_CHECK": "false",
    "MCBE_STARTUP_SECURITY_REPORT": "false",
    "MCBE_LOG_LEVEL": "WARNING",
    "PYTHONUTF8": "1",
}


def _playwright_command() -> list[str]:
    """Use Playwright's JS entry point without relying on a ZIP-preserved mode bit."""
    cli = ROOT / "node_modules" / "playwright" / "cli.js"
    if not cli.is_file():
        print("Playwright fehlt. Zuerst `npm ci --ignore-scripts` ausführen.", file=sys.stderr)
        raise SystemExit(2)
    node = shutil.which("node")
    if not node:
        print("Node.js fehlt oder ist nicht im PATH verfügbar.", file=sys.stderr)
        raise SystemExit(2)
    return [node, str(cli)]


def _project_venv_python() -> Path | None:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    candidate = ROOT / ".venv" / relative
    return candidate if candidate.is_file() else None


def _run_in_project_venv(args: list[str]) -> int | None:
    """Re-launch through the repository venv when npm used a global Python."""

    if os.environ.get(VENV_REEXEC_ENV) == "1":
        return None
    project_python = _project_venv_python()
    if project_python is None:
        return None
    try:
        if project_python.resolve() == Path(sys.executable).resolve():
            return None
    except OSError:
        if os.path.normcase(str(project_python)) == os.path.normcase(sys.executable):
            return None

    env = os.environ.copy()
    env[VENV_REEXEC_ENV] = "1"
    completed = subprocess.run(
        [str(project_python), str(Path(__file__).resolve()), *args],
        cwd=ROOT,
        env=env,
    )
    return completed.returncode


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection((SERVER_HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


def _print_log_tail(log_path: Path, *, lines: int = 80) -> None:
    if not log_path.exists():
        return
    rows = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not rows:
        return
    try:
        display_path = log_path.relative_to(ROOT)
    except ValueError:
        display_path = log_path
    print(f"\n--- {display_path} tail ---", file=sys.stderr)
    for row in rows[-lines:]:
        print(row, file=sys.stderr)
    print("--- end server log ---\n", file=sys.stderr)


def _server_env(spec: ServerSpec) -> dict[str, str]:
    env = os.environ.copy()
    env.update(COMMON_ENV)
    env.update({key: str(TMP / relative) for key, relative in PROFILE_DIRS.items()})
    env.update(
        {
            "MCBE_EDITOR_HOST": SERVER_HOST,
            "MCBE_EDITOR_PORT": str(spec.port),
            "MCBE_DATA_ROOT": str(TMP / spec.data_root),
            "MCBE_READ_ONLY": spec.read_only,
            "MCBE_REQUIRE_SERVER_OFFLINE": spec.require_server_offline,
        }
    )
    return env


def _start_server(spec: ServerSpec) -> tuple[subprocess.Popen, object, Path]:
    if _port_is_open(spec.port):
        print(f"Port {spec.port} is already in use; stop the existing server or choose a free smoke-test port.", file=sys.stderr)
        raise SystemExit(2)

    TMP.mkdir(parents=True, exist_ok=True)
    for relative in PROFILE_DIRS.values():
        (TMP / relative).mkdir(parents=True, exist_ok=True)

    log_path = TMP / f"browser-smoke-server-{spec.port}.log"
    log_file = log_path.open("w", encoding="utf-8")
    cmd = [
        sys.executable,
        str(ROOT / "main.py"),
        "--host",
        SERVER_HOST,
        "--port",
        str(spec.port),
        "--no-browser",
    ]
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=_server_env(spec),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        **kwargs,
    )
    return process, log_file, log_path


def _wait_for_health(spec: ServerSpec, process: subprocess.Popen, log_path: Path) -> None:
    url = f"http://{SERVER_HOST}:{spec.port}/healthz"
    deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _print_log_tail(log_path)
            raise RuntimeError(f"Browser smoke server on port {spec.port} exited with code {process.returncode}.")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    _print_log_tail(log_path)
    raise RuntimeError(f"Browser smoke server on port {spec.port} did not become healthy within {SERVER_START_TIMEOUT_SECONDS:.0f}s.")


def _terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
        return
    os.killpg(process.pid, signal.SIGTERM)


def _kill_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.kill()
        return
    os.killpg(process.pid, signal.SIGKILL)


def _stop_servers(servers: list[tuple[subprocess.Popen, object, Path]]) -> None:
    for process, _, _ in reversed(servers):
        _terminate_process(process)
    for process, _, log_path in reversed(servers):
        try:
            process.wait(timeout=SERVER_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"Could not stop browser smoke server {process.pid}; see {log_path}.", file=sys.stderr)
    for _, log_file, _ in servers:
        log_file.close()


def _run_playwright(args: list[str]) -> int:
    env = os.environ.copy()
    env["MCBE_BROWSER_SMOKE_EXTERNAL_SERVER"] = "1"
    env["MCBE_BROWSER_SMOKE_OUTPUT_DIR"] = str(TMP / "playwright-results")
    cmd = [*_playwright_command(), "test", *args]
    return subprocess.run(cmd, cwd=ROOT, env=env).returncode


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    relaunched_code = _run_in_project_venv(args)
    if relaunched_code is not None:
        return relaunched_code
    prune_stale_test_artifacts(protected=(TMP,))
    servers: list[tuple[subprocess.Popen, object, Path]] = []
    exit_code = 1
    try:
        for spec in SERVER_SPECS:
            process, log_file, log_path = _start_server(spec)
            servers.append((process, log_file, log_path))
            _wait_for_health(spec, process, log_path)
        exit_code = _run_playwright(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
    finally:
        _stop_servers(servers)
    if exit_code == 0:
        shutil.rmtree(TMP, ignore_errors=True)
    elif TMP.exists():
        print(f"Browser smoke diagnostics retained at {TMP}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
