#!/usr/bin/env python3
"""Validate release archive hygiene, directory dry-runs and manifest integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

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

BAD_SUFFIXES = set(BLOCKED_RELEASE_SUFFIXES)
BAD_FILE_NAMES = set(BLOCKED_RELEASE_FILE_NAMES)
BAD_FILE_PREFIXES = BLOCKED_RELEASE_FILE_PREFIXES
RELEASE_MANIFEST_NAME = "RELEASE_MANIFEST.json"
MANIFEST_FORMAT = "mcbe-inventory-editor-release-manifest"


def _manifest_name(names: list[str]) -> str | None:
    matches = [name for name in names if PurePosixPath(name).name == RELEASE_MANIFEST_NAME]
    return matches[0] if len(matches) == 1 else None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_hash(entries: list[dict]) -> str:
    h = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item.get("path", ""))):
        h.update(str(entry.get("path", "")).encode("utf-8"))
        h.update(b"\0")
        h.update(str(entry.get("sha256", "")).encode("ascii", errors="ignore"))
        h.update(b"\0")
        h.update(str(entry.get("size", "")).encode("ascii", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()


def _common_root_prefix(file_names: list[str]) -> str:
    parts = [PurePosixPath(name).parts for name in file_names if name and not name.endswith("/")]
    if not parts:
        return ""
    first = parts[0][0] if parts[0] else ""
    if first and all(len(item) > 1 and item[0] == first for item in parts):
        return first
    return ""


def _relative_archive_name(name: str, root_prefix: str) -> str:
    posix = PurePosixPath(name)
    if root_prefix:
        try:
            rel = posix.relative_to(PurePosixPath(root_prefix))
        except ValueError:
            rel = posix
    else:
        rel = posix
    return "" if str(rel) == "." else str(rel)


def _check_member_hygiene(name: str, rel: str) -> list[str]:
    failures: list[str] = []
    rel_posix = PurePosixPath(rel)
    if not rel or name.endswith("/"):
        return failures
    if rel == RELEASE_MANIFEST_NAME:
        return failures
    if not is_runtime_relative_path(rel_posix):
        failures.append(f"unexpected non-runtime path: {name}")
    if any(part == "data" and (index == 0 or rel_posix.parts[index - 1] != "tests") for index, part in enumerate(rel_posix.parts)):
        failures.append(f"forbidden runtime data path: {name}")
    if any(is_blocked_release_dir_name(part) for part in rel_posix.parts):
        failures.append(f"forbidden path part: {name}")
    if any(is_generated_world_work_dir(part) for part in rel_posix.parts):
        failures.append(f"forbidden generated world work directory: {name}")
    if rel_posix.suffix.casefold() in BAD_SUFFIXES:
        failures.append(f"forbidden bytecode file: {name}")
    if rel_posix.name in BAD_FILE_NAMES or any(rel_posix.name == prefix or rel_posix.name.startswith(prefix + ".") for prefix in BAD_FILE_PREFIXES):
        failures.append(f"forbidden local/generated file: {name}")
    if rel_posix.name.endswith("~"):
        failures.append(f"forbidden editor backup file: {name}")
    if rel_posix.name == ".env" or (rel_posix.name.startswith(".env.") and rel_posix.name != ".env.example"):
        failures.append(f"forbidden environment file: {name}")
    if rel_posix.name.endswith((".mcbe-player.zip", ".mcbe-player-bundle.zip")):
        failures.append(f"forbidden player export: {name}")
    is_nested_package = rel_posix.suffix.lower() in {
        ".zip",
        ".mcworld",
        ".mcpack",
        ".mcaddon",
    } or rel_posix.name.endswith((".private.fixture.zip", ".metadata-sanitized.zip"))
    if is_nested_package:
        failures.append(f"forbidden private/pack fixture artifact: {name}")
    return failures


def _validate_manifest(names: list[str], read_file, root_prefix: str, manifest_name: str | None) -> list[str]:
    failures: list[str] = []
    if not manifest_name:
        return ["RELEASE_MANIFEST.json missing or duplicated"]
    try:
        manifest = json.loads(read_file(manifest_name).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"RELEASE_MANIFEST.json invalid: {exc}"]
    if manifest.get("format") != MANIFEST_FORMAT:
        failures.append("RELEASE_MANIFEST.json has unknown format")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        failures.append("RELEASE_MANIFEST.json has no files list")
        entries = []
    by_path = {}
    name_set = set(names)
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append("RELEASE_MANIFEST.json contains non-object file entry")
            continue
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel:
            failures.append("RELEASE_MANIFEST.json contains entry without path")
            continue
        by_path[rel] = entry
        archive_name = str(PurePosixPath(root_prefix) / rel) if root_prefix else rel
        if archive_name not in name_set:
            failures.append(f"manifest file missing from archive: {rel}")
            continue
        data = read_file(archive_name)
        if entry.get("size") != len(data):
            failures.append(f"manifest size mismatch: {rel}")
        if entry.get("sha256") != _sha256(data):
            failures.append(f"manifest sha256 mismatch: {rel}")
    for name in names:
        if name.endswith("/"):
            continue
        posix = PurePosixPath(name)
        if posix.name == RELEASE_MANIFEST_NAME:
            continue
        rel = _relative_archive_name(name, root_prefix)
        if rel and rel not in by_path:
            failures.append(f"archive file missing from manifest: {rel}")
    if entries and manifest.get("content_sha256") != _content_hash(entries):
        failures.append("RELEASE_MANIFEST.json content_sha256 mismatch")
    return failures


def _check_required(names: list[str], root_prefix: str = "") -> list[str]:
    failures: list[str] = []
    rel_names = {_relative_archive_name(name, root_prefix) for name in names}
    for required in sorted(REQUIRED_RUNTIME_FILES):
        if required not in rel_names:
            failures.append(f"required runtime file missing: {required}")
    if any(name.endswith("/item_db.py") or name == "item_db.py" for name in names):
        failures.append("legacy item_db.py must not be shipped")
    return failures


def _print_result(label: str, failures: list[str]) -> int:
    if failures:
        print("Release check FAILED:", file=sys.stderr)
        for failure in failures[:100]:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"Release check OK: {label}")
    return 0


def check_archive(path: str) -> int:
    failures: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        file_names = [name for name in names if name and not name.endswith("/")]
        root_prefix = _common_root_prefix(file_names)
        if file_names and not root_prefix:
            failures.append("release archive must contain exactly one top-level root directory")
        manifest_name = _manifest_name(file_names)
        for name in names:
            rel = _relative_archive_name(name, root_prefix)
            failures.extend(_check_member_hygiene(name, rel))
        failures.extend(_check_required(file_names, root_prefix))
        failures.extend(_validate_manifest(file_names, archive.read, root_prefix, manifest_name))
    return _print_result(path, failures)


def check_path(path: str) -> int:
    """Dry-run the release include set for a source/release directory.

    Private fixtures and local data may exist in the working tree as long as the
    release builder would exclude them. This mode answers: "Would a release built
    from this tree pass hygiene checks?" without creating an archive.
    """

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        print(f"Release check FAILED:\n- path is not a directory: {root}", file=sys.stderr)
        return 1
    project_root = root
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from scripts.make_release_zip import should_include
    except Exception as exc:  # pragma: no cover - defensive CLI path
        print(f"Release check FAILED:\n- cannot import release include rules: {exc}", file=sys.stderr)
        return 1
    failures: list[str] = []
    names: list[str] = []
    for candidate in iter_runtime_files(root):
        if not should_include(candidate, root=root):
            continue
        rel = candidate.relative_to(root).as_posix()
        names.append(rel)
        failures.extend(_check_member_hygiene(rel, rel))
    failures.extend(_check_required(names))
    return _print_result(str(root), failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an MCBE Inventory Editor release ZIP or release dry-run path.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--archive", help="ZIP file to inspect.")
    group.add_argument("--path", help="Project directory to inspect with the release include rules.")
    args = parser.parse_args(argv)
    if args.archive:
        return check_archive(args.archive)
    return check_path(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
