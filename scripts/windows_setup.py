"""Preflight and install the Windows runtime; called by setup.bat per interpreter."""

from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import os
import platform
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.windows_wheels import WHEEL_VERSION, sha256, validated_wheel

ROOT = Path(__file__).resolve().parents[1]
REDIST_HELP = "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist"


def require_cpp_runtime() -> None:
    try:
        ctypes.WinDLL("msvcp140.dll")
    except OSError as exc:
        raise ValueError("Microsoft Visual C++ Runtime is missing or cannot be loaded. Install the latest Visual C++ "
                         f"Redistributable for this Python architecture, then run setup again: {REDIST_HELP}") from exc


def supported_python() -> bool:
    return (platform.python_implementation() == "CPython" and (3, 12) <= sys.version_info[:2] < (3, 15)
            and not sysconfig.get_config_var("Py_GIL_DISABLED") and sys.platform == "win32")


def bundled_wheel(root: Path) -> Path | None:
    if sysconfig.get_platform() != "win-amd64":
        return None
    return validated_wheel(root, f"cp{sys.version_info.major}{sys.version_info.minor}")


def published_wheel_available() -> bool:
    return sys.version_info[:2] == (3, 12) and sysconfig.get_platform() in {"win-amd64", "win-arm64"}


def compiler_available() -> bool:
    program_files = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    vswhere = program_files / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        return False
    found = subprocess.run(
        [str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
         "-property", "installationPath"], capture_output=True, text=True, timeout=15, check=True,
    ).stdout.strip()
    if not found or not (Path(found) / "VC/Auxiliary/Build/vcvarsall.bat").is_file():
        return False
    if not list((Path(found) / "VC/Tools/MSVC").glob("*/bin/Hostx64/x64/cl.exe")):
        return False
    sdk = program_files / "Windows Kits/10"
    return any((sdk / "Lib" / headers.name / "um/x64/kernel32.lib").is_file()
               and (headers / "um/Windows.h").is_file() and (headers / "ucrt/stdio.h").is_file()
               for headers in (sdk / "Include").glob("*"))


def installed_driver() -> bool:
    try:
        if importlib.metadata.version("amulet-leveldb") != WHEEL_VERSION:
            return False
        import leveldb
        return callable(leveldb.LevelDB)
    except (ImportError, importlib.metadata.PackageNotFoundError):
        return False


def installation_mode(root: Path, *, allow_build: bool = True, existing: bool = True) -> str:
    if not supported_python():
        raise ValueError("Supported: standard CPython 3.12, 3.13 or 3.14 on Windows")
    # Validate a supplied bundle even if the current environment already works.
    wheel = bundled_wheel(root)
    if existing and installed_driver():
        return "installed"
    if wheel is not None:
        return "bundled"
    if published_wheel_available():
        return "published"
    if allow_build and sysconfig.get_platform() == "win-amd64" and compiler_available():
        return "source"
    raise ValueError("No compatible wheel or C++ build tools/Windows SDK found. Use the runtime release ZIP with bundled "
                     "Windows x64 wheels, Python 3.12 with a published wheel, or install the C++ build tools and SDK.")


def install(root: Path, *, allow_build: bool = True) -> None:
    if sys.prefix == sys.base_prefix:
        raise ValueError("Installation is allowed only inside the project's .venv")
    if Path(sys.prefix).resolve() != (root / ".venv").resolve() or not Path(sys.prefix).resolve().is_relative_to(root.resolve()):
        raise ValueError("Run setup.bat to install exclusively into this project's .venv")
    mode = installation_mode(root, allow_build=allow_build)
    require_cpp_runtime()
    print(f"Python {platform.python_version()}: LevelDB installation mode: {mode}", flush=True)

    def pip(*args: str) -> None:
        subprocess.run([sys.executable, "-m", "pip", *args], cwd=root, check=True)

    pip("install", "--only-binary=:all:", "--require-hashes", "-r", "requirements/bootstrap.lock")
    if mode == "bundled":
        wheel = bundled_wheel(root)
        assert wheel is not None
        with tempfile.TemporaryDirectory(prefix="wheel-install-", dir=sys.prefix) as temporary:
            locked = Path(temporary) / "wheel.txt"
            locked.write_text(f"amulet-leveldb @ {wheel.as_uri()} --hash=sha256:{sha256(wheel)}\n", encoding="utf-8")
            pip("install", "--no-index", "--no-deps", "--require-hashes", "-r", str(locked))
    if mode == "source":
        pip("install", "--only-binary=:all:", "--require-hashes", "-r", "requirements/build.lock")
        pip("install", "--no-build-isolation", "--only-binary=:all:", "--no-binary=amulet-leveldb",
            "--require-hashes", "-r", "requirements/runtime.lock")
    else:
        pip("install", "--only-binary=:all:", "--require-hashes", "-r", "requirements/runtime.lock")
    pip("check")
    if not installed_driver():
        raise ValueError("LevelDB could not be imported after installation. Install or repair the latest Microsoft "
                         f"Visual C++ Redistributable for this Python architecture: {REDIST_HELP}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("probe-wheel", "probe-build", "preflight", "install"))
    parser.add_argument("--no-build", action="store_true", help="Never compile a dependency locally")
    args = parser.parse_args()
    try:
        if args.action == "install":
            install(ROOT, allow_build=not args.no_build)
        else:
            mode = installation_mode(ROOT, allow_build=args.action != "probe-wheel" and not args.no_build,
                                     existing=args.action == "preflight")
            if args.action == "preflight":
                require_cpp_runtime()
                print(f"LevelDB installation mode: {mode}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Setup unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
