"""Identify reusable icon builds independently of editor and catalog labels."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path

from .i18n import t
from .path_safety import is_linklike_stat, is_unsafe_windows_name

# Bump for changes to icon selection, extraction, rendering or display targets,
# not for editor releases, translations, logging or unrelated catalog data.
BUILD_CONTRACT = 2
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ICON_BYTES = 2 * 1024 * 1024
MAX_ICON_FILES = 20_000
REPORT_PREFIX = "MCBE_ICON_UPDATE_V1:"
RELEASE_FIELDS = ("resource_pack_release", "resource_pack_asset", "resource_pack_asset_size", "resource_pack_url")
ASSET_FIELDS = ("resource_pack_asset_id", "resource_pack_asset_updated_at", "resource_pack_asset_digest")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_inputs(release: dict, items: list[str], blocks: set[str] | None, extras: set[str]) -> dict:
    release = release if isinstance(release, dict) else {}
    targets = set(items) | extras
    return {
        "contract": BUILD_CONTRACT,
        "release": {key: release[key] for key in (*RELEASE_FIELDS, *ASSET_FIELDS) if key in release},
        "items": sorted(set(items)),
        "extra_items": sorted(extras),
        "blocks": None if blocks is None else sorted(blocks & targets),
    }


def same_release(first: dict, second: dict) -> bool:
    return (
        isinstance(first, dict)
        and bool(first)
        and isinstance(second, dict)
        and bool(second)
        and all(first.get(key) == second.get(key) for key in RELEASE_FIELDS)
        and all(first[key] == second[key] for key in ASSET_FIELDS if first.get(key) is not None and second.get(key) is not None)
    )


def _stamp(path: Path) -> tuple[int, int, int, int, int]:
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or is_linklike_stat(info):
        raise ValueError("Linked or non-regular icon input")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _file_digest(path: Path, stamp: tuple, limit: int) -> str:
    if not 0 < stamp[2] <= limit:
        raise ValueError("Icon input size outside bounds")
    checksum = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        # Windows stat() and fstat() expose different ctime semantics on some
        # Python versions. Compare identity, size and mtime across the two;
        # the final path stamp also checks for changes during the read.
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != stamp[:4]:
            raise ValueError("Icon input changed while opening")
        total = 0
        while chunk := stream.read(64 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError("Icon input size outside bounds")
            checksum.update(chunk)
    if total != stamp[2] or _stamp(path) != stamp:
        raise ValueError("Icon input changed while reading")
    return checksum.hexdigest()


def file_digest(path: Path, *, limit: int = MAX_ICON_BYTES) -> str:
    # A timestamp is not evidence of unchanged contents (notably after a
    # timestamp-preserving restore on Windows). Every integrity check reads bytes.
    return _file_digest(path, _stamp(path), limit)


def validate_archive(
    path: Path,
    release: dict,
    *,
    manifest: dict | None = None,
    limit: int,
    validate_zip: Callable[[Path], None],
) -> str:
    """Verify one source for downloads, full builds and partial repairs alike.

    Legacy installations can lack a historical digest. Their archive still has
    to pass size/ZIP checks and any upstream digest; partial repair cannot mint
    a verification receipt for the existing images.
    """
    stamp = _stamp(path)
    if stamp[2] != int(release["resource_pack_asset_size"]):
        raise ValueError(t("Das Resource-Pack hat nicht die erwartete Größe."))
    checksum = _file_digest(path, stamp, limit)
    upstream = release.get("resource_pack_asset_digest")
    if isinstance(upstream, str) and upstream.startswith("sha256:") and upstream != f"sha256:{checksum}":
        raise RuntimeError(t("Das Resource-Pack stimmt nicht mit der veröffentlichten Prüfsumme überein."))
    receipt = (manifest or {}).get("verification", {})
    if (
        isinstance(receipt, dict)
        and receipt.get("archive_sha256")
        and same_release((manifest or {}).get("release", {}), release)
        and checksum != receipt["archive_sha256"]
    ):
        raise ValueError(t("Das lokale Resource-Pack stimmt nicht mit der Prüfsumme des installierten Icon-Bestands überein."))
    validate_zip(path)
    require_archive_unchanged(path, checksum, limit=limit)
    return checksum


def require_archive_unchanged(path: Path, checksum: str, *, limit: int) -> None:
    if file_digest(path, limit=limit) != checksum:
        raise ValueError(t("Das Resource-Pack wurde während der Verarbeitung verändert. Bitte erneut prüfen."))


def _check_directories(root: Path) -> None:
    for directory in (root, root / "textures", root / "textures/items", root / "textures/display"):
        try:
            info = directory.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or is_linklike_stat(info):
            raise ValueError("Linked or invalid icon directory")


def read_manifest(root: Path, *, strict: bool = False) -> dict | None:
    try:
        _check_directories(root)
        path = root / "manifest.json"
        before = _stamp(path)
        if not 0 < before[2] <= MAX_MANIFEST_BYTES:
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != before[:4]:
                return None
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES or _stamp(path) != before:
            return None
        manifest = json.loads(raw)
        return manifest if isinstance(manifest, dict) else None
    except FileNotFoundError:
        return None
    except OSError:
        if strict:
            raise
        return None
    except (ValueError, RecursionError):
        return None


def image_files(manifest: dict) -> list[str]:
    files = []
    if not isinstance(manifest.get("items"), dict):
        raise ValueError("Missing icon mapping")
    for field, prefix, directory in (("items", "minecraft:", "items"), ("display_assets", "mcbe:", "display")):
        mapping = manifest.get(field, {})
        if not isinstance(mapping, dict) or len(mapping) > MAX_ICON_FILES:
            raise ValueError("Invalid icon mapping")
        for identifier, texture in mapping.items():
            if not isinstance(identifier, str) or not identifier.startswith(prefix) or not isinstance(texture, str) or not texture:
                raise ValueError("Invalid icon identifier")
            name = identifier.removeprefix(prefix)
            if not name or name in {".", ".."} or any(char in name for char in ("/", "\\", "\0")) or is_unsafe_windows_name(name):
                raise ValueError("Invalid icon filename")
            files.append(f"textures/{directory}/{name}.png")
    if len(files) > MAX_ICON_FILES:
        raise ValueError("Oversized icon mapping")
    return sorted(files)


def image_hashes(root: Path, manifest: dict) -> dict[str, str]:
    _check_directories(root)
    return {name: file_digest(root / name, limit=MAX_ICON_BYTES) for name in image_files(manifest)}


def image_signature(root: Path, manifest: dict | None = None) -> str | None:
    manifest = manifest if manifest is not None else read_manifest(root)
    if manifest is None:
        return None
    try:
        return digest({"items": manifest.get("items"), "display_assets": manifest.get("display_assets", {}), "files": image_hashes(root, manifest)})
    except (OSError, ValueError):
        return None


def _manifest_digest(manifest: dict) -> str:
    return digest({key: value for key, value in manifest.items() if key not in {"verification", "generated_at"}})


def add_verification(root: Path, manifest: dict, inputs: dict, archive_sha256: str) -> None:
    manifest["verification"] = {
        "schema": 1,
        "inputs": inputs,
        "inputs_sha256": digest(inputs),
        "archive_sha256": archive_sha256,
        "manifest_sha256": _manifest_digest(manifest),
        "files": image_hashes(root, manifest),
    }


def assess_cache(root: Path, inputs: dict, *, manifest: dict | None = None) -> dict:
    """Check local usability/build identity without networking or repairing files."""
    manifest = read_manifest(root, strict=True) if manifest is None else manifest
    if manifest is None:
        return {"state": "missing", "reason": "missing_or_invalid_manifest"}
    if manifest.get("source") != "Mojang/bedrock-samples full release":
        return {"state": "unverified", "reason": "unknown_source"}
    receipt = manifest.get("verification")
    if not isinstance(receipt, dict):
        return {"state": "unverified", "reason": "legacy"}
    if receipt.get("schema") != 1 or receipt.get("inputs_sha256") != digest(receipt.get("inputs")):
        return {"state": "unverified", "reason": "invalid_verification"}
    if receipt.get("manifest_sha256") != _manifest_digest(manifest) or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("archive_sha256", ""))):
        return {"state": "unverified", "reason": "invalid_verification"}
    if receipt.get("inputs_sha256") != digest(inputs):
        return {"state": "stale", "reason": "inputs_changed"}
    try:
        if receipt.get("files") != image_hashes(root, manifest):
            return {"state": "damaged", "reason": "files_changed"}
    except (FileNotFoundError, ValueError):
        return {"state": "damaged", "reason": "files_missing_or_unreadable"}
    return {"state": "current", "reason": "verified"}


def extract_report(output: str) -> tuple[str, dict | None]:
    visible = []
    report = None
    for line in output.splitlines(keepends=True):
        if line.startswith(REPORT_PREFIX):
            try:
                value = json.loads(line[len(REPORT_PREFIX) :])
                if isinstance(value, dict) and value.get("schema") == 1:
                    report = value
            except (ValueError, RecursionError):
                pass
        else:
            visible.append(line)
    return "".join(visible), report
