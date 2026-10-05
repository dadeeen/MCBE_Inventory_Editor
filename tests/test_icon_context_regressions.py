"""Icon scan/status continuity and byte access to indexed display assets."""
from __future__ import annotations

import zipfile
import json
from uuid import uuid4
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from mcbe_editor import icon_api_routes as routes
from mcbe_editor import icons


@pytest.fixture(autouse=True)
def isolate_sources(monkeypatch):
    monkeypatch.setenv("MCBE_ICON_ROOTS", "")
    monkeypatch.setattr(icons, "_default_roots", lambda: [])
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [])


def _deps(tmp_path):
    state = {}
    return SimpleNamespace(
        read_only=False, settings_path=str(tmp_path / "sources.json"), data_root=str(tmp_path),
        get_icon_index=lambda: state.get("index", {}), set_icon_index=lambda value: state.update(index=value),
        jsonify=lambda value: value, json_string=lambda data, key: data.get(key, ""),
        response=lambda data, **kwargs: {"data": data, **kwargs},
        api_error=lambda message, *args: {"success": False, "error": message},
        log_api_exception=lambda *args: pytest.fail(f"Unexpected route error: {args}"), audit_event=lambda *args, **kwargs: None,
    )


def _world(tmp_path, name, item):
    world = tmp_path / name
    texture = world / "resource_packs" / "textures" / "items" / (item + ".png")
    texture.parent.mkdir(parents=True)
    texture.write_bytes(item.encode())
    pack_id = str(uuid4())
    (world / "resource_packs/manifest.json").write_text(json.dumps({
        "format_version": 2, "header": {"uuid": pack_id, "version": [1, 0, 0], "name": name},
        "modules": [{"type": "resources", "uuid": str(uuid4()), "version": [1, 0, 0]}],
    }), encoding="utf-8")
    (world / "world_resource_packs.json").write_text(json.dumps([{"pack_id": pack_id, "version": [1, 0, 0]}]), encoding="utf-8")
    return world


def _context(worker, world):
    return icons.icon_context_id(icons.configured_icon_sources(worker.settings_path, extra_sources=routes._icon_extra_sources_from_world(str(world))))


@pytest.mark.parametrize("read_only", [False, True])
def test_world_icon_urls_survive_other_world_scans_and_fresh_workers(tmp_path, monkeypatch, read_only):
    world_a = _world(tmp_path, "world_a", "apple")
    world_b = _world(tmp_path, "world_b", "apple")
    (world_b / "resource_packs/textures/items/apple.png").write_bytes(b"world-b")
    publisher = _deps(tmp_path)
    response_b = routes.icons_scan({"world_path": str(world_b)}, publisher)
    # An older request for A may reach the server after B completed.
    response_a = routes.icons_scan({"world_path": str(world_a)}, publisher)
    fresh_worker = _deps(tmp_path)
    fresh_worker.read_only = read_only
    monkeypatch.setattr(routes, "scan_icons", lambda *args, **kwargs: pytest.fail("Reading published icons must not scan"))
    for response, expected in ((response_b, b"world-b"), (response_a, b"apple"), (response_b, b"world-b")):
        url = urlsplit(response["icons"]["minecraft:apple"]["url"])
        context = parse_qs(url.query)["context"][0]
        result = routes.icon_file(url.path.rsplit("/", 1)[1], fresh_worker, context_id=context)
        assert result["data"] == expected
    assert response_a["icons"] != response_b["icons"]


@pytest.mark.parametrize("read_only", [False, True])
def test_explicit_status_selects_its_world_across_workers(tmp_path, monkeypatch, read_only):
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    publisher = _deps(tmp_path)
    routes.icons_scan({"world_path": str(second)}, publisher)
    routes.icons_scan({"world_path": str(first)}, publisher)
    worker = _deps(tmp_path)
    worker.read_only = read_only
    if read_only:
        monkeypatch.setattr(routes, "scan_icons", lambda *args, **kwargs: pytest.fail("Readonly status must not scan"))
    result = routes.icons_status(worker, world_path=str(second))
    assert "minecraft:carrot" in result["icons"]
    assert "minecraft:apple" not in result["icons"]


def test_readonly_missing_world_context_cannot_use_another_world(tmp_path, monkeypatch):
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    worker = _deps(tmp_path)
    routes.icons_scan({"world_path": str(first)}, worker)
    worker.read_only = True
    monkeypatch.setattr(routes, "scan_icons", lambda *args, **kwargs: pytest.fail("Readonly status must not scan"))
    result = routes.icons_status(worker, world_path=str(second))
    assert result["icons"] == {}


@pytest.mark.parametrize("action", ["add", "remove", "disable", "move", "vanilla"])
def test_source_mutations_use_the_request_world_instead_of_the_last_scan(tmp_path, action):
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    pack = _world(tmp_path, "manual", "stone") / "resource_packs"
    worker = _deps(tmp_path)
    worker.json_bool = lambda data, key, default: data.get(key, default)
    worker.run_update_icons = lambda **kwargs: (0, "")
    icons.add_icon_source(worker.settings_path, str(pack))
    routes.icons_scan({"world_path": str(first)}, worker)
    data = {"world_path": str(second), "path": str(pack), "enabled": False, "direction": "up"}
    handler = {
        "add": routes.icons_sources_add, "remove": routes.icons_sources_remove,
        "disable": routes.icons_sources_set_enabled, "move": routes.icons_sources_move,
        "vanilla": routes.icons_vanilla_update,
    }[action]
    result = handler(data, worker)
    assert result["success"] is True
    assert "minecraft:carrot" in result["icons"]
    assert "minecraft:apple" not in result["icons"]


def test_context_publication_is_shared_through_http_and_keeps_world_priority(tmp_path, monkeypatch):
    import main

    worker = _deps(tmp_path)
    deps = replace(main.icon_route_deps(), settings_path=worker.settings_path, data_root=worker.data_root,
                   get_icon_index=worker.get_icon_index, set_icon_index=worker.set_icon_index)
    monkeypatch.setattr(main, "icon_route_deps", lambda: deps)
    client = main.app.test_client()
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "apple")
    (second / "resource_packs/textures/items/apple.png").write_bytes(b"world-b")
    first_response = client.post("/api/icons/scan", json={"world_path": str(first)}, headers={"X-CSRF-Token": main.CSRF_TOKEN})
    assert first_response.status_code == 200
    first_data = first_response.get_json()
    second_response = client.post("/api/icons/scan", json={"world_path": str(second)}, headers={"X-CSRF-Token": main.CSRF_TOKEN})
    assert second_response.status_code == 200
    second_data = second_response.get_json()
    assert client.get(first_data["icons"]["minecraft:apple"]["url"]).data == b"apple"
    assert client.get(second_data["icons"]["minecraft:apple"]["url"]).data == b"world-b"
    status = client.get("/api/icons/status", query_string={"world_path": str(first)}).get_json()
    sources = client.get("/api/icons/sources", query_string={"world_path": str(second)}).get_json()
    assert status["icons"] == first_data["icons"]
    assert sources["icons"] == second_data["icons"]
    preview = next(row for row in first_data["health"]["sample"] if row["item_id"] == "minecraft:apple")
    assert client.get(preview["url"]).data == b"apple"
    # A token from A must not be resolved through B's context.
    context_b = parse_qs(urlsplit(second_data["icons"]["minecraft:apple"]["url"]).query)["context"][0]
    assert client.get(f"/api/icons/{first_data['icons']['minecraft:apple']['token']}?context={context_b}").status_code == 404
    for invalid in ("../icon_index_cache", "", "A" * 64, "0" * 63):
        response = client.get("/api/icons/unused", query_string={"context": invalid})
        assert response.status_code == 404
    assert client.get("/api/icons/status", query_string={"world_path": "\x00"}).status_code == 400
    assert client.get("/api/icons/sources", query_string={"world_path": "\x00"}).status_code == 400


def test_published_contexts_survive_more_than_eight_worlds(tmp_path, monkeypatch):
    worker = _deps(tmp_path)
    worlds = [_world(tmp_path, f"world_{i}", "apple") for i in range(12)]
    first = routes.icons_scan({"world_path": str(worlds[0])}, worker)
    for world in worlds[1:]:
        routes.icons_scan({"world_path": str(world)}, worker)
    assert len(icons._context_cache_files(icons._cache_file(worker.settings_path))) == 12
    context = _context(worker, worlds[0])
    fresh = _deps(tmp_path)
    fresh.read_only = True
    monkeypatch.setattr(routes, "scan_icons", lambda *a, **kw: pytest.fail("Reading a publication must not scan"))
    token = first["icons"]["minecraft:apple"]["token"]
    assert routes.icon_file(token, fresh, context_id=context)["data"] == b"apple"
    assert routes.icons_status(fresh, world_path=str(worlds[0]))["icons"] == first["icons"]


def test_context_candidate_cache_reuses_json_and_detects_republication(tmp_path, monkeypatch):
    from unittest.mock import patch

    worker = _deps(tmp_path)
    world = _world(tmp_path, "world", "apple")
    scanned = routes.icons_scan({"world_path": str(world)}, worker)
    context = _context(worker, world)
    token = scanned["icons"]["minecraft:apple"]["token"]
    with patch.object(icons.json, "loads", wraps=icons.json.loads) as decoded:
        for _ in range(5):
            assert icons.load_cached_icon_candidate(worker.settings_path, context, token).read_bytes() == b"apple"
    assert decoded.call_count == 1
    texture = world / "resource_packs/textures/items/apple.png"
    texture.write_bytes(b"changed-apple")
    updated = routes.icons_scan({"world_path": str(world)}, worker)
    new_token = updated["icons"]["minecraft:apple"]["token"]
    assert new_token != token
    assert icons.load_cached_icon_candidate(worker.settings_path, context, token) is None
    assert icons.load_cached_icon_candidate(worker.settings_path, context, new_token).read_bytes() == b"changed-apple"
    icons.clear_icon_cache(worker.settings_path)
    assert icons.load_cached_icon_candidate(worker.settings_path, context, new_token) is None
    assert icons._cached_context_candidates.cache_info().currsize == 0


@pytest.mark.parametrize("operation", ["source", "vanilla"])
def test_global_source_changes_invalidate_other_world_publications(tmp_path, operation):
    worker = _deps(tmp_path)
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    routes.icons_scan({"world_path": str(first)}, worker)
    routes.icons_scan({"world_path": str(second)}, worker)
    if operation == "source":
        pack = _world(tmp_path, "manual", "stone") / "resource_packs"
        result = routes.icons_sources_add({"path": str(pack), "world_path": str(first)}, worker)
    else:
        worker.json_bool = lambda data, key, default: data.get(key, default)
        worker.run_update_icons = lambda **kwargs: (0, "")
        result = routes.icons_vanilla_update({"world_path": str(first)}, worker)
    assert result["success"] is True
    assert icons.load_cached_icon_index(worker.settings_path, context_id=_context(worker, second)) is None
    refreshed = routes.icons_status(_deps(tmp_path), world_path=str(second))
    assert "minecraft:carrot" in refreshed["icons"]
    assert "minecraft:apple" not in refreshed["icons"]
    assert ("minecraft:stone" in refreshed["icons"]) is (operation == "source")


def test_readonly_can_use_legacy_cache_only_with_matching_world_sources(tmp_path, monkeypatch):
    world = _world(tmp_path, "world", "apple")
    worker = _deps(tmp_path)
    icons.scan_icons(worker.settings_path, force=True, extra_sources=routes._icon_extra_sources_from_world(str(world)))
    worker.read_only = True
    monkeypatch.setattr(routes, "scan_icons", lambda *args, **kwargs: pytest.fail("Readonly status must not scan"))
    result = routes.icons_status(worker, world_path=str(world))
    assert "minecraft:apple" in result["icons"]
    other = _world(tmp_path, "other", "carrot")
    assert routes.icons_status(worker, world_path=str(other))["icons"] == {}


def test_status_preserves_world_sources_and_their_priority(tmp_path):
    world = _world(tmp_path, "world_a", "apple")
    deps = _deps(tmp_path)
    scanned = routes.icons_scan({"world_path": str(world)}, deps)
    assert scanned["success"] is True
    token = scanned["icons"]["minecraft:apple"]["token"]
    for _ in range(2):
        result = routes.icons_status(deps)
        assert result["icons"]["minecraft:apple"]["token"] == token
        assert deps.get_icon_index()["_by_token"][token].read_bytes() == b"apple"
        assert any(source["world"] for source in result["sources"])


def test_source_changes_do_not_erase_world_derived_icons(tmp_path):
    world = _world(tmp_path, "world_a", "apple")
    other = _world(tmp_path, "manual", "carrot") / "resource_packs"
    deps = _deps(tmp_path)
    routes.icons_scan({"world_path": str(world)}, deps)
    result = routes.icons_sources_add({"path": str(other)}, deps)
    assert result["success"] is True
    assert {"minecraft:apple", "minecraft:carrot"} <= result["icons"].keys()


@pytest.mark.parametrize("next_world", ["world_b", ""])
def test_explicit_world_rescan_replaces_not_accumulates_world_sources(tmp_path, next_world):
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    deps = _deps(tmp_path)
    routes.icons_scan({"world_path": str(first)}, deps)
    result = routes.icons_scan({"world_path": str(second) if next_world else ""}, deps)
    assert "minecraft:apple" not in result["icons"]
    assert ("minecraft:carrot" in result["icons"]) is bool(next_world)
    refreshed = routes.icons_status(deps)
    assert refreshed["icons"] == result["icons"]


def test_status_uses_latest_published_world_context_across_workers(tmp_path):
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    worker_a, worker_b = _deps(tmp_path), _deps(tmp_path)
    routes.icons_scan({"world_path": str(first)}, worker_a)
    routes.icons_scan({"world_path": str(second)}, worker_b)
    refreshed = routes.icons_status(worker_a)
    assert "minecraft:carrot" in refreshed["icons"]
    assert "minecraft:apple" not in refreshed["icons"]


@pytest.mark.parametrize("worker_state", ["stale", "fresh"])
@pytest.mark.parametrize("action", ["add", "remove", "disable", "move"])
def test_source_changes_preserve_latest_published_world_across_workers(tmp_path, worker_state, action):
    worker_a, worker_b = _deps(tmp_path), _deps(tmp_path)
    worker_a.json_bool = lambda data, key, default: data.get(key, default)
    packs = [_world(tmp_path, f"manual_{i}", f"item_{i}") / "resource_packs" for i in range(3)]
    for pack in packs[:2]:
        icons.add_icon_source(worker_a.settings_path, str(pack))
    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    if worker_state == "stale":
        routes.icons_scan({"world_path": str(first)}, worker_a)
    routes.icons_scan({"world_path": str(second)}, worker_b)

    # These real mutations invalidate the shared cache before their rescan.
    if action == "add":
        result = routes.icons_sources_add({"path": str(packs[2])}, worker_a)
    elif action == "remove":
        result = routes.icons_sources_remove({"path": str(packs[0])}, worker_a)
    elif action == "disable":
        result = routes.icons_sources_set_enabled({"path": str(packs[0]), "enabled": False}, worker_a)
    else:
        result = routes.icons_sources_move({"path": str(packs[0]), "direction": "up"}, worker_a)
    assert result["success"] is True

    manual = icons.load_icon_sources(worker_a.settings_path)["sources"]
    paths = [source["path"] for source in manual]
    if action == "add":
        assert str(packs[2]) in paths
    elif action == "remove":
        assert str(packs[0]) not in paths
    elif action == "disable":
        assert next(source for source in manual if source["path"] == str(packs[0]))["enabled"] is False
    else:
        assert paths[0] == str(packs[0])

    # Both the mutation response and the next worker's status retain world B.
    for index in (result, routes.icons_status(worker_b)):
        assert [source["path"] for source in index["sources"] if source.get("world")] == [str(second / "resource_packs")]
        assert "minecraft:carrot" in index["icons"]
        assert "minecraft:apple" not in index["icons"]


def test_readonly_status_reuses_world_index_without_scanning(tmp_path, monkeypatch):
    deps = _deps(tmp_path)
    world = _world(tmp_path, "world", "apple")
    routes.icons_scan({"world_path": str(world)}, deps)
    deps.read_only = True
    monkeypatch.setattr(routes, "scan_icons", lambda *args, **kwargs: pytest.fail("Readonly status scanned files"))
    assert "minecraft:apple" in routes.icons_status(deps)["icons"]


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("cache_hit", [False, True])
@pytest.mark.parametrize("category,asset_id", [("items", "minecraft:apple"), ("display", "mcbe:axolotl_gold")])
def test_every_indexed_icon_category_can_read_its_bytes(tmp_path, monkeypatch, archive, cache_hit, category, asset_id):
    root = tmp_path / ("pack.zip" if archive else "pack")
    member = f"textures/{category}/{asset_id.split(':')[1]}.png"
    raw = b"fixture-icon-bytes"
    if archive:
        with zipfile.ZipFile(root, "w") as zf:
            zf.writestr(member, raw)
    else:
        path = root / member
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(root))
    settings = str(tmp_path / "sources.json")
    result = icons.scan_icons(settings_path=settings, force=True)
    if cache_hit:
        result = icons.scan_icons(settings_path=settings)
        assert result["cache"]["state"] == "hit"
    public = result["icons" if category == "items" else "display_icons"][asset_id]
    assert result["_by_token"][public["token"]].read_bytes() == raw


@pytest.mark.parametrize("archive", [False, True])
def test_display_asset_read_keeps_size_checks(tmp_path, monkeypatch, archive):
    root = tmp_path / ("pack.zip" if archive else "pack")
    member = "textures/display/axolotl_gold.png"
    if archive:
        with zipfile.ZipFile(root, "w") as zf:
            zf.writestr(member, b"small")
    else:
        path = root / member
        path.parent.mkdir(parents=True)
        path.write_bytes(b"small")
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(root))
    result = icons.scan_icons(settings_path=str(tmp_path / "sources.json"), force=True)
    token = result["display_icons"]["mcbe:axolotl_gold"]["token"]
    monkeypatch.setattr(icons, "_MAX_FILE_BYTES", 4)
    with pytest.raises(ValueError):
        result["_by_token"][token].read_bytes()


@pytest.mark.parametrize("change", ["changed", "removed"])
def test_stale_source_files_do_not_resurrect_an_older_workers_world(tmp_path, change):
    import os
    import shutil

    first = _world(tmp_path, "world_a", "apple")
    second = _world(tmp_path, "world_b", "carrot")
    worker_a, worker_b = _deps(tmp_path), _deps(tmp_path)
    routes.icons_scan({"world_path": str(first)}, worker_a)
    routes.icons_scan({"world_path": str(second)}, worker_b)
    source = second / "resource_packs"
    if change == "removed":
        shutil.rmtree(source)
    else:
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    # Normal readonly cache reads must continue to reject stale references.
    assert icons.load_cached_icon_index(worker_a.settings_path) is None
    result = routes.icons_status(worker_a)
    assert "minecraft:apple" not in result["icons"]
    assert ("minecraft:carrot" in result["icons"]) is (change == "changed")
    assert any(source.get("world") and source["path"] == str(second / "resource_packs") for source in result["sources"])
