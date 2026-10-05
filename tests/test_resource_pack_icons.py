"""Pack selection and icon bindings use synthetic, non-playable fixtures."""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from uuid import uuid4

import pytest

from mcbe_editor import icon_api_routes as routes
from mcbe_editor import icons
from mcbe_editor.resource_packs import select_world_packs
from tests.test_icon_context_regressions import _deps


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("MCBE_ICON_ROOTS", "")
    monkeypatch.setattr(icons, "_default_roots", lambda: [])
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [])


def _pack(root, name, files, *, kind="resources", pack_id=None, version=None, archive=False, subpacks=None):
    pack_id, version = pack_id or str(uuid4()), version or [1, 0, 0]
    path = root / (name + ".mcpack" if archive else name)
    manifest = {
        "format_version": 2,
        "header": {"uuid": pack_id, "version": version, "name": name},
        "modules": [{"type": kind, "uuid": str(uuid4()), "version": version}],
    }
    if subpacks is not None:
        manifest["subpacks"] = subpacks
    files = {"manifest.json": manifest, **files}
    raw_files = {key: value if isinstance(value, bytes) else json.dumps(value).encode() for key, value in files.items()}
    root.mkdir(parents=True, exist_ok=True)
    if archive:
        with zipfile.ZipFile(path, "w") as zf:
            for key, value in raw_files.items():
                zf.writestr("pack/" + key, value)
    else:
        for key, value in raw_files.items():
            file = path / key
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(value)
    return path, {"pack_id": pack_id, "version": version}


def _world(root, name, resources=(), behaviors=()):
    world = root / "worlds" / name
    world.mkdir(parents=True, exist_ok=True)
    for kind, registrations in (("resource", resources), ("behavior", behaviors)):
        (world / f"world_{kind}_packs.json").write_text(json.dumps(list(registrations)), encoding="utf-8")
    return world


def _item(identifier="demo:wrench", key="demo:tool"):
    return {
        "format_version": "1.21.0",
        "minecraft:item": {
            "description": {"identifier": identifier},
            "components": {"minecraft:icon": {"textures": {"default": key}}},
        },
    }


def _scan(root, world):
    worker = _deps(root)
    public = routes.icons_scan({"world_path": str(world)}, worker)
    assert public["success"] is True
    return public, worker


def _bytes(worker, item):
    index = worker.get_icon_index()
    return index["_by_token"][index["icons"][item]["token"]].read_bytes()


@pytest.mark.parametrize("archive", [False, True])
def test_declared_namespaced_item_resolves_renamed_png_through_both_packs(tmp_path, archive):
    _, rp = _pack(
        tmp_path / "resource_packs",
        "resources",
        {
            "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/custom/renamed_icon"}}},
            "textures/custom/renamed_icon.png": b"wrench icon",
        },
        archive=archive,
    )
    _, bp = _pack(tmp_path / "behavior_packs", "behavior", {"items/tool.json": _item()}, kind="data", archive=archive)
    world = _world(tmp_path, "active", [rp], [bp])
    public, worker = _scan(tmp_path, world)
    assert _bytes(worker, "demo:wrench") == b"wrench icon"
    assert "minecraft:renamed_icon" not in public["icons"]
    assert public["warnings"] == []
    cached = routes.icons_status(_deps(tmp_path), world_path=str(world))
    assert cached["icons"] == public["icons"]
    assert cached["cache"]["state"] == "hit"


def test_inactive_installed_packs_cannot_override_active_or_vanilla_world(tmp_path, monkeypatch):
    _, active = _pack(tmp_path / "resource_packs", "active", {"textures/items/apple.png": b"active"})
    _pack(tmp_path / "resource_packs", "inactive", {"textures/items/apple.png": b"inactive", "textures/items/carrot.png": b"inactive"})
    monkeypatch.setattr(icons, "_default_roots", lambda: [tmp_path])
    world = _world(tmp_path, "with_pack", [active])
    public, worker = _scan(tmp_path, world)
    assert _bytes(worker, "minecraft:apple") == b"active"
    assert "minecraft:carrot" not in public["icons"]
    plain, _ = _scan(tmp_path, _world(tmp_path, "plain"))
    assert plain["icons"] == {}


@pytest.mark.parametrize("atlas_override", [False, True])
def test_stack_merges_atlas_and_images_independently_and_honors_priority(tmp_path, atlas_override):
    _, base = _pack(
        tmp_path / "resource_packs",
        "base",
        {
            "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/items/a"}}},
            "textures/items/a.png": b"base",
            "textures/items/b.png": b"remapped",
        },
    )
    override_files = (
        {"textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/items/b"}}}}
        if atlas_override
        else {"textures/items/a.png": b"override"}
    )
    _, top = _pack(tmp_path / "resource_packs", "top", override_files)
    _, bp = _pack(tmp_path / "behavior_packs", "behavior", {"items/tool.json": _item()}, kind="data")
    a = _world(tmp_path, "a", [top, base], [bp])
    b = _world(tmp_path, "b", [base, top], [bp])
    public_a, worker_a = _scan(tmp_path, a)
    public_b, worker_b = _scan(tmp_path, b)
    assert _bytes(worker_a, "demo:wrench") == (b"remapped" if atlas_override else b"override")
    assert _bytes(worker_b, "demo:wrench") == b"base"
    assert public_a["icons"] != public_b["icons"]


@pytest.mark.parametrize("with_pack", [False, True])
def test_four_worlds_with_identical_sources_share_one_publication_and_readonly_access(tmp_path, monkeypatch, with_pack):
    vanilla = tmp_path / "vanilla"
    png = vanilla / "textures/items/apple.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"vanilla")
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [vanilla])
    _, rp = _pack(tmp_path / "resource_packs", "shared", {"textures/items/apple.png": b"pack"})
    worlds = [_world(tmp_path, str(i), [rp] if with_pack else []) for i in range(4)]
    first, worker = _scan(tmp_path, worlds[0])
    for world in worlds[1:]:
        readonly = _deps(tmp_path)
        readonly.read_only = True
        public = routes.icons_status(readonly, world_path=str(world))
        assert public["icons"] == first["icons"]
        assert public["cache"]["state"] == "hit"
    assert len(icons._context_cache_files(icons._cache_file(worker.settings_path))) == 1


def test_pack_file_changes_invalidate_index_without_world_or_root_mtime_change(tmp_path):
    path, rp = _pack(tmp_path / "resource_packs", "pack", {"textures/items/apple.png": b"one"})
    world = _world(tmp_path, "world", [rp])
    first, worker = _scan(tmp_path, world)
    (path / "textures/items/apple.png").write_bytes(b"changed")
    second = routes.icons_status(worker, world_path=str(world))
    assert second["cache"]["state"] == "rebuilt"
    assert second["icons"] != first["icons"]
    assert _bytes(worker, "minecraft:apple") == b"changed"


@pytest.mark.parametrize("fault", ["missing", "version", "duplicate", "invalid_list", "subpack"])
def test_unresolved_activation_is_reported_and_does_not_import_unrelated_packs(tmp_path, fault):
    _, rp = _pack(
        tmp_path / "resource_packs",
        "pack",
        {"textures/items/apple.png": b"wrong"},
        subpacks=[{"folder_name": "variant", "memory_tier": 1}] if fault == "subpack" else None,
    )
    if fault == "missing":
        rp = {**rp, "pack_id": str(uuid4())}
    if fault == "version":
        rp = {**rp, "version": [9, 0, 0]}
    if fault == "duplicate":
        _pack(tmp_path / "resource_packs", "duplicate", {"textures/items/apple.png": b"other"}, pack_id=rp["pack_id"])
    world = _world(tmp_path, "world", [rp])
    if fault == "invalid_list":
        (world / "world_resource_packs.json").write_text("{ broken", encoding="utf-8")
    public, _ = _scan(tmp_path, world)
    assert public["warnings"]
    assert public["icons"] == {}


@pytest.mark.parametrize("archive", [False, True])
def test_explicit_subpack_uses_only_selected_variant(tmp_path, archive):
    _, rp = _pack(
        tmp_path / "resource_packs",
        "pack",
        {
            "textures/items/apple.png": b"base",
            "subpacks/one/textures/items/apple.png": b"one",
            "subpacks/two/textures/items/apple.png": b"two",
        },
        archive=archive,
        subpacks=[{"folder_name": "one"}, {"folder_name": "two"}],
    )
    first, one = _scan(tmp_path, _world(tmp_path, "one", [{**rp, "subpack": "one"}]))
    second, two = _scan(tmp_path, _world(tmp_path, "two", [{**rp, "subpack": "two"}]))
    assert _bytes(one, "minecraft:apple") == b"one"
    assert _bytes(two, "minecraft:apple") == b"two"
    assert first["icons"] != second["icons"]


@pytest.mark.parametrize("reference", ["../outside", "/absolute", "C:/absolute", ["textures/items/a", "textures/items/b"], "textures/items/missing"])
def test_unsafe_missing_or_variant_texture_is_reported_without_filename_guess(tmp_path, reference):
    _, rp = _pack(
        tmp_path / "resource_packs",
        "pack",
        {
            "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": reference}}},
            "textures/items/a.png": b"a",
            "textures/items/b.png": b"b",
            "textures/items/wrench.png": b"guess",
        },
    )
    _, bp = _pack(tmp_path / "behavior_packs", "behavior", {"items/tool.json": _item()}, kind="data")
    public, _ = _scan(tmp_path, _world(tmp_path, "world", [rp], [bp]))
    assert "demo:wrench" not in public["icons"]
    assert any("demo:wrench" in warning for warning in public["warnings"])


def test_selection_diagnostics_do_not_contaminate_shared_vanilla_index(tmp_path):
    missing = _world(tmp_path, "missing", [{"pack_id": str(uuid4()), "version": [1, 0, 0]}])
    plain = _world(tmp_path, "plain")
    bad, _ = _scan(tmp_path, missing)
    good, _ = _scan(tmp_path, plain)
    assert bad["warnings"]
    assert not good["warnings"]
    assert bad["cache"]["path"] == good["cache"]["path"]


def test_pack_list_is_read_only_and_missing_lists_select_vanilla(tmp_path):
    world = tmp_path / "world"
    world.mkdir()
    before = list(world.iterdir())
    assert select_world_packs(str(world)).sources == []
    assert list(world.iterdir()) == before


def test_shared_publication_and_custom_item_work_through_http_on_fresh_worker(tmp_path, monkeypatch):
    import main

    _, rp = _pack(
        tmp_path / "resource_packs",
        "rp",
        {
            "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/icons/file"}}},
            "textures/icons/file.png": b"custom icon",
        },
    )
    _, bp = _pack(tmp_path / "behavior_packs", "bp", {"items/tool.json": _item()}, kind="data")
    world = _world(tmp_path, "world", [rp], [bp])
    public, publisher = _scan(tmp_path, world)
    reader = _deps(tmp_path)
    deps = replace(
        main.icon_route_deps(),
        settings_path=publisher.settings_path,
        data_root=publisher.data_root,
        get_icon_index=reader.get_icon_index,
        set_icon_index=reader.set_icon_index,
        read_only=True,
    )
    monkeypatch.setattr(main, "icon_route_deps", lambda: deps)
    client = main.app.test_client()
    assert client.get(public["icons"]["demo:wrench"]["url"]).data == b"custom icon"
    assert client.get("/api/icons/status", query_string={"world_path": str(world)}).get_json()["icons"] == public["icons"]


def _vanilla(root, monkeypatch):
    path = root / "vanilla"
    image = path / "textures/items/apple.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"vanilla apple")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "items": {"minecraft:apple": "items/actual_apple"},
                "item_texture_data": {"fruit_icon": ["items/actual_apple"]},
                "item_icon_definitions": {"apple": {"texture": "fruit_icon"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [path])
    return path


def test_rp_can_redirect_vanilla_atlas_key_without_item_definition(tmp_path, monkeypatch):
    _vanilla(tmp_path, monkeypatch)
    _, rp = _pack(
        tmp_path / "resource_packs",
        "rp",
        {
            "textures/item_texture.json": {"texture_data": {"fruit_icon": {"textures": "textures/custom/fruit"}}},
            "textures/custom/fruit.png": b"new apple",
        },
    )
    public, worker = _scan(tmp_path, _world(tmp_path, "world", [rp]))
    assert _bytes(worker, "minecraft:apple") == b"new apple"
    assert not public["warnings"]


def test_custom_item_can_reference_an_existing_vanilla_sprite(tmp_path, monkeypatch):
    _vanilla(tmp_path, monkeypatch)
    _, rp = _pack(
        tmp_path / "resource_packs",
        "rp",
        {
            "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/items/actual_apple"}}},
        },
    )
    _, bp = _pack(tmp_path / "behavior_packs", "bp", {"items/tool.json": _item()}, kind="data")
    public, worker = _scan(tmp_path, _world(tmp_path, "world", [rp], [bp]))
    assert _bytes(worker, "demo:wrench") == b"vanilla apple"
    assert not public["warnings"]


def test_new_vanilla_world_uses_cache_without_scanning_again(tmp_path, monkeypatch):
    _vanilla(tmp_path, monkeypatch)
    world_a, world_b = _world(tmp_path, "a"), _world(tmp_path, "b")
    first, _ = _scan(tmp_path, world_a)
    monkeypatch.setattr(icons, "_scan_directory", lambda *a, **kw: pytest.fail("Shared Vanilla must not be scanned again"))
    second = routes.icons_status(_deps(tmp_path), world_path=str(world_b))
    assert first["icons"] == second["icons"]
    assert second["cache"]["state"] == "hit"


def test_declared_texture_alias_survives_cache_roundtrip_and_file_size_checks(tmp_path, monkeypatch):
    _, rp = _pack(
        tmp_path / "resource_packs",
        "rp",
        {
            "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/custom/tool"}}},
            "textures/custom/tool.png": b"small",
        },
        archive=True,
    )
    _, bp = _pack(tmp_path / "behavior_packs", "bp", {"items/tool.json": _item()}, kind="data")
    world = _world(tmp_path, "world", [rp], [bp])
    _, worker = _scan(tmp_path, world)
    cached = icons.load_cached_icon_index(worker.settings_path, context_id=worker.get_icon_index()["_context_id"])
    candidate = cached["_by_token"][cached["icons"]["demo:wrench"]["token"]]
    assert candidate.read_bytes() == b"small"
    monkeypatch.setattr(icons, "_MAX_FILE_BYTES", 2)
    with pytest.raises(ValueError):
        candidate.read_bytes()


def test_json_comments_are_supported_but_duplicate_keys_are_rejected(tmp_path):
    path, rp = _pack(
        tmp_path / "resource_packs",
        "pack",
        {
            "textures/item_texture.json": b'{/* comment */ "texture_data":{"apple":{"textures":"textures/items/apple"}}}',
            "textures/items/apple.png": b"apple",
        },
    )
    world = _world(tmp_path, "world", [rp])
    public, worker = _scan(tmp_path, world)
    assert _bytes(worker, "minecraft:apple") == b"apple"
    assert not public["warnings"]
    (path / "textures/item_texture.json").write_bytes(b'{"texture_data":{},"texture_data":{}}')
    public, _ = _scan(tmp_path, world)
    assert public["warnings"]
    assert public["icons"] == {}


def test_same_explicit_and_active_pack_is_one_source(tmp_path):
    path, rp = _pack(tmp_path / "resource_packs", "pack", {"textures/items/apple.png": b"apple"})
    worker = _deps(tmp_path)
    icons.add_icon_source(worker.settings_path, str(path))
    plain = routes.icons_status(worker, world_path=str(_world(tmp_path, "plain")))
    active = routes.icons_status(worker, world_path=str(_world(tmp_path, "active", [rp])))
    assert plain["icons"] == active["icons"]
    assert plain["cache"]["path"] == active["cache"]["path"]
    assert len(active["sources"]) == 1


def test_custom_block_materials_report_the_standard_preview_limit(tmp_path, monkeypatch):
    _vanilla(tmp_path, monkeypatch)
    _, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/blocks/stone.png": b"block material"})
    public, _ = _scan(tmp_path, _world(tmp_path, "world", [rp]))
    assert any("Blockmaterial" in warning for warning in public["warnings"])


def test_nested_item_definition_and_json_only_changes_refresh_on_another_worker(tmp_path):
    path, rp = _pack(
        tmp_path / "resource_packs",
        "rp",
        {
            "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/custom/a"}}},
            "textures/custom/a.png": b"a",
            "textures/custom/b.png": b"b",
        },
    )
    bp_path, bp = _pack(tmp_path / "behavior_packs", "bp", {"items/tools/wrench.json": _item()}, kind="data")
    world = _world(tmp_path, "world", [rp], [bp])
    _scan(tmp_path, world)
    (path / "textures/item_texture.json").write_text(json.dumps({"texture_data": {"demo:tool": {"textures": "textures/custom/b"}}}))
    reader = _deps(tmp_path)
    assert routes.icons_status(reader, world_path=str(world))["cache"]["state"] == "rebuilt"
    assert _bytes(reader, "demo:wrench") == b"b"
    (bp_path / "items/tools/wrench.json").write_text(json.dumps(_item(identifier="demo:hammer")))
    result = routes.icons_status(reader, world_path=str(world))
    assert "demo:wrench" not in result["icons"]
    assert _bytes(reader, "demo:hammer") == b"b"


def test_pack_reorder_and_deactivation_select_profiles_without_forced_scan(tmp_path):
    _, a = _pack(tmp_path / "resource_packs", "a", {"textures/items/apple.png": b"a"})
    _, b = _pack(tmp_path / "resource_packs", "b", {"textures/items/apple.png": b"b"})
    world = _world(tmp_path, "world", [a, b])
    _, reader = _scan(tmp_path, world)
    listing = world / "world_resource_packs.json"
    listing.write_text(json.dumps([b, a]))
    routes.icons_status(reader, world_path=str(world))
    assert _bytes(reader, "minecraft:apple") == b"b"
    listing.write_text("[]")
    assert not routes.icons_status(reader, world_path=str(world))["icons"]
    listing.write_text(json.dumps([a, b]))
    assert routes.icons_status(reader, world_path=str(world))["cache"]["state"] == "hit"
    assert _bytes(reader, "minecraft:apple") == b"a"


def test_readonly_rejects_stale_worker_index_and_writes_nothing(tmp_path):
    path, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"apple"})
    world = _world(tmp_path, "world", [rp])
    _, reader = _scan(tmp_path, world)
    reader.read_only = True
    (path / "textures/items/apple.png").write_bytes(b"changed")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    result = routes.icons_status(reader, world_path=str(world))
    assert not result["icons"]
    assert result["warnings"]
    assert not reader.get_icon_index()["icons"]
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}


def test_pack_mutation_during_resolution_cannot_publish_index(tmp_path, monkeypatch):
    from mcbe_editor import icon_pack_resolution

    path, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"apple"})
    world = _world(tmp_path, "world", [rp])
    reader = _deps(tmp_path)
    original = icon_pack_resolution.resolve_pack_icons

    def replacing(sources):
        result = original(sources)
        (path / "textures/items/apple.png").write_bytes(b"replaced")
        return result

    monkeypatch.setattr(icon_pack_resolution, "resolve_pack_icons", replacing)
    result = routes.icons_scan({"world_path": str(world)}, reader)
    assert result["success"] is False
    assert "während des Einlesens" in result["error"]
    assert not icons._cache_file(reader.settings_path).exists()
    assert not icons._context_cache_files(icons._cache_file(reader.settings_path))


def test_pack_identity_change_between_selection_and_scan_is_reported(tmp_path):
    path, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"apple"})
    world = _world(tmp_path, "world", [rp])
    sources = select_world_packs(str(world)).sources
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["header"]["version"] = [2, 0, 0]
    manifest_path.write_text(json.dumps(manifest))
    result = icons.scan_icons(str(tmp_path / "sources.json"), extra_sources=sources)
    assert not result["icons"]
    assert any("Version" in warning for warning in result["warnings"])


@pytest.mark.parametrize("fault", ["traversal", "duplicate", "oversize", "invalid_uuid"])
def test_invalid_pack_data_is_rejected_with_diagnostics(tmp_path, monkeypatch, fault):
    from mcbe_editor import resource_packs

    files = {"textures/items/apple.png": b"apple"}
    if fault == "invalid_uuid":
        files["manifest.json"] = {"header": {"uuid": 2, "version": [1, 0, 0]}, "modules": [{"type": "resources"}]}
    path, rp = _pack(tmp_path / "resource_packs", "rp", files, archive=True)
    with zipfile.ZipFile(path, "a") as zf:
        if fault == "traversal":
            zf.writestr("pack/../outside.png", b"outside")
        elif fault == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                zf.writestr("pack/textures/items/apple.png", b"duplicate")
        elif fault == "oversize":
            monkeypatch.setattr(resource_packs, "MAX_METADATA_BYTES", 800)
            zf.writestr("pack/textures/item_texture.json", b" " * 900)
    result, _ = _scan(tmp_path, _world(tmp_path, "world", [rp]))
    assert not result["icons"]
    assert result["warnings"]


@pytest.mark.parametrize("fault", ["metadata", "subpack"])
def test_explicit_pack_with_unusable_manifest_does_not_revert_to_filename_guess(tmp_path, fault):
    path, _ = _pack(
        tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"wrong"}, subpacks=[{"folder_name": "variant"}] if fault == "subpack" else None
    )
    if fault == "metadata":
        (path / "manifest.json").write_text("{ broken")
    reader = _deps(tmp_path)
    icons.add_icon_source(reader.settings_path, str(path))
    result = routes.icons_status(reader, world_path=str(_world(tmp_path, "world")))
    assert not result["icons"]
    assert result["warnings"]


def test_old_vanilla_binding_metadata_gets_an_update_hint(tmp_path, monkeypatch):
    vanilla = _vanilla(tmp_path, monkeypatch)
    (vanilla / "manifest.json").write_text(json.dumps({"items": {"minecraft:apple": "items/actual_apple"}}))
    _, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/actual_apple.png": b"override"})
    result, reader = _scan(tmp_path, _world(tmp_path, "world", [rp]))
    assert _bytes(reader, "minecraft:apple") == b"override"
    assert any("Vanilla-Icons aktualisieren" in warning for warning in result["warnings"])


@pytest.mark.parametrize("key,path", [("missing", None), ("model", "textures/entity/tool")])
def test_unsupported_definition_uses_standard_icon_and_reports_reason(tmp_path, monkeypatch, key, path):
    _vanilla(tmp_path, monkeypatch)
    files = {"textures/item_texture.json": {"texture_data": {key: {"textures": path}}}} if path else {}
    if path:
        files[path + ".png"] = b"raw model atlas"
    _, rp = _pack(tmp_path / "resource_packs", "rp", files)
    _, bp = _pack(tmp_path / "behavior_packs", "bp", {"items/apple.json": _item("minecraft:apple", key)}, kind="data")
    result, reader = _scan(tmp_path, _world(tmp_path, "world", [rp], [bp]))
    assert _bytes(reader, "minecraft:apple") == b"vanilla apple"
    assert any("minecraft:apple" in warning for warning in result["warnings"])


def test_atomic_image_replacement_with_retained_times_changes_browser_url(tmp_path):
    import os

    path, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"first"})
    world = _world(tmp_path, "world", [rp])
    first, reader = _scan(tmp_path, world)
    image = path / "textures/items/apple.png"
    before = image.stat()
    replacement = path / "replacement.png"
    replacement.write_bytes(b"other")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, image)
    second = routes.icons_status(reader, world_path=str(world))
    assert second["icons"]["minecraft:apple"]["url"] != first["icons"]["minecraft:apple"]["url"]
    assert _bytes(reader, "minecraft:apple") == b"other"


@pytest.mark.parametrize("member", ["manifest.json", "textures/item_texture.json"])
@pytest.mark.parametrize("compression", [zipfile.ZIP_DEFLATED, zipfile.ZIP_LZMA])
def test_corrupt_compressed_metadata_is_reported_without_crashing(tmp_path, member, compression):
    import struct

    if compression == zipfile.ZIP_LZMA:
        pytest.importorskip("lzma")
    path, rp = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"apple"})
    archive = path.parent / "compressed.mcpack"
    files = {file.relative_to(path).as_posix(): file.read_bytes() for file in path.rglob("*") if file.is_file()}
    if member not in files:
        files[member] = b'{"texture_data":{}}'
    with zipfile.ZipFile(archive, "w", compression=compression) as zf:
        for name, raw in files.items():
            zf.writestr(name, raw)
    with zipfile.ZipFile(archive) as zf:
        offset = zf.getinfo(member).header_offset
    raw = bytearray(archive.read_bytes())
    name, extra = struct.unpack_from("<HH", raw, offset + 26)
    data_offset = offset + 30 + name + extra
    if compression == zipfile.ZIP_DEFLATED:
        raw[data_offset] = 7
    else:
        raw[data_offset + 4] ^= 0xFF
    archive.write_bytes(raw)
    # Use just the corrupt archive as a world-local pack candidate.
    world = _world(tmp_path, "world", [rp])
    target = world / "resource_packs"
    target.mkdir()
    archive.replace(target / archive.name)
    if member == "manifest.json":
        # No valid shared copy may satisfy the intentionally broken activation.
        (path / "manifest.json").unlink()
    result, _ = _scan(tmp_path, world)
    assert not result["icons"]
    assert result["warnings"]


def test_oversized_higher_priority_image_cannot_silently_use_lower_pack_image(tmp_path, monkeypatch):
    _, base = _pack(tmp_path / "resource_packs", "base", {"textures/items/apple.png": b"small"})
    _, top = _pack(tmp_path / "resource_packs", "top", {"textures/items/apple.png": b"too big for this test"})
    monkeypatch.setattr(icons, "_MAX_FILE_BYTES", 10)
    result, _ = _scan(tmp_path, _world(tmp_path, "world", [top, base]))
    assert not result["icons"]
    assert any("minecraft:apple" in warning and "zu groß" in warning for warning in result["warnings"])


def test_disabled_global_pack_does_not_walk_pack_files_or_resolve_textures(tmp_path, monkeypatch):
    from mcbe_editor import icon_pack_resolution, resource_packs

    _vanilla(tmp_path, monkeypatch)
    path, _ = _pack(tmp_path / "resource_packs", "rp", {"textures/items/apple.png": b"inactive"})
    reader = _deps(tmp_path)
    icons.add_icon_source(reader.settings_path, str(path))
    icons.set_icon_source_enabled(reader.settings_path, str(path), False)
    monkeypatch.setattr(resource_packs, "PackReader", lambda *a, **kw: pytest.fail("Disabled pack files must not be walked"))
    monkeypatch.setattr(icon_pack_resolution, "resolve_pack_icons", lambda *a: pytest.fail("No active pack to resolve"))
    result = routes.icons_status(reader, world_path=str(_world(tmp_path, "world")))
    assert _bytes(reader, "minecraft:apple") == b"vanilla apple"
    assert not result["warnings"]
