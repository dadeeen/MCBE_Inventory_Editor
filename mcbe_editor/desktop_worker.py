"""Allowlisted updater subprocesses for a windowed, frozen executable.

The frozen executable is not a Python CLI: ``-m`` and ``-c`` cannot be used.
Explicit UTF-8 output files also work when Windows provides no standard streams.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

WORKERS = frozenset({"scripts.update_db", "scripts.update_icons"})


def run_frozen_update(module: str, args: list[str], *, cwd: str, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    if module not in WORKERS:
        raise ValueError("Unsupported desktop worker")
    with tempfile.TemporaryDirectory(prefix="mcbe-update-") as temporary:
        output = Path(temporary) / "output.txt"
        command = [sys.executable, "--worker", module, "--worker-output", str(output), "--", *args]
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        text = output.read_text(encoding="utf-8") if output.is_file() else "Desktop worker exited without output."
        return subprocess.CompletedProcess(command, result.returncode, text)


def worker_main(module: str, output: Path, args: list[str]) -> int:
    if module not in WORKERS:
        raise ValueError("Unsupported desktop worker")
    previous = sys.argv
    try:
        sys.argv = [module, *args]
        with output.open("w", encoding="utf-8") as handle, contextlib.redirect_stdout(handle), contextlib.redirect_stderr(handle):
            try:
                if module == "scripts.update_db":
                    from scripts.update_db import main
                else:
                    from scripts.update_icons import main
                return int(main() or 0)
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else int(exc.code is not None)
            except Exception:
                traceback.print_exc()
                return 1
    finally:
        sys.argv = previous
