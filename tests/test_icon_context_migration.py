"""Version-10 publications survive upgrades without reading inactive packs."""

import errno
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from mcbe_editor import icon_api_routes as routes
from mcbe_editor import icons
from mcbe_editor.block_icon_renderer import encode_rgba_png
from tests.test_icon_cache_state import installed as installed, snapshot
from tests.test_icon_context_regressions import _world
from tests.test_icon_status_failures import status_installation as status_installation
from tests.test_resource_pack_icons import _pack


def _publish_v10(settings, sources, texture):
    # Frozen v0.8.4 context shape: disabled sources still contributed their
    # pack metadata. Do not use the current context-ID function or serializer.
    identity = [
        {
            "path": source.get("path"),
            "enabled": bool(source.get("enabled", True)),
            "vanilla": bool(source.get("vanilla")),
            **{key: source.get(key, "") for key in ("pack_kind", "pack_prefix", "subpack")},
        }
        for source in sources
    ]
    context = hashlib.sha256(json.dumps([10, identity], sort_keys=True).encode("utf-8")).hexdigest()
    token = hashlib.sha256(str(texture).encode()).hexdigest()[:24]
    data = {
        "version": 10,
        "context_id": context,
        # File/catalog stamps have the same contract in v10. Bind the frozen
        # publication to this test's temporary files and active catalog.
        "sources_signature": icons._sources_signature(sources),
        "sources": sources,
        "icons": {
            "minecraft:apple": {
                "item_id": "minecraft:apple",
                "path": str(texture),
                "source": "Synthetic v0.8.4 world pack",
                "token": token,
                "source_root": str(texture.parents[2]),
                "declared": False,
            }
        },
        "display_icons": {},
        "scanned_files": 1,
        "variant_aliases": 0,
        "warnings": [],
        "warning_records": [],
    }
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    path = settings.parent / "icon_index_contexts" / f"{context}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    (settings.parent / "icon_index_cache.json").write_bytes(raw)
    return context, path


@pytest.fixture
def legacy_installation(status_installation, request):
    status = status_installation
    root = status.installation.root.parent
    archive = getattr(request, "param", False)
    disabled, _ = _pack(root / "packs", "disabled", {}, archive=archive)
    settings = Path(status.deps.settings_path)
    settings.write_text(json.dumps({"sources": [{"path": str(disabled), "enabled": False}]}), encoding="utf-8")
    worlds = [_world(root, name, "apple") for name in ("world_a", "world_b")]
    contexts, paths, images = [], [], []
    for index, world in enumerate(worlds):
        texture = world / "resource_packs/textures/items/apple.png"
        image = encode_rgba_png(16, 16, bytes((30 + index, 80, 50, 255)) * 256)
        texture.write_bytes(image)
        sources = icons.configured_icon_sources(str(settings), extra_sources=routes._icon_extra_sources_from_world(str(world)))
        for source in sources:
            if not source["enabled"]:
                source.update(pack_kind="resources", pack_prefix="pack/" if archive else "")
        context, path = _publish_v10(settings, sources, texture)
        contexts.append(context)
        paths.append(path)
        images.append(image)
    status.deps = replace(status.deps, read_only=True)
    status.index = {}
    return SimpleNamespace(status=status, disabled=disabled, worlds=worlds, contexts=contexts, paths=paths, images=images, root=root)


@pytest.mark.parametrize("legacy_installation", [False, True], indirect=True, ids=["folder", "mcpack"])
@pytest.mark.parametrize("latest", ["same", "other_world", "absent"])
def test_readonly_upgrade_reuses_v10_context_and_image_urls_without_writes(legacy_installation, monkeypatch, latest):
    case = legacy_installation
    status = case.status
    latest_path = case.root / "icon_index_cache.json"
    if latest == "same":
        latest_path.write_bytes(case.paths[0].read_bytes())
    elif latest == "absent":
        latest_path.unlink()
    current_sources = icons.configured_icon_sources(status.deps.settings_path, extra_sources=routes._icon_extra_sources_from_world(str(case.worlds[0])))
    assert icons.icon_context_id(current_sources) != case.contexts[0]
    before = snapshot(case.root)
    scan = Mock(side_effect=AssertionError("Migration must not scan"))
    write = Mock(side_effect=AssertionError("Read-only migration must not write"))
    monkeypatch.setattr(routes, "scan_icons", scan)
    monkeypatch.setattr(icons, "_write_cache", write)
    original_open, original_scandir = os.open, os.scandir

    def open_file(path, *args, **kwargs):
        if Path(path).is_relative_to(case.disabled):
            pytest.fail("Disabled pack contents must not be read")
        return original_open(path, *args, **kwargs)

    def scandir(path):
        if isinstance(path, (str, os.PathLike)) and Path(path).is_relative_to(case.disabled):
            pytest.fail("Disabled pack must not be traversed")
        return original_scandir(path)

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", open_file)
        guarded.setattr(os, "scandir", scandir)
        response = status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])})
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1 and data["cache"]["state"] == "hit"
        url = data["icons"]["minecraft:apple"]["url"]
        assert parse_qs(urlsplit(url).query)["context"] == [case.contexts[0]]
        # The image request may be routed to a different, still-empty worker.
        status.index = {}
        image = status.client.get(url)
        assert image.status_code == 200 and image.data == case.images[0]
    scan.assert_not_called()
    write.assert_not_called()
    status.installation.download.assert_not_called()
    assert snapshot(case.root) == before


@pytest.mark.parametrize(
    "change", ["activate", "remove", "different_path", "different_world", "changed_active_file", "old_io_warning", "reordered", "unrecognized_context"]
)
def test_migration_does_not_adopt_a_different_or_invalid_configuration(legacy_installation, change):
    case = legacy_installation
    settings = Path(case.status.deps.settings_path)
    world = case.worlds[0]
    if change == "activate":
        settings.write_text(json.dumps({"sources": [{"path": str(case.disabled), "enabled": True}]}), encoding="utf-8")
    elif change == "remove":
        settings.write_text(json.dumps({"sources": []}), encoding="utf-8")
    elif change == "different_path":
        replacement, _ = _pack(case.root / "packs", "replacement", {})
        settings.write_text(json.dumps({"sources": [{"path": str(replacement), "enabled": False}]}), encoding="utf-8")
    elif change == "different_world":
        world = _world(case.root, "unprepared_world", "carrot")
    elif change == "changed_active_file":
        (world / "resource_packs/textures/items/apple.png").write_bytes(b"changed")
    elif change == "old_io_warning":
        data = json.loads(case.paths[0].read_bytes())
        data["warning_records"] = [{"message_key": "{type}", "message_params": {"type": "PermissionError"}, "source_indices": [0]}]
        case.paths[0].write_text(json.dumps(data), encoding="utf-8")
    else:
        data = json.loads(case.paths[0].read_bytes())
        case.paths[0].unlink()
        if change == "reordered":
            _publish_v10(settings, list(reversed(data["sources"])), world / "resource_packs/textures/items/apple.png")
        else:
            data["context_id"] = "a" * 64
            case.paths[0].with_name(data["context_id"] + ".json").write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(case.root)
    response = case.status.client.get("/api/icons/status", query_string={"world_path": str(world)})
    assert response.status_code == 503
    assert "icons" not in response.get_json() and "count" not in response.get_json()
    assert snapshot(case.root) == before


@pytest.mark.parametrize("field,value", [("pack_kind", "data"), ("pack_prefix", "another/"), ("subpack", "other")])
def test_only_inactive_pack_metadata_is_ignored_in_context_identity(field, value):
    source = {"path": "synthetic/pack", "enabled": True, "pack_kind": "resources", "pack_prefix": "pack/", "subpack": "default"}
    assert icons.icon_context_id([source]) != icons.icon_context_id([{**source, field: value}])
    disabled = {**source, "enabled": False}
    assert icons.icon_context_id([disabled]) == icons.icon_context_id([{**disabled, field: value}])
    second = {**source, "path": "synthetic/other"}
    assert icons.icon_context_id([source, second, disabled]) != icons.icon_context_id([second, source, disabled])


@pytest.mark.parametrize("failure", ["publication", "directory", "unrelated_publication"])
def test_migration_read_failure_retains_cause_and_allows_retry(legacy_installation, monkeypatch, failure):
    case = legacy_installation
    status = case.status
    denied = case.paths[0]
    if failure == "unrelated_publication":
        denied = denied.with_name("0" * 64 + ".json")
        denied.write_text("{}", encoding="utf-8")
    elif failure == "directory":
        denied = denied.parent
    original_read, original_scandir = Path.read_text, os.scandir

    def read_text(path, *args, **kwargs):
        if path == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_read(path, *args, **kwargs)

    def scandir(path):
        if isinstance(path, (str, os.PathLike)) and Path(path) == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_scandir(path)

    before = snapshot(case.root)
    previous = status.index
    with monkeypatch.context() as fault:
        fault.setattr(Path, "read_text", read_text)
        fault.setattr(os, "scandir", scandir)
        response = status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])})
    if failure == "unrelated_publication":
        assert response.status_code == 200
    else:
        assert response.status_code == 503
        assert "Permission denied" in response.get_json()["error"]
        assert str(denied) not in response.get_json()["error"]
        assert status.index is previous
    retry = status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])})
    assert retry.status_code == 200 and retry.get_json()["count"] == 1
    assert snapshot(case.root) == before


@pytest.mark.parametrize("legacy_installation", [False, True], indirect=True, ids=["folder", "mcpack"])
@pytest.mark.parametrize("latest_world", [0, 1], ids=["requested_world", "other_world"])
def test_unreadable_latest_keeps_valid_legacy_status_and_image_urls(legacy_installation, monkeypatch, latest_world):
    case = legacy_installation
    status = case.status
    latest = case.root / "icon_index_cache.json"
    latest.write_bytes(case.paths[latest_world].read_bytes())
    original_read = Path.read_text
    reads = []

    def read_text(path, *args, **kwargs):
        reads.append(path)
        if path == latest:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_read(path, *args, **kwargs)

    before = snapshot(case.root)
    scan = Mock(side_effect=AssertionError("Read-only fallback must not scan"))
    write = Mock(side_effect=AssertionError("Read-only fallback must not write"))
    monkeypatch.setattr(routes, "scan_icons", scan)
    monkeypatch.setattr(icons, "_write_cache", write)
    with monkeypatch.context() as fault:
        fault.setattr(Path, "read_text", read_text)
        response = status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])})
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1 and data["cache"]["state"] == "hit"
        url = data["icons"]["minecraft:apple"]["url"]
        assert parse_qs(urlsplit(url).query)["context"] == [case.contexts[0]]
        status.index = {}  # A different worker must resolve the retained URL.
        image = status.client.get(url)
        assert image.status_code == 200 and image.data == case.images[0]
    assert latest in reads and case.paths[0] in reads
    scan.assert_not_called()
    write.assert_not_called()
    status.deps.log_api_exception.assert_not_called()
    status.installation.download.assert_not_called()
    assert snapshot(case.root) == before
    assert status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])}).status_code == 200


@pytest.mark.parametrize("unavailable", ["missing", "invalid", "stale", "no_legacy_search", "directory"])
def test_unreadable_latest_preserves_error_if_no_valid_fallback_exists(legacy_installation, monkeypatch, unavailable):
    case = legacy_installation
    status = case.status
    latest = case.root / "icon_index_cache.json"
    original_publication = case.paths[0].read_bytes()
    settings = Path(status.deps.settings_path)
    original_settings = settings.read_bytes()
    texture = case.worlds[0] / "resource_packs/textures/items/apple.png"
    original_image, image_stat = texture.read_bytes(), texture.stat()
    if unavailable == "missing":
        case.paths[0].unlink()
    elif unavailable == "invalid":
        case.paths[0].write_bytes(b"invalid JSON")
    elif unavailable == "stale":
        texture.write_bytes(b"changed image")
    elif unavailable == "no_legacy_search":
        settings.write_text(json.dumps({"sources": [{"path": str(case.disabled), "enabled": True}]}), encoding="utf-8")
    original_read, original_scandir = Path.read_text, os.scandir

    def read_text(path, *args, **kwargs):
        if path == latest:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_read(path, *args, **kwargs)

    def scandir(path):
        if unavailable == "directory" and isinstance(path, (str, os.PathLike)) and Path(path) == case.paths[0].parent:
            raise OSError(errno.EIO, "Directory read failed", str(path))
        return original_scandir(path)

    before = snapshot(case.root)
    previous = status.index = {"success": True, "count": 7, "icons": {}, "sources": []}
    with monkeypatch.context() as fault:
        fault.setattr(Path, "read_text", read_text)
        fault.setattr(os, "scandir", scandir)
        response = status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])})
    assert response.status_code == 503
    data = response.get_json()
    assert data["status"] == "unavailable" and "Permission denied" in data["error"]
    assert str(latest) not in data["error"] and "Directory read failed" not in data["error"]
    assert "count" not in data and "icons" not in data
    assert status.index is previous
    status.store.assert_not_called()
    status.deps.log_api_exception.assert_called_once()
    assert snapshot(case.root) == before
    # Releasing the error and restoring the prepared state must permit a retry.
    case.paths[0].write_bytes(original_publication)
    settings.write_bytes(original_settings)
    texture.write_bytes(original_image)
    os.utime(texture, ns=(image_stat.st_atime_ns, image_stat.st_mtime_ns))
    retry = status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])})
    assert retry.status_code == 200 and retry.get_json()["count"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive file sharing")
def test_exclusively_locked_foreign_latest_allows_readonly_legacy_access(legacy_installation):
    import ctypes
    from ctypes import wintypes

    case = legacy_installation
    status = case.status
    latest = case.root / "icon_index_cache.json"  # The fixture publishes world B last.
    before = snapshot(case.root)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    # GENERIC_READ, no FILE_SHARE flags, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
    handle = create_file(str(latest), 0x80000000, 0, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        with pytest.raises(PermissionError):
            latest.read_bytes()
        assert icons.load_cached_icon_index(status.deps.settings_path, context_id=case.contexts[0])["count"] == 1
        response = status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])})
        assert response.status_code == 200 and response.get_json()["count"] == 1
        url = response.get_json()["icons"]["minecraft:apple"]["url"]
        assert parse_qs(urlsplit(url).query)["context"] == [case.contexts[0]]
        status.index = {}
        image = status.client.get(url)
        assert image.status_code == 200 and image.data == case.images[0]
    finally:
        if not close_handle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    status.deps.log_api_exception.assert_not_called()
    assert snapshot(case.root) == before
    assert status.client.get("/api/icons/status", query_string={"world_path": str(case.worlds[0])}).status_code == 200
