#!/usr/bin/env python3
"""Create an auditable runtime source ZIP from the project tree.

The bundle uses an explicit runtime allowlist. Tests, CI configuration,
development helpers, local caches, app data, backups, and player exports never
enter the archive even if they exist in a developer checkout after tests.

Every release ZIP also receives a generated RELEASE_MANIFEST.json.  The runtime
uses that manifest to make it obvious whether the current tree is a clean
release tree or a source/development checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
import zipfile
from pathlib import Path

try:
    from scripts.release_rules import (
        BLOCKED_RELEASE_FILE_NAMES,
        BLOCKED_RELEASE_FILE_PREFIXES,
        BLOCKED_RELEASE_SUFFIXES,
        is_blocked_release_dir_name,
        is_generated_world_work_dir,
    )
    from scripts.runtime_layout import REQUIRED_RUNTIME_FILES, is_runtime_relative_path, iter_runtime_files
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from release_rules import (  # type: ignore[no-redef]
        BLOCKED_RELEASE_FILE_NAMES,
        BLOCKED_RELEASE_FILE_PREFIXES,
        BLOCKED_RELEASE_SUFFIXES,
        is_blocked_release_dir_name,
        is_generated_world_work_dir,
    )
    from runtime_layout import REQUIRED_RUNTIME_FILES, is_runtime_relative_path, iter_runtime_files  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ARCHIVE_ROOT = "mcbe_inventory_editor"
RELEASE_MANIFEST_NAME = "RELEASE_MANIFEST.json"

EXCLUDED_SUFFIXES = set(BLOCKED_RELEASE_SUFFIXES)
EXCLUDED_FILE_PREFIXES = BLOCKED_RELEASE_FILE_PREFIXES
EXCLUDED_FILE_NAMES = set(BLOCKED_RELEASE_FILE_NAMES) | {RELEASE_MANIFEST_NAME}


def should_include(path: Path, *, root: Path = ROOT) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if path.is_symlink() or not is_runtime_relative_path(rel):
        return False
    if any(is_blocked_release_dir_name(part) for part in rel.parts):
        return False
    if any(is_generated_world_work_dir(part) for part in rel.parts):
        return False
    if path.suffix.casefold() in EXCLUDED_SUFFIXES:
        return False
    if path.name in EXCLUDED_FILE_NAMES or any(path.name == prefix or path.name.startswith(prefix + ".") for prefix in EXCLUDED_FILE_PREFIXES):
        return False
    if path.name.endswith("~"):
        return False
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return False
    if path.name.endswith((".mcbe-player.zip", ".mcbe-player-bundle.zip")):
        return False
    if path.name in {"Sample-World.zip"} or path.suffix.lower() in {".zip", ".mcworld", ".mcpack", ".mcaddon"}:
        return False
    return not path.name.endswith((".private.fixture.zip", ".metadata-sanitized.zip"))


def _project_version() -> str:
    try:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def _file_entry(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT).as_posix()),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def build_zip(output: Path) -> int:
    from mcbe_editor.distribution import build_manifest

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for path in iter_runtime_files(ROOT):
        if path.resolve() == output:
            continue
        if not should_include(path):
            continue
        paths.append(path)
    paths.sort()

    included = {path.relative_to(ROOT).as_posix() for path in paths}
    missing = sorted(REQUIRED_RUNTIME_FILES - included)
    if missing:
        print("Runtime package build FAILED: required files are missing:", file=sys.stderr)
        for rel in missing:
            print(f"- {rel}", file=sys.stderr)
        return 1

    files = [_file_entry(path) for path in paths]
    manifest = build_manifest(project_version=_project_version(), files=files)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    count = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            archive.write(path, Path(ARCHIVE_ROOT) / path.relative_to(ROOT))
            count += 1
        archive.writestr(str(Path(ARCHIVE_ROOT) / RELEASE_MANIFEST_NAME), manifest_bytes)
        count += 1
    print(f"Created {output} with {count} files including {RELEASE_MANIFEST_NAME}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a clean MCBE Inventory Editor runtime source ZIP.")
    parser.add_argument("--output", required=True, help="Target ZIP path.")
    args = parser.parse_args(argv)
    return build_zip(Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
