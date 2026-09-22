"""Only synthetic directories; junction targets are never game data."""

import os
import stat
from contextlib import contextmanager
from types import SimpleNamespace
import zipfile

import pytest

from mcbe_editor import backup, world
from mcbe_editor.backup_consistency import source_snapshot
from mcbe_editor.path_safety import is_linklike, is_linklike_stat


@contextmanager
def directory_link(target, link):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    try:
        assert is_linklike(link)
        yield link
    finally:
        # Remove the link itself, never recurse into its target.
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


def test_reparse_attribute_is_rejected_even_for_regular_file_mode():
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
    assert is_linklike_stat(info)


@pytest.mark.parametrize("boundary", ["world", "db"])
def test_world_and_scanner_reject_directory_links(tmp_path, monkeypatch, boundary):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    root = tmp_path / "scan"
    root.mkdir()
    target = tmp_path / "outside"
    (target / "db").mkdir(parents=True)
    if boundary == "world":
        world_path = root / "world"
        link, destination = world_path, target
    else:
        world_path = root / "world"
        world_path.mkdir()
        link, destination = world_path / "db", target / "db"
    with directory_link(destination, link), pytest.raises(ValueError, match="Symlink|Reparse"):
        assert world.scan_minecraft_worlds([str(root)]) == []
        world.ensure_valid_world_path(str(world_path))
    assert (target / "db").is_dir()


@pytest.mark.parametrize("kind", ["automatic", "manual", "pre_restore"])
def test_backup_aborts_on_link_instead_of_skipping_or_reading_target(tmp_path, monkeypatch, kind):
    root = tmp_path / "world"
    (root / "db").mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    secret = target / "private.txt"
    secret.write_bytes(b"synthetic outside data")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    with directory_link(target, root / "pack"):
        with pytest.raises(ValueError, match="Symlink|Reparse"):
            source_snapshot(str(root))
        with pytest.raises(ValueError, match="Symlink|Reparse"):
            backup.create_backup(str(root), backup_kind=kind)
    assert secret.read_bytes() == b"synthetic outside data"
    assert not list((tmp_path / "backups").rglob("*.zip"))


def test_backup_rejects_file_symlink(tmp_path, monkeypatch):
    root = tmp_path / "world"
    (root / "db").mkdir(parents=True)
    target = tmp_path / "outside.txt"
    target.write_bytes(b"outside")
    try:
        (root / "linked.txt").symlink_to(target)
    except OSError:
        pytest.skip("File symlink creation requires Windows developer mode or privileges")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    with pytest.raises(ValueError, match="Symlink|Reparse"):
        backup.create_backup(str(root))


@pytest.mark.parametrize("name", [
    "db/entry:stream", "db/CON", "db/nul.txt", "db/COM1.log", "db/LPT9", "db/COM¹", "db/CONOUT$",
    "db/trailing.", "db/trailing ", "db/a<file", "db/a?file", "db/a\x01file", "db//CURRENT", "db/./CURRENT",
])
def test_restore_rejects_nonportable_members_before_extracting(tmp_path, name):
    archive = tmp_path / "source.zip"
    target = tmp_path / "staging"
    target.mkdir()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("db/CURRENT", b"safe")
        zf.writestr(name, b"unsafe")
    with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="Unsicherer Pfad"):
        backup.safe_extract_zip(zf, str(target))
    assert list(target.iterdir()) == []


def test_restore_accepts_portable_unicode_names(tmp_path):
    assert backup._safe_zip_member_name("behavior_packs/Überprüfung/file.json") == "behavior_packs/Überprüfung/file.json"
    assert backup._safe_zip_member_name("db/") == "db"


def test_release_walker_does_not_include_junction_contents(tmp_path):
    from scripts.runtime_layout import iter_runtime_files
    from scripts.make_release_zip import should_include

    root = tmp_path / "release"
    (root / "static").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("synthetic private file", encoding="utf-8")
    with directory_link(outside, root / "static" / "assets"):
        assert list(iter_runtime_files(root)) == []
        assert not should_include(root / "static" / "assets" / "private.txt", root=root)


def test_icon_scanner_skips_junction_and_cached_read_rechecks_parent(tmp_path):
    from mcbe_editor import icons

    root = tmp_path / "pack"
    item_dir = root / "textures" / "items"
    item_dir.mkdir(parents=True)
    icon = item_dir / "apple.png"
    icon.write_bytes(b"original icon")
    candidates = {}
    icons._scan_directory(root, "test", candidates, {}, 0)
    candidate = icons.IconCandidate.from_cache_entry(candidates["minecraft:apple"].to_cache_entry())
    assert candidate.source_root == root
    assert candidate.read_bytes() == b"original icon"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "apple.png").write_bytes(b"external private data")
    icon.unlink()
    item_dir.rmdir()
    with directory_link(outside, item_dir):
        with pytest.raises(ValueError, match="Symlink|Reparse"):
            candidate.read_bytes()
        scanned = {}
        icons._scan_directory(root, "test", scanned, {}, 0)
        assert scanned == {}


def test_icon_read_rejects_file_replaced_during_open(tmp_path, monkeypatch):
    from mcbe_editor import icons

    root = tmp_path / "pack"
    source = root / "textures" / "items" / "apple.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original icon")
    outside = tmp_path / "external.png"
    outside.write_bytes(b"external private data")
    candidates = {}
    icons._scan_directory(root, "test", candidates, {}, 0)
    real_open = os.open

    def swap_before_open(path, flags, *args, **kwargs):
        return real_open(outside if path == source else path, flags, *args, **kwargs)

    monkeypatch.setattr(icons.os, "open", swap_before_open)
    with pytest.raises(ValueError, match="ersetzt"):
        candidates["minecraft:apple"].read_bytes()


def test_icon_file_symlink_is_never_registered(tmp_path):
    from mcbe_editor import icons

    root = tmp_path / "pack"
    icon = root / "textures" / "items" / "apple.png"
    icon.parent.mkdir(parents=True)
    outside = tmp_path / "external.png"
    outside.write_bytes(b"external private data")
    try:
        icon.symlink_to(outside)
    except OSError:
        pytest.skip("File symlink creation requires Windows developer mode or privileges")
    candidates = {}
    icons._scan_directory(root, "test", candidates, {}, 0)
    assert candidates == {}


def test_cached_icon_rejects_replaced_parent_above_source_root(tmp_path):
    from mcbe_editor import icons

    parent = tmp_path / "source-parent"
    root = parent / "pack"
    source = root / "textures" / "items" / "apple.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original icon")
    candidates = {}
    icons._scan_directory(root, "test", candidates, {}, 0)
    candidate = icons.IconCandidate.from_cache_entry(candidates["minecraft:apple"].to_cache_entry())
    outside = tmp_path / "outside"
    replacement = outside / "pack" / "textures" / "items" / "apple.png"
    replacement.parent.mkdir(parents=True)
    replacement.write_bytes(b"external private data")
    parent.rename(tmp_path / "original-parent")
    with directory_link(outside, parent), pytest.raises(ValueError, match="Symlink|Reparse"):
        candidate.read_bytes()
