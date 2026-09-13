"""Icon scan/status continuity and byte access to indexed display assets."""
from __future__ import annotations

import zipfile
from types import SimpleNamespace

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
        api_error=lambda message, *args: {"success": False, "error": message},
        log_api_exception=lambda *args: pytest.fail(f"Unexpected route error: {args}"), audit_event=lambda *args, **kwargs: None,
    )


def _world(tmp_path, name, item):
    world = tmp_path / name
    texture = world / "resource_packs" / "textures" / "items" / (item + ".png")
    texture.parent.mkdir(parents=True)
    texture.write_bytes(item.encode())
    return world


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
