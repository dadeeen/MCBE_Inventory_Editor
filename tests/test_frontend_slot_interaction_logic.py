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


def test_frontend_slot_interaction_drag_payload_and_plans() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_interaction_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_interaction_logic.js" });

            const logic = context.window.MCBESlotInteractionLogic;
            const plain = value => JSON.parse(JSON.stringify(value));
            assert.deepStrictEqual(
                plain(logic.parseDragPayloadRaw(JSON.stringify({ slot: 5, container: "ender_chest" }))),
                { slot: 5, container: "ender_chest" },
            );
            assert.strictEqual(logic.parseDragPayloadRaw("12"), null);
            assert.deepStrictEqual(plain(logic.parseDragPayloadRaw("12x")), { slot: 12, container: "inventory" });

            assert.deepStrictEqual(plain(logic.dragStartPlan({
                slotId: 7,
                containerName: "inventory",
                protectedKnown: false,
                hasItem: true,
            })), {
                ok: true,
                effectAllowed: "copyMove",
                payload: JSON.stringify({ slot: 7, container: "inventory" }),
            });
            assert.deepStrictEqual(plain(logic.dragStartPlan({ protectedKnown: true, hasItem: true })), { ok: false });
            assert.deepStrictEqual(plain(logic.dragOverPlan({ protectedKnown: false, copyMode: true })), {
                ok: true,
                dropEffect: "copy",
            });
            assert.deepStrictEqual(plain(logic.dragOverPlan({ protectedKnown: true })), { ok: false });
            assert.deepStrictEqual(plain(logic.dropPlan({
                rawPayload: JSON.stringify({ slot: 1, container: "inventory" }),
                toContainerName: "ender_chest",
                toSlot: 2,
                copyMode: true,
            })), {
                ok: true,
                fromContainerName: "inventory",
                fromSlot: 1,
                toContainerName: "ender_chest",
                toSlot: 2,
                copyMode: true,
            });
            """
        )
    )


def test_frontend_slot_interaction_move_and_keyboard_plans() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_interaction_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_interaction_logic.js" });

            const logic = context.window.MCBESlotInteractionLogic;
            const plain = value => JSON.parse(JSON.stringify(value));
            assert.deepStrictEqual(plain(logic.moveOrCopyPlan({
                fromContainerName: "inventory",
                fromSlot: 1,
                toContainerName: "inventory",
                toSlot: 1,
                hasFromItem: true,
            })), { ok: false, reason: "same_slot" });
            assert.deepStrictEqual(plain(logic.moveOrCopyPlan({
                fromSlot: 1,
                toSlot: 2,
                toProtected: true,
                hasFromItem: true,
            })), {
                ok: false,
                reason: "protected_slot",
                protectedSlot: 2,
                protectedContainer: "inventory",
            });
            assert.deepStrictEqual(plain(logic.moveOrCopyPlan({
                fromSlot: 1,
                toSlot: 2,
                hasFromItem: true,
            })), { ok: true });

            assert.deepStrictEqual(plain(logic.keyboardSlotPlan({
                key: "Enter",
                slotId: 1,
                containerName: "inventory",
            })), { ok: true, action: "activate" });
            assert.deepStrictEqual(plain(logic.keyboardSlotPlan({
                key: "Delete",
                slotId: 1,
                containerName: "inventory",
                hasItem: true,
            })), { ok: true, action: "clear" });
            assert.deepStrictEqual(plain(logic.keyboardSlotPlan({
                key: "Delete",
                slotId: 1,
                containerName: "inventory",
                hasItem: false,
            })), { ok: false, action: "clear", reason: "empty_slot" });

            assert.deepStrictEqual(plain(logic.keyboardSlotPlan({
                key: "ArrowDown",
                slotId: 9,
                containerName: "inventory",
            })), {
                ok: true,
                action: "navigate",
                target: { container: "inventory", slot: 18 },
            });
            assert.deepStrictEqual(plain(logic.keyboardSlotPlan({
                key: "ArrowLeft",
                slotId: 0,
                containerName: "inventory",
            })), {
                ok: true,
                action: "navigate",
                target: { container: "inventory", slot: 35 },
            });
            assert.deepStrictEqual(plain(logic.keyboardSlotPlan({
                key: "ArrowUp",
                slotId: 0,
                containerName: "ender_chest",
            })), {
                ok: true,
                action: "navigate",
                target: { container: "ender_chest", slot: 0 },
            });
            """
        )
    )
