"""Process runners for data and icon update scripts."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcbe_editor.i18n import SUPPORTED_LOCALES
from mcbe_editor.item_db_transaction import PARENT_LOCK_ENV, configured_targets, item_db_update_operation, recover_item_db
from mcbe_editor.update_db_report import extract_report
from mcbe_editor.update_output_i18n import UPDATE_LOCALE_ENV
from mcbe_editor.update_progress import PROGRESS_ENV, write_progress

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class ItemDbUpdateInterruptedError(RuntimeError):
    """A terminated worker with the independently recovered disk outcome."""

    def __init__(self, *, returncode: int, output: str, recovery: str, timed_out: bool = False):
        super().__init__("Item database worker terminated")
        self.returncode = returncode
        self.output = output
        self.recovery = recovery
        self.timed_out = timed_out


def _run_update(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    if getattr(sys, "frozen", False):
        from mcbe_editor.desktop_worker import run_frozen_update

        return run_frozen_update(cmd[2], cmd[3:], cwd=kwargs["cwd"], env=kwargs["env"], timeout=kwargs["timeout"])
    return subprocess.run(cmd, **kwargs)


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


def _normalized_locale(locale: str) -> str:
    normalized = str(locale or "").strip().lower()
    return normalized if normalized in SUPPORTED_LOCALES else "de"


def run_update_db(
    app_root: Path,
    app_config: Any,
    *,
    dry_run: bool = False,
    force: bool = False,
    only: str | None = None,
    use_cache: bool = False,
    expected_review_token: str | None = None,
    locale: str = "de",
    progress_path: Path | None = None,
) -> tuple[int, str]:
    """Run the item_db update script and return its output."""
    cmd = [sys.executable, "-m", "scripts.update_db", "--json-summary"]
    if dry_run:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    if use_cache:
        cmd.append("--cache")
    if expected_review_token:
        if not use_cache:
            raise ValueError("Ein Dry-Run-Prüfbeleg erfordert das interne Cache-Replay.")
        cmd.extend(["--expected-review-token", expected_review_token])
    if only:
        cmd.extend(["--only", only])

    env = os.environ.copy()
    persistent_paths = {
        "MCBE_DATA_ROOT": getattr(app_config, "data_root", None),
        "MCBE_ITEM_DB_PATH": app_config.item_db_path,
        "MCBE_UPDATE_CACHE_DIR": app_config.update_cache_dir,
        "MCBE_SOURCE_VERSION_PATH": app_config.source_version_path,
        "MCBE_SOURCE_VERSION_HISTORY_PATH": app_config.source_version_history_path,
    }
    for name, value in persistent_paths.items():
        if value:
            # Resolve before subprocess.run changes the working directory.
            env[name] = str(Path(value).expanduser().resolve())
    env["NO_COLOR"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env[UPDATE_LOCALE_ENV] = _normalized_locale(locale)
    env.pop(PROGRESS_ENV, None)
    if progress_path is not None:
        env[PROGRESS_ENV] = str(progress_path.resolve())

    _ensure_dirs(
        {
            _path_parent(app_config.item_db_path),
            Path(app_config.update_cache_dir).expanduser() if app_config.update_cache_dir else None,
            _path_parent(app_config.source_version_path),
            _path_parent(app_config.source_version_history_path),
        }
    )

    targets = configured_targets(app_config.item_db_path, app_config.source_version_path, app_config.source_version_history_path)
    env[PARENT_LOCK_ENV] = str(targets[0])
    with item_db_update_operation(targets):
        return _run_item_db_worker(cmd, app_root, env, targets, progress_path)


def _run_item_db_worker(cmd: list[str], app_root: Path, env: dict[str, str], targets: tuple[Path, ...], progress_path: Path | None) -> tuple[int, str]:
    recover_item_db(targets)
    try:
        proc = _run_update(
            cmd,
            cwd=str(app_root),
            env=env,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run kills and waits for the child before raising (also in
        # the frozen runner). Recovery cannot race a surviving worker.
        recovery = recover_item_db(targets)
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        raise ItemDbUpdateInterruptedError(returncode=-1, output=strip_terminal_formatting(output), recovery=recovery, timed_out=True) from exc
    except Exception as exc:
        recovery = recover_item_db(targets)
        if recovery != "none":
            raise ItemDbUpdateInterruptedError(returncode=-1, output="", recovery=recovery) from exc
        raise
    recovery = recover_item_db(targets)
    _, report = extract_report(strip_terminal_formatting(proc.stdout))
    # A completed update can intentionally return nonzero for blocked sections
    # while reporting its applied sections. Preserve that ordinary result.
    reported_commit = report is not None and report.get("applied") is True
    if recovery == "rolled_back" or (proc.returncode != 0 and recovery == "committed" and not reported_commit):
        raise ItemDbUpdateInterruptedError(returncode=proc.returncode or 1, output=strip_terminal_formatting(proc.stdout), recovery=recovery)
    if progress_path is not None:
        write_progress(progress_path, "finalizing")
    return proc.returncode, strip_terminal_formatting(proc.stdout)


def run_update_icons(
    app_root: Path,
    app_config: Any,
    *,
    force: bool = False,
    use_cache: bool = False,
    locale: str = "de",
    progress_path: Path | None = None,
) -> tuple[int, str]:
    """Run the vanilla icon update script and return its output."""
    cmd = [sys.executable, "-m", "scripts.update_icons"]
    if force:
        cmd.append("--force")
    if use_cache:
        cmd.append("--cache")

    env = os.environ.copy()
    data_root = Path(app_config.data_root or "data").expanduser().resolve()
    icon_root = data_root / "icons" / "vanilla"
    persistent_paths = {
        "MCBE_DATA_ROOT": str(data_root),
        "MCBE_ICON_CACHE_ROOT": str(icon_root),
        "MCBE_ITEM_DB_PATH": app_config.item_db_path,
        "MCBE_UPDATE_CACHE_DIR": app_config.update_cache_dir,
    }
    for name, value in persistent_paths.items():
        if value:
            env[name] = str(Path(value).expanduser().resolve())
    env["NO_COLOR"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env[UPDATE_LOCALE_ENV] = _normalized_locale(locale)
    env.pop(PROGRESS_ENV, None)
    if progress_path is not None:
        env[PROGRESS_ENV] = str(progress_path.resolve())

    cache_dir = Path(env.get("MCBE_UPDATE_CACHE_DIR") or data_root / "cache" / "item_update").expanduser().resolve()
    env["MCBE_UPDATE_CACHE_DIR"] = str(cache_dir)
    _ensure_dirs(
        {
            data_root,
            icon_root.parent,
            cache_dir,
        }
    )

    # The parent survives an updater timeout and removes this run's partial
    # download and rendered staging after the child has terminated. Keep each
    # directory beside its destination so publication remains an atomic rename.
    with (
        tempfile.TemporaryDirectory(prefix=".icon-download-", dir=cache_dir) as download_dir,
        tempfile.TemporaryDirectory(prefix=f".{icon_root.name}.staging-", dir=icon_root.parent) as staging_dir,
    ):
        env["MCBE_ICON_DOWNLOAD_TEMP_DIR"] = download_dir
        env["MCBE_ICON_STAGING_DIR"] = staging_dir
        proc = _run_update(
            cmd,
            cwd=str(app_root),
            env=env,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
            check=False,
        )
    if progress_path is not None:
        write_progress(progress_path, "finalizing")
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
