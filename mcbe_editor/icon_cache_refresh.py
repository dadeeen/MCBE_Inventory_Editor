"""Extend an existing Vanilla cache from its local, matching source archive."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

from . import icon_cache_state
from .archive_errors import ZIP_READ_ERRORS
from .block_icon_renderer import decode_png
from .icon_cache import publish_icon_cache
from .path_safety import is_linklike, is_linklike_stat, is_unsafe_windows_name

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.RLock()
_FileStamp = tuple[int, int, int, int, int]
_RefreshSignature = tuple[str, tuple[tuple[str, _FileStamp | None], ...], str]
_ATTEMPTS: OrderedDict[tuple[str, str], _RefreshSignature] = OrderedDict()
_REFRESH_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError, RuntimeError, *ZIP_READ_ERRORS)
_MAX_MANIFEST_BYTES = icon_cache_state.MAX_MANIFEST_BYTES


def _file_stamp(path: Path) -> _FileStamp | None:
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or is_linklike_stat(info):
        raise ValueError("Linked or non-regular cache file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _display_path(root: Path, asset_id: str) -> Path:
    return root / "textures" / "display" / f"{asset_id.removeprefix('mcbe:')}.png"


def _reject_links(directory: str, names: list[str]) -> list[str]:
    if any(is_linklike(Path(directory) / name) for name in names):
        raise ValueError("Linked cache entries cannot be refreshed automatically")
    return []


def refresh_cached_display_assets(target_root: Path, cache_dir: Path, *, force: bool = False) -> bool:
    """Repair missing display assets without downloads or changing item icons.

    Unchanged source failures are attempted once per process. Archive and
    manifest contents, or an explicit rescan, trigger retries after a restore.
    """
    with _LOCK:
        try:
            return _refresh(target_root, cache_dir, force=force)
        except _REFRESH_ERRORS as exc:
            _LOGGER.warning("Lokaler Vanilla-Icon-Cache konnte nicht ergänzt werden: %s", exc)
            return False


def _refresh(target_root: Path, cache_dir: Path, *, force: bool) -> bool:
    target_root = Path(os.path.abspath(target_root))
    cache_dir = Path(os.path.abspath(cache_dir))
    manifest_path = target_root / "manifest.json"
    manifest_stamp = _file_stamp(manifest_path)
    if manifest_stamp is None:
        # An explicitly removed cache stays removed; do not install one here.
        return False
    for path in (target_root, target_root / "textures", target_root / "textures" / "display", cache_dir):
        if is_linklike(path):
            return False

    from scripts import update_icons as updater

    required = {*updater.AXOLOTL_DISPLAY_ASSETS, *(f"mcbe:banner_{code}" for code in updater.BANNER_TEXTURES)}
    files = {asset_id: _file_stamp(_display_path(target_root, asset_id)) for asset_id in sorted(required)}
    key = str(target_root), str(cache_dir)

    with manifest_path.open("rb") as stream:
        original = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(original) > _MAX_MANIFEST_BYTES:
        return False
    manifest = json.loads(original)
    if not isinstance(manifest, dict) or manifest.get("source") != "Mojang/bedrock-samples full release":
        return False
    if type(manifest.get("schema_version")) is not int or not 1 <= manifest["schema_version"] <= 6:
        return False
    if not isinstance(manifest.get("items"), dict) or not isinstance(manifest.get("display_assets", {}), dict):
        return False
    display_assets = manifest.get("display_assets", {}).copy()
    missing = {asset_id for asset_id, stamp in files.items() if asset_id not in display_assets or not stamp or stamp[2] <= 0}
    if not missing:
        return False
    release = manifest.get("release")
    if not isinstance(release, dict) or not updater._valid_release_metadata(release):
        return False
    archive_name = release["resource_pack_asset"]
    if not updater._MANAGED_ICON_RELEASE_ZIP_RE.fullmatch(archive_name) or is_unsafe_windows_name(archive_name):
        return False
    archive_path = cache_dir / archive_name
    archive_stamp = _file_stamp(archive_path)
    if not archive_stamp or archive_stamp[2] != int(release["resource_pack_asset_size"]):
        return False
    current = hashlib.sha256(original).hexdigest(), tuple(files.items()), icon_cache_state.file_digest(archive_path, limit=updater.MAX_RESOURCE_PACK_BYTES)
    if not force and _ATTEMPTS.get(key) == current:
        _ATTEMPTS.move_to_end(key)
        return False
    _ATTEMPTS[key] = current
    _ATTEMPTS.move_to_end(key)
    while len(_ATTEMPTS) > 16:
        _ATTEMPTS.popitem(last=False)
    archive_sha256 = updater.validate_icon_archive(archive_path, release, manifest=manifest)
    with zipfile.ZipFile(archive_path) as archive:
        textures = updater._texture_members(archive)
        item_textures = updater.parse_texture_data(updater._read_json_member(archive, "textures/item_texture.json"))
        aliases = updater.build_data_driven_texture_aliases(item_textures, list(updater.AXOLOTL_DISPLAY_ASSETS.values()))
        images = list(updater.display_asset_images(archive, textures, item_textures, aliases, only=missing))
    if not images or _file_stamp(archive_path) != archive_stamp:
        return False
    for _, _, png, _ in images:
        decode_png(png)

    # A private staging copy keeps old images available until publication and
    # lets the existing publisher roll back a failed rename/copy on Windows.
    with tempfile.TemporaryDirectory(prefix=f".{target_root.name}.staging-", dir=target_root.parent) as temp:
        staging = Path(temp)
        shutil.copytree(target_root, staging, dirs_exist_ok=True, symlinks=True, ignore=_reject_links)
        for asset_id, texture_path, png, _ in images:
            path = _display_path(staging, asset_id)
            if not (stamp := files[asset_id]) or stamp[2] <= 0:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png)
            display_assets[asset_id] = texture_path
        manifest.update(
            display_assets=display_assets,
            display_asset_targets=len(required),
            mapped_display_assets=len(display_assets),
            sha256=hashlib.sha256(json.dumps({"items": manifest["items"], "display_assets": display_assets}, sort_keys=True).encode("utf-8")).hexdigest(),
        )
        # Partial repair may restore an existing receipt, but cannot certify
        # unrelated images or change the build identity of an older install.
        receipt = manifest.get("verification")
        if isinstance(receipt, dict) and isinstance(receipt.get("inputs"), dict):
            before = icon_cache_state.assess_cache(target_root, receipt["inputs"])
            after = icon_cache_state.assess_cache(staging, receipt["inputs"], manifest=manifest)
            if before["state"] in {"current", "damaged"} and after["state"] != "current":
                _ATTEMPTS.pop(key, None)
                return False
        icon_cache_state.require_archive_unchanged(archive_path, archive_sha256, limit=updater.MAX_RESOURCE_PACK_BYTES)
        updater.atomic_write_text(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return publish_icon_cache(staging, target_root, expected_manifest=(original, manifest_stamp[:2]), warn=_LOGGER.warning)
