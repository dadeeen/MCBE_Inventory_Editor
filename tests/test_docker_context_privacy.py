"""Synthetic COPY-tree checks; these do not claim to run a Docker engine."""

from fnmatch import fnmatchcase
import json
from pathlib import Path, PurePosixPath

import pytest

from mcbe_editor import distribution
from scripts.release_rules import BLOCKED_RELEASE_DIR_NAMES, BLOCKED_RELEASE_FILE_NAMES, BLOCKED_RELEASE_SUFFIXES

ROOT = Path(__file__).resolve().parents[1]


def ignored_fixture_path(relative: str) -> bool:
    """Evaluate the slash globs used by these nested fixture paths.

    All exclusion patterns exercised here start with **/ and use filename
    wildcards or character classes; an excluded ancestor excludes its children.
    This deliberately is not a general Dockerignore parser.
    """
    path = PurePosixPath(relative)
    candidates = [relative, *(parent.as_posix() for parent in path.parents if parent.as_posix() != ".")]
    ignored = False
    for raw in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
        pattern = raw.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negate = pattern.startswith("!")
        pattern = pattern.removeprefix("!").rstrip("/")
        if any(fnmatchcase(candidate, pattern) for candidate in candidates):
            ignored = not negate
    return ignored


def mixed_case(text: str) -> str:
    return "".join(character.upper() if index % 2 else character.lower() for index, character in enumerate(text))


def shared_private_policy_paths() -> list[str]:
    names = [f"static/{name}/nested/PRIVATE_MARKER.bin" for name in sorted(BLOCKED_RELEASE_DIR_NAMES)]
    names += [f"mcbe_editor/{name}" for name in sorted(BLOCKED_RELEASE_FILE_NAMES)]
    names += [f"templates/private-marker{suffix}" for suffix in sorted(BLOCKED_RELEASE_SUFFIXES)]
    names += [
        "static/.pytest-local/nested/PRIVATE_MARKER.bin",
        "static/.coverage.local",
        "static/private/world/db/player.bin",
        "static/export.mcworld",
        "static/export.mcpack",
        "static/export.mcaddon",
        "mcbe_editor/backup.zip",
    ]
    variants = set()
    for name in names:
        root, tail = name.split("/", 1)
        variants.update(root + "/" + variant for variant in (tail, tail.upper(), mixed_case(tail)))
    return sorted(variants)


@pytest.mark.parametrize(
    "relative",
    [
        "mcbe_editor/.ENV.local",
        "static/.Env",
        "templates/SETTINGS.JSON",
        "mcbe_editor/BACKUP_SETTINGS.JSON",
        "templates/SETUP.JSON",
        "static/SOURCE_VERSION.JSON",
        "static/SOURCE_VERSION_HISTORY.JSON",
        "mcbe_editor/service.LOG",
        "mcbe_editor/service.Log.1",
        "templates/audit.JSONL",
        "templates/audit.JsOnL.2026",
        "static/DATA/session.json",
        "mcbe_editor/world_BACKUPS/db/player.bin",
        "static/world_RESTORING/db/player.bin",
        "static/world_RESTORING_2026/db/player.bin",
        "templates/world_ROLLBACK_2026/db/player.bin",
        "templates/PLAYER_EXPORTS/player.bin",
        "mcbe_editor/PLAYER_RAW_EXPORT_INDEX.JSON",
        "static/PRIVATE/world/db/player.bin",
        "static/export.MCWORLD",
        "static/export.MCPACK",
        "static/export.MCADDON",
        "mcbe_editor/backup.ZIP",
    ],
)
def test_docker_copied_trees_exclude_private_state_before_manifesting(tmp_path, monkeypatch, relative):
    # Simulate only Dockerfile's three recursive COPY inputs with synthetic bytes.
    # The real manifest writer accepts every copied file, so a clean manifest
    # cannot substitute for excluding private source files from the context.
    files = {
        "pyproject.toml": b"[project]\nversion='1.2.3'\n",
        "main.py": b"# runtime\n",
        "mcbe_editor/resources/item_db.json": b"{}\n",
        "static/app.js": b"// runtime\n",
        "templates/index.html": b"<main>runtime</main>\n",
        relative: b"SYNTHETIC_PRIVATE_MARKER",
    }
    for name, data in files.items():
        if ignored_fixture_path(name):
            continue
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest_path = distribution.write_tree_manifest(tmp_path)
    monkeypatch.setattr(distribution, "APP_ROOT", tmp_path)
    monkeypatch.setattr(distribution, "RELEASE_MANIFEST", manifest_path)
    assert distribution.distribution_snapshot()["kind"] == "release"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    shipped = {entry["path"] for entry in manifest["files"]}
    assert shipped == set(files) - {relative}, f"Private context member reached the clean image manifest: {relative}"


@pytest.mark.parametrize(
    "relative",
    [
        "mcbe_editor/resources/item_db.json",
        "static/app.js",
        "templates/index.html",
        "requirements/runtime.lock",
        "requirements/bootstrap.lock",
        "requirements/docker.lock",
        "templates/.env.example",
    ],
)
def test_docker_context_retains_runtime_inputs_and_explicit_env_example(relative):
    assert not ignored_fixture_path(relative)


@pytest.mark.parametrize("relative", shared_private_policy_paths())
def test_docker_context_covers_shared_release_private_names_in_every_case(relative):
    assert ignored_fixture_path(relative), f"Private artifact is still included in the Docker context: {relative}"


def test_docker_context_retains_every_actual_runtime_copy_input():
    from scripts.make_release_zip import should_include
    from scripts.runtime_layout import iter_runtime_files

    copied = {"mcbe_editor", "static", "templates"}
    actual = [path.relative_to(ROOT).as_posix() for path in iter_runtime_files(ROOT) if should_include(path)]
    actual = [relative for relative in actual if PurePosixPath(relative).parts[0] in copied]
    assert actual, "The positive control must inspect actual runtime files"
    for relative in actual:
        assert not ignored_fixture_path(relative), f"Docker excludes a required runtime asset: {relative}"
    for relative in ("static/brand.PNG", "templates/.ENV.EXAMPLE", "static/custom/Texture.JSON", "mcbe_editor/native.SO"):
        assert not ignored_fixture_path(relative), f"Docker excludes a legitimate custom runtime asset: {relative}"
