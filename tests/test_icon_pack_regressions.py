"""Regressions for pack layering, discovery failures and image delivery."""

import json
import struct
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from mcbe_editor import icons
from mcbe_editor import icon_api_routes as routes
from tests.test_icon_context_regressions import _deps
from tests.test_resource_pack_icons import _bytes, _item, _pack, _scan, _vanilla, _world


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("MCBE_ICON_ROOTS", "")
    monkeypatch.setattr(icons, "_default_roots", lambda: [])
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [])


@pytest.mark.parametrize(
    "reference",
    [
        ["textures/items/a", "textures/items/b"],
        {"textures": "textures/items/a", "tint_color": "#ff0000"},
        [],
        None,
        {},
        [None, "textures/items/a"],
        [{}, "textures/items/a"],
        [[], "textures/items/a"],
    ],
)
def test_unresolved_atlas_entry_does_not_guess_an_item_named_png(tmp_path, reference):
    _, rp = _pack(
        tmp_path / "resource_packs",
        "rp",
        {
            "textures/item_texture.json": {"texture_data": {"apple": reference}},
            "textures/items/apple.png": b"wrong guess",
            "textures/items/a.png": b"a",
            "textures/items/b.png": b"b",
        },
    )
    result, _ = _scan(tmp_path, _world(tmp_path, "world", [rp]))
    assert "minecraft:apple" not in result["icons"]
    assert any("minecraft:apple" in warning for warning in result["warnings"])


@pytest.mark.parametrize("fault", ["installed_root", "users_root", "search_limit"])
def test_optional_discovery_failure_preserves_completed_world_local_pack(tmp_path, monkeypatch, fault):
    world = _world(tmp_path, "world")
    _, rp = _pack(world / "resource_packs", "local", {"textures/items/apple.png": b"local"})
    (world / "world_resource_packs.json").write_text(json.dumps([rp]))
    optional = tmp_path / "installation"
    blocked = optional / ("Users" if fault == "users_root" else "resource_packs")
    blocked.mkdir(parents=True)
    monkeypatch.setattr(icons, "_default_roots", lambda: [blocked if fault == "users_root" else optional])
    if fault == "search_limit":
        from mcbe_editor import resource_packs

        monkeypatch.setattr(resource_packs, "MAX_PACKS", 2)
        for name in ("one", "two", "three"):
            _pack(blocked, name, {})
    else:
        original = Path.iterdir

        def denied(path):
            if path == blocked:
                raise PermissionError("synthetic denied directory")
            return original(path)

        monkeypatch.setattr(Path, "iterdir", denied)
    result, reader = _scan(tmp_path, world)
    assert _bytes(reader, "minecraft:apple") == b"local"
    assert result["warnings"]


def test_incomplete_discovery_level_cannot_hide_a_duplicate_pack(tmp_path, monkeypatch):
    from mcbe_editor import resource_packs

    world = _world(tmp_path, "world")
    _, rp = _pack(world / "resource_packs", "a", {"textures/items/apple.png": b"ambiguous"})
    _pack(world / "resource_packs", "b", {}, pack_id=rp["pack_id"])
    (world / "world_resource_packs.json").write_text(json.dumps([rp]))
    monkeypatch.setattr(resource_packs, "MAX_PACKS", 1)
    result, _ = _scan(tmp_path, world)
    assert "minecraft:apple" not in result["icons"]
    assert result["warnings"]


@pytest.mark.parametrize("read_only", [False, True])
def test_corrupt_compressed_icon_is_a_handled_http_error(tmp_path, monkeypatch, read_only):
    import main

    path, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"apple" * 50}, archive=True)
    with zipfile.ZipFile(path) as zf:
        files = {info.filename: zf.read(info) for info in zf.infolist()}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    with zipfile.ZipFile(path) as zf:
        offset = zf.getinfo("pack/textures/items/apple.png").header_offset
    raw = bytearray(path.read_bytes())
    name, extra = struct.unpack_from("<HH", raw, offset + 26)
    raw[offset + 30 + name + extra] = 7
    path.write_bytes(raw)
    public, publisher = _scan(tmp_path, _world(tmp_path, "world", [rp]))
    reader = _deps(tmp_path)
    logged = []
    deps = replace(
        main.icon_route_deps(),
        settings_path=publisher.settings_path,
        data_root=publisher.data_root,
        get_icon_index=reader.get_icon_index,
        set_icon_index=reader.set_icon_index,
        read_only=read_only,
        log_api_exception=lambda *args: logged.append(args),
    )
    monkeypatch.setattr(main, "icon_route_deps", lambda: deps)
    response = main.app.test_client().get(public["icons"]["minecraft:apple"]["url"])
    assert response.status_code == 404
    assert logged and logged[0][0] == "icons.file"


@pytest.mark.parametrize("override", [False, True])
def test_base_item_without_icon_in_higher_behavior_pack_hides_lower_custom_icon(tmp_path, monkeypatch, override):
    _vanilla(tmp_path, monkeypatch)
    atlas = {"demo:tool": {"textures": "textures/custom/tool"}}
    if override:
        atlas["fruit_icon"] = {"textures": "textures/custom/fruit"}
    _, rp = _pack(
        tmp_path / "resource_packs",
        "rp",
        {
            "textures/item_texture.json": {"texture_data": atlas},
            "textures/custom/tool.png": b"lower custom icon",
            "textures/custom/fruit.png": b"replacement apple",
        },
    )
    _, lower = _pack(tmp_path / "behavior_packs", "lower", {"items/apple.json": _item("minecraft:apple")}, kind="data")
    top_item = _item("minecraft:apple")
    top_item["minecraft:item"]["components"] = {"minecraft:max_stack_size": 32}
    _, top = _pack(tmp_path / "behavior_packs", "top", {"items/apple.json": top_item}, kind="data")
    _, reader = _scan(tmp_path, _world(tmp_path, "world", [rp], [top, lower]))
    assert _bytes(reader, "minecraft:apple") == (b"replacement apple" if override else b"vanilla apple")


def test_behavior_item_without_icon_preserves_global_loose_override(tmp_path, monkeypatch):
    _vanilla(tmp_path, monkeypatch)
    image = tmp_path / "global" / "textures/items/apple.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"global apple")
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(tmp_path / "global"))
    item = _item("minecraft:apple")
    item["minecraft:item"]["components"] = {"minecraft:max_stack_size": 32}
    _, bp = _pack(tmp_path / "behavior_packs", "behavior", {"items/apple.json": item}, kind="data")
    _, reader = _scan(tmp_path, _world(tmp_path, "world", behaviors=[bp]))
    assert _bytes(reader, "minecraft:apple") == b"global apple"


@pytest.mark.parametrize("pack_kind", ["declared", "loose"])
def test_catalog_change_invalidates_icon_targets_and_material_classification(tmp_path, monkeypatch, pack_kind):
    from mcbe_editor import item_data

    identifier = "minecraft:icon_regression_future_item"
    assert identifier not in item_data.ITEMS
    texture = ("items" if pack_kind == "declared" else "blocks") + "/icon_regression_future_item.png"
    path, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/" + texture: b"new item"})
    if pack_kind == "loose":
        (path / "manifest.json").unlink()
        monkeypatch.setenv("MCBE_ICON_ROOTS", str(path))
    world = _world(tmp_path, "world", [rp] if pack_kind == "declared" else [])
    first, reader = _scan(tmp_path, world)
    assert (identifier in first["icons"]) is (pack_kind == "loose")
    monkeypatch.setattr(item_data, "ITEMS", {**item_data.ITEMS, identifier: ("New item", "New item")})
    second = routes.icons_status(reader, world_path=str(world))
    assert second["cache"]["state"] == "rebuilt"
    assert (identifier in second["icons"]) is (pack_kind == "declared")


def test_catalog_replacement_during_scan_cannot_mix_item_rules(tmp_path, monkeypatch):
    from mcbe_editor import icon_pack_resolution, item_data

    identifier = "minecraft:icon_regression_future_item"
    _, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/icon_regression_future_item.png": b"new item"})
    world = _world(tmp_path, "world", [rp])
    original = icon_pack_resolution.resolve_pack_icons

    def replace_catalog(sources):
        monkeypatch.setattr(item_data, "ITEMS", {**item_data.ITEMS, identifier: ("New item", "New item")})
        return original(sources)

    monkeypatch.setattr(icon_pack_resolution, "resolve_pack_icons", replace_catalog)
    first, reader = _scan(tmp_path, world)
    assert identifier not in first["icons"]
    second = routes.icons_status(reader, world_path=str(world))
    assert second["cache"]["state"] == "rebuilt"
    assert identifier in second["icons"]


@pytest.mark.parametrize("fresh_worker", [False, True])
def test_readonly_rejects_publication_from_a_different_item_catalog(tmp_path, monkeypatch, fresh_worker):
    from mcbe_editor import item_data

    _, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"apple"})
    world = _world(tmp_path, "world", [rp])
    _, reader = _scan(tmp_path, world)
    monkeypatch.setattr(item_data, "BLOCK_ITEM_IDS", item_data.BLOCK_ITEM_IDS | {"minecraft:apple"})
    if fresh_worker:
        reader = _deps(tmp_path)
    reader.read_only = True
    result = routes.icons_status(reader, world_path=str(world))
    assert not result["icons"]
    assert result["warnings"]
