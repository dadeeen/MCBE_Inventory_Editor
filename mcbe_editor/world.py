import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path

from .config import load_config
from .i18n import t

LOCAL_PLAYER_KEY = b"~local_player"

DEFAULT_SCAN_PATHS_FILE = Path(__file__).resolve().parent.parent / "settings.json"
# Backwards-compatible alias used by older tests/extensions.
SCAN_PATHS_FILE = DEFAULT_SCAN_PATHS_FILE
DEFAULT_WORLD_SCAN_DEPTH = 2
MAX_WORLD_SCAN_DEPTH = 4
DEFAULT_WORLD_SCAN_MAX_DIRS = 2000
MAX_WORLD_SCAN_MAX_DIRS = 20000
_SCAN_PATHS_LOCK = threading.RLock()
_SOURCE_LABELS = {
    "docker-root": "Docker /worlds",
    "minecraft-default": "Minecraft Bedrock",
    "configured-root": "Konfigurierter Welt-Root",
    "user-root": "Eigener Suchort",
}
_SKIP_SCAN_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".cache_item_update",
    "cache",
    "backups",
    "db",
}


def get_scan_paths_file() -> Path:
    # Tests/extensions historically monkeypatch SCAN_PATHS_FILE directly. Honor
    # that override before using the portable config path.
    if SCAN_PATHS_FILE != DEFAULT_SCAN_PATHS_FILE:
        return Path(SCAN_PATHS_FILE).expanduser()
    config = load_config()
    if config.settings_path:
        return Path(config.settings_path).expanduser()
    return SCAN_PATHS_FILE


BEDROCK_PACKAGE_NAMES = (
    "Microsoft.MinecraftUWP_8wekyb3d8bbwe",
    "Microsoft.MinecraftWindowsBeta_8wekyb3d8bbwe",
)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in paths:
        normalized = _normalize_path(candidate)
        if normalized in seen:
            continue
        result.append(candidate)
        seen.add(normalized)
    return result


def _candidate_local_appdata_roots() -> list[Path]:
    candidates: list[Path] = []
    for raw in (os.environ.get("LOCALAPPDATA"),):
        if raw:
            candidates.append(Path(raw))
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / "AppData" / "Local")
    with contextlib.suppress(RuntimeError, OSError):
        candidates.append(Path.home() / "AppData" / "Local")

    return _dedupe_paths(candidates)


def _candidate_roaming_appdata_roots() -> list[Path]:
    candidates: list[Path] = []
    for raw in (os.environ.get("APPDATA"),):
        if raw:
            candidates.append(Path(raw))
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / "AppData" / "Roaming")
    with contextlib.suppress(RuntimeError, OSError):
        candidates.append(Path.home() / "AppData" / "Roaming")

    return _dedupe_paths(candidates)


def _candidate_roaming_bedrock_saves(*, existing_only: bool) -> list[Path]:
    """Return post-GDK Windows Bedrock per-user minecraftWorlds roots.

    Newer Minecraft for Windows builds store worlds below
    AppData/Roaming/Minecraft Bedrock/Users/<account id>/games/com.mojang.
    The account-id directory is not stable or knowable in advance, so concrete
    candidates are derived by enumerating existing Users/* directories.
    """

    candidates: list[Path] = []
    for roaming_root in _candidate_roaming_appdata_roots():
        users_root = roaming_root / "Minecraft Bedrock" / "Users"
        if not users_root.is_dir():
            continue
        try:
            user_dirs = sorted(
                (child for child in users_root.iterdir() if child.is_dir() and not child.is_symlink()),
                key=lambda item: item.name.lower(),
            )
        except OSError:
            continue
        for user_dir in user_dirs:
            saves = user_dir / "games" / "com.mojang" / "minecraftWorlds"
            if user_dir.name.lower() == "shared" and not saves.is_dir():
                continue
            if existing_only and not saves.is_dir():
                continue
            candidates.append(saves)
    return candidates


def get_minecraft_saves_candidates(*, existing_only: bool = True) -> list[Path]:
    """Return likely Windows Bedrock save roots in priority order.

    Current Minecraft for Windows builds can keep worlds below the GDK-style
    AppData/Roaming/Minecraft Bedrock/Users/<account id>/... tree.  Older
    Microsoft Store/UWP installs used AppData/Local/Packages/.../LocalState.
    We scan both layouts and keep all concrete existing roots so multiple
    Minecraft users or old/new installs can be offered in the UI.
    """

    candidates: list[Path] = []
    candidates.extend(_candidate_roaming_bedrock_saves(existing_only=existing_only))

    for local_root in _candidate_local_appdata_roots():
        packages = local_root / "Packages"
        for package in BEDROCK_PACKAGE_NAMES:
            candidates.append(packages / package / "LocalState" / "games" / "com.mojang" / "minecraftWorlds")

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_path(candidate)
        if normalized in seen:
            continue
        if existing_only and not candidate.is_dir():
            continue
        result.append(candidate)
        seen.add(normalized)
    return result


def get_minecraft_saves_dir():
    candidates = get_minecraft_saves_candidates(existing_only=True)
    return candidates[0] if candidates else None


def _normalize_path(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def _is_path_within_root(path: str | os.PathLike, root: str | os.PathLike) -> bool:
    try:
        real_path = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))
        real_root = os.path.realpath(os.path.abspath(os.path.normpath(str(root))))
        return os.path.commonpath([real_root, real_path]) == real_root
    except (OSError, ValueError):
        return False


def _empty_settings() -> dict:
    return {"scan_roots": []}


def _coerce_scan_root(entry) -> dict | None:
    if isinstance(entry, str):
        path = entry.strip()
        if not path:
            return None
        return {"path": path, "enabled": True, "label": ""}
    if not isinstance(entry, dict):
        return None
    path = str(entry.get("path") or "").strip()
    if not path:
        return None
    return {
        "path": path,
        "enabled": bool(entry.get("enabled", True)),
        "label": str(entry.get("label") or "").strip(),
    }


def _load_settings():
    try:
        with open(get_scan_paths_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError, RecursionError):
        return _empty_settings()
    if not isinstance(data, dict):
        return _empty_settings()

    scan_roots: list[dict] = []
    seen: set[str] = set()

    # v30 format: explicit roots with enabled/label metadata.
    for entry in data.get("scan_roots", []) if isinstance(data.get("scan_roots"), list) else []:
        root = _coerce_scan_root(entry)
        if not root:
            continue
        normalized = _normalize_path(root["path"])
        if normalized in seen:
            continue
        scan_roots.append(root)
        seen.add(normalized)

    # Legacy v28/v29 format: extra_scan_paths list[str]. Keep reading it, but
    # future writes use scan_roots only to keep the persisted file transparent.
    for entry in data.get("extra_scan_paths", []) if isinstance(data.get("extra_scan_paths"), list) else []:
        root = _coerce_scan_root(entry)
        if not root:
            continue
        normalized = _normalize_path(root["path"])
        if normalized in seen:
            continue
        scan_roots.append(root)
        seen.add(normalized)

    return {"scan_roots": scan_roots}


def _save_settings(data):
    with _SCAN_PATHS_LOCK:
        scan_roots = []
        seen: set[str] = set()
        for entry in data.get("scan_roots", []) if isinstance(data, dict) else []:
            root = _coerce_scan_root(entry)
            if not root:
                continue
            normalized = _normalize_path(root["path"])
            if normalized in seen:
                continue
            scan_roots.append(root)
            seen.add(normalized)

        scan_paths_file = get_scan_paths_file()
        scan_paths_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{scan_paths_file.name}.", suffix=".tmp", dir=scan_paths_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"scan_roots": scan_roots}, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_name, scan_paths_file)
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(tmp_name)
            raise


def _scan_root_entry(path: str | os.PathLike, *, kind: str, enabled: bool = True, removable: bool = False, label: str = "") -> dict:
    return {
        "path": str(path),
        "label": label,
        "kind": kind,
        "enabled": bool(enabled),
        "removable": bool(removable),
    }


def get_configured_scan_roots(*, include_disabled: bool = True) -> list[dict]:
    """Return configured world scan roots with metadata for UI/API display."""

    config = load_config()
    roots: list[dict] = []
    seen: set[str] = set()

    def add_root(entry: dict) -> None:
        path = entry.get("path")
        if not path:
            return
        if config.is_docker and config.worlds_root and not _is_path_within_root(path, config.worlds_root):
            return
        normalized = _normalize_path(path)
        if normalized in seen:
            return
        if not include_disabled and not entry.get("enabled", True):
            return

        # Built-in roots should stay quiet unless they exist. User-configured
        # roots are different: keep stale/missing entries visible in the UI so
        # people can see, disable, or remove broken Docker mounts/NAS paths.
        keep_for_diagnostics = include_disabled and bool(entry.get("removable"))
        if os.path.isdir(path) or keep_for_diagnostics:
            roots.append(entry)
            seen.add(normalized)

    if config.worlds_root and os.path.isdir(config.worlds_root):
        add_root(
            _scan_root_entry(
                config.worlds_root,
                kind="docker-root" if config.is_docker else "configured-root",
                enabled=True,
                removable=False,
                label="Docker-Weltenordner" if config.is_docker else "Konfigurierter Welt-Root",
            )
        )

    default_roots = get_minecraft_saves_candidates(existing_only=True)
    legacy_default = get_minecraft_saves_dir()
    if legacy_default:
        default_roots.insert(0, legacy_default)
    for default in _dedupe_paths(default_roots):
        add_root(_scan_root_entry(default, kind="minecraft-default", enabled=True, removable=False, label="Minecraft-Standardordner"))

    settings = _load_settings()
    for root in settings.get("scan_roots", []):
        entry = _scan_root_entry(
            root["path"],
            kind="user-root",
            enabled=bool(root.get("enabled", True)),
            removable=True,
            label=str(root.get("label") or ""),
        )
        add_root(entry)

    return roots


def get_configured_paths():
    return [root["path"] for root in get_configured_scan_roots(include_disabled=False)]


def _is_world_dir(path: Path) -> bool:
    """Return True for real Bedrock world folders, without following symlinks."""

    try:
        return path.is_dir() and not path.is_symlink() and (path / "db").is_dir() and not (path / "db").is_symlink()
    except OSError:
        return False


def _new_scan_stats(max_dirs: int | None = None) -> dict:
    if max_dirs is None:
        max_dirs = _world_scan_max_dirs()
    return {
        "checked_dirs": 0,
        "max_dirs": max(1, min(int(max_dirs), MAX_WORLD_SCAN_MAX_DIRS)),
        "truncated": False,
        "skipped_symlinks": 0,
        "inaccessible_dirs": 0,
        "warnings": [],
    }


def _warn_once(stats: dict | None, message: str) -> None:
    if stats is None:
        return
    warnings = stats.setdefault("warnings", [])
    if message not in warnings:
        warnings.append(message)


def _merge_scan_stats(target: dict, source: dict) -> None:
    """Merge one root's bounded scan statistics into the global result."""

    for key in ("checked_dirs", "skipped_symlinks", "inaccessible_dirs"):
        target[key] = int(target.get(key, 0)) + int(source.get(key, 0))
    target["truncated"] = bool(target.get("truncated")) or bool(source.get("truncated"))
    for warning in source.get("warnings", []):
        _warn_once(target, warning)


def _has_world_below(path: Path, max_depth: int) -> bool:
    stats = _new_scan_stats()
    return bool(_scan_single_dir(path, max_depth=max_depth, stats=stats))


def _world_scan_depth() -> int:
    configured = getattr(load_config(), "world_scan_depth", DEFAULT_WORLD_SCAN_DEPTH)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = DEFAULT_WORLD_SCAN_DEPTH
    return max(0, min(value, MAX_WORLD_SCAN_DEPTH))


def _world_scan_max_dirs() -> int:
    configured = getattr(load_config(), "world_scan_max_dirs", DEFAULT_WORLD_SCAN_MAX_DIRS)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = DEFAULT_WORLD_SCAN_MAX_DIRS
    return max(100, min(value, MAX_WORLD_SCAN_MAX_DIRS))


def _validate_scan_path(abs_path: str) -> Path:
    candidate = Path(abs_path)
    config = load_config()
    if config.is_docker and config.worlds_root and not _is_path_within_root(abs_path, config.worlds_root):
        raise ValueError(f"Im Docker/LAN-Modus sind nur Suchpfade unter {config.worlds_root} erlaubt.")
    if candidate.is_symlink():
        raise ValueError("Symlink-Suchpfade werden aus Sicherheitsgründen nicht unterstützt.")
    if not candidate.is_dir():
        raise ValueError(f"Pfad existiert nicht: {abs_path}")
    if not _is_world_dir(candidate) and not _has_world_below(candidate, _world_scan_depth()):
        raise ValueError(
            f"Unter {abs_path} wurde keine Minecraft-Bedrock-Welt gefunden. "
            "Erwartet wird entweder ein direkter Weltordner mit 'db' oder ein Sammelordner mit Welten darunter."
        )
    return candidate


def add_scan_path(path, *, label: str = "", enabled: bool = True):
    abs_path = os.path.abspath(os.path.normpath(path))
    _validate_scan_path(abs_path)
    with _SCAN_PATHS_LOCK:
        settings = _load_settings()
        roots = settings.setdefault("scan_roots", [])
        normalized_existing = {_normalize_path(root["path"]) for root in roots if root.get("path")}
        if _normalize_path(abs_path) in normalized_existing:
            raise ValueError(f"Pfad ist bereits konfiguriert: {abs_path}")
        roots.append({"path": abs_path, "enabled": bool(enabled), "label": str(label or "")})
        _save_settings(settings)


def remove_scan_path(path):
    abs_path = os.path.abspath(os.path.normpath(path))
    normalized_target = _normalize_path(abs_path)
    with _SCAN_PATHS_LOCK:
        settings = _load_settings()
        roots = settings.get("scan_roots", [])
        for existing in list(roots):
            if _normalize_path(existing.get("path", "")) == normalized_target:
                roots.remove(existing)
                _save_settings({"scan_roots": roots})
                return
    raise ValueError(f"Pfad ist nicht konfiguriert: {abs_path}")


def set_scan_path_enabled(path, enabled: bool):
    abs_path = os.path.abspath(os.path.normpath(path))
    normalized_target = _normalize_path(abs_path)
    with _SCAN_PATHS_LOCK:
        settings = _load_settings()
        roots = settings.get("scan_roots", [])
        for existing in roots:
            if _normalize_path(existing.get("path", "")) == normalized_target:
                if enabled:
                    _validate_scan_path(abs_path)
                existing["enabled"] = bool(enabled)
                _save_settings({"scan_roots": roots})
                return
    raise ValueError(f"Pfad ist nicht konfiguriert: {abs_path}")


def _world_entry(world_path: Path, scan_root: Path, source: dict | None = None) -> dict:
    name = world_path.name
    levelname_path = world_path / "levelname.txt"
    if levelname_path.exists():
        with contextlib.suppress(OSError):
            detected_name = levelname_path.read_text(encoding="utf-8", errors="ignore").strip()
            if detected_name:
                name = detected_name

    try:
        folder = str(world_path.relative_to(scan_root))
    except ValueError:
        folder = world_path.name
    if folder == ".":
        folder = world_path.name

    source = source or {}
    source_kind = str(source.get("kind") or "scan-root")
    source_label = str(source.get("label") or _SOURCE_LABELS.get(source_kind, "Suchbereich"))

    modified_ts = None
    modified_iso = ""
    with contextlib.suppress(OSError):
        modified_ts = world_path.stat().st_mtime
        import datetime as _dt

        modified_iso = _dt.datetime.fromtimestamp(modified_ts).isoformat(timespec="seconds")

    return {
        "path": str(world_path),
        "name": name,
        "folder": folder,
        "source_root": str(scan_root),
        "source_kind": source_kind,
        "source_label": source_label,
        "modified_ts": modified_ts,
        "modified_iso": modified_iso,
    }


def _scan_single_dir(saves_dir, max_depth: int | None = None, stats: dict | None = None, source: dict | None = None):
    worlds = []
    root = Path(saves_dir)

    # The scanner only walks downwards inside each configured root. It never
    # inspects parent directories. Symlinks are skipped so a mounted root cannot
    # silently escape into another host path.
    try:
        if root.is_symlink():
            _warn_once(stats, t("Suchpfad {path} ist ein Symlink und wurde übersprungen.", path=root))
            return worlds
        if not root.is_dir():
            return worlds
    except OSError:
        _warn_once(stats, f"Suchpfad {root} konnte nicht gelesen werden.")
        return worlds

    if max_depth is None:
        max_depth = _world_scan_depth()
    max_depth = max(0, min(int(max_depth), MAX_WORLD_SCAN_DEPTH))
    if stats is None:
        stats = _new_scan_stats()

    stack = [(root, 0)]
    while stack:
        if stats["checked_dirs"] >= stats["max_dirs"]:
            stats["truncated"] = True
            _warn_once(
                stats,
                t(
                    "Weltsuche nach {count} geprüften Ordnern abgebrochen. "
                    "Bitte einen engeren Weltordner mounten oder MCBE_WORLD_SCAN_MAX_DIRS bewusst erhöhen.",
                    count=stats["max_dirs"],
                ),
            )
            break

        current, depth = stack.pop()
        stats["checked_dirs"] += 1

        if _is_world_dir(current):
            worlds.append(_world_entry(current, root, source=source))
            # Once a Bedrock world is found, do not scan its internals. The
            # LevelDB folder can contain many files and is never a place for
            # nested worlds.
            continue
        if depth >= max_depth:
            continue

        try:
            entries = list(current.iterdir())
        except OSError:
            stats["inaccessible_dirs"] += 1
            continue

        children = []
        for child in entries:
            try:
                if child.is_symlink():
                    stats["skipped_symlinks"] += 1
                    continue
                if not child.is_dir():
                    continue
            except OSError:
                stats["inaccessible_dirs"] += 1
                continue
            if child.name in _SKIP_SCAN_DIR_NAMES:
                continue
            if child.name.startswith(".") and ("_restoring_" in child.name or "_rollback_" in child.name):
                continue
            children.append(child)

        for child in reversed(sorted(children, key=lambda item: item.name.lower())):
            if stats["checked_dirs"] + len(stack) >= stats["max_dirs"]:
                stats["truncated"] = True
                _warn_once(
                    stats,
                    t(
                        "Weltsuche nach {count} geplanten/geprüften Ordnern begrenzt. "
                        "Bitte keinen breiten Hostpfad wie /, /home oder ein komplettes NAS nach /worlds mounten.",
                        count=stats["max_dirs"],
                    ),
                )
                break
            stack.append((child, depth + 1))

    if stats.get("skipped_symlinks"):
        _warn_once(stats, "Symlinks wurden bei der Weltsuche aus Sicherheitsgründen übersprungen.")
    if stats.get("inaccessible_dirs"):
        _warn_once(stats, "Einige Ordner konnten bei der Weltsuche nicht gelesen werden und wurden übersprungen.")
    return worlds


def _scan_root_diagnostic(root: dict) -> dict:
    path = root.get("path", "")
    status = "ok"
    message = "Suchbereich aktiv"
    try:
        candidate = Path(path)
        if not root.get("enabled", True):
            status = "disabled"
            message = "deaktiviert"
        elif not path:
            status = "missing"
            message = "kein Pfad"
        elif candidate.is_symlink():
            status = "skipped"
            message = "Symlink wird aus Sicherheitsgründen übersprungen"
        elif not candidate.exists():
            status = "missing"
            message = "nicht vorhanden"
        elif not candidate.is_dir():
            status = "invalid"
            message = "kein Ordner"
    except OSError as exc:
        status = "unreadable"
        message = f"nicht lesbar: {exc.__class__.__name__}"
    return {
        "path": str(path),
        "kind": root.get("kind", "scan-root"),
        "label": root.get("label") or _SOURCE_LABELS.get(root.get("kind"), "Suchbereich"),
        "enabled": bool(root.get("enabled", True)),
        "removable": bool(root.get("removable", False)),
        "status": status,
        "message": message,
        "world_count": 0,
    }


def scan_minecraft_worlds_with_meta(paths=None):
    if paths is None:
        roots = get_configured_scan_roots(include_disabled=True)
    else:
        roots = [_scan_root_entry(path, kind="manual-root", enabled=True, removable=False, label="Manueller Suchbereich") for path in paths]

    active_roots = [root for root in roots if root.get("enabled", True)]
    seen = set()
    result = []
    stats = _new_scan_stats()
    diagnostics = []
    diagnostic_by_norm: dict[str, dict] = {}

    for root in roots:
        diag = _scan_root_diagnostic(root)
        diagnostics.append(diag)
        if root.get("path"):
            diagnostic_by_norm[_normalize_path(root["path"])] = diag

    roots_with_paths = [root for root in active_roots if root.get("path")]
    for root_index, root in enumerate(roots_with_paths):
        root_path = root.get("path")
        remaining_roots = len(roots_with_paths) - root_index
        remaining_budget = max(0, stats["max_dirs"] - stats["checked_dirs"])
        diag = diagnostic_by_norm.get(_normalize_path(root_path))
        if remaining_budget == 0:
            stats["truncated"] = True
            if diag is not None and diag["status"] == "ok":
                diag["status"] = "limited"
                diag["message"] = "nicht geprüft, weil das globale Suchlimit erreicht wurde"
            continue

        # Give every remaining root a fair share of the still available global
        # budget. Unused directories from small/missing roots automatically flow
        # into the shares calculated for later roots.
        root_budget = max(1, remaining_budget // remaining_roots)
        root_stats = _new_scan_stats(max_dirs=root_budget)
        worlds_for_root = 0
        for w in _scan_single_dir(root_path, stats=root_stats, source=root):
            norm = _normalize_path(w["path"])
            if norm in seen:
                continue
            seen.add(norm)
            result.append(w)
            worlds_for_root += 1
        _merge_scan_stats(stats, root_stats)
        if diag is not None:
            diag["world_count"] = worlds_for_root
            if diag["status"] == "ok" and root_stats["truncated"]:
                diag["status"] = "limited"
                diag["message"] = f"nur teilweise geprüft (Limit: {root_budget} Ordner)"
            elif diag["status"] == "ok" and worlds_for_root == 0:
                diag["message"] = "geprüft, keine Welten gefunden"

    result.sort(key=lambda w: (-(w.get("modified_ts") or 0), str(w.get("name") or "").lower()))
    return {
        "worlds": result,
        "warnings": stats.get("warnings", []),
        "checked_dirs": stats.get("checked_dirs", 0),
        "truncated": bool(stats.get("truncated")),
        "scan_roots": diagnostics,
    }


def scan_minecraft_worlds(paths=None):
    # Backwards-compatible behavior for tests/extensions that monkeypatch
    # get_configured_paths(). The richer metadata endpoint uses
    # get_configured_scan_roots() when paths are omitted.
    if paths is None:
        paths = get_configured_paths()
    return scan_minecraft_worlds_with_meta(paths=paths)["worlds"]


def ensure_valid_world_path(world_path: str) -> str:
    if not world_path:
        raise ValueError("Kein Pfad angegeben.")
    world_path = os.path.abspath(os.path.normpath(world_path))

    config = load_config()
    if config.is_docker and config.worlds_root:
        worlds_root = os.path.abspath(os.path.normpath(config.worlds_root))
        if not _is_path_within_root(world_path, worlds_root):
            raise ValueError(f"Im Docker/LAN-Modus sind nur Welten unter {worlds_root} erlaubt.")

    candidate = Path(world_path)
    if candidate.is_symlink():
        raise ValueError("Symlink-Weltpfade werden aus Sicherheitsgründen nicht unterstützt.")
    if not os.path.isdir(world_path):
        raise ValueError("Welt-Ordner existiert nicht.")
    db_path = os.path.join(world_path, "db")
    if os.path.islink(db_path):
        raise ValueError("Der 'db'-Ordner darf kein Symlink sein.")
    if not os.path.isdir(db_path):
        candidate_worlds = []
        if candidate.is_dir():
            with contextlib.suppress(Exception):
                candidate_worlds = _scan_single_dir(candidate, max_depth=1, stats=_new_scan_stats(max_dirs=250))
        if candidate_worlds:
            examples = ", ".join(w.get("name") or w.get("folder") or "Welt" for w in candidate_worlds[:3])
            raise ValueError(
                t(
                    "Der angegebene Pfad ist ein Such-/Sammelordner, aber kein direkter Weltordner. "
                    "Wähle eine gefundene Welt darunter aus ({examples}) oder öffne den Ordner, der direkt den 'db'-Ordner enthält.",
                    examples=examples,
                )
            )
        raise ValueError(
            t(
                "Kein 'db'-Ordner unter {path} gefunden. "
                "Bitte den direkten Minecraft-Bedrock-Weltordner wählen, nicht den übergeordneten Speicher-/Saves-Ordner.",
                path=world_path,
            )
        )
    return db_path


def get_world_name(world_path: str) -> str:
    levelname_path = os.path.join(world_path, "levelname.txt")
    if os.path.exists(levelname_path):
        try:
            with open(levelname_path, encoding="utf-8", errors="ignore") as file:
                name = file.read().strip()
                if name:
                    return name
        except OSError:
            pass
    return os.path.basename(os.path.normpath(world_path))


def detect_capabilities(world_path: str) -> dict:
    """Return conservative feature flags for the current world folder.

    This is deliberately small for now; it gives the UI/API a stable place for
    future Minecraft-version and player-key detection.
    """

    ensure_valid_world_path(world_path)
    return {
        "supports_local_player": True,
        "supports_multiple_players": False,
        "world_format": "bedrock-leveldb",
        "write_mode": "local_player_only",
    }
