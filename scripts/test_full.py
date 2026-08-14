#!/usr/bin/env python3
"""Run the release/full test suite and fail if core native dependencies are missing."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    from test_artifacts import prune_stale_test_artifacts, test_artifact_root, unique_test_artifact_path
else:
    from .test_artifacts import prune_stale_test_artifacts, test_artifact_root, unique_test_artifact_path

CORE_TEST_DEPENDENCIES = ("amulet_nbt", "leveldb")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASETEMP = test_artifact_root() / "full-suite-basetemp"
DEFAULT_FAULTHANDLER_TIMEOUT_SECONDS = 120


def _missing_core_dependencies() -> list[str]:
    return [name for name in CORE_TEST_DEPENDENCIES if importlib.util.find_spec(name) is None]


def _has_pytest_ini_override(args: list[str], name: str) -> bool:
    for index, arg in enumerate(args):
        if arg == "-o" and index + 1 < len(args) and args[index + 1].startswith(f"{name}="):
            return True
        if arg.startswith("-o") and arg[2:].lstrip().startswith(f"{name}="):
            return True
    return False


def _add_default_hang_diagnostics(args: list[str]) -> None:
    if not _has_pytest_ini_override(args, "faulthandler_timeout"):
        args.extend(["-o", f"faulthandler_timeout={DEFAULT_FAULTHANDLER_TIMEOUT_SECONDS}"])
    if not _has_pytest_ini_override(args, "faulthandler_exit_on_timeout"):
        args.extend(["-o", "faulthandler_exit_on_timeout=true"])


def _default_basetemp() -> Path:
    return unique_test_artifact_path(DEFAULT_BASETEMP.name)


def _prepare_default_basetemp() -> Path:
    path = _default_basetemp()
    prune_stale_test_artifacts(protected=(path,))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _run_pytest(cmd: list[str]) -> int:
    proc = subprocess.Popen(cmd, cwd=ROOT)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            return proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            return proc.wait()


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    default_basetemp: Path | None = None
    missing = _missing_core_dependencies()
    if missing:
        print(
            "Full test suite requires installed core dependencies: " + ", ".join(missing),
            file=sys.stderr,
        )
        print(
            "Use Python 3.12 and install the locked build and dev requirements before running release/CI tests.",
            file=sys.stderr,
        )
        return 2
    if not any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in args):
        default_basetemp = _prepare_default_basetemp()
        args.append(f"--basetemp={default_basetemp}")
    else:
        prune_stale_test_artifacts()
    _add_default_hang_diagnostics(args)
    cmd = [sys.executable, "-m", "pytest", "tests", *args]
    result = _run_pytest(cmd)
    if result == 0 and default_basetemp is not None:
        shutil.rmtree(default_basetemp, ignore_errors=True)
    elif default_basetemp is not None and default_basetemp.exists():
        print(f"Full test diagnostics retained at {default_basetemp}", file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
