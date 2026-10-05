"""Icon diagnostics stay consistent across languages, workers and cache formats."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from flask import Flask

from mcbe_editor import icon_api_routes as routes
from mcbe_editor import icons, resource_packs
from tests.node_runner import run_node
from tests.test_icon_context_regressions import _deps
from tests.test_resource_pack_icons import _item, _pack, _world


@pytest.fixture(autouse=True)
def isolated_sources(monkeypatch):
    monkeypatch.setenv("MCBE_ICON_ROOTS", "")
    monkeypatch.setattr(icons, "_default_roots", lambda: [])
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [])


def problem_world(root):
    _, registration = _pack(root / "resource_packs", "synthetic-pack", {
        "textures/item_texture.json": {"texture_data": {"apple": {"textures": "textures/items/missing"}}},
        "textures/items/carrot.png": b"synthetic carrot",
    })
    return _world(root, "world", [registration])


def test_pack_warnings_agree_with_source_and_overall_status_on_cache_hit(tmp_path):
    world = problem_world(tmp_path)
    scanned = routes.icons_scan({"world_path": str(world)}, _deps(tmp_path))
    cached = routes.icons_status(_deps(tmp_path), world_path=str(world))
    assert cached["cache"]["state"] == "hit"
    for result in (scanned, cached):
        assert "minecraft:carrot" in result["icons"]
        assert len(result["warnings"]) == result["health"]["warning_count"] == 1
        assert result["health"]["status"] == result["sources"][0]["status"] == "warning"
        assert result["sources"][0]["warning_count"] == 1
        assert not any(key.startswith("_") for key in result)


def test_selection_warning_count_is_request_local(tmp_path):
    missing = _world(tmp_path, "missing", [{"pack_id": str(uuid4()), "version": [1, 0, 0]}])
    clean = _world(tmp_path, "clean")
    worker = _deps(tmp_path)
    result = routes.icons_status(worker, world_path=str(missing))
    assert len(result["warnings"]) == result["health"]["warning_count"] == 1
    assert not worker.get_icon_index()["warnings"]
    result = routes.icons_status(worker, world_path=str(clean))
    assert result["cache"]["state"] == "hit"
    assert result["health"]["warning_count"] == 0
    assert result["warnings"] == []


@pytest.mark.parametrize("problem", ["definition", "atlas", "asset"])
def test_cross_pack_warning_belongs_to_the_responsible_source(tmp_path, problem):
    files = {
        "textures/item_texture.json": {"texture_data": {"demo:tool": {"textures": "textures/items/tool"}}},
        "textures/items/carrot.png": b"synthetic carrot",
    }
    if problem != "atlas":
        files["textures/items/tool.png"] = b"synthetic tool"
    mapping, rp = _pack(tmp_path / "resource_packs", "mapping", files)
    override, top = _pack(tmp_path / "resource_packs", "override", {
        "textures/items/tool.png": b"",
    } if problem == "asset" else {})
    item = _item()
    if problem == "definition":
        item["minecraft:item"]["components"] = {}
    behavior, bp = _pack(tmp_path / "behavior_packs", "behavior", {"items/tool.json": item}, kind="data")
    world = _world(tmp_path, "stack", [top, rp], [bp])
    expected = {"definition": behavior, "atlas": mapping, "asset": override}[problem]
    scanned = routes.icons_scan({"world_path": str(world)}, _deps(tmp_path))
    cached = routes.icons_status(_deps(tmp_path), world_path=str(world))
    assert cached["cache"]["state"] == "hit"
    for result in (scanned, cached):
        assert "minecraft:carrot" in result["icons"]
        assert len(result["warnings"]) == result["health"]["warning_count"] == 1
        assert result["health"]["status"] == "warning"
        for source in result["sources"]:
            affected = Path(source["path"]) == expected
            assert source["warning_count"] == int(affected)
            assert source["status"] == ("warning" if affected else "ok")


@pytest.mark.parametrize("first_language,second_language", [("de", "en"), ("en", "de")])
@pytest.mark.parametrize("read_only", [False, True])
def test_cached_warnings_follow_request_language_without_rescan(tmp_path, monkeypatch, first_language, second_language, read_only):
    app = Flask(__name__)
    world = problem_world(tmp_path)
    with app.test_request_context(headers={"Accept-Language": first_language}):
        first = routes.icons_scan({"world_path": str(world)}, _deps(tmp_path))
    cache = Path(first["cache"]["path"])
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert stored["warnings"][0].startswith("Icon für")
    assert stored["warning_records"][0]["message_params"]["reason"]["message_key"] == "deklarierte Bilddatei fehlt"
    before = cache.read_bytes(), cache.stat().st_mtime_ns
    reader = _deps(tmp_path)
    reader.read_only = read_only
    monkeypatch.setattr("mcbe_editor.icon_pack_resolution.resolve_pack_icons", lambda *_: pytest.fail("Unexpected rebuild"))
    with app.test_request_context(headers={"Accept-Language": second_language}):
        second = routes.icons_status(reader, world_path=str(world))
    assert second["cache"]["state"] == "hit"
    assert second["icons"] == first["icons"]
    assert second["warnings"] != first["warnings"]
    assert ("declared image file is missing" if second_language == "en" else "deklarierte Bilddatei fehlt") in second["warnings"][0]
    assert (cache.read_bytes(), cache.stat().st_mtime_ns) == before
    # The sources endpoint also localizes an already loaded worker index.
    with app.test_request_context(headers={"Accept-Language": first_language}):
        assert routes.icons_sources(reader)["warnings"] == first["warnings"]


def test_manual_pack_validation_details_remain_translatable(tmp_path):
    path, _ = _pack(tmp_path, "invalid-pack", {"manifest.json": b'{"header":{},"header":{}}'})
    worker = _deps(tmp_path)
    icons.add_icon_source(worker.settings_path, str(path))
    app = Flask(__name__)
    with app.test_request_context(headers={"Accept-Language": "en"}):
        first = routes.icons_scan({}, worker)
    with app.test_request_context(headers={"Accept-Language": "de"}):
        second = routes.icons_status(_deps(tmp_path), world_path="")
        configured = routes.icons_sources(worker)["configured_sources"]
    assert second["cache"]["state"] == "hit"
    assert "duplicate key: header" in first["warnings"][0]
    assert "mehrfach belegten Schlüssel: header" in second["warnings"][0]
    assert second["sources"][0]["status"] == "warning"
    assert isinstance(configured[0]["pack_error"], str)
    assert "mehrfach belegten Schlüssel: header" in configured[0]["pack_error"]


def test_old_diagnostics_remain_readable_and_upgrade_only_with_write_access(tmp_path):
    world = problem_world(tmp_path)
    first = routes.icons_scan({"world_path": str(world)}, _deps(tmp_path))
    cache = Path(first["cache"]["path"])
    stored = json.loads(cache.read_text(encoding="utf-8"))
    del stored["warning_records"]
    cache.write_text(json.dumps(stored), encoding="utf-8")
    before = cache.read_bytes(), cache.stat().st_mtime_ns
    reader = _deps(tmp_path)
    reader.read_only = True
    with patch.object(routes, "scan_icons", side_effect=AssertionError("Read-only scan")):
        legacy = routes.icons_status(reader, world_path=str(world))
    assert legacy["icons"] == first["icons"]
    assert legacy["warnings"][:-1] == first["warnings"]
    assert "Schreibzugriff" in legacy["warnings"][-1]
    assert legacy["health"]["warning_count"] == len(legacy["warnings"])
    assert (cache.read_bytes(), cache.stat().st_mtime_ns) == before
    updated = routes.icons_status(_deps(tmp_path), world_path=str(world))
    assert updated["cache"]["state"] == "rebuilt"
    assert updated["icons"] == first["icons"]
    assert json.loads(cache.read_text(encoding="utf-8"))["warning_records"]
    assert routes.icons_status(_deps(tmp_path), world_path=str(world))["cache"]["state"] == "hit"


def test_legacy_index_without_warnings_stays_a_cache_hit(tmp_path, monkeypatch):
    _, registration = _pack(tmp_path / "resource_packs", "healthy", {"textures/items/apple.png": b"synthetic apple"})
    world = _world(tmp_path, "healthy", [registration])
    first = routes.icons_scan({"world_path": str(world)}, _deps(tmp_path))
    cache = Path(first["cache"]["path"])
    stored = json.loads(cache.read_text(encoding="utf-8"))
    del stored["warning_records"]
    cache.write_text(json.dumps(stored), encoding="utf-8")
    before = cache.read_bytes(), cache.stat().st_mtime_ns
    monkeypatch.setattr("mcbe_editor.icon_pack_resolution.resolve_pack_icons", lambda *_: pytest.fail("Unexpected rebuild"))
    cached = routes.icons_status(_deps(tmp_path), world_path=str(world))
    assert cached["cache"]["state"] == "hit"
    assert cached["icons"] == first["icons"]
    assert cached["warnings"] == []
    assert cached["health"]["status"] == "ok"
    assert (cache.read_bytes(), cache.stat().st_mtime_ns) == before


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("read_only", [False, True])
def test_status_prepares_each_manual_pack_once(tmp_path, archive, read_only):
    pack, _ = _pack(tmp_path, "manual", {"textures/items/apple.png": b"synthetic apple"}, archive=archive)
    worker = _deps(tmp_path)
    icons.add_icon_source(worker.settings_path, str(pack))
    with patch.object(resource_packs, "_manifest", wraps=resource_packs._manifest) as manifests:
        first = routes.icons_scan({}, worker)
    assert manifests.call_count == 1
    worker.read_only = read_only
    with patch.object(resource_packs, "_manifest", wraps=resource_packs._manifest) as manifests:
        cached = routes.icons_status(worker, world_path="")
    assert manifests.call_count == 1
    assert cached["cache"]["state"] == "hit"
    assert cached["icons"] == first["icons"]


def test_icon_manager_reports_partial_success_and_retains_empty_states():
    run_node(r'''
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const context = {window: {}};
        vm.runInNewContext(fs.readFileSync("static/icon_manager_view.js", "utf8"), context);
        const render = context.window.MCBEIconManagerView.iconManagerHtml;
        for (const summary of [
            {count: 1, warnings: ["missing texture"]},
            {count: 1, health: {status: "warning"}},
        ]) assert.ok(render(summary).includes("bereit mit Einschränkungen"));
        const healthy = render({count: 1, health: {status: "ok"}});
        assert.ok(healthy.includes(">bereit<"));
        assert.ok(!healthy.includes("bereit mit Einschränkungen"));
        assert.ok(render({count: 0, health: {enabled_sources: 1}}).includes("keine Treffer"));
        assert.ok(render({count: 0}).includes("Fallback aktiv"));
    ''')
