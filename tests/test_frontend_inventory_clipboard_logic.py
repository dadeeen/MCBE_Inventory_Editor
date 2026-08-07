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


def test_frontend_inventory_clipboard_logic_context_menu_models() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_clipboard_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_clipboard_logic.js" });

            const logic = context.window.MCBEInventoryClipboardLogic;
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.contextMenuButtonModel({ hasClipboard: true, protectedKnown: false }))),
                { copyVisible: true, pasteVisible: true, cutVisible: true, clearVisible: true },
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.contextMenuButtonModel({ hasClipboard: true, protectedKnown: true }))),
                { copyVisible: false, pasteVisible: false, cutVisible: false, clearVisible: false },
            );

            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.contextSlotActionPlan({
                    action: "paste",
                    slotId: 4,
                    hasClipboard: true,
                    hasSourceItem: false,
                }))),
                { ok: true, operation: "paste", requiresUndo: true, selectSlot: true },
            );
            assert.strictEqual(logic.contextSlotActionPlan({ action: "copy", slotId: 4, hasSourceItem: false }).reason, "empty_source");
            assert.strictEqual(logic.contextSlotActionPlan({ action: "clear", slotId: 4, hasSourceItem: true }).operation, "clear");
            // Leeren eines leeren Slots darf keinen Dirty-Status/Undo-Push auslösen.
            assert.strictEqual(logic.contextSlotActionPlan({ action: "clear", slotId: 4, hasSourceItem: false }).reason, "empty_source");
            assert.strictEqual(logic.contextSlotActionPlan({ action: "cut", slotId: 4, protectedKnown: true }).showProtected, true);
            """
        )
    )


def test_frontend_inventory_clipboard_logic_keyboard_copy_paste_plans() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_clipboard_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_clipboard_logic.js" });

            const logic = context.window.MCBEInventoryClipboardLogic;
            const enderTarget = { slotId: 2, containerName: "ender_chest", isEnder: true };
            assert.strictEqual(logic.keyboardCopyPlan({ sourceTarget: enderTarget, hasSourceItem: true }).operation, "copy");
            assert.strictEqual(logic.keyboardCopyPlan({ sourceTarget: enderTarget, hasSourceItem: false }).reason, "empty_source");

            // Geschützte Slots (z. B. read-only Root-Ausrüstung) dürfen nicht
            // ins Clipboard kopiert werden.
            const protectedTarget = { slotId: 101, containerName: "inventory", isEnder: false };
            const protectedCopy = logic.keyboardCopyPlan({
                sourceTarget: protectedTarget,
                hasSourceItem: true,
                protectedSource: true,
            });
            assert.strictEqual(protectedCopy.ok, false);
            assert.strictEqual(protectedCopy.reason, "protected_slot");
            assert.strictEqual(protectedCopy.showProtected, true);
            assert.deepStrictEqual(protectedCopy.target, protectedTarget);

            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.keyboardPastePlan({
                    selection: { selectedSlots: [], selectedEnderSlot: 2 },
                    singleTarget: enderTarget,
                    protectedEnder: false,
                    hasClipboard: true,
                }))),
                { ok: true, operation: "paste_ender", target: enderTarget, requiresUndo: true },
            );
            assert.strictEqual(
                logic.keyboardPastePlan({
                    selection: { selectedSlots: [], selectedEnderSlot: 2 },
                    singleTarget: enderTarget,
                    protectedEnder: true,
                    hasClipboard: true,
                }).showProtected,
                true,
            );

            const pasteInventory = logic.keyboardPastePlan({
                selection: { selectedSlots: [1, 2, 3], selectedEnderSlot: -1 },
                singleTarget: null,
                writableSlots: [1, 3],
                hasClipboard: true,
            });
            assert.strictEqual(pasteInventory.operation, "paste_inventory");
            assert.strictEqual(pasteInventory.skippedProtected, true);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(pasteInventory.writableSlots)), [1, 3]);
            assert.strictEqual(
                logic.keyboardPastePlan({
                    selection: { selectedSlots: [2], selectedEnderSlot: -1 },
                    writableSlots: [],
                    hasClipboard: true,
                }).reason,
                "no_writable_inventory_slots",
            );
            """
        )
    )


def test_frontend_inventory_clipboard_logic_keyboard_cut_is_single_target_and_atomic() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/inventory_clipboard_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/inventory_clipboard_logic.js" });

            const logic = context.window.MCBEInventoryClipboardLogic;
            const enderTarget = { slotId: 2, containerName: "ender_chest", isEnder: true };
            assert.strictEqual(
                logic.keyboardCutPlan({
                    singleTarget: enderTarget,
                    protectedTarget: false,
                    hasSourceItem: true,
                }).operation,
                "cut_ender",
            );
            assert.strictEqual(
                logic.keyboardCutPlan({
                    singleTarget: enderTarget,
                    protectedTarget: false,
                    hasSourceItem: false,
                }).reason,
                "empty_source",
            );

            const inventoryTarget = { slotId: 1, containerName: "inventory", isEnder: false };
            assert.strictEqual(
                logic.keyboardCutPlan({
                    singleTarget: inventoryTarget,
                    protectedTarget: false,
                    hasSourceItem: true,
                }).operation,
                "cut_inventory",
            );
            assert.strictEqual(
                logic.keyboardCutPlan({
                    singleTarget: inventoryTarget,
                    protectedTarget: true,
                    hasSourceItem: true,
                }).reason,
                "protected_slot",
            );

            const multiSelection = logic.keyboardCutPlan({
                singleTarget: null,
                protectedTarget: false,
                hasSourceItem: true,
            });
            assert.strictEqual(multiSelection.ok, false);
            assert.strictEqual(multiSelection.reason, "single_selection_required");
            """
        )
    )


def test_frontend_inventory_clipboard_controller_never_clears_multi_selection_on_cut() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            class Element {}
            const context = {
                Element,
                window: {
                    t: text => text,
                    MCBESelectionState: {
                        hasSelection: () => true,
                        selectedSingleTarget: () => null,
                    },
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/inventory_clipboard_logic.js", "utf8"),
                context,
                { filename: "static/inventory_clipboard_logic.js" },
            );

            const inventory = {
                1: { slot: 1, name: "minecraft:diamond", count: 5 },
                2: { slot: 2, name: "minecraft:iron_sword", count: 1 },
            };
            let undoCalls = 0;
            let dirtyCalls = 0;
            let clearCalls = 0;
            const toasts = [];
            const doc = {
                querySelector: () => null,
            };
            const controller = context.window.MCBEInventoryClipboardLogic.createInventoryClipboardController({
                doc,
                win: { getSelection: () => null },
                getInventory: () => inventory,
                getCurrentSelectionState: () => ({ selectedSlots: [1, 2], selectedEnderSlot: -1 }),
                getActiveWorkflowView: () => "inventory",
                pushUndo: () => { undoCalls += 1; },
                setDirty: () => { dirtyCalls += 1; },
                clearTargets: () => { clearCalls += 1; },
                showToast: message => { toasts.push(message); },
            });
            const event = {
                ctrlKey: true,
                metaKey: false,
                shiftKey: false,
                altKey: false,
                key: "x",
                target: new Element(),
                preventDefault: () => {},
            };

            assert.strictEqual(controller.handleKeydown(event), true);
            assert.strictEqual(clearCalls, 0);
            assert.strictEqual(undoCalls, 0);
            assert.strictEqual(dirtyCalls, 0);
            assert.strictEqual(inventory[1].name, "minecraft:diamond");
            assert.strictEqual(inventory[2].name, "minecraft:iron_sword");
            assert.strictEqual(controller.state().hasClipboard, false);
            assert.strictEqual(toasts.length, 1);
            """
        )
    )
