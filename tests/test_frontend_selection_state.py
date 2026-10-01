import textwrap

from tests.node_runner import run_node


def test_frontend_selection_state_selected_single_target() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/selection_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/selection_state.js" });

            const state = context.window.MCBESelectionState;
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedSingleTarget({ selectedSlots: [4], selectedEnderSlot: -1 }))),
                { slotId: 4, containerName: "inventory", isEnder: false },
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedSingleTarget({ selectedSlots: [], selectedEnderSlot: 2 }))),
                { slotId: 2, containerName: "ender_chest", isEnder: true },
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedSingleTarget({ selectedSlots: [1, 2], selectedEnderSlot: -1 }))),
                null,
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedSingleTarget({ selectedSlots: [1], selectedEnderSlot: 3 }))),
                { slotId: 3, containerName: "ender_chest", isEnder: true },
            );
            """
        )
    )


def test_frontend_selection_state_clipboard_source_and_writable_slots() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/selection_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/selection_state.js" });

            const state = context.window.MCBESelectionState;
            assert.strictEqual(state.hasSelection({ selectedSlots: [], selectedEnderSlot: -1 }), false);
            assert.strictEqual(state.hasSelection({ selectedSlots: [1], selectedEnderSlot: -1 }), true);
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedClipboardSourceTarget({ selectedSlots: [4, 5], selectedEnderSlot: -1 }))),
                { slotId: 4, containerName: "inventory", isEnder: false },
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedClipboardSourceTarget({ selectedSlots: [4], selectedEnderSlot: 2 }))),
                { slotId: 2, containerName: "ender_chest", isEnder: true },
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedClipboardSourceTarget({ selectedSlots: [], selectedEnderSlot: -1 }))),
                null,
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(state.selectedWritableInventorySlots(
                    { selectedSlots: [1, 2, 3], selectedEnderSlot: 4 },
                    slotId => slotId === 2,
                ))),
                [1, 3],
            );
            """
        )
    )
