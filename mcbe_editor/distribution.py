from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
RELEASE_MANIFEST = APP_ROOT / "RELEASE_MANIFEST.json"
MANIFEST_FORMAT = "mcbe-inventory-editor-release-manifest"

# Runtime/developer by-products that may exist next to a valid release without
# changing the shipped application content. Security-relevant private artifacts
# such as fixtures/private/ and dist/*.zip are intentionally NOT ignored here.
IGNORED_TREE_EXTRA_PARTS = {
    "data",
    "__pycache__",
    ".pytest_cache",
    ".pip-tools-cache",
    ".ruff_cache",
    ".mypy_cache",
    ".lockcheck",
    ".venv",
    "venv",
}
IGNORED_TREE_EXTRA_SUFFIXES = {".pyc", ".pyo"}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _safe_relative(path: Path, root: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return None


def release_manifest() -> dict[str, Any] | None:
    data = _read_json(RELEASE_MANIFEST)
    if not data or data.get("format") != MANIFEST_FORMAT:
        return None
    return data


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_ignored_tree_extra(rel: Path) -> bool:
    return any(part in IGNORED_TREE_EXTRA_PARTS for part in rel.parts) or rel.suffix in IGNORED_TREE_EXTRA_SUFFIXES


def _tree_manifest_status(manifest: dict[str, Any]) -> dict[str, Any]:
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return {"status": "invalid", "issues": ["files list missing"], "extra_files": [], "missing_files": [], "modified_files": []}
    by_path: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            issues.append("invalid manifest entry")
            continue
        by_path[entry["path"]] = entry

    actual_files: dict[str, Path] = {}
    extra_files: list[str] = []
    for path in APP_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(APP_ROOT)
        if rel_path.name == "RELEASE_MANIFEST.json":
            continue
        if _is_ignored_tree_extra(rel_path):
            continue
        rel = rel_path.as_posix()
        actual_files[rel] = path
        if rel not in by_path:
            extra_files.append(rel)

    missing_files: list[str] = []
    modified_files: list[str] = []
    for rel, entry in by_path.items():
        path = APP_ROOT / rel
        if not path.is_file():
            missing_files.append(rel)
            continue
        try:
            size = path.stat().st_size
            digest = _sha256_file(path)
        except OSError:
            modified_files.append(rel)
            continue
        if entry.get("size") != size or entry.get("sha256") != digest:
            modified_files.append(rel)

    if extra_files:
        issues.append(f"{len(extra_files)} unmanifested file(s)")
    if missing_files:
        issues.append(f"{len(missing_files)} missing manifest file(s)")
    if modified_files:
        issues.append(f"{len(modified_files)} modified manifest file(s)")

    status = "clean" if not issues else "dirty"
    return {
        "status": status,
        "issues": issues,
        "extra_files": sorted(extra_files)[:25],
        "missing_files": sorted(missing_files)[:25],
        "modified_files": sorted(modified_files)[:25],
    }


def distribution_snapshot() -> dict[str, Any]:
    manifest = release_manifest()
    has_git = (APP_ROOT / ".git").exists()
    if manifest:
        file_count = len(manifest.get("files", [])) if isinstance(manifest.get("files"), list) else None
        manifest_status = _tree_manifest_status(manifest)
        kind = "release" if manifest_status.get("status") == "clean" else "release-dirty"
        return {
            "kind": kind,
            "app_root": str(APP_ROOT),
            "release_manifest_present": True,
            "project_version": manifest.get("project_version"),
            "created_at": manifest.get("created_at"),
            "file_count": file_count,
            "content_sha256": manifest.get("content_sha256"),
            "source_tree_hint": bool(has_git or kind == "release-dirty"),
            "manifest_status": manifest_status,
        }
    return {
        "kind": "source",
        "app_root": str(APP_ROOT),
        "release_manifest_present": False,
        "project_version": None,
        "created_at": None,
        "file_count": None,
        "content_sha256": None,
        "source_tree_hint": bool(has_git or (APP_ROOT / "tests").is_dir()),
        "manifest_status": {"status": "not-present", "issues": [], "extra_files": [], "missing_files": [], "modified_files": []},
    }


def data_root_snapshot(data_root: str | None) -> dict[str, Any]:
    if not data_root:
        return {"configured": False, "path": None, "portable": False, "exists": False, "writable": False}
    root = Path(data_root).expanduser()
    portable_rel = _safe_relative(root, APP_ROOT)
    exists = root.exists()
    writable = False
    created = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        created = not exists
        probe = root / ".write-test.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        exists = True
        writable = True
    except OSError:
        writable = False
    known_files = []
    if root.exists() and root.is_dir():
        for name in ["settings.json", "setup.json", "item_db.json", "source_version.json", "source_version_history.json"]:
            known_files.append({"name": name, "present": (root / name).exists()})
        known_files.extend(
            [
                {"name": "backups/", "present": (root / "backups").is_dir()},
                {"name": "audit/events.jsonl", "present": (root / "audit" / "events.jsonl").exists()},
                {"name": "cache/item_update/", "present": (root / "cache" / "item_update").is_dir()},
            ]
        )
    return {
        "configured": True,
        "path": str(root),
        "portable": portable_rel is not None,
        "relative_to_app_root": portable_rel,
        "exists": exists,
        "created_during_check": created,
        "writable": writable,
        "known_entries": known_files,
    }


def release_manifest_hash(files: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for entry in sorted(files, key=lambda item: str(item.get("path", ""))):
        h.update(str(entry.get("path", "")).encode("utf-8"))
        h.update(b"\0")
        h.update(str(entry.get("sha256", "")).encode("ascii", errors="ignore"))
        h.update(b"\0")
        h.update(str(entry.get("size", "")).encode("ascii", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()


def build_manifest(*, project_version: str, files: list[dict[str, Any]], created_by: str = "scripts/make_release_zip.py") -> dict[str, Any]:
    return {
        "format": MANIFEST_FORMAT,
        "manifest_version": 1,
        "project_version": project_version,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "created_by": created_by,
        "content_sha256": release_manifest_hash(files),
        "files": sorted(files, key=lambda item: item["path"]),
        "notes": [
            "This file is generated at release-build time.",
            "The app treats a clean tree with this manifest as a release tree; a manifest with extra or changed files is reported as release-dirty.",
        ],
    }


def write_tree_manifest(root: Path, *, created_by: str = "python -m mcbe_editor.distribution") -> Path:
    """Create a manifest for an already staged runtime tree.

    Docker uses this after copying an explicit runtime allowlist. The manifest
    therefore describes the final image content instead of the developer's
    broader source checkout.
    """
    root = root.expanduser().resolve()
    project_data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = str(project_data["project"]["version"])
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == RELEASE_MANIFEST.name:
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = build_manifest(project_version=project_version, files=files, created_by=created_by)
    output = root / RELEASE_MANIFEST.name
    tmp = root / f".{RELEASE_MANIFEST.name}.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a release manifest for an explicitly staged runtime tree.")
    parser.add_argument("--write-manifest", metavar="PATH", required=True, help="Staged runtime directory to manifest.")
    args = parser.parse_args(argv)
    output = write_tree_manifest(Path(args.write_manifest))
    print(f"Created {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
