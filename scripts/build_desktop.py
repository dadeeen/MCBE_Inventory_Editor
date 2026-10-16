"""Build and validate a portable Windows folder; never overwrite an installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def verify_bundle(directory: Path) -> None:
    """Reject application state and unrelated source material before packaging."""
    from mcbe_editor.path_safety import is_linklike

    forbidden = {"data", "tests", "fixtures", ".git", ".venv", "node_modules", ".env", "desktop.log", "desktop.lock"}
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if is_linklike(path) or any(part.casefold() in forbidden or part.casefold().startswith(".env.") for part in relative.parts):
            raise ValueError(f"Unexpected file in desktop bundle: {relative}")
        if path.is_file() and (
            path.suffix.lower() in {".bat", ".cmd", ".mcworld", ".mcpack", ".mcaddon"}
            or path.name.casefold().endswith((".mcbe-player.zip", ".mcbe-player-bundle.zip"))
        ):
            raise ValueError(f"Unexpected file in desktop bundle: {relative}")
    for name in ("MCBEInventoryEditor.exe", "_internal/python312.dll", "_internal/templates/index.html", "_internal/static/app.js"):
        if not (directory / name).is_file():
            raise ValueError(f"Missing desktop bundle file: {name}")


def smoke_bundle(directory: Path, temporary: Path) -> None:
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(("MCBE_", "PYTHON", "WEBVIEW2_")) or key == "VIRTUAL_ENV":
            env.pop(key)
    profile = temporary / "profile"
    profile.mkdir()
    worlds = temporary / "worlds"
    worlds.mkdir()
    env.update(
        PATH=str(Path(os.environ["SYSTEMROOT"]) / "System32"),
        LOCALAPPDATA=str(profile),
        APPDATA=str(profile),
        USERPROFILE=str(profile),
        MCBE_WORLDS_ROOT=str(worlds),
        MCBE_STARTUP_NETWORK_CHECK="false",
        MCBE_STARTUP_SECURITY_REPORT="false",
        MCBE_LOG_LEVEL="WARNING",
    )
    report = temporary / "report.json"
    proc = subprocess.run(
        [
            str(directory / "MCBEInventoryEditor.exe"),
            "--data-dir",
            str(temporary / "data"),
            "--port",
            "0",
            "--diagnose",
            str(report),
            "--with-window",
        ],
        cwd=temporary,
        env=env,
        timeout=120,
        check=False,
    )
    result = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    if proc.returncode or result.get("ok") is not True or result.get("checks", {}).get("native_close") is not True:
        log = temporary / "data" / "desktop.log"
        details = log.read_text(encoding="utf-8")[-8000:] if log.is_file() else "No desktop log was written."
        raise RuntimeError(f"Packaged application check failed: {result}\n{details}")
    smoke_recovery(directory / "MCBEInventoryEditor.exe", temporary, env)
    print("Packaged assets, updater entry points, native window/close and guarded recovery passed with no Python in PATH.")


def smoke_recovery(executable: Path, temporary: Path, env: dict[str, str]) -> None:
    """Exercise the packaged recovery CLI only against a newly created journal."""
    from mcbe_editor.backup import _write_restore_transaction

    root = temporary / "recovery-worlds"
    root.mkdir()
    world = root / "Welt ü"
    transaction_id = "0123456789abcdef"
    rollback = root / f".{world.name}_rollback_interrupted_{transaction_id}"
    staging = root / f".{world.name}_restoring_interrupted"
    for path, contents in ((rollback, b"original world"), (staging, b"selected backup")):
        (path / "db").mkdir(parents=True)
        (path / "db" / "state.dat").write_bytes(contents)
    journal = Path(_write_restore_transaction(str(root), world.name, str(rollback), str(staging), transaction_id))
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    output = temporary / "recovery-report.txt"
    for confirmed, read_only in ((False, False), (True, True), (True, False)):
        command = [
            str(executable),
            "--data-dir",
            str(temporary / "data"),
            "--recovery-report",
            str(output),
            "--recover",
            str(world),
        ]
        if confirmed:
            command.append("--confirm-server-stopped")
        output.unlink(missing_ok=True)
        proc = subprocess.run(command, cwd=temporary, env={**env, "MCBE_READ_ONLY": str(read_only).lower()}, timeout=60, check=False)
        text = output.read_text(encoding="utf-8") if output.is_file() else "No recovery report was written."
        try:
            results = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Packaged recovery exited with {proc.returncode}: {text}") from exc
        blocked = not confirmed or read_only
        expected = "deferred-write-gate" if blocked else "original-restored"
        if proc.returncode != int(blocked) or len(results) != 1 or results[0].get("status") != expected:
            raise RuntimeError(f"Packaged recovery check failed: {results}")
        if blocked:
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            if before != after:
                raise RuntimeError("Blocked packaged recovery changed the synthetic world")
        elif (world / "db" / "state.dat").read_bytes() != b"original world" or journal.exists() or rollback.exists() or staging.exists():
            raise RuntimeError("Packaged recovery did not restore the original synthetic world")


def build(output: Path) -> Path:
    from mcbe_editor.distribution import build_manifest
    from scripts.runtime_layout import RUNTIME_DOC_PATHS

    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Build the Windows x64 desktop package with standard CPython 3.12 x64.")
    archive = output.parent / f"{output.name}.zip"
    if output.exists() or archive.exists() or archive.with_suffix(".zip.sha256").exists():
        raise FileExistsError(f"Output already exists; choose a new --output directory: {output}")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    temporary_root = ROOT / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    # TemporaryDirectory owns only a newly created child of the ignored workspace.
    with tempfile.TemporaryDirectory(prefix="desktop-build-", dir=temporary_root) as temp:
        temporary = Path(temp).resolve()
        if not temporary.is_relative_to(temporary_root.resolve()):
            raise ValueError("Desktop staging directory is outside the workspace")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--distpath",
                str(temporary / "dist"),
                "--workpath",
                str(temporary / "work"),
                str(ROOT / "packaging/windows/desktop.spec"),
            ],
            cwd=ROOT,
            check=True,
        )
        staged = temporary / "dist" / "MCBEInventoryEditor"
        for name in ("README.md", "README.de.md", "SECURITY.md", "SECURITY.de.md", "LICENSE"):
            shutil.copy2(ROOT / name, staged / name)
        for name in RUNTIME_DOC_PATHS:
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", staged / "_internal" / "PYTHON_LICENSE.txt")
        verify_bundle(staged)
        smoke_bundle(staged, temporary)
        verify_bundle(staged)
        files = [
            {"path": path.relative_to(staged).as_posix(), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(staged.rglob("*"))
            if path.is_file()
        ]
        manifest = build_manifest(project_version=version, files=files, created_by="scripts/build_desktop.py")
        (staged / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, output)
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                zipped.write(path, Path("MCBEInventoryEditor") / path.relative_to(output))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"mcbe_inventory_editor_{version}_windows_x64")
    args = parser.parse_args()
    print(build(args.output.expanduser().resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
