"""Validate the optional, release-built Windows LevelDB wheels using only stdlib."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from email.parser import Parser
from pathlib import Path

WHEEL_VERSION = "1.0.6"
WHEEL_PYTHONS = ("cp313", "cp314")
LICENSE_FILES = ("LICENSE.amulet-leveldb.txt", "LICENSE.leveldb.txt", "LICENSE.zlib.txt")


def wheel_name(abi: str) -> str:
    return f"amulet_leveldb-{WHEEL_VERSION}-{abi}-{abi}-win_amd64.whl"


OPTIONAL_WHEEL_PATHS = frozenset(
    f"wheels/{abi}/{name}"
    for abi in WHEEL_PYTHONS
    for name in (wheel_name(abi), "provenance.json", *LICENSE_FILES)
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_lock_sha256(root: Path) -> str:
    # Git may check .txt files out as CRLF on Windows and LF in the package job.
    return hashlib.sha256((root / "requirements/build.txt").read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def leveldb_requirement(root: Path) -> str:
    text = (root / "requirements/runtime.txt").read_text(encoding="utf-8")
    match = re.search(r"(?m)^amulet-leveldb==([^\s]+).*?(?=\n[^ \t#\\]|\Z)", text, re.S)
    if not match or match[1] != WHEEL_VERSION:
        raise ValueError("Windows wheel support must match the locked LevelDB version")
    hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", match[0])
    if not hashes:
        raise ValueError("Missing locked LevelDB hashes")
    return f"amulet-leveldb=={WHEEL_VERSION} " + " ".join(f"--hash=sha256:{value}" for value in hashes) + "\n"


def validate_wheel_file(path: Path, abi: str) -> None:
    if path.name != wheel_name(abi):
        raise ValueError("Unexpected Windows wheel filename")
    with zipfile.ZipFile(path) as archive:
        prefix = f"amulet_leveldb-{WHEEL_VERSION}.dist-info/"
        metadata = Parser().parsestr(archive.read(prefix + "METADATA").decode("utf-8"))
        tags = Parser().parsestr(archive.read(prefix + "WHEEL").decode("utf-8"))
        if metadata.get("Version") != WHEEL_VERSION or metadata.get("Name", "").replace("_", "-").lower() != "amulet-leveldb":
            raise ValueError("Unexpected wheel package metadata")
        if f"{abi}-{abi}-win_amd64" not in tags.get_all("Tag", []):
            raise ValueError("Unexpected wheel ABI")


def validated_wheel(root: Path, abi: str) -> Path | None:
    if abi not in WHEEL_PYTHONS:
        return None
    directory = root / "wheels" / abi
    if not directory.exists():
        return None
    if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
        raise ValueError("Wheel bundle must stay inside the project")
    manifest = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("source"), dict):
        raise ValueError("Invalid wheel provenance manifest")
    expected = {wheel_name(abi), *LICENSE_FILES}
    files = manifest.get("files", {})
    if not isinstance(files, dict) or manifest.get("schema") != 1 or manifest.get("abi") != abi or set(files) != expected:
        raise ValueError("Invalid wheel provenance manifest")
    source_hash = manifest.get("source", {}).get("sha256")
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash) or source_hash not in leveldb_requirement(root):
        raise ValueError("Wheel source does not match the locked upstream distribution")
    if manifest.get("build_requirements_sha256") != build_lock_sha256(root):
        raise ValueError("Wheel build requirements do not match this release")
    for name in expected:
        path = directory / name
        if path.is_symlink() or sha256(path) != files[name]:
            raise ValueError(f"Wheel bundle integrity check failed: {name}")
    path = directory / wheel_name(abi)
    validate_wheel_file(path, abi)
    return path
