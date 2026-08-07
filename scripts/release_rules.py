"""Shared denylist for local/private artifacts that must never ship."""

from __future__ import annotations

BLOCKED_RELEASE_DIR_NAMES = frozenset(
    {
        ".agents",
        ".claude",
        ".codex",
        ".git",
        ".idea",
        ".lockcheck",
        ".mypy_cache",
        ".pip-tools-cache",
        ".playwright-cli",
        ".pytest_cache",
        ".ruff_cache",
        ".tmp",
        ".venv",
        ".vscode",
        "__pycache__",
        "diagnostics",
        "dist",
        "htmlcov",
        "node_modules",
        "player_exports",
        "playwright-report",
        "private",
        "test-results",
        "vendor",
        "venv",
    }
)
BLOCKED_RELEASE_DIR_PREFIXES = (".pytest-",)

BLOCKED_RELEASE_SUFFIXES = frozenset({".bak", ".jsonl", ".log", ".orig", ".pyc", ".pyo", ".swp", ".tmp"})
BLOCKED_RELEASE_FILE_PREFIXES = (".coverage",)
BLOCKED_RELEASE_FILE_NAMES = frozenset(
    {
        ".DS_Store",
        "Desktop.ini",
        "Sample-World.zip",
        "Thumbs.db",
        "coverage.xml",
        "item_db.py",
        "player_raw_export_index.json",
        "settings.json",
        "setup.json",
        "source_version.json",
        "source_version_history.json",
    }
)


def is_generated_world_work_dir(part: str) -> bool:
    return part.endswith("_backups") or part.endswith("_restoring") or "_restoring_" in part or "_rollback_" in part


def is_blocked_release_dir_name(part: str) -> bool:
    normalized = part.casefold()
    return normalized in BLOCKED_RELEASE_DIR_NAMES or any(normalized.startswith(prefix) for prefix in BLOCKED_RELEASE_DIR_PREFIXES)
