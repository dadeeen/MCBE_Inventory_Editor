"""Explicit operator recovery for restores deferred at application startup.

Run ``-m mcbe_editor.restore_recovery --help`` from the application root with
the installation's interpreter, for example ``.venv\\Scripts\\python.exe``.
The CLI reuses journal validation and the same world locks as normal writes.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from .backup import recover_interrupted_restores
from .config import AppConfig, load_config
from .server_status import write_gate
from .world import get_configured_scan_roots


def recovery_command(*args: str) -> str:
    # A bare "python" may be missing or older than the runtime on Windows.
    interpreter = Path(sys.executable)
    with contextlib.suppress(ValueError):
        interpreter = interpreter.relative_to(Path.cwd())
    command = [str(interpreter), "-m", "mcbe_editor.restore_recovery", *args]
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def recovery_help_command() -> str:
    return recovery_command("--help")


def recovery_write_gate(config: AppConfig, *, server_stopped_confirmed: bool = False) -> dict:
    # Renaming a world needs the strict policy even if ordinary local editing
    # was configured with require_server_offline=False. Read-only still wins.
    return write_gate(replace(config, require_server_offline=True), unknown_status_confirmed=server_stopped_confirmed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unterbrochene Welt-Restores prüfen oder nach Bestätigung wiederaufnehmen.")
    parser.add_argument("paths", nargs="*", help="Welt- oder Suchordner; ohne Angabe gelten die konfigurierten Suchorte.")
    parser.add_argument(
        "--confirm-server-stopped", action="store_true",
        help="Bestätigt für diesen Lauf, dass Minecraft und Server vollständig gestoppt sind; erlaubt Recovery bei unbekanntem Status.",
    )
    args = parser.parse_args(argv)
    config = load_config()

    def gate_check() -> dict:
        gate = recovery_write_gate(config, server_stopped_confirmed=args.confirm_server_stopped)
        if gate["allowed"] and not args.confirm_server_stopped:
            return {**gate, "allowed": False, "reason": "Recovery benötigt --confirm-server-stopped."}
        return gate

    roots = args.paths or [root["path"] for root in get_configured_scan_roots(include_disabled=False, include_missing=True) if root.get("path")]
    results = recover_interrupted_restores(
        roots, max_depth=config.world_scan_depth, max_dirs=config.world_scan_max_dirs, recovery_gate_check=gate_check,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(result.get("status") in {"deferred-write-gate", "manual-recovery-required"} for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
