"""Only synthetic directories; junction targets are never game data."""

import os
import stat
from contextlib import contextmanager
from pathlib import Path
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


WINDOWS_ONLY_UNSAFE_NAMES = [
    "db/entry:stream", "db/CON", "db/nul.txt", "db/COM1.log", "db/LPT9", "db/COM¹", "db/CONOUT$",
    "db/trailing.", "db/trailing ", "db/a<file", "db/a?file", "db/a\x01file",
]


@pytest.mark.parametrize(("name", "windows_rules"), [
    *((name, True) for name in WINDOWS_ONLY_UNSAFE_NAMES),
    ("db//CURRENT", False), ("db/./CURRENT", False), ("db/../CURRENT", False),
])
def test_restore_rejects_unsafe_members_before_extracting(tmp_path, monkeypatch, name, windows_rules):
    monkeypatch.setattr(backup, "_WINDOWS_PATH_RULES", windows_rules)
    archive = tmp_path / "source.zip"
    target = tmp_path / "staging"
    target.mkdir()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("db/CURRENT", b"safe")
        zf.writestr(name, b"unsafe")
    with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="Unsicherer Pfad"):
        backup.safe_extract_zip(zf, str(target))
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("name", WINDOWS_ONLY_UNSAFE_NAMES)
def test_windows_name_rules_do_not_apply_to_posix_worlds(monkeypatch, name):
    # Validation only: extracting these names on NTFS would create streams or devices.
    monkeypatch.setattr(backup, "_WINDOWS_PATH_RULES", False)
    assert backup._safe_zip_member_name(name) == name


@pytest.mark.skipif(os.name == "nt", reason="Windows cannot create these names")
def test_posix_world_with_windows_reserved_names_can_be_backed_up_and_restored(tmp_path, monkeypatch):
    world_path = tmp_path / "world"
    names = ["db/CURRENT", "resource_packs/Pack/textures/aux.png", "behavior_packs/My Pack: Remastered/manifest.json", "resource_packs/Pack v1./pack.json"]
    for name in names:
        (world_path / name).parent.mkdir(parents=True, exist_ok=True)
        (world_path / name).write_bytes(name.encode())
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))

    created = Path(backup.create_backup(str(world_path)))
    with zipfile.ZipFile(created) as zf:
        assert set(names) <= set(zf.namelist())
    (world_path / names[1]).write_bytes(b"changed")
    backup.restore_backup(str(world_path), created.name)
    assert {name: (world_path / name).read_bytes() for name in names} == {name: name.encode() for name in names}


def test_restore_journal_search_skips_entries_with_unreadable_type(tmp_path, monkeypatch):
    root = tmp_path / "worlds"
    unreadable = root / "a_unreadable"
    unreadable.mkdir(parents=True)
    journal = root / "server" / ".mcbe_restore_0123456789abcdef.json"
    journal.parent.mkdir()
    journal.write_text("{}", encoding="utf-8")
    real_is_linklike = backup.is_linklike

    def is_linklike(path):
        # POSIX lstat fails with EACCES below a readable but unsearchable directory.
        if Path(path) == unreadable:
            raise PermissionError("entry type unavailable")
        return real_is_linklike(path)

    monkeypatch.setattr(backup, "is_linklike", is_linklike)
    assert backup._restore_journals_below(str(root), max_depth=4, max_dirs=100) == [str(journal)]


def test_restore_accepts_portable_unicode_names(tmp_path):
    assert backup._safe_zip_member_name("behavior_packs/Überprüfung/file.json") == "behavior_packs/Überprüfung/file.json"
    assert backup._safe_zip_member_name("db/") == "db"


def test_restore_alias_collision_preserves_current_world(tmp_path, monkeypatch):
    world_path = tmp_path / "world"
    (world_path / "db").mkdir(parents=True)
    original = world_path / "db" / "CURRENT"
    original.write_bytes(b"current world")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    backups_dir = Path(backup.ensure_safe_backup_location(str(world_path)))
    backups_dir.mkdir(parents=True)
    archive = backups_dir / "aliased.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("db/LongFilename.txt", b"first member")
        zf.writestr("db/LONGFI~1.TXT", b"second member")
    real_open = open

    def aliased_open(path, *args, **kwargs):
        # Exercise the filesystem alias on hosts without native DOS short names.
        path = Path(path)
        if path.name == "LONGFI~1.TXT":
            path = path.with_name("LongFilename.txt")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(backup, "open", aliased_open, raising=False)
    with pytest.raises(ValueError, match="kollidierende Dateisystempfade"):
        backup.restore_backup(str(world_path), archive.name)
    assert original.read_bytes() == b"current world"
    assert set(world_path.rglob("*")) == {world_path / "db", original}
    assert not list(tmp_path.glob(".world_*"))
    assert not list(tmp_path.glob(".mcbe_restore_*.json"))


@pytest.mark.skipif(os.name != "nt", reason="Native DOS 8.3 aliases are Windows-specific")
@pytest.mark.parametrize("kind", ["file", "directory"])
def test_restore_rejects_native_short_name_aliases(tmp_path, kind):
    probe = tmp_path / "probe"
    probe.mkdir()
    if kind == "file":
        first, second = "LongFilename.txt", "LONGFI~1.TXT"
        (probe / first).write_bytes(b"probe")
        alias = probe / second
    else:
        first, second = "LongDirectoryName/first.txt", "LONGDI~1/second.txt"
        (probe / "LongDirectoryName").mkdir()
        alias = probe / "LONGDI~1"
    if not alias.exists():
        pytest.skip("This filesystem does not create DOS 8.3 aliases")
    target = tmp_path / "staging"
    target.mkdir()
    archive = tmp_path / "aliased.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"db/{first}", b"first member")
        zf.writestr(f"db/{second}", b"second member")

    with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="kollidierende Dateisystempfade"):
        backup.safe_extract_zip(zf, str(target))
    files = [path for path in target.rglob("*") if path.is_file()]
    assert files == [target / "db" / first]
    assert files[0].read_bytes() == b"first member"


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
