from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from mcbe_editor import item_data, nbt
from mcbe_editor.inventory import build_inventory_nbt, nbt_to_json
from scripts import update_db


def _component_archive(definitions: list[tuple[str, dict]]) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index, (item_id, components) in enumerate(definitions):
            archive.writestr(
                f"behavior_pack/items/item_{index}.json",
                json.dumps({"minecraft:item": {"description": {"identifier": item_id}, "components": components}}),
            )
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


@pytest.mark.parametrize("component,expected", [(16, 16), ({"value": 16}, 16), ({}, 64), ({"value": 1}, 1)])
def test_updater_reads_both_documented_stack_component_forms(component, expected):
    with _component_archive([("minecraft:future_item", {"minecraft:max_stack_size": component})]) as archive:
        limits, _durability = update_db.parse_json_item_component_limits(archive)
    assert limits == {"minecraft:future_item": expected}


@pytest.mark.parametrize("component", [None, True, False, 0, -1, 128, "16", 1.5, [], {"value": True}, {"value": None}, {"future": 16}])
def test_updater_refuses_invalid_explicit_stack_components(component):
    with (
        _component_archive([("minecraft:future_item", {"minecraft:max_stack_size": component})]) as archive,
        pytest.raises(RuntimeError, match="max_stack_size"),
    ):
        update_db.parse_json_item_component_limits(archive)


def test_updater_does_not_infer_64_from_missing_component_or_item_suffix():
    item_id = "minecraft:future_planks"
    with _component_archive([(item_id, {"minecraft:display_name": "Future Planks"})]) as archive:
        limits, _durability = update_db.parse_json_item_component_limits(archive)
    assert item_id not in limits
    merged, _ = update_db.merge_item_limits({item_id: 16}, {}, limits, {}, previous_component_stack_items={item_id})
    assert item_id not in merged
    assert item_data.get_max_stack(item_id, merged) == 1
    assert not item_data.has_verified_stack_limit(item_id, merged)


@pytest.mark.parametrize("second_components", [{"minecraft:max_stack_size": {"value": 16}}, {}])
def test_updater_refuses_conflicting_definitions_instead_of_last_file_wins(second_components):
    with _component_archive([
        ("minecraft:future_item", {"minecraft:max_stack_size": 1}),
        ("minecraft:future_item", second_components),
    ]) as archive, pytest.raises(RuntimeError, match="Stacklimits"):
        update_db.parse_json_item_component_limits(archive)


@pytest.mark.parametrize("limit", [True, 0, -1, 128, "16", 1.5, None])
def test_database_does_not_coerce_invalid_stack_limits(tmp_path, limit):
    path = tmp_path / "item_db.json"
    path.write_text(json.dumps({"items": {}, "stack_limits": {"minecraft:stone": limit}}), encoding="utf-8")
    with pytest.raises(item_data.InvalidItemDatabaseError):
        item_data.load_item_database(path)


def test_old_database_default_does_not_restore_an_unverified_64(tmp_path):
    path = tmp_path / "item_db.json"
    path.write_text(json.dumps({"items": {}, "defaults": {"max_stack": 64}}), encoding="utf-8")
    assert item_data.load_item_database(path)["DEFAULT_MAX_STACK"] == 1
    assert not item_data.has_verified_stack_limit("minecraft:stone", {})
    assert item_data.get_max_stack("minecraft:stone", {}) == 1
    limits = {"minecraft:item.bed": 64, "minecraft:bed": 1}
    assert item_data.get_max_stack("minecraft:item.bed", limits) == 1


@pytest.mark.parametrize("name,limit", [
    ("oak_boat", 1), ("pale_oak_chest_boat", 1), ("bamboo_chest_raft", 1),
    ("oak_sign", 16), ("pale_oak_hanging_sign", 16), ("bucket", 16),
    ("cod_bucket", 1), ("tadpole_bucket", 1), ("hopper_minecart", 1),
    ("blue_egg", 16), ("armor_stand", 64), ("black_shulker_box", 1),
    ("music_disc_lava_chicken", 1), ("netherite_horse_armor", 1),
    ("cake", 64), ("lodestone_compass", 64), ("straw_bed", 16), ("red_cushion", 16),
    ("poplar_sign", 16), ("poplar_hanging_sign", 16), ("poplar_boat", 1), ("poplar_chest_boat", 1),
    ("red_wool_stairs", 64), ("shelf_mushroom", 64),
])
def test_reviewed_engine_limits_are_enforced_on_new_stacks(name, limit):
    item_id = f"minecraft:{name}"
    empty = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
    payload = {"slot": 0, "name": item_id, "count": limit, "damage": 0}
    assert item_data.get_max_stack(item_id) == limit
    assert update_db.merge_item_limits({}, {}, {}, {})[0][item_id] == limit
    assert build_inventory_nbt(empty, [payload], item_data.ENCHANTMENTS)[0]["Count"].py_data == limit
    with pytest.raises(ValueError, match="Stacklimit"):
        build_inventory_nbt(empty, [{**payload, "count": limit + 1}], item_data.ENCHANTMENTS)


@pytest.mark.parametrize("name", ["straw_bed", "red_cushion", "poplar_boat", "red_wool_stairs", "shelf_mushroom"])
def test_unverified_new_items_allow_one_and_preserve_real_original_amounts(name, monkeypatch):
    item_id = f"minecraft:{name}"
    # Simulate a future registry update with no measured limit, even after the
    # current catalog's remaining gaps have been verified by the engine.
    monkeypatch.delitem(item_data.STACK_LIMITS, item_id, raising=False)
    assert item_data.is_addable_item_id(item_id)
    assert not item_data.has_verified_stack_limit(item_id)
    empty = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
    payload = {"slot": 0, "name": item_id, "count": 1, "damage": 0}
    assert build_inventory_nbt(empty, [payload], item_data.ENCHANTMENTS)[0]["Count"].py_data == 1
    with pytest.raises(ValueError, match="ungeprüft"):
        build_inventory_nbt(empty, [{**payload, "count": 64, "original_count": 64}], item_data.ENCHANTMENTS)

    original = nbt.CompoundTag({
        "Slot": nbt.ByteTag(0), "Name": nbt.StringTag(item_id), "Count": nbt.ByteTag(16),
        "Damage": nbt.ShortTag(0), "tag": nbt.CompoundTag({"future_data": nbt.LongTag(123)}),
    })
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([original])})
    parsed, _ = nbt_to_json(player)
    saved = build_inventory_nbt(player, [parsed[0]], item_data.ENCHANTMENTS)
    assert saved[0].save_to() == original.save_to()
    moved = build_inventory_nbt(
        player, [{**parsed[0], "slot": 1, "source_player_key": "synthetic", "source_container": "inventory"}],
        item_data.ENCHANTMENTS, target_player_key="synthetic",
    )[0]
    assert moved["Slot"].py_data == 1
    assert moved["Count"].py_data == 16
    assert moved["tag"].save_to() == original["tag"].save_to()
    with pytest.raises(ValueError, match="ungeprüft"):
        build_inventory_nbt(player, [{**parsed[0], "count": 8}], item_data.ENCHANTMENTS)
    assert original["Count"].py_data == 16


def test_frontend_uses_identical_limits_and_never_silently_reduces_unverified_stacks():
    source = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const context = {window: {}};
for (const file of ['item_catalog', 'slot_detail_logic', 'slot_display', 'bulk_edit_logic', 'inventory_state']) {
    vm.runInNewContext(fs.readFileSync(`static/${file}.js`, 'utf8'), context);
}
const db = JSON.parse(fs.readFileSync('mcbe_editor/resources/item_db.json', 'utf8'));
let limits = {...db.stack_limits, __default__: 64};
const catalog = context.window.MCBEItemCatalog.createItemCatalog({
    getItemsDb: () => db.items, getCompatItemAliases: () => db.compat_item_aliases,
    getAddableItems: () => new Set(db.addable_items), getStackLimits: () => limits,
    maxBedrockStackCount: 127,
});
for (const id of db.addable_items) {
    assert.strictEqual(catalog.getMaxStack(id), db.stack_limits[id] ?? 1, id);
}
assert.strictEqual(catalog.getMaxStack('minecraft:red_cushion'), 16);
delete limits['minecraft:red_cushion']; // Simulate a newly discovered, unverified ID.
assert.strictEqual(catalog.hasVerifiedStackLimit('minecraft:red_cushion'), false);
limits['minecraft:item.bed'] = 64;
assert.strictEqual(catalog.getMaxStack('minecraft:item.bed'), 1);
limits['minecraft:red_cushion'] = true;
assert.strictEqual(catalog.hasVerifiedStackLimit('minecraft:red_cushion'), false);
assert.strictEqual(catalog.getMaxStack('minecraft:red_cushion'), 1);
const detail = context.window.MCBESlotDetailLogic;
assert.strictEqual(detail.stackCountFromForm({rawCount: 8, maxStack: 1, stackLimitVerified: false}), 8);
const original = {name: 'minecraft:red_cushion', count: 16, slot: 0, damage: 0};
const form = {slotId: 0, rawName: original.name, rawCount: 16, previousItem: original,
    maxStack: 1, stackLimitVerified: false};
assert.strictEqual(detail.buildDetailItemFromForm(form).item.count, 16);
assert.strictEqual(detail.buildDetailItemFromForm({...form, rawCount: 8}).ok, false);
assert.strictEqual(detail.buildDetailItemFromForm({...form, previousItem: null}).ok, false);
assert.strictEqual(detail.quickMaxStackPlan({hasTarget: true, rawName: original.name,
    maxStack: 1, stackLimitVerified: false}).ok, false);
const display = context.window.MCBESlotDisplay.slotQuickActionsModel({
    isValidItem: true, maxStack: 1, stackLimitVerified: false,
});
assert.strictEqual(display.maxStackDisabled, true);
assert.ok(display.subtitleHtml.includes('ungeprüft'));
assert.strictEqual(context.window.MCBEBulkEditLogic.bulkFillPlan({rawName: original.name,
    rawCount: 64, maxStack: 1, stackLimitVerified: false, writableCount: 1}).ok, false);
const map = {0: {...original}, 1: {name: 'minecraft:stone', count: 2}};
const changed = context.window.MCBEInventoryState.setTargetCounts(
    [{map, slotId: 0}, {map, slotId: 1}],
    {desired: 64, getMaxStack: catalog.getMaxStack, hasVerifiedStackLimit: catalog.hasVerifiedStackLimit});
assert.strictEqual(changed, 1);
assert.strictEqual(map[0].count, 16);
assert.strictEqual(map[1].count, 64);
"""
    result = subprocess.run(["node", "-e", source], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
