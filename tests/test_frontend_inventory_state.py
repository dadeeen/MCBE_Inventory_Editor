import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_inventory_state_selected_bulk_targets_skip_protected_slots() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_state.js" });

            const state = context.window.MCBEInventoryState;
            const inventory = { 1: { name: "minecraft:stone" } };
            const enderChestInventory = { 2: { name: "minecraft:diamond" } };
            const targets = state.selectedBulkTargets({
                selectedSlots: [1, 3],
                selectedEnderSlot: 2,
                inventory,
                enderChestInventory,
                isProtectedKnownSlot: (slotId, container) => container === "inventory" && slotId === 3,
            });

            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(targets.map(({ container, slotId }) => ({ container, slotId })))),
                [
                    { container: "inventory", slotId: 1 },
                    { container: "ender_chest", slotId: 2 },
                ],
            );
            assert.strictEqual(targets[0].map, inventory);
            assert.strictEqual(targets[1].map, enderChestInventory);
            assert.strictEqual(
                state.bulkSelectionLabel(targets.length, { selectedEnderSlot: 2 }),
                "2 markierte Slot(s) inkl. Enderchest",
            );
            """
        )
    )


def test_frontend_inventory_state_visible_targets_and_set_counts() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_state.js" });

            const state = context.window.MCBEInventoryState;
            const inventory = {
                0: { name: "minecraft:stone", count: 4 },
                1: { name: "minecraft:air", count: 1 },
                2: { name: "minecraft:snowball", count: 2 },
            };
            const targets = [
                { map: inventory, slotId: 0 },
                { map: inventory, slotId: 1 },
                { map: inventory, slotId: 2 },
            ];
            const visibleTargets = state.visibleItemTargets(
                targets,
                item => !!(item && item.name && item.name !== "minecraft:air" && Number(item.count || 0) > 0),
            );
            const changed = state.setTargetCounts(visibleTargets, {
                desired: 99,
                getMaxStack: name => name === "minecraft:snowball" ? 16 : 64,
                maxBedrockStackCount: 127,
            });

            assert.strictEqual(changed, 2);
            assert.strictEqual(inventory[0].count, 64);
            assert.strictEqual(inventory[1].count, 1);
            assert.strictEqual(inventory[2].count, 16);
            """
        )
    )


def test_frontend_inventory_state_first_empty_writable_slot_skips_full_and_protected_slots() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_state.js" });

            const state = context.window.MCBEInventoryState;
            const source = {
                0: { name: "minecraft:stone", count: 1 },
                1: { name: "minecraft:air", count: 1 },
                2: { name: "minecraft:dirt", count: 0 },
            };

            assert.strictEqual(
                state.firstEmptyWritableSlot({
                    containerName: "inventory",
                    source,
                    slotCount: 4,
                    isProtectedKnownSlot: slotId => slotId === 1,
                }),
                2,
            );
            assert.strictEqual(
                state.firstEmptyWritableSlot({
                    containerName: "inventory",
                    source: {
                        0: { name: "minecraft:stone", count: 1 },
                        1: { name: "minecraft:dirt", count: 1 },
                    },
                    slotCount: 2,
                }),
                null,
            );
            """
        )
    )


def test_frontend_inventory_state_damaged_item_targets_for_selected_slots() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_state.js" });

            const state = context.window.MCBEInventoryState;
            const inventory = {
                0: { name: "minecraft:iron_pickaxe", count: 1, damage: 12 },
                1: { name: "minecraft:iron_pickaxe", count: 0, damage: 12 },
                2: { name: "minecraft:stone", count: 1, damage: 4 },
            };
            const targets = state.damagedItemTargets(
                [
                    { map: inventory, slotId: 0 },
                    { map: inventory, slotId: 1 },
                    { map: inventory, slotId: 2 },
                ],
                {
                    maxDamage: { "minecraft:iron_pickaxe": 250 },
                    isItemVisiblePresent: item => Number(item?.count || 0) > 0,
                },
            );

            assert.deepStrictEqual(JSON.parse(JSON.stringify(targets.map(target => target.slotId))), [0]);
            """
        )
    )


def test_frontend_inventory_state_damaged_inventory_targets_match_repair_all_semantics() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_state.js" });

            const state = context.window.MCBEInventoryState;
            const inventory = {
                0: { name: "minecraft:iron_helmet", count: 1, damage: 2 },
                1: { name: "minecraft:air", count: 1, damage: 9 },
            };
            const enderChestInventory = {
                4: { name: "minecraft:iron_helmet", count: 0, damage: 3 },
                5: { name: "minecraft:stone", count: 64, damage: 8 },
            };
            const targets = state.damagedInventoryTargets({
                sources: [{ map: inventory }, { map: enderChestInventory }],
                maxDamage: { "minecraft:iron_helmet": 165 },
            });

            assert.deepStrictEqual(JSON.parse(JSON.stringify(targets.map(target => target.slotId))), ["0", "4"]);
            state.repairTargets(targets);
            assert.strictEqual(inventory[0].damage, 0);
            assert.strictEqual(enderChestInventory[4].damage, 0);
            """
        )
    )


def test_frontend_inventory_state_repair_targets_skip_potion_data_values_and_invisible_items() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_state.js" });

            const state = context.window.MCBEInventoryState;
            const inventory = {
                0: { name: "minecraft:iron_pickaxe", count: 1, damage: 12 },
                1: { name: "minecraft:potion", count: 1, damage: 20 },
                2: { name: "minecraft:iron_pickaxe", count: 0, damage: 9 },
            };
            const targets = state.damagedInventoryTargets({
                sources: [{ map: inventory }],
                maxDamage: { "minecraft:iron_pickaxe": 250 },
                isItemVisiblePresent: item => !!(item && item.name && item.name !== "minecraft:air" && Number(item.count || 0) > 0),
            });

            assert.deepStrictEqual(JSON.parse(JSON.stringify(targets.map(target => target.slotId))), ["0"]);
            """
        )
    )


def test_frontend_inventory_state_repairs_sword_armor_and_spear_identically() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_state.js" });

            const state = context.window.MCBEInventoryState;
            const inventory = {
                0: { name: "minecraft:iron_sword", count: 1, damage: 11 },
                1: { name: "minecraft:iron_chestplate", count: 1, damage: 12 },
                2: { name: "minecraft:copper_spear", count: 1, damage: 13 },
                3: { name: "minecraft:stone", count: 1, damage: 14 },
            };
            const targets = state.damagedInventoryTargets({
                sources: [{ map: inventory }],
                maxDamage: {
                    "minecraft:iron_sword": 250,
                    "minecraft:iron_chestplate": 240,
                    "minecraft:copper_spear": 190,
                },
            });

            assert.deepStrictEqual(JSON.parse(JSON.stringify(targets.map(target => target.slotId))), ["0", "1", "2"]);
            assert.strictEqual(state.repairTargets(targets), 3);
            assert.deepStrictEqual(
                [inventory[0].damage, inventory[1].damage, inventory[2].damage, inventory[3].damage],
                [0, 0, 0, 14],
            );
            """
        )
    )
