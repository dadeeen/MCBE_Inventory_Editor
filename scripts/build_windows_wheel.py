"""Build a release LevelDB wheel from hash-locked upstream source, without changing it."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.windows_wheels import (
    WHEEL_PYTHONS,
    WHEEL_VERSION,
    build_lock_sha256,
    leveldb_requirement,
    sha256,
    validate_wheel_file,
    wheel_name,
)

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path, source: Path | None = None) -> None:
    abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
    if (abi not in WHEEL_PYTHONS or sysconfig.get_platform() != "win-amd64"
            or platform.python_implementation() != "CPython" or sysconfig.get_config_var("Py_GIL_DISABLED")):
        raise ValueError("Build with standard CPython 3.13 or 3.14 on Windows x64")
    pins = re.findall(r"(?m)^([a-zA-Z0-9_-]+)==([^\s]+)", (ROOT / "requirements/build.txt").read_text())
    versions = {name: importlib.metadata.version(name) for name, _version in pins}
    if any(versions[name] != version for name, version in pins):
        raise ValueError("Install the hash-locked requirements/build.lock before building")
    requirement = leveldb_requirement(ROOT)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="leveldb-build-", dir=output.parent) as temporary:
        work = Path(temporary)
        if source is None:
            locked = work / "source.txt"
            locked.write_text(requirement, encoding="utf-8")
            subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--no-build-isolation",
                            "--no-binary=:all:", "--require-hashes", "-r", str(locked), "-d", str(work)], check=True)
            source = work / f"amulet_leveldb-{WHEEL_VERSION}.tar.gz"
        source = source.resolve()
        source_hash = sha256(source)
        if source_hash not in requirement:
            raise ValueError("Upstream source archive hash is not in requirements/runtime.txt")
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-cache-dir",
                        "--wheel-dir", str(work / "built"), str(source)], check=True)
        wheel = work / "built" / wheel_name(abi)
        validate_wheel_file(wheel, abi)
        files = {wheel.name: wheel.read_bytes()}
        with tarfile.open(source) as archive:
            prefix = f"amulet_leveldb-{WHEEL_VERSION}/"
            files["LICENSE.amulet-leveldb.txt"] = archive.extractfile(prefix + "LICENSE").read()
            header = archive.extractfile(prefix + "zlib/zlib.h").read()
            files["LICENSE.zlib.txt"] = header[:header.index(b"*/") + 2] + b"\n"
        files["LICENSE.leveldb.txt"] = (ROOT / "requirements/licenses/leveldb.txt").read_bytes()
        for name, data in files.items():
            (output / name).write_bytes(data)
        manifest = {
            "schema": 1, "abi": abi, "python": platform.python_version(), "platform": sysconfig.get_platform(),
            "source": {"file": source.name, "sha256": source_hash},
            "build_requirements_sha256": build_lock_sha256(ROOT), "build_tools": versions,
            "builder_sha256": sha256(Path(__file__)), "git_revision": os.environ.get("GITHUB_SHA"),
            "ci_run": os.environ.get("GITHUB_RUN_ID"), "files": {name: sha256(output / name) for name in files},
            "note": "Unmodified upstream sdist; Windows zlib static library is supplied by upstream in that sdist.",
        }
        (output / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built and validated {wheel_name(abi)} with provenance and license notices")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", type=Path, help="Optional existing sdist; its hash must match the lock")
    args = parser.parse_args()
    build(args.output, args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
