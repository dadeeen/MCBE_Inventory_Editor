"""Process runners for data and icon update scripts."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_terminal_formatting(output: str) -> str:
    """Remove terminal-only ANSI control sequences from captured web output."""
    return _ANSI_ESCAPE_RE.sub("", str(output or "")).replace("\r\n", "\n").replace("\r", "\n")


def _path_parent(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser().parent


def _ensure_dirs(paths: set[Path | None]) -> None:
    for directory in paths:
        if directory:
            directory.mkdir(parents=True, exist_ok=True)


def run_update_db(
    app_root: Path,
    app_config: Any,
    *,
    dry_run: bool = False,
    force: bool = False,
    only: str | None = None,
    use_cache: bool = True,
) -> tuple[int, str]:
    """Run the item_db update script and return its output."""
    cmd = [sys.executable, "-m", "scripts.update_db"]
    if dry_run:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    if use_cache:
        cmd.append("--cache")
    if only:
        cmd.extend(["--only", only])

    env = os.environ.copy()
    persistent_paths = {
        "MCBE_ITEM_DB_PATH": app_config.item_db_path,
        "MCBE_UPDATE_CACHE_DIR": app_config.update_cache_dir,
        "MCBE_SOURCE_VERSION_PATH": app_config.source_version_path,
        "MCBE_SOURCE_VERSION_HISTORY_PATH": app_config.source_version_history_path,
    }
    for name, value in persistent_paths.items():
        if value:
            env[name] = value
    env["NO_COLOR"] = "1"

    _ensure_dirs(
        {
            _path_parent(app_config.item_db_path),
            Path(app_config.update_cache_dir).expanduser() if app_config.update_cache_dir else None,
            _path_parent(app_config.source_version_path),
            _path_parent(app_config.source_version_history_path),
        }
    )

    proc = subprocess.run(
        cmd,
        cwd=str(app_root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    return proc.returncode, strip_terminal_formatting(proc.stdout)


def run_update_icons(
    app_root: Path,
    app_config: Any,
    *,
    force: bool = False,
    use_cache: bool = True,
) -> tuple[int, str]:
    """Run the vanilla icon update script and return its output."""
    cmd = [sys.executable, "-m", "scripts.update_icons"]
    if force:
        cmd.append("--force")
    if use_cache:
        cmd.append("--cache")

    env = os.environ.copy()
    data_root = Path(app_config.data_root or "data").expanduser()
    icon_root = data_root / "icons" / "vanilla"
    persistent_paths = {
        "MCBE_DATA_ROOT": str(data_root),
        "MCBE_ICON_CACHE_ROOT": str(icon_root),
        "MCBE_ITEM_DB_PATH": app_config.item_db_path,
        "MCBE_UPDATE_CACHE_DIR": app_config.update_cache_dir,
    }
    for name, value in persistent_paths.items():
        if value:
            env[name] = str(value)
    env["NO_COLOR"] = "1"

    _ensure_dirs(
        {
            data_root,
            icon_root.parent,
            Path(app_config.update_cache_dir).expanduser() if app_config.update_cache_dir else None,
        }
    )

    proc = subprocess.run(
        cmd,
        cwd=str(app_root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        check=False,
    )
    return proc.returncode, strip_terminal_formatting(proc.stdout)


def looks_like_network_failure(output: str) -> bool:
    lowered = output.lower()
    return any(
        marker in lowered
        for marker in (
            "name or service not known",
            "temporary failure in name resolution",
            "network is unreachable",
            "connection timed out",
            "timed out",
            "connection refused",
            "urlopen error",
            "ssl:",
        )
    )
