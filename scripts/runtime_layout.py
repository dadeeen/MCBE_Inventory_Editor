"""Explicit file layout for the auditable runtime source bundle."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePath

RUNTIME_ROOT_FILES = frozenset(
    {
        ".dockerignore",
        "Dockerfile",
        "LICENSE",
        "README.md",
        "README.de.md",
        "SECURITY.md",
        "SECURITY.de.md",
        "docker-compose.example.yml",
        "docker-compose.viewer.example.yml",
        "main.py",
        "pyproject.toml",
        "setup.bat",
        "start.bat",
    }
)

RUNTIME_TREE_DIRS = frozenset({"mcbe_editor", "static", "templates"})

RUNTIME_DOC_PATHS = frozenset(
    {
        "docs/assets/editor-inventory.png",
        "docs/assets/editor-overview.png",
    }
)

RUNTIME_REQUIREMENT_PATHS = frozenset(
    {
        "requirements/bootstrap.lock",
        "requirements/bootstrap.txt",
        "requirements/build.lock",
        "requirements/build.txt",
        "requirements/build-constraints.txt",
        "requirements/dev.lock",
        "requirements/dev.txt",
        "requirements/docker.lock",
        "requirements/docker.txt",
        "requirements/runtime.lock",
        "requirements/runtime.txt",
    }
)

RUNTIME_SCRIPT_PATHS = frozenset(
    {
        "scripts/__init__.py",
        "scripts/docker/build_image.bat",
        "scripts/docker/build_image.sh",
        "scripts/docker/export_image.bat",
        "scripts/doctor.py",
        "scripts/export_player_raws.py",
        "scripts/fixture_world.py",
        "scripts/hash_password.py",
        "scripts/horse_diagnostic.py",
        "scripts/horse_diagnostic_gui.cmd",
        "scripts/horse_diagnostic_gui.py",
        "scripts/security_check.py",
        "scripts/update_db.py",
        "scripts/update_icons.py",
    }
)

RUNTIME_EXACT_PATHS = frozenset(set(RUNTIME_ROOT_FILES) | set(RUNTIME_REQUIREMENT_PATHS) | set(RUNTIME_SCRIPT_PATHS) | set(RUNTIME_DOC_PATHS))

REQUIRED_RUNTIME_FILES = frozenset(
    set(RUNTIME_EXACT_PATHS)
    | {
        "mcbe_editor/__init__.py",
        "mcbe_editor/resources/enchantment_max_levels.json",
        "mcbe_editor/resources/item_availability.json",
        "mcbe_editor/resources/item_db.json",
        "static/app.js",
        "templates/index.html",
    }
)


def is_runtime_relative_path(path: PurePath) -> bool:
    """Return whether a relative file path belongs in the runtime bundle."""

    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False
    if len(parts) == 1:
        return parts[0] in RUNTIME_ROOT_FILES
    if parts[0] in RUNTIME_TREE_DIRS:
        return True
    relative = path.as_posix()
    return relative in RUNTIME_DOC_PATHS or relative in RUNTIME_REQUIREMENT_PATHS or relative in RUNTIME_SCRIPT_PATHS


def iter_runtime_files(root: Path) -> Iterator[Path]:
    """Yield only files that can belong to a runtime package.

    Enumerating the explicit top-level allowlist prevents local caches, private
    fixtures, virtual environments, and test artifacts from being traversed at
    all. Hygiene filtering still happens separately so unexpected files inside
    one of the runtime trees remain excluded.
    """

    root = root.expanduser().resolve()
    for relative in sorted(RUNTIME_EXACT_PATHS):
        candidate = root / Path(relative)
        if candidate.is_file() or candidate.is_symlink():
            yield candidate

    for directory in sorted(RUNTIME_TREE_DIRS):
        tree_root = root / directory
        if not tree_root.is_dir() or tree_root.is_symlink():
            continue
        for candidate in sorted(tree_root.rglob("*")):
            if candidate.is_file() or candidate.is_symlink():
                yield candidate
