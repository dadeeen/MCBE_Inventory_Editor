from __future__ import annotations

import contextlib
import json
import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

WarningHandler = Callable[[str], None]


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif _path_exists(path):
        shutil.rmtree(path)


def _cache_is_complete(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return False
    if not isinstance(manifest, dict):
        return False
    items = manifest.get("items")
    if not isinstance(items, dict):
        return False
    for item_id, texture_path in items.items():
        if not isinstance(item_id, str) or not item_id.startswith("minecraft:") or not isinstance(texture_path, str) or not texture_path.strip():
            return False
        asset_name = item_id.removeprefix("minecraft:")
        if not asset_name or asset_name in {".", ".."} or "\0" in asset_name or "/" in asset_name or "\\" in asset_name:
            return False
        icon_path = path / "textures" / "items" / f"{asset_name}.png"
        try:
            icon_stat = icon_path.stat(follow_symlinks=False)
        except OSError:
            return False
        if not icon_path.is_file() or icon_path.is_symlink() or icon_stat.st_size <= 0:
            return False
    display_assets = manifest.get("display_assets", {})
    if not isinstance(display_assets, dict):
        return False
    for asset_id, texture_path in display_assets.items():
        if not isinstance(asset_id, str) or not asset_id.startswith("mcbe:") or not isinstance(texture_path, str) or not texture_path.strip():
            return False
        asset_name = asset_id.removeprefix("mcbe:")
        if not asset_name or asset_name in {".", ".."} or "\0" in asset_name or "/" in asset_name or "\\" in asset_name:
            return False
        icon_path = path / "textures" / "display" / f"{asset_name}.png"
        try:
            icon_stat = icon_path.stat(follow_symlinks=False)
        except OSError:
            return False
        if not icon_path.is_file() or icon_path.is_symlink() or icon_stat.st_size <= 0:
            return False
    return True


def _rollback_paths(target_root: Path) -> list[Path]:
    try:
        candidates = list(target_root.parent.glob(f".{target_root.name}.rollback-*"))
    except OSError:
        return []

    def modified(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return -1

    return sorted(candidates, key=modified, reverse=True)


@contextmanager
def _cache_lock(target_root: Path) -> Iterator[None]:
    """Serialize cache publication/recovery across processes."""

    target_root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target_root.parent / f".{target_root.name}.lock"
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _warn(handler: WarningHandler | None, message: str) -> None:
    if handler is not None:
        handler(message)


def _recover_icon_cache_unlocked(target_root: Path, *, warn: WarningHandler | None = None) -> None:
    rollbacks = _rollback_paths(target_root)
    if not rollbacks:
        return

    if _cache_is_complete(target_root):
        for rollback in rollbacks:
            try:
                _remove_path(rollback)
            except OSError as exc:
                _warn(warn, f"Veralteter Icon-Cache-Rollback konnte nicht entfernt werden: {rollback}: {exc}")
        return

    valid_rollback = next((path for path in rollbacks if _cache_is_complete(path)), None)
    if valid_rollback is None:
        return

    if _path_exists(target_root):
        _remove_path(target_root)
    os.replace(valid_rollback, target_root)
    for rollback in rollbacks:
        if rollback == valid_rollback:
            continue
        with contextlib.suppress(OSError):
            _remove_path(rollback)


def recover_icon_cache(target_root: Path, *, warn: WarningHandler | None = None) -> None:
    """Recover the last complete cache after an interrupted publication."""

    with _cache_lock(target_root):
        _recover_icon_cache_unlocked(target_root, warn=warn)


def publish_icon_cache(staging: Path, target_root: Path, *, warn: WarningHandler | None = None) -> None:
    """Publish a complete cache while preserving the previous cache on failure."""

    if staging.parent != target_root.parent:
        raise ValueError("Icon-Staging und Ziel müssen im selben Verzeichnis liegen.")
    if not _cache_is_complete(staging):
        raise ValueError("Der neue Icon-Cache ist unvollständig und wird nicht veröffentlicht.")

    with _cache_lock(target_root):
        _recover_icon_cache_unlocked(target_root, warn=warn)
        rollback = target_root.parent / f".{target_root.name}.rollback-{os.urandom(8).hex()}"
        moved_old = False
        if _path_exists(target_root):
            os.replace(target_root, rollback)
            moved_old = True

        published = False
        try:
            try:
                os.replace(staging, target_root)
                published = True
            except PermissionError:
                # Some Windows setups reject directory renames transiently.
                # Copy to the absent target, then let recovery distinguish a
                # complete publication from a partial crash artifact.
                shutil.copytree(staging, target_root)
                published = True
        except Exception as exc:
            with contextlib.suppress(OSError):
                if _path_exists(target_root):
                    _remove_path(target_root)
            if moved_old and _path_exists(rollback):
                try:
                    os.replace(rollback, target_root)
                except OSError as restore_exc:
                    raise RuntimeError(
                        f"Icon-Cache-Veröffentlichung fehlgeschlagen und der vorherige Cache konnte nicht wiederhergestellt werden: {restore_exc}"
                    ) from exc
            raise

        if published and _path_exists(staging):
            try:
                _remove_path(staging)
            except OSError as exc:
                _warn(warn, f"Icon-Staging konnte nach erfolgreicher Veröffentlichung nicht entfernt werden: {staging}: {exc}")

        if moved_old and _path_exists(rollback):
            try:
                _remove_path(rollback)
            except OSError as exc:
                _warn(warn, f"Alter Icon-Cache konnte nach erfolgreicher Veröffentlichung nicht entfernt werden: {rollback}: {exc}")
