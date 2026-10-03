"""Catalog updates publish data without replacing executable modules or active reads."""

from __future__ import annotations

import copy
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mcbe_editor import inventory, item_data, nbt, services
from mcbe_editor.bedrock_nbt import save_player_nbt
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.players import encode_player_key


PROBE_ITEM = "minecraft:catalog_probe"
PROBE_ALIAS = "minecraft:catalog_alias"
PROBE_EFFECT = 100
PROBE_ENCHANTMENT = 100
PLAYER_KEY = encode_player_key(b"~local_player")


@pytest.fixture(autouse=True)
def restore_catalog():
    original = item_data.current_item_catalog()
    try:
        yield
    finally:
        item_data.publish_item_catalog(original)


def write_catalog(path, generation=1):
    raw = {
        "schema_version": 3,
        "behavior_item_source": {
            "resource_pack_release": "v999.0.0",
            "stack_limit_items": [PROBE_ITEM], "durability_items": [PROBE_ITEM],
        },
        "items": {PROBE_ITEM: [f"Gegenstand {generation}", f"Item {generation}"]},
        "addable_items": [PROBE_ITEM],
        "stack_limits": {PROBE_ITEM: generation},
        "durability": {PROBE_ITEM: 100 * generation},
        "compat_item_aliases": {PROBE_ALIAS: PROBE_ITEM},
        "effects": {str(PROBE_EFFECT): [f"Effekt {generation}", f"Effect {generation}", "Beschreibung", "Description"]},
        "enchantments": {str(PROBE_ENCHANTMENT): [f"Zauber {generation}", f"Enchantment {generation}", generation]},
        "item_components": {"enchantable": {PROBE_ITEM: {"slot": "sword", "value": generation}}},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return raw


def make_service(catalog):
    return services.BedrockEditorService(
        catalog["ITEMS"], catalog["ENCHANTMENTS"], db_factory=LevelDbWriter, item_catalog=catalog,
    )


def make_world(path):
    (path / "db").mkdir(parents=True)
    item = nbt.CompoundTag({
        "Name": nbt.StringTag(PROBE_ITEM), "Slot": nbt.ByteTag(0), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0),
        "tag": nbt.CompoundTag({"ench": nbt.ListTag([
            nbt.CompoundTag({"id": nbt.ShortTag(PROBE_ENCHANTMENT), "lvl": nbt.ShortTag(1)}),
        ])}),
    })
    effect = nbt.CompoundTag({
        "Id": nbt.ByteTag(PROBE_EFFECT), "Amplifier": nbt.ByteTag(0), "Duration": nbt.IntTag(200),
    })
    player = nbt.NamedTag(nbt.CompoundTag({
        "Inventory": nbt.ListTag([item]), "ActiveEffects": nbt.ListTag([effect, effect.copy()]),
        "Health": nbt.ShortTag(20), "PlayerGameType": nbt.IntTag(0),
    }))
    db = LevelDbWriter(str(path / "db"))
    try:
        db.put(b"~local_player", save_player_nbt(player))
    finally:
        db.close()
    return str(path)


def test_prepare_has_no_side_effects_and_publication_keeps_code_identity(tmp_path, monkeypatch):
    original = item_data.current_item_catalog()
    before = copy.deepcopy(original)
    functions = (item_data.get_max_stack, inventory.parse_effects, inventory.validate_inventory_item, services.BedrockEditorService)
    path = tmp_path / "catalog.json"
    write_catalog(path)
    monkeypatch.setattr(importlib, "reload", lambda *_: pytest.fail("Catalog updates must not reload code"))

    prepared = item_data.prepare_item_catalog(path)
    assert item_data.current_item_catalog() is original
    assert original == before
    assert PROBE_ITEM not in item_data.ITEMS
    assert prepared["OFFICIAL_ENCHANTMENT_ITEM_SLOTS"][PROBE_ITEM] == {"sword"}
    assert prepared["ENCHANTMENT_COMPATIBILITY"]["official_item_slots"][PROBE_ITEM] == ["sword"]

    item_data.publish_item_catalog(prepared)
    assert item_data.current_item_catalog() is prepared
    assert item_data.get_max_stack(PROBE_ALIAS) == 1
    assert item_data.get_max_damage(PROBE_ALIAS) == 100
    assert item_data.item_component(PROBE_ITEM, "enchantable")["value"] == 1
    assert inventory.EFFECTS is prepared["EFFECTS"]
    assert inventory.ENCHANTMENTS is prepared["ENCHANTMENTS"]
    assert functions == (item_data.get_max_stack, inventory.parse_effects, inventory.validate_inventory_item, services.BedrockEditorService)
    assert original == before


@pytest.mark.parametrize("failure", ["json", "non_object", "components", "compatibility", "derived"])
def test_failed_preparation_keeps_entire_live_catalog(tmp_path, monkeypatch, failure):
    original = item_data.current_item_catalog()
    before = copy.deepcopy(original)
    path = tmp_path / "catalog.json"
    raw = write_catalog(path)
    if failure == "json":
        path.write_text("{broken", encoding="utf-8")
    elif failure == "non_object":
        path.write_text("[]", encoding="utf-8")
    elif failure == "components":
        raw["item_components"]["enchantable"][PROBE_ITEM]["slot"] = "not_a_slot"
        path.write_text(json.dumps(raw), encoding="utf-8")
    elif failure == "compatibility":
        compatibility = tmp_path / "compatibility.json"
        compatibility.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("MCBE_ENCHANTMENT_COMPATIBILITY_PATH", str(compatibility))
    else:
        def fail(_components):
            raise ValueError("derived rules failed")
        monkeypatch.setattr(item_data, "_official_enchantment_slots", fail)
    with pytest.raises(ValueError):
        item_data.reload_item_database(path)
    assert item_data.current_item_catalog() is original
    assert original == before
    assert item_data.ITEMS is original["ITEMS"]
    assert item_data.ENCHANTMENT_COMPATIBILITY is original["ENCHANTMENT_COMPATIBILITY"]
    assert item_data.catalog_values()["ITEMS"] is original["ITEMS"]


def test_repeated_reload_does_not_inherit_optional_defaults(tmp_path):
    path = tmp_path / "catalog.json"
    raw = write_catalog(path)
    raw["defaults"] = {"max_damage": 9999, "max_data_value": 9000}
    path.write_text(json.dumps(raw), encoding="utf-8")
    first = item_data.reload_item_database(path)
    write_catalog(path, generation=2)
    second = item_data.reload_item_database(path)
    assert first["DEFAULT_MAX_DAMAGE"] == 9999
    assert first["MAX_DATA_VALUE"] == 9000
    assert second["DEFAULT_MAX_DAMAGE"] == 1561
    assert second["MAX_DATA_VALUE"] == 32767
    assert first["STACK_LIMITS"][PROBE_ITEM] == 1
    assert second["STACK_LIMITS"][PROBE_ITEM] == 2


def test_nested_context_restores_after_exception_and_legacy_helpers_remain_usable(tmp_path, monkeypatch):
    path = tmp_path / "catalog.json"
    write_catalog(path, 1)
    first = item_data.prepare_item_catalog(path)
    write_catalog(path, 2)
    second = item_data.prepare_item_catalog(path)
    item_data.publish_item_catalog(second)
    with item_data.use_item_catalog(first):
        assert item_data.get_max_stack(PROBE_ALIAS) == 1
        with pytest.raises(RuntimeError), item_data.use_item_catalog(second):
            assert item_data.get_max_stack(PROBE_ALIAS) == 2
            raise RuntimeError("stop")
        assert item_data.get_max_stack(PROBE_ALIAS) == 1
    assert item_data.get_max_stack(PROBE_ALIAS) == 2
    monkeypatch.setattr(item_data, "STACK_LIMITS", {PROBE_ITEM: 3})
    assert item_data.get_max_stack(PROBE_ITEM) == 3
    with item_data.use_item_catalog(second):
        assert item_data.get_max_stack(PROBE_ITEM) == 2
    assert item_data.get_max_stack(PROBE_ITEM) == 3


def assert_generation(result, generation):
    assert result["success"] is True
    assert PROBE_ITEM in result["addable_items"]
    assert PROBE_ITEM in result["item_availability"]["classifications"]["unreviewed"]
    assert result["items_db"][PROBE_ITEM][1] == f"Item {generation}"
    assert result["stack_limits"][PROBE_ITEM] == generation
    assert result["max_damage"][PROBE_ITEM] == generation * 100
    assert result["effects_db"][PROBE_EFFECT][1] == f"Effect {generation}"
    assert result["ench_db"][PROBE_ENCHANTMENT]["max_lvl"] == generation
    assert result["item_components"]["enchantable"][PROBE_ITEM]["value"] == generation
    assert result["inventory"][0]["enchantments"] == [{"id": PROBE_ENCHANTMENT, "lvl": 1}]
    assert result["effects"][1]["opaque"] is True


def test_concurrent_service_reads_keep_their_whole_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    path = tmp_path / "catalog.json"
    write_catalog(path, 1)
    first = item_data.reload_item_database(path)
    old_service = make_service(first)
    old_world = make_world(tmp_path / "old-world")
    new_world = make_world(tmp_path / "new-world")
    entered, release = threading.Event(), threading.Event()
    read_player = old_service._read_player

    def pause_read(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return read_player(*args, **kwargs)

    monkeypatch.setattr(old_service, "_read_player", pause_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_read = pool.submit(old_service.load_player, old_world, PLAYER_KEY)
        try:
            assert entered.wait(5)
            write_catalog(path, 2)
            second = item_data.reload_item_database(path)
            new_read = pool.submit(make_service(second).load_player, new_world, PLAYER_KEY)
            assert_generation(new_read.result(timeout=5), 2)
        finally:
            release.set()
        assert_generation(old_read.result(timeout=5), 1)
    assert_generation(old_service.load_player(old_world, PLAYER_KEY), 1)
    assert item_data.get_max_stack(PROBE_ITEM) == 2


def test_service_exception_releases_catalog_context(tmp_path, monkeypatch):
    path = tmp_path / "catalog.json"
    write_catalog(path, 1)
    first = item_data.prepare_item_catalog(path)
    write_catalog(path, 2)
    second = item_data.reload_item_database(path)
    service = make_service(first)
    def fail(_world):
        assert item_data.get_max_stack(PROBE_ITEM) == 1
        raise ValueError("open failed")
    monkeypatch.setattr(service, "_open_db_readonly", fail)
    world = make_world(tmp_path / "world")
    with pytest.raises(ValueError, match="open failed"):
        service.load_player(world, PLAYER_KEY)
    assert item_data.current_item_catalog() is second
    assert item_data.get_max_stack(PROBE_ITEM) == 2


@pytest.fixture
def application(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import main
    path = tmp_path / "catalog.json"
    write_catalog(path, 1)
    monkeypatch.setattr(main, "_item_db_runtime_path", lambda: path)
    monkeypatch.setattr(main, "_item_db_operation_root", lambda: tmp_path / "locks")
    monkeypatch.setattr(main, "editor_service", main.editor_service)
    monkeypatch.setattr(main, "_ITEM_DB_RUNTIME_SIGNATURE", None)
    monkeypatch.setattr(main, "_ITEM_DB_RELOAD_FAILURE", None)
    main.reload_item_db_after_update()
    return main, path


def test_application_publishes_new_service_without_reloading_code(application, monkeypatch):
    main, path = application
    old = main.editor_service
    cls = main.BedrockEditorService
    parse = inventory.parse_effects
    monkeypatch.setattr(importlib, "reload", lambda *_: pytest.fail("Module reload called"))
    write_catalog(path, 2)
    result = main.reload_item_db_after_update()
    assert result["reloaded"] is True
    assert main.editor_service is not old
    assert type(main.editor_service) is cls
    assert main.BedrockEditorService is cls
    assert inventory.parse_effects is parse
    assert old.item_catalog["STACK_LIMITS"][PROBE_ITEM] == 1
    assert main.editor_service.item_catalog["STACK_LIMITS"][PROBE_ITEM] == 2
    assert main._item_db_file_signature() == main._ITEM_DB_RUNTIME_SIGNATURE


@pytest.mark.parametrize("failure", ["json", "non_object", "service", "status", "changed", "missing"])
def test_application_does_not_publish_incomplete_update(application, monkeypatch, failure):
    main, path = application
    old = main.editor_service
    catalog = item_data.current_item_catalog()
    signature = main._ITEM_DB_RUNTIME_SIGNATURE
    write_catalog(path, 2)
    def fail(*_args, **_kwargs):
        raise ValueError("preparation failed")
    if failure == "json":
        path.write_text("{broken", encoding="utf-8")
    elif failure == "non_object":
        path.write_text("[]", encoding="utf-8")
    elif failure == "service":
        monkeypatch.setattr(main, "BedrockEditorService", fail)
    elif failure == "status":
        monkeypatch.setattr(main.status_snapshots, "item_db_status_snapshot", fail)
    elif failure == "changed":
        status = main.status_snapshots.item_db_status_snapshot
        def change_file(*args):
            result = status(*args)
            write_catalog(path, 3)
            return result
        monkeypatch.setattr(main.status_snapshots, "item_db_status_snapshot", change_file)
    else:
        path.unlink()
    with pytest.raises((ValueError, OSError)):
        main.reload_item_db_after_update()
    assert main.editor_service is old
    assert item_data.current_item_catalog() is catalog
    assert signature == main._ITEM_DB_RUNTIME_SIGNATURE
    assert item_data.get_max_stack(PROBE_ITEM) == 1


def test_external_bad_catalog_keeps_serving_and_retries_when_repaired(application, monkeypatch):
    main, path = application
    old = main.editor_service
    path.write_text("{broken", encoding="utf-8")
    calls = []
    prepare = item_data.prepare_item_catalog
    def record(*args):
        calls.append(1)
        return prepare(*args)
    monkeypatch.setattr(item_data, "prepare_item_catalog", record)
    assert main.reload_item_db_after_external_worker_update() is None
    assert main.reload_item_db_after_external_worker_update() is None
    assert len(calls) == 1
    assert main.editor_service is old
    failed_status = main.item_db_status_snapshot()
    assert "reload_warning" in failed_status
    assert failed_status["verification"]["verified"] is False
    assert failed_status["verification"]["reason"] == "runtime-reload-failed"
    # No quarantine/recovery writes on a running worker's rejected reload.
    assert path.read_text(encoding="utf-8") == "{broken"
    write_catalog(path, 2)
    assert main.reload_item_db_after_external_worker_update() is None
    assert len(calls) == 2
    assert main._ITEM_DB_RELOAD_FAILURE is None
    assert "reload_warning" not in main.item_db_status_snapshot()
    assert main.editor_service.item_catalog["STACK_LIMITS"][PROBE_ITEM] == 2


def test_known_reload_failure_does_not_wait_for_a_running_update(application):
    main, path = application
    path.write_text("{broken", encoding="utf-8")
    assert main.reload_item_db_after_external_worker_update() is None
    assert main._ITEM_DB_RELOAD_FAILURE is not None
    # An update can hold this lock for minutes; requests such as its progress
    # polling must still pass while the file is known to be unloadable.
    with ThreadPoolExecutor(max_workers=1) as pool, main._ITEM_DB_UPDATE_LOCK:
        assert pool.submit(main.reload_item_db_after_external_worker_update).result(timeout=5) is None


def test_catalog_reload_warning_is_visible_even_with_valid_disk_metadata():
    from tests.node_runner import run_node

    run_node(r'''
        const assert = require("node:assert/strict");
        global.window = global;
        require("./static/data_source_view.js");
        const view = MCBEDataSourceView;
        const status = {status: "ok", verification: {verified: true}};
        assert.equal(view.itemDbStatusRank(status), 0);
        status.reload_warning = "The active catalog was retained.";
        assert.equal(view.itemDbStatusRank(status), 1);
        assert.equal(view.itemDbStatusValue(status), "Item-DB-Aktualisierung fehlgeschlagen.");
        assert.equal(view.itemDbSourceText(status), status.reload_warning);
        assert.match(view.itemDbStatusHtml({itemDbStatus: status}), /The active catalog was retained/);
    ''')


def test_existing_function_defaults_follow_the_bound_catalog(tmp_path):
    path = tmp_path / "catalog.json"
    write_catalog(path, 1)
    first = item_data.prepare_item_catalog(path)
    write_catalog(path, 2)
    second = item_data.reload_item_database(path)
    enchantment = nbt.CompoundTag({"id": nbt.ShortTag(PROBE_ENCHANTMENT), "lvl": nbt.ShortTag(2)})
    extract = inventory._core._editable_known_enchantment_values
    with item_data.use_item_catalog(first):
        assert extract(enchantment) is None
    with item_data.use_item_catalog(second):
        assert extract(enchantment) == (PROBE_ENCHANTMENT, 2)
    assert extract(enchantment) == (PROBE_ENCHANTMENT, 2)


def test_service_saves_use_their_catalog_limits_after_publication(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    path = tmp_path / "catalog.json"
    write_catalog(path, 1)
    first = item_data.reload_item_database(path)
    old = make_service(first)
    world = make_world(tmp_path / "world")
    loaded = old.load_player(world, PLAYER_KEY)
    items = list(loaded["inventory"].values())
    items[0]["count"] = 2
    write_catalog(path, 2)
    second = item_data.reload_item_database(path)
    with pytest.raises(ValueError, match="Vanilla-Stacklimit 1"):
        old.save_player(world, PLAYER_KEY, items, {}, base_revision=loaded["player_revision"])
    assert old.load_player(world, PLAYER_KEY)["player_revision"] == loaded["player_revision"]
    current = make_service(second)
    result = current.save_player(world, PLAYER_KEY, items, {}, base_revision=loaded["player_revision"])
    assert result["success"] is True
    assert result["no_op"] is False
    assert current.load_player(world, PLAYER_KEY)["inventory"][0]["count"] == 2


def test_publication_waits_for_active_service_mutations(application, monkeypatch):
    main, path = application
    old = main.editor_service
    write_catalog(path, 2)
    started, preparing = threading.Event(), threading.Event()
    prepare = item_data.prepare_item_catalog
    def record(*args):
        preparing.set()
        return prepare(*args)
    def reload():
        started.set()
        return main.reload_item_db_after_update()
    monkeypatch.setattr(item_data, "prepare_item_catalog", record)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with main._SERVICE_MUTATION_LOCK:
            result = pool.submit(reload)
            assert started.wait(5)
            assert not preparing.wait(0.1)
            assert main.editor_service is old
        assert result.result(timeout=5)["reloaded"] is True
        assert preparing.is_set()
        assert main.editor_service is not old
