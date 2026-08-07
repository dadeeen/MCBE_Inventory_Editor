#!/usr/bin/env python3
"""Inspect and prepare private Minecraft Bedrock sample worlds for tests.

This script deliberately works without amulet_nbt/amulet-leveldb so it can run
in lightweight CI jobs.  That also means it cannot fully anonymize player NBT in
LevelDB.  Treat worlds with a real ``db/`` as private unless they were sanitized
by a LevelDB/NBT-aware process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPORT_FORMAT = "mcbe-private-world-fixture-report"
PUBLIC_SCANNER_NOTICE = "PUBLIC_SCANNER_FIXTURE.txt"
SANITIZATION_NOTICE = "SANITIZATION_NOTICE.txt"
PLAYER_MARKERS = (b"~local_player", b"player_", b"minecraft:player")
DEFAULT_PUBLIC_ROOT = "public_scanner_fixture"
DEFAULT_PRIVATE_ROOT = "private_fixture_world"


class FixtureWorldError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_parts(name: str) -> tuple[str, ...]:
    if "\\" in name or name.startswith("/"):
        raise FixtureWorldError(f"Unsicherer ZIP-Pfad: {name!r}")
    parts = PurePosixPath(name).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise FixtureWorldError(f"Unsicherer ZIP-Pfad: {name!r}")
    if any(":" in part for part in parts[:1]):
        raise FixtureWorldError(f"Unsicherer ZIP-Pfad: {name!r}")
    return parts


def _common_root(names: list[str]) -> str | None:
    real_names = [name for name in names if name and not name.endswith("/")]
    if not real_names:
        return None
    first_parts = _safe_parts(real_names[0])
    if len(first_parts) < 2:
        return None
    root = first_parts[0]
    for name in real_names[1:]:
        parts = _safe_parts(name)
        if len(parts) < 2 or parts[0] != root:
            return None
    return root


def _strip_common_root(name: str, root: str | None) -> str:
    parts = _safe_parts(name)
    if root and parts and parts[0] == root:
        parts = parts[1:]
    return "/".join(parts)


def _iter_world_entries(archive: zipfile.ZipFile) -> tuple[str | None, list[tuple[zipfile.ZipInfo, str]]]:
    names = archive.namelist()
    root = _common_root(names)
    entries: list[tuple[zipfile.ZipInfo, str]] = []
    for info in archive.infolist():
        if not info.filename or info.filename.endswith("/"):
            continue
        rel = _strip_common_root(info.filename, root)
        if not rel:
            continue
        entries.append((info, rel))
    return root, entries


def _read_text_entry(archive: zipfile.ZipFile, entries: list[tuple[zipfile.ZipInfo, str]], rel_name: str, *, include_private: bool) -> dict[str, Any]:
    for info, rel in entries:
        if rel == rel_name:
            data = archive.read(info)
            text = data.decode("utf-8", errors="replace").strip()
            result: dict[str, Any] = {
                "present": True,
                "byte_length": len(data),
                "sha256": _sha256_bytes(data),
                "text_length": len(text),
            }
            if include_private:
                result["text"] = text
            return result
    return {"present": False}


def inspect_world_zip(path: Path, *, include_private: bool = False) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FixtureWorldError(f"Datei existiert nicht: {path}")

    with zipfile.ZipFile(path) as archive:
        root, entries = _iter_world_entries(archive)
        rel_names = [rel for _info, rel in entries]
        total_uncompressed = sum(info.file_size for info, _rel in entries)
        db_entries = [(info, rel) for info, rel in entries if rel == "db" or rel.startswith("db/")]
        db_files = [(info, rel) for info, rel in db_entries if not rel.endswith("/")]
        marker_hits = {marker.decode("ascii", errors="replace"): 0 for marker in PLAYER_MARKERS}
        db_scanned_bytes = 0
        db_scanned_files = 0
        for info, _rel in db_files:
            # The report is a privacy triage, not a full forensic scan.  Reading
            # the DB files here is OK because the script is run explicitly by the
            # developer against a private local fixture.
            data = archive.read(info)
            db_scanned_files += 1
            db_scanned_bytes += len(data)
            for marker in PLAYER_MARKERS:
                marker_hits[marker.decode("ascii", errors="replace")] += data.count(marker)

    contains_player_markers = any(count > 0 for count in marker_hits.values())
    is_public_scanner = _is_public_scanner_fixture(rel_names, db_files)
    effective_db_files = [] if is_public_scanner else db_files
    with zipfile.ZipFile(path) as archive:
        levelname = _read_text_entry(archive, entries, "levelname.txt", include_private=include_private)

    return {
        "format": REPORT_FORMAT,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "input": {
            "name": path.name,
            "size": path.stat().st_size,
            "sha256": _sha256_file(path),
        },
        "zip": {
            "common_root": root,
            "entry_count": len(entries),
            "total_uncompressed_size": total_uncompressed,
            "has_top_level_folder": bool(root),
        },
        "world_shape": {
            "has_level_dat": "level.dat" in rel_names,
            "has_level_dat_old": "level.dat_old" in rel_names,
            "has_levelname_txt": "levelname.txt" in rel_names,
            "has_world_icon": "world_icon.jpeg" in rel_names or "world_icon.png" in rel_names,
            "has_db_dir": any(rel == "db" or rel.startswith("db/") for rel in rel_names),
            "db_file_count": len(db_files),
            "db_total_size": sum(info.file_size for info, _rel in db_files),
            "public_scanner_fixture": is_public_scanner,
        },
        "levelname": levelname,
        "privacy": {
            "contains_leveldb": bool(effective_db_files),
            "contains_player_markers": contains_player_markers,
            "player_marker_counts": marker_hits,
            "db_scanned_files": db_scanned_files,
            "db_scanned_bytes": db_scanned_bytes,
            "safe_to_commit": is_public_scanner or not effective_db_files,
            "recommendation": (
                "Public scanner fixture: safe to commit, but not usable for real player/NBT integration tests."
                if is_public_scanner
                else (
                    "Treat this archive as private. Without amulet-leveldb/amulet_nbt this script cannot anonymize player NBT in LevelDB."
                    if effective_db_files
                    else "No LevelDB files were present; this may be a scanner-only fixture."
                )
            ),
        },
    }


def _is_public_scanner_fixture(rel_names: list[str], db_files: list[tuple[zipfile.ZipInfo, str]]) -> bool:
    """Return True for deliberately public, non-playable scanner fixtures.

    These fixtures intentionally contain only ``db/.placeholder`` so scanner and
    restore-preview code can exercise a Bedrock-like folder shape.  They must not
    be reported as private LevelDB worlds just because the placeholder lives
    under ``db/``.
    """

    rel_set = set(rel_names)
    allowed = {
        "levelname.txt",
        "world_behavior_packs.json",
        "world_resource_packs.json",
        "db/.placeholder",
        PUBLIC_SCANNER_NOTICE,
    }
    if PUBLIC_SCANNER_NOTICE not in rel_set or "db/.placeholder" not in rel_set:
        return False
    if any(rel.startswith("db/") and rel != "db/.placeholder" for _info, rel in db_files):
        return False
    forbidden_private = {"level.dat", "level.dat_old", "world_icon.jpeg", "world_icon.png"}
    if rel_set & forbidden_private:
        return False
    return rel_set.issubset(allowed)


def _write_json(data: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(f"Wrote {output}")
    else:
        print(text, end="")


def _write_zip_entry(out: zipfile.ZipFile, name: str, data: bytes | str) -> None:
    if isinstance(data, str):
        data = data.encode("utf-8")
    info = zipfile.ZipInfo(name)
    info.compress_type = zipfile.ZIP_DEFLATED
    out.writestr(info, data)


def make_scanner_fixture(input_zip: Path, output_zip: Path, *, level_name: str = "MCBE Test Fixture") -> dict[str, Any]:
    """Create a public, non-playable scanner fixture from a private world ZIP.

    The generated archive deliberately drops all LevelDB files and replaces them
    with an empty db/.placeholder file. It is useful for world scanner, ZIP hygiene
    and restore-preview tests, but not for player/NBT integration tests.
    """

    report = inspect_world_zip(input_zip, include_private=False)
    output_zip = output_zip.expanduser().resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    root = DEFAULT_PUBLIC_ROOT
    kept: list[str] = []
    dropped_db_files = 0
    with zipfile.ZipFile(input_zip) as archive, zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        _old_root, entries = _iter_world_entries(archive)
        for _info, rel in entries:
            # Public scanner fixtures must not reuse private binary world data.
            # Keep only neutral, freshly generated metadata plus an empty db/
            # marker so world-scan/restore-preview code can exercise paths.
            if rel.startswith("db/"):
                dropped_db_files += 1
        _write_zip_entry(out, f"{root}/levelname.txt", level_name + "\n")
        _write_zip_entry(out, f"{root}/world_behavior_packs.json", "[]\n")
        _write_zip_entry(out, f"{root}/world_resource_packs.json", "[]\n")
        _write_zip_entry(out, f"{root}/db/.placeholder", "scanner fixture only; original LevelDB was intentionally removed\n")
        kept.extend(["levelname.txt", "world_behavior_packs.json", "world_resource_packs.json", "db/.placeholder"])
        _write_zip_entry(
            out,
            f"{root}/{PUBLIC_SCANNER_NOTICE}",
            "This archive was generated for non-NBT scanner/restore-preview tests.\n"
            "It is not a playable Bedrock world and contains no original LevelDB files.\n",
        )
    return {
        "format": "mcbe-public-scanner-fixture-result",
        "input_report": report,
        "output": {"path": str(output_zip), "size": output_zip.stat().st_size, "sha256": _sha256_file(output_zip)},
        "level_name": level_name,
        "kept_entries": sorted(set(kept)),
        "dropped_leveldb_files": dropped_db_files,
        "safe_to_commit": True,
        "limits": "Scanner fixture only; not usable for real player/NBT integration tests.",
    }


def make_private_metadata_copy(input_zip: Path, output_zip: Path, *, level_name: str = "Private Fixture World", strip_icon: bool = True) -> dict[str, Any]:
    """Create a private metadata-normalized copy while preserving LevelDB.

    This is convenient for local tests, but it is still private because player
    data in LevelDB is intentionally untouched.
    """

    report = inspect_world_zip(input_zip, include_private=False)
    output_zip = output_zip.expanduser().resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    root = DEFAULT_PRIVATE_ROOT
    with zipfile.ZipFile(input_zip) as archive, zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        _old_root, entries = _iter_world_entries(archive)
        for info, rel in entries:
            if rel == "levelname.txt":
                _write_zip_entry(out, f"{root}/levelname.txt", level_name + "\n")
                continue
            if strip_icon and (rel == "world_icon.jpeg" or rel == "world_icon.png"):
                continue
            data = archive.read(info)
            _write_zip_entry(out, f"{root}/{rel}", data)
        _write_zip_entry(
            out,
            f"{root}/{SANITIZATION_NOTICE}",
            "Private metadata-normalized copy. LevelDB/player NBT was NOT anonymized.\n"
            "Do not commit or publish this file unless it was later processed by a real LevelDB/NBT anonymizer.\n",
        )
    return {
        "format": "mcbe-private-metadata-copy-result",
        "input_report": report,
        "output": {"path": str(output_zip), "size": output_zip.stat().st_size, "sha256": _sha256_file(output_zip)},
        "level_name": level_name,
        "safe_to_commit": False,
        "limits": "LevelDB/player NBT is preserved and remains private.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or prepare Minecraft Bedrock fixture world ZIPs.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    inspect_p = sub.add_parser("inspect", help="Create a privacy/shape report for a world ZIP.")
    inspect_p.add_argument("--world-zip", required=True)
    inspect_p.add_argument("--output")
    inspect_p.add_argument("--include-private", action="store_true", help="Include raw text metadata such as levelname in the report.")

    scanner_p = sub.add_parser("make-scanner-fixture", help="Create a public scanner-only fixture with LevelDB removed.")
    scanner_p.add_argument("--world-zip", required=True)
    scanner_p.add_argument("--output", required=True)
    scanner_p.add_argument("--level-name", default="MCBE Test Fixture")
    scanner_p.add_argument("--report-output")

    private_p = sub.add_parser("make-private-metadata-copy", help="Create a private metadata-normalized copy that preserves LevelDB.")
    private_p.add_argument("--world-zip", required=True)
    private_p.add_argument("--output", required=True)
    private_p.add_argument("--level-name", default="Private Fixture World")
    private_p.add_argument("--keep-icon", action="store_true")
    private_p.add_argument("--report-output")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "inspect":
            report = inspect_world_zip(Path(args.world_zip), include_private=args.include_private)
            _write_json(report, Path(args.output) if args.output else None)
            return 0
        if args.cmd == "make-scanner-fixture":
            result = make_scanner_fixture(Path(args.world_zip), Path(args.output), level_name=args.level_name)
            _write_json(result, Path(args.report_output) if args.report_output else None)
            return 0
        if args.cmd == "make-private-metadata-copy":
            result = make_private_metadata_copy(Path(args.world_zip), Path(args.output), level_name=args.level_name, strip_icon=not args.keep_icon)
            _write_json(result, Path(args.report_output) if args.report_output else None)
            return 0
    except (FixtureWorldError, zipfile.BadZipFile, OSError) as exc:
        print(f"fixture_world: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
