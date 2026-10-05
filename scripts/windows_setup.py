"""Install the hash-locked Windows runtime exclusively into the project's .venv."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def supported_python() -> bool:
    return (
        platform.python_implementation() == "CPython"
        and (3, 12) <= sys.version_info[:2] < (3, 15)
        and not sysconfig.get_config_var("Py_GIL_DISABLED")
        and sys.platform == "win32"
    )


def preflight() -> None:
    if not supported_python():
        raise ValueError("Supported: standard CPython 3.12, 3.13 or 3.14 on Windows")


def install(root: Path) -> None:
    preflight()
    if sys.prefix == sys.base_prefix:
        raise ValueError("Installation is allowed only inside the project's .venv")
    environment = Path(sys.prefix).resolve()
    if environment != (root / ".venv").resolve() or not environment.is_relative_to(root.resolve()):
        raise ValueError("Run setup.bat to install exclusively into this project's .venv")
    for name in ("bootstrap", "runtime"):
        if not all((root / "requirements" / f"{name}.{suffix}").is_file() for suffix in ("lock", "txt")):
            raise ValueError(f"Missing hash-locked requirements/{name}.lock or {name}.txt")
    print(f"Installing runtime wheels for Python {platform.python_version()}", flush=True)
    for name in ("bootstrap", "runtime"):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--only-binary=:all:", "--require-hashes", "-r", f"requirements/{name}.lock"],
            cwd=root,
            check=True,
        )
    subprocess.run([sys.executable, "-m", "pip", "check"], cwd=root, check=True)
    # A fresh process sees newly installed packages and detects broken imports.
    subprocess.run(
        [sys.executable, "-c", "import flask, waitress; from mcbe_editor.db import LevelDbAdapter; from mcbe_editor import nbt"],
        cwd=root,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "install"))
    args = parser.parse_args()
    try:
        if args.action == "install":
            install(ROOT)
        else:
            preflight()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Setup unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
