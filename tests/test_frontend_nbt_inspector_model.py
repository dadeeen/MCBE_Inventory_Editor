"""Read-only NBT inspection retains exact values and trustworthy origins."""

import textwrap

from tests.node_runner import run_node

MODEL_SETUP = r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const context = {window: {}};
const load = name => vm.runInNewContext(fs.readFileSync(`static/${name}.js`, "utf8"), context);
load("nbt_inspector_model");
const model = context.window.MCBENbtInspectorModel;
const clone = value => JSON.parse(JSON.stringify(value));
const original = () => ({
    slot: 2, source_slot: 2, source_container: "inventory",
    source_player_key: "local_player", source_world_path: "C:/SyntheticWorld",
    source_item_digest: "a".repeat(64), name: "minecraft:diamond_pickaxe", count: 1,
    nbt_view: {type: "CompoundTag", value: {
        Name: {type: "StringTag", value: "minecraft:diamond_pickaxe"},
        Count: {type: "ByteTag", value: 1},
        tag: {type: "CompoundTag", value: {Damage: {type: "IntTag", value: 37}}},
    }},
});
const options = item => ({item, containerName: "inventory", cleanSnapshot: {inv: {2: original()}, ec: {}},
    worldPath: "C:/SyntheticWorld", playerKey: "local_player"});
"""


def run_model_test(source: str) -> None:
    run_node(MODEL_SETUP + textwrap.dedent(source))


def test_original_follows_item_provenance_after_edit_move_and_copy() -> None:
    run_model_test(
        """
        load("inventory_state");
        const item = original();
        const inventoryState = context.window.MCBEInventoryState;
        const edited = {...item, damage: 90, display_name: "Edited"};
        delete edited.nbt_view;
        const moved = inventoryState.cloneItemForSlot(edited, 8, "ender_chest", "inventory");
        const copied = inventoryState.cloneClipboardForTarget(moved, 5, "inventory");
        for (const [current, containerName] of [[item, "inventory"], [edited, "inventory"], [moved, "ender_chest"], [copied, "inventory"]]) {
            const input = {...options(current), containerName};
            const before = JSON.stringify(input);
            const resolved = model.resolveOriginal(input);
            assert.strictEqual(resolved.item, input.cleanSnapshot.inv[2]);
            assert.strictEqual(resolved.containerName, "inventory");
            assert.strictEqual(resolved.slotId, 2);
            assert.strictEqual(resolved.item.nbt_view.value.tag.value.Damage.value, 37);
            assert.strictEqual(JSON.stringify(input), before);
        }
        """
    )


def test_original_rejects_replacement_stale_or_missing_provenance() -> None:
    run_model_test(
        """
        const itemPatches = [
            {replace_original_nbt: true}, {origin_world_mismatch: true},
            {source_world_path: "D:/OtherWorld"}, {source_world_path: ""},
            {source_player_key: "other_player"}, {source_player_key: ""},
            {source_container: "__cross_world__"}, {source_container: undefined},
            {source_slot: 3}, {source_slot: "2"}, {source_slot: null},
            {source_item_digest: "b".repeat(64)}, {source_item_digest: "invalid"},
            {source_item_digest: undefined}, {name: "minecraft:apple"},
        ];
        for (const patch of itemPatches) {
            assert.strictEqual(model.resolveOriginal(options({...original(), ...patch})), null, JSON.stringify(patch));
        }
        for (const patch of [{cleanSnapshot: null}, {worldPath: ""}, {worldPath: "D:/OtherWorld"},
            {playerKey: "other_player"}, {playerKey: ""}, {containerName: "unexpected"}]) {
            assert.strictEqual(model.resolveOriginal({...options(original()), ...patch}), null);
        }
        const input = options(original());
        input.cleanSnapshot.inv[9] = input.cleanSnapshot.inv[2];
        delete input.cleanSnapshot.inv[2];
        assert.strictEqual(model.resolveOriginal(input), null, "Must not search other slots by matching item ID or digest");
        """
    )


def test_original_checks_baseline_context_and_exact_fallback_without_digest() -> None:
    run_model_test(
        r"""
        for (const patch of [{source_world_path: "D:/OtherWorld"}, {source_player_key: "other_player"},
            {source_container: "ender_chest"}, {source_slot: 7}, {slot: 7},
            {replace_original_nbt: true}, {origin_world_mismatch: true}, {nbt_view: null}]) {
            const input = options(original());
            Object.assign(input.cleanSnapshot.inv[2], patch);
            assert.strictEqual(model.resolveOriginal(input), null, JSON.stringify(patch));
        }
        const input = options(original());
        input.item.source_world_path = "C:\\SyntheticWorld\\";
        assert.ok(model.resolveOriginal(input), "Equivalent separators do not invalidate a source");
        delete input.item.source_item_digest;
        delete input.cleanSnapshot.inv[2].source_item_digest;
        assert.ok(model.resolveOriginal(input));
        delete input.item.nbt_view;
        assert.strictEqual(model.resolveOriginal(input), null, "Source slot and item ID alone are not proof");
        input.item.nbt_view = original().nbt_view;
        input.item.nbt_view.value.Count.value = 2;
        assert.strictEqual(model.resolveOriginal(input), null);
        input.item.nbt_view = original().nbt_view;
        input.item.nbt_view.value.cycle = input.item.nbt_view;
        assert.strictEqual(model.resolveOriginal(input), null);
        """
    )


def test_original_uses_refreshed_saved_baseline_and_handles_undo() -> None:
    run_model_test(
        """
        load("inventory_state");
        load("state_snapshot");
        let inventory = {2: original()};
        let enderChestInventory = {};
        const snapshots = context.window.MCBEStateSnapshot.createStateSnapshot(() => ({inventory, enderChestInventory}));
        let cleanSnapshot = snapshots.takeSnapshot();
        const beforeMove = snapshots.takeSnapshot();
        enderChestInventory[8] = context.window.MCBEInventoryState.cloneItemForSlot(inventory[2], 8, "ender_chest", "inventory");
        delete inventory[2];
        let input = {...options(enderChestInventory[8]), containerName: "ender_chest", cleanSnapshot};
        assert.strictEqual(model.resolveOriginal(input).slotId, 2);
        inventory = beforeMove.inv;
        enderChestInventory = beforeMove.ec;
        assert.ok(model.resolveOriginal({...options(inventory[2]), cleanSnapshot}), "Undo restores a valid source");

        const savedItem = {...original(), slot: 8};
        savedItem.nbt_view.value.tag.value.Damage.value = 42;
        inventory = {};
        enderChestInventory = {8: savedItem};
        const origins = context.window.MCBEInventoryState.createInventoryOriginController({
            getWorldPath: () => "C:/SyntheticWorld", getCurrentPlayerKey: () => "local_player",
            getInventory: () => inventory, getEnderChestInventory: () => enderChestInventory,
        });
        origins.normalizeOriginsToCurrentSavedState({inventory: {}, ender_chest: {8: "b".repeat(64)}},
            {inventory: {}, ender_chest: {8: savedItem}});
        cleanSnapshot = snapshots.takeSnapshot();
        input = {...options(enderChestInventory[8]), containerName: "ender_chest", cleanSnapshot};
        const resolved = model.resolveOriginal(input);
        assert.strictEqual(resolved.slotId, 8);
        assert.strictEqual(resolved.containerName, "ender_chest");
        assert.strictEqual(resolved.item.nbt_view.value.tag.value.Damage.value, 42);
        assert.strictEqual(model.resolveOriginal({...input, item: original()}), null, "Former sources cannot resolve after save");
        """
    )


def test_read_only_root_equipment_only_resolves_its_original_echo() -> None:
    run_model_test(
        """
        for (const [source_container, slot] of [["armor", 103], ["offhand", -106]]) {
            const item = {...original(), source_container, slot, source_slot: slot, root_equipment_read_only: true};
            const input = {...options(item), cleanSnapshot: {inv: {[slot]: clone(item)}, ec: {}}};
            assert.strictEqual(model.resolveOriginal(input).containerName, source_container);
            assert.strictEqual(model.resolveOriginal({...input, item: {...item, slot: 3}}), null);
            assert.strictEqual(model.resolveOriginal({...input, containerName: "ender_chest"}), null);
            assert.strictEqual(model.resolveOriginal({...input, item: {...item, root_equipment_read_only: false}}), null);
        }
        """
    )


def test_tree_retains_nbt_types_exact_numbers_and_empty_values() -> None:
    run_model_test(
        """
        const view = {type: "CompoundTag", value: {
            byte: {type: "ByteTag", value: -128}, short: {type: "ShortTag", value: 32767},
            int: {type: "IntTag", value: -2147483648}, long: {type: "LongTag", value: "9223372036854775807"},
            float: {type: "FloatTag", value: "NaN"}, double: {type: "DoubleTag", value: "-Infinity"},
            text: {type: "StringTag", value: ""}, empty: {type: "CompoundTag", value: {}},
            list: {type: "ListTag", value: []}, bytes: {type: "ByteArrayTag", value: [-128, 127]},
            ints: {type: "IntArrayTag", value: [2147483647]},
            longs: {type: "LongArrayTag", value: ["-9223372036854775808", 7]},
        }};
        const before = JSON.stringify(view);
        const nodes = model.flattenTree(view);
        const byPath = new Map(nodes.map(node => [node.id, node]));
        assert.strictEqual(nodes[0].id, "$");
        assert.strictEqual(nodes[0].parentId, null);
        assert.strictEqual(nodes[0].depth, 0);
        assert.strictEqual(nodes[0].count, 12);
        assert.strictEqual(nodes[0].children, true);
        for (const key of ["byte", "short", "int", "long", "float", "double", "text"]) {
            assert.strictEqual(byPath.get(`$.${key}`).type, view.value[key].type);
            assert.strictEqual(byPath.get(`$.${key}`).value, view.value[key].value);
        }
        assert.strictEqual(model.nodeValueText(byPath.get("$.long")), "9223372036854775807");
        assert.strictEqual(model.nodeValueText(byPath.get("$.double")), "-Infinity");
        assert.strictEqual(model.nodeValueText(byPath.get("$.text")), '""');
        assert.strictEqual(model.nodeValueText(byPath.get("$.empty")), "{0}");
        assert.strictEqual(byPath.get("$.empty").children, false);
        assert.strictEqual(model.nodeValueText(byPath.get("$.list")), "[0]");
        for (const [key, type] of [["bytes", "ByteTag"], ["ints", "IntTag"], ["longs", "LongTag"]]) {
            assert.strictEqual(byPath.get(`$.${key}[0]`).type, type);
            assert.strictEqual(byPath.get(`$.${key}[0]`).parentId, `$.${key}`);
            assert.strictEqual(byPath.get(`$.${key}[0]`).key, "[0]");
            assert.strictEqual(byPath.get(`$.${key}[0]`).depth, 2);
        }
        assert.strictEqual(byPath.get("$.longs[0]").value, "-9223372036854775808");
        assert.strictEqual(model.hasPartial(view), false);
        assert.strictEqual(JSON.stringify(view), before);
        """
    )


def test_tree_paths_are_unambiguous_and_preserve_untrusted_keys_as_data() -> None:
    run_model_test(
        r"""
        const keys = ["normal", "with.dot", "a[0]", "quoted\"key", "", "__proto__", "constructor", "<img onerror=alert(1)>"];
        const value = Object.fromEntries(keys.map(key => [key, {type: "StringTag", value: `<${key}>`} ]));
        value.List = {type: "ListTag", value: [{type: "CompoundTag", value: {entry: {type: "IntTag", value: 8}}}]};
        const nodes = model.flattenTree({type: "CompoundTag", value});
        const paths = nodes.map(node => node.id);
        assert.deepStrictEqual(Array.from(paths), ["$", "$.normal", '$["with.dot"]', '$["a[0]"]',
            '$["quoted\\\"key"]', '$[""]', "$.__proto__", "$.constructor", '$["<img onerror=alert(1)>"]',
            "$.List", "$.List[0]", "$.List[0].entry"]);
        assert.strictEqual(new Set(paths).size, paths.length);
        assert.strictEqual(nodes.find(node => node.id === "$.__proto__").value, "<__proto__>");
        assert.strictEqual({}.polluted, undefined);
        """
    )


def test_tree_keeps_declared_list_element_types_even_for_empty_lists() -> None:
    run_model_test(
        """
        for (const list_type_id of [0, 1, 8, 10, 127]) {
            for (const value of [[], [{type: "IntTag", value: 1}]]) {
                const view = {type: "ListTag", value, list_type_id};
                const before = JSON.stringify(view);
                assert.strictEqual(model.flattenTree(view)[0].listTypeId, list_type_id);
                assert.strictEqual(JSON.stringify(view), before);
            }
        }
        for (const list_type_id of [undefined, null, "10", 1.5, NaN]) {
            assert.strictEqual(model.flattenTree({type: "ListTag", value: [], list_type_id})[0].listTypeId, undefined);
        }
        assert.strictEqual(model.flattenTree({type: "IntArrayTag", value: [], list_type_id: 3})[0].listTypeId, undefined);
        """
    )


def test_tree_reports_partial_nodes_and_totals_without_translating_metadata() -> None:
    run_model_test(
        """
        for (const reason of ["depth", "items", "string", "budget"]) {
            const view = {type: "CompoundTag", value: {tag: {type: "StringTag", value: "limited", truncation: {reason}}}};
            assert.strictEqual(model.hasPartial(view), true);
            const node = model.flattenTree(view)[1];
            assert.strictEqual(node.partial, true);
            assert.ok(model.nodeValueText(node).endsWith(" …"));
        }
        const view = {type: "ListTag", value: [{type: "ByteTag", value: 1}], truncation: {reason: "items", total: 81, shown: 1}};
        const node = model.flattenTree(view)[0];
        assert.strictEqual(node.count, 1);
        assert.strictEqual(node.totalCount, 81);
        assert.strictEqual(node.children, true);
        assert.strictEqual(model.hasPartial({type: "IntArrayTag", value: [2], truncated: "79 further values"}), true);
        assert.strictEqual(model.hasPartial({type: "StringTag", value: "ordinary text..."}), false);
        assert.strictEqual(model.flattenTree({...view, truncation: {total: -1}})[0].totalCount, undefined);
        """
    )


def test_tree_limits_cycles_and_extreme_inputs_without_mutation() -> None:
    run_model_test(
        """
        for (const value of [null, undefined, "invalid", []]) assert.strictEqual(model.flattenTree(value).length, 0);
        const cycle = {type: "CompoundTag", value: {}};
        cycle.value.self = cycle;
        const cycleNodes = model.flattenTree(cycle);
        assert.strictEqual(cycleNodes.length, 2);
        assert.strictEqual(cycleNodes[1].partial, true);
        assert.strictEqual(cycle.value.self, cycle);
        let deep = {type: "IntTag", value: 3};
        for (let i = 0; i < 100; i += 1) deep = {type: "ListTag", value: [deep]};
        assert.strictEqual(model.flattenTree(deep).length, 33);
        assert.strictEqual(model.hasPartial(deep), true);
        const wide = {type: "IntArrayTag", value: Array.from({length: 3000}, (_, index) => index)};
        const nodes = model.flattenTree(wide);
        assert.strictEqual(nodes.length, 2048);
        assert.strictEqual(nodes[0].partial, true);
        assert.strictEqual(wide.value.length, 3000);
        for (const view of [{type: "CompoundTag", value: "malformed"}, {type: "ListTag", value: {}},
            {type: "IntArrayTag", value: [{unexpected: 1}]}, {unexpected: 1}]) {
            assert.strictEqual(model.hasPartial(view), true);
            for (const node of model.flattenTree(view)) assert.strictEqual(typeof model.nodeValueText(node), "string");
        }
        """
    )
