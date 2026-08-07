from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import AppConfig


def _looks_like_world(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink() and (path / "db").is_dir() and not (path / "db").is_symlink()
    except OSError:
        return False


def _has_world_hint(root: Path, *, max_depth: int = 3, max_dirs: int = 200) -> bool:
    if _looks_like_world(root):
        return True
    checked = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and checked < max_dirs:
        current, depth = stack.pop()
        checked += 1
        try:
            if current.is_symlink() or not current.is_dir():
                continue
            if _looks_like_world(current):
                return True
            if depth >= max_depth:
                continue
            for child in current.iterdir():
                if child.name in {"db", "cache", "backups", "__pycache__"}:
                    continue
                stack.append((child, depth + 1))
        except OSError:
            continue
    return False


def worlds_root_status(config: AppConfig) -> dict[str, Any]:
    """Summarize whether the Docker worlds root appears usable.

    This is intentionally shallow and log-oriented.  The real world scanner still
    performs the authoritative, bounded scan when the UI asks for worlds.
    """

    root_value = config.worlds_root
    if not root_value:
        return {
            "mode": config.mode,
            "root": None,
            "status": "not-configured",
            "bind_mount_required": config.is_docker,
            "message": "Kein Welt-Root konfiguriert.",
        }

    root = Path(root_value)
    if not root.exists():
        return {
            "mode": config.mode,
            "root": str(root),
            "status": "missing",
            "bind_mount_required": config.is_docker,
            "message": f"Welt-Root existiert nicht: {root}",
        }
    if root.is_symlink():
        return {
            "mode": config.mode,
            "root": str(root),
            "status": "symlink",
            "bind_mount_required": config.is_docker,
            "message": f"Welt-Root ist ein Symlink und wird nicht empfohlen: {root}",
        }
    if not root.is_dir():
        return {
            "mode": config.mode,
            "root": str(root),
            "status": "not-directory",
            "bind_mount_required": config.is_docker,
            "message": f"Welt-Root ist kein Ordner: {root}",
        }

    try:
        entries = [p for p in root.iterdir() if not p.name.startswith(".")]
    except OSError as exc:
        return {
            "mode": config.mode,
            "root": str(root),
            "status": "unreadable",
            "bind_mount_required": config.is_docker,
            "message": f"Welt-Root kann nicht gelesen werden: {exc}",
        }

    if not entries:
        return {
            "mode": config.mode,
            "root": str(root),
            "status": "empty",
            "bind_mount_required": config.is_docker,
            "message": (f"Welt-Root {root} ist leer. Im Docker-Modus muss der Host-Weltenordner nach {root} gemountet werden."),
        }

    return {
        "mode": config.mode,
        "root": str(root),
        "status": "ok",
        "bind_mount_required": config.is_docker,
        "entry_count": len(entries),
        "contains_world_hint": _has_world_hint(root, max_depth=min(max(config.world_scan_depth, 0), 3)),
        "message": f"Welt-Root {root} ist lesbar.",
    }


def write_gate_setup_status(config: AppConfig) -> dict[str, Any]:
    if not config.require_server_offline:
        if config.is_local:
            return {
                "status": "disabled",
                "message": (
                    "Server-Offline-Schreibsperre ist im Lokalmodus deaktiviert. "
                    "Öffne Welten nur, wenn Minecraft oder ein Bedrock-Server diese Welt nicht parallel nutzt."
                ),
                "writes_blocked_without_server_host": False,
                "local_world_access_warning": True,
            }
        return {
            "status": "disabled",
            "message": "Server-Offline-Schreibsperre ist deaktiviert.",
            "writes_blocked_without_server_host": False,
            "local_world_access_warning": False,
        }
    if not config.server_host:
        return {
            "status": "server-host-missing",
            "message": (
                "MCBE_REQUIRE_SERVER_OFFLINE=true, aber MCBE_SERVER_HOST ist nicht gesetzt. "
                "Schreibaktionen werden blockiert, weil der Serverstatus unbekannt ist."
            ),
            "writes_blocked_without_server_host": True,
            "local_world_access_warning": False,
        }
    return {
        "status": "configured",
        "message": f"Server-Offline-Schreibsperre prüft {config.server_host}:{config.server_port}.",
        "writes_blocked_without_server_host": False,
        "local_world_access_warning": False,
    }
