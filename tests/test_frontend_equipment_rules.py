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


def test_frontend_equipment_rules_mirror_backend_wearability() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/equipment_rules.js", "utf8"), context, { filename: "static/equipment_rules.js" });

            const rules = context.window.MCBEEquipmentRules;
            rules.setItemComponents({
                wearable: {
                    "minecraft:future_hat": { slot: "slot.armor.head" },
                    "minecraft:future_sword": { slot: "slot.weapon.offhand" },
                    "minecraft:future_boots": { slot: "slot.armor.body" },
                    "minecraft:totem_of_undying": { slot: "slot.weapon.mainhand" },
                },
            });

            // Ausrüstungs-Slots erkennen (nur Inventar-Container).
            assert.strictEqual(rules.isEquipmentSlot(103), true);
            assert.strictEqual(rules.isEquipmentSlot(-106), true);
            assert.strictEqual(rules.isEquipmentSlot(0), false);
            assert.strictEqual(rules.isEquipmentSlot(103, "ender_chest"), false);

            // Rüstung: Slot ergibt sich aus der Item-ID.
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(103, "minecraft:diamond_helmet"), true);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(103, "minecraft:carved_pumpkin"), true);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(103, "minecraft:zombie_head"), true);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(102, "minecraft:elytra"), true);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(101, "minecraft:iron_leggings"), true);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(100, "minecraft:golden_boots"), true);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(103, "minecraft:diamond_boots"), false);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(102, "minecraft:stone"), false);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(103, "minecraft:future_hat"), true);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(-106, "minecraft:future_sword"), true);
            // Body-Slot ist kein editierbarer Spieler-Rüstungsslot; die offizielle
            // Komponente schlägt außerdem das irreführende _boots-Suffix.
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(100, "minecraft:future_boots"), false);

            // Schildhand: Bedrock-Positivliste. minecraft:wearable ist nicht das
            // Prädikat für die Offhand-Erlaubnis, ergänzt die Liste also nur.
            // totem_of_undying trägt hier bewusst eine Mainhand-Komponente und
            // muss trotzdem in der Schildhand erlaubt bleiben.
            ["shield", "totem_of_undying", "arrow", "firework_rocket", "filled_map", "nautilus_shell"].forEach(name => {
                assert.strictEqual(rules.itemAllowedInEquipmentSlot(-106, `minecraft:${name}`), true, name);
            });
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(102, "minecraft:totem_of_undying"), false);
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(-106, "minecraft:diamond_sword"), false);

            // Normale Slots unbeschränkt.
            assert.strictEqual(rules.itemAllowedInEquipmentSlot(5, "minecraft:stone"), true);

            assert.ok(rules.notWearableMessage(103, "minecraft:stone").includes("Helm"));
            assert.ok(rules.notWearableMessage(-106, "minecraft:stone").includes("Schildhand"));
            """
        )
    )


def test_frontend_move_plan_blocks_non_wearable_equipment_targets() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/equipment_rules.js", "utf8"), context, { filename: "static/equipment_rules.js" });
            vm.runInNewContext(fs.readFileSync("static/slot_interaction_logic.js", "utf8"), context, { filename: "static/slot_interaction_logic.js" });

            const logic = context.window.MCBESlotInteractionLogic;

            // Stein in den Helm-Slot ziehen wird blockiert.
            const blocked = logic.moveOrCopyPlan({
                fromSlot: 5,
                toSlot: 103,
                hasFromItem: true,
                fromItemName: "minecraft:stone",
            });
            assert.strictEqual(blocked.ok, false);
            assert.strictEqual(blocked.reason, "not_wearable");
            assert.strictEqual(blocked.slot, 103);

            // Helm in den Helm-Slot ist erlaubt.
            const allowed = logic.moveOrCopyPlan({
                fromSlot: 5,
                toSlot: 103,
                hasFromItem: true,
                fromItemName: "minecraft:diamond_helmet",
            });
            assert.strictEqual(allowed.ok, true);

            // Tausch: das Ziel-Item müsste zurück in den Ausrüstungs-Slot passen.
            const swapBlocked = logic.moveOrCopyPlan({
                fromSlot: 103,
                toSlot: 5,
                hasFromItem: true,
                hasToItem: true,
                fromItemName: "minecraft:diamond_helmet",
                toItemName: "minecraft:stone",
            });
            assert.strictEqual(swapBlocked.ok, false);
            assert.strictEqual(swapBlocked.reason, "not_wearable");
            assert.strictEqual(swapBlocked.slot, 103);

            // Kopieren aus dem Ausrüstungs-Slot heraus bleibt erlaubt
            // (das Ziel-Item wird beim Kopieren überschrieben, nicht getauscht).
            const copyOut = logic.moveOrCopyPlan({
                fromSlot: 103,
                toSlot: 5,
                hasFromItem: true,
                hasToItem: true,
                fromItemName: "minecraft:diamond_helmet",
                toItemName: "minecraft:stone",
                copyMode: true,
            });
            assert.strictEqual(copyOut.ok, true);

            // Ohne geladenes Regel-Modul bleibt das alte Verhalten bestehen.
            const bare = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/slot_interaction_logic.js", "utf8"), bare, { filename: "static/slot_interaction_logic.js" });
            const fallback = bare.window.MCBESlotInteractionLogic.moveOrCopyPlan({
                fromSlot: 5,
                toSlot: 103,
                hasFromItem: true,
                fromItemName: "minecraft:stone",
            });
            assert.strictEqual(fallback.ok, true);
            """
        )
    )


def test_frontend_paste_plans_block_non_wearable_equipment_targets() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/equipment_rules.js", "utf8"), context, { filename: "static/equipment_rules.js" });
            vm.runInNewContext(fs.readFileSync("static/inventory_clipboard_logic.js", "utf8"), context, { filename: "static/inventory_clipboard_logic.js" });

            const logic = context.window.MCBEInventoryClipboardLogic;

            // Kontextmenü-Paste in den Helm-Slot mit Stein wird blockiert.
            const ctxBlocked = logic.contextSlotActionPlan({
                action: "paste",
                slotId: 103,
                hasClipboard: true,
                clipboardItemName: "minecraft:stone",
            });
            assert.strictEqual(ctxBlocked.ok, false);
            assert.strictEqual(ctxBlocked.reason, "not_wearable");

            const ctxAllowed = logic.contextSlotActionPlan({
                action: "paste",
                slotId: 103,
                hasClipboard: true,
                clipboardItemName: "minecraft:iron_helmet",
            });
            assert.strictEqual(ctxAllowed.ok, true);

            // Tastatur-Paste überspringt nicht-tragbare Ausrüstungsziele.
            const partial = logic.keyboardPastePlan({
                selection: { selectedSlots: [5, 103], selectedEnderSlot: -1 },
                writableSlots: [5, 103],
                hasClipboard: true,
                clipboardItemName: "minecraft:stone",
            });
            assert.strictEqual(partial.ok, true);
            assert.deepStrictEqual(partial.writableSlots, [5]);
            assert.strictEqual(partial.skippedNotWearable, true);

            const allBlocked = logic.keyboardPastePlan({
                selection: { selectedSlots: [103], selectedEnderSlot: -1 },
                writableSlots: [103],
                hasClipboard: true,
                clipboardItemName: "minecraft:stone",
            });
            assert.strictEqual(allBlocked.ok, false);
            assert.strictEqual(allBlocked.reason, "not_wearable");
            """
        )
    )
