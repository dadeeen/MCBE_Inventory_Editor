"""Exercise actual HTTP status handlers, including failed reads and retries."""

import errno
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import icon_api_routes as routes
from mcbe_editor import icons
from mcbe_editor.icon_diagnostics import error_record, warning_record
from tests.test_icon_cache_state import installed as installed, snapshot


@pytest.mark.parametrize("failure", ["scan", "cache", "context"])
@pytest.mark.parametrize("locale", ["de", "en"])
def test_status_failure_preserves_unknown_state_and_can_retry(monkeypatch, failure, locale):
    import main

    previous = {"success": True, "count": 7, "icons": {}, "sources": []}
    ready = {"success": True, "count": 8, "icons": {}, "sources": [], "warnings": []}
    store = Mock()
    deps = replace(main.icon_route_deps(), read_only=failure == "cache", get_icon_index=lambda: previous, set_icon_index=store)
    monkeypatch.setattr(main, "icon_route_deps", lambda: deps)
    error = PermissionError(errno.EACCES, "Permission denied", "/private/synthetic-icons")
    monkeypatch.setattr(routes, "_requested_icon_context", lambda *_args: ([], []))
    if failure == "context":
        monkeypatch.setattr(routes, "_requested_icon_context", Mock(side_effect=[error, ([], [])]))
    if failure == "cache":
        monkeypatch.setattr(routes, "configured_icon_sources", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(routes, "load_prepared_icon_index", Mock(side_effect=[error, ready]))
    else:
        monkeypatch.setattr(routes, "_scan_and_store_icons", Mock(side_effect=[error, ready]) if failure == "scan" else Mock(return_value=ready))
    client = main.app.test_client()
    first = client.get("/api/icons/status", headers={"Accept-Language": locale})
    assert first.status_code == 503
    data = first.get_json()
    assert data["success"] is False
    assert data["status"] == "unavailable" and data["code"] == "icons_status_unavailable"
    assert "Permission denied" in data["error"]
    assert ("Icon-Status" if locale == "de" else "icon status") in data["error"]
    assert "/private/synthetic-icons" not in data["error"]
    assert "count" not in data and "missing_banner_patterns" not in data
    store.assert_not_called()
    assert previous["count"] == 7
    second = client.get("/api/icons/status", headers={"Accept-Language": locale})
    assert second.status_code == 200
    assert second.get_json()["count"] == 8 and second.get_json()["success"]


@pytest.fixture
def status_installation(installed, monkeypatch):
    """Use real source discovery, index persistence and HTTP status handling."""
    import main

    monkeypatch.setenv("MCBE_ICON_ROOTS", "")
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [installed.root])
    result = SimpleNamespace(installation=installed, index={"success": True, "count": 7, "icons": {}, "sources": []})
    result.store = Mock(side_effect=lambda index: setattr(result, "index", index))
    result.deps = replace(
        main.icon_route_deps(),
        settings_path=str(installed.root.parent / "sources.json"),
        data_root=str(installed.root.parent),
        item_db_path=str(installed.db),
        read_only=False,
        get_icon_index=lambda: result.index,
        set_icon_index=result.store,
        log_api_exception=Mock(),
    )
    monkeypatch.setattr(main, "icon_route_deps", lambda: result.deps)
    result.client = main.app.test_client()
    return result


def index_files(status):
    return [icons._cache_file(status.deps.settings_path), *Path(status.deps.settings_path).parent.glob("icon_index_contexts/*.json")]


def deny_scandir(monkeypatch, denied):
    original = os.scandir

    def scandir(path):
        if isinstance(path, (str, os.PathLike)) and Path(path) == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(denied))
        return original(path)

    monkeypatch.setattr(os, "scandir", scandir)


@pytest.mark.parametrize("directory", [".", "textures/items", "textures/display"])
def test_actual_failed_directory_read_never_publishes_empty_or_partial_status(status_installation, monkeypatch, directory):
    status = status_installation
    root = status.installation.root
    denied = root / directory
    denied.mkdir(parents=True, exist_ok=True)
    images_before = snapshot(root)
    previous = status.index
    with monkeypatch.context() as fault:
        deny_scandir(fault, denied)
        response = status.client.get("/api/icons/status")
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "unavailable" and "Permission denied" in payload["error"]
    assert str(root) not in payload["error"]
    assert "count" not in payload and "vanilla_cache" not in payload
    assert status.index is previous
    status.store.assert_not_called()
    status.deps.log_api_exception.assert_called_once()
    assert not any(path.exists() for path in index_files(status))
    retry = status.client.get("/api/icons/status")
    assert retry.status_code == 200
    assert retry.get_json()["count"] == 1
    assert retry.get_json()["vanilla_cache"]["state"] == "current"
    assert snapshot(root) == images_before


def test_failed_rescan_preserves_both_published_index_and_worker_state(status_installation, monkeypatch):
    status = status_installation
    assert status.client.get("/api/icons/status").status_code == 200
    published = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in index_files(status)}
    previous = status.index
    status.store.reset_mock()
    with monkeypatch.context() as fault:
        deny_scandir(fault, status.installation.root / "textures/items")
        with pytest.raises(PermissionError):
            routes._scan_and_store_icons(status.deps, force=True, extra_sources=[])
    assert status.index is previous
    status.store.assert_not_called()
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in published} == published
    assert status.client.get("/api/icons/status").get_json()["count"] == 1


@pytest.mark.parametrize("target", ["manifest", "atlas", "vanilla", "archive", "disabled"])
def test_pack_metadata_io_errors_are_not_cached_as_content_warnings(status_installation, monkeypatch, target):
    from tests.test_resource_pack_icons import _pack

    status = status_installation
    pack, _ = _pack(
        status.installation.root.parent,
        "custom",
        {"textures/item_texture.json": {"texture_data": {}}},
        archive=target == "archive",
    )
    Path(status.deps.settings_path).write_text(json.dumps({"sources": [{"path": str(pack), "enabled": target != "disabled"}]}), encoding="utf-8")
    denied = (
        pack
        if target == "archive"
        else status.installation.root / "manifest.json"
        if target == "vanilla"
        else pack / ("textures/item_texture.json" if target == "atlas" else "manifest.json")
    )
    original = os.open

    def open_file(path, *args, **kwargs):
        if Path(path) == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(os, "open", open_file)
        response = status.client.get("/api/icons/status")
    if target == "disabled":
        assert response.status_code == 200 and response.get_json()["count"] == 1
    else:
        assert response.status_code == 503
        assert "Permission denied" in response.get_json()["error"]
        status.store.assert_not_called()
        assert not any(path.exists() for path in index_files(status))
        assert status.client.get("/api/icons/status").status_code == 200


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("target", ["latest", "context", "settings"])
def test_actual_index_and_settings_read_errors_keep_cause_and_allow_retry(status_installation, monkeypatch, read_only, target):
    status = status_installation
    assert status.client.get("/api/icons/status").status_code == 200
    paths = index_files(status)
    denied = paths[0] if target == "latest" else paths[1] if target == "context" else Path(status.deps.settings_path)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    previous = status.index
    status.store.reset_mock()
    status.deps = replace(status.deps, read_only=read_only)
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "read_text", read_text)
        response = status.client.get("/api/icons/status")
    assert response.status_code == 503
    assert "Permission denied" in response.get_json()["error"]
    assert str(denied) not in response.get_json()["error"]
    assert "Kein gültiger Icon-Index" not in response.get_json()["error"]
    assert status.index is previous
    status.store.assert_not_called()
    status.deps.log_api_exception.assert_called_once()
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
    retry = status.client.get("/api/icons/status")
    assert retry.status_code == 200 and retry.get_json()["count"] == 1


@pytest.mark.parametrize("read_only", [False, True])
def test_existing_index_with_old_io_warning_is_not_trusted(status_installation, read_only):
    status = status_installation
    assert status.client.get("/api/icons/status").status_code == 200
    images_before = snapshot(status.installation.root)
    paths = index_files(status)
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["icons"] = {}
        data["warning_records"] = [
            warning_record("{path}: {type}: {error}", path=status.installation.root, type="PermissionError", error=error_record(PermissionError("denied")))
        ]
        path.write_text(json.dumps(data), encoding="utf-8")
    poisoned = {path: path.read_bytes() for path in paths}
    status.deps = replace(status.deps, read_only=read_only)
    response = status.client.get("/api/icons/status")
    if read_only:
        assert response.status_code == 503
        assert "count" not in response.get_json()
        assert {path: path.read_bytes() for path in paths} == poisoned
        status.deps = replace(status.deps, read_only=False)
        response = status.client.get("/api/icons/status")
    assert response.status_code == 200 and response.get_json()["count"] == 1
    assert snapshot(status.installation.root) == images_before
    assert status.client.get("/api/icons/status").get_json()["cache"]["state"] == "hit"
