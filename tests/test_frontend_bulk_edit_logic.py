import textwrap

from tests.node_runner import run_node


def test_frontend_bulk_edit_logic_fill_and_clear_plans() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/bulk_edit_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/bulk_edit_logic.js" });

            const logic = context.window.MCBEBulkEditLogic;
            const plain = value => JSON.parse(JSON.stringify(value));

            assert.strictEqual(logic.normalizedItemName(" Minecraft:Stone "), "minecraft:stone");
            assert.deepStrictEqual(plain(logic.bulkFillPlan({
                rawName: "minecraft:missing",
                isValidItemId: false,
            })).toast, {
                message: "Ungültige Item-ID. Erwartet wird z. B. minecraft:stone.",
                type: "warning",
                ms: 4000,
            });
            assert.deepStrictEqual(plain(logic.bulkFillPlan({
                rawName: "minecraft:stone",
                isValidItemId: true,
                maxStack: 64,
                maxDamage: 0,
                rawCount: "99",
                rawDamage: "8",
                writableCount: 2,
                selectedCount: 3,
                selectionLabel: "2 markierte Slot(s)",
            })), {
                ok: true,
                item: { name: "minecraft:stone", count: 64, damage: 0 },
                undoLabel: "Markierte Slots mit minecraft:stone gefüllt",
                skippedProtected: true,
                statusMessage: "2 markierte Slot(s) gefüllt mit minecraft:stone – noch nicht gespeichert",
                actionMessage: "2 markierte Slot(s) gefüllt mit minecraft:stone – noch nicht gespeichert",
            });
            assert.deepStrictEqual(plain(logic.bulkClearPlan({
                writableCount: 2,
                selectedCount: 2,
                selectionLabel: "2 markierte Slot(s)",
            })), {
                ok: true,
                undoLabel: "Markierte Slots geleert",
                skippedProtected: false,
                statusMessage: "2 markierte Slot(s) geleert – noch nicht gespeichert",
                actionMessage: "2 markierte Slot(s) geleert – noch nicht gespeichert",
            });
            assert.strictEqual(logic.bulkClearPlan({ writableCount: 0 }).ok, false);
            """
        )
    )


def test_frontend_bulk_edit_logic_count_and_repair_plans() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/bulk_edit_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/bulk_edit_logic.js" });

            const logic = context.window.MCBEBulkEditLogic;
            const plain = value => JSON.parse(JSON.stringify(value));

            assert.deepStrictEqual(plain(logic.bulkSetCountPlan({ targetCount: 0, rawDesired: "5" })).toast, {
                message: "Keine belegten markierten Slots gefunden.",
                type: "warning",
                ms: 3000,
            });
            assert.deepStrictEqual(plain(logic.bulkSetCountPlan({ targetCount: 2, rawDesired: "0" })).toast, {
                message: "Bitte eine gültige Menge eingeben.",
                type: "warning",
                ms: 3000,
            });
            assert.deepStrictEqual(plain(logic.bulkSetCountPlan({ targetCount: 2, rawDesired: "5" })), {
                ok: true,
                desired: 5,
                undoLabel: "Menge für markierte Slots gesetzt",
            });
            assert.deepStrictEqual(plain(logic.bulkSetCountOutcome(3)), {
                recordMessage: "Menge für 3 markierte Slot(s) gesetzt",
                toast: {
                    message: "Menge für 3 Slot(s) gesetzt – noch nicht gespeichert.",
                    type: "info",
                    ms: 2500,
                },
            });
            assert.deepStrictEqual(plain(logic.bulkRepairSelectedPlan({ targetCount: 2 })), {
                ok: true,
                undoLabel: "Markierte Items repariert",
                recordMessage: "2 markierte Item(s) repariert",
                toast: {
                    message: "2 markierte Item(s) repariert – noch nicht gespeichert.",
                    type: "info",
                    ms: 2500,
                },
            });
            assert.deepStrictEqual(plain(logic.repairAllPlan({ targetCount: 4 })), {
                ok: true,
                undoLabel: "Alle reparierbaren Items repariert",
                statusMessage: "Reparierte haltbare Items: 4 (inkl. Enderchest) – noch nicht gespeichert.",
                statusType: "info",
                actionMessage: "Haltbare Items repariert: 4",
            });
            assert.deepStrictEqual(plain(logic.repairAllPlan({ targetCount: 0 })), {
                ok: false,
                statusMessage: "Keine haltbaren Items mit Abnutzung gefunden.",
                statusType: "warning",
            });
            """
        )
    )


def test_bulk_fill_rejects_unsupported_variants_before_replacing_selected_items() -> None:
    run_node(
        r"""
        const assert = require('assert');
        const fs = require('fs');
        global.window = {};
        for (const file of ['selection_state', 'inventory_state', 'bulk_edit_logic']) {
            eval(fs.readFileSync(`static/${file}.js`, 'utf8'));
        }
        for (const [name, invalid, valid, variants] of [
            ['minecraft:banner', 16, 15, Array.from({length:16}, (_,damage) => ({damage}))],
            ['minecraft:empty_map', 1, 2, [{damage:0}, {damage:2}]],
        ]) {
            const inventory = {0:{slot:0,name:'minecraft:diamond',count:3},1:{slot:1,name:'minecraft:stone',count:4}};
            const before = JSON.stringify(inventory);
            let click, undo = 0, dirty = 0;
            const messages = [];
            const elements = {
                fillButton:{addEventListener(_event, listener) { click = listener; }},
                bulkItemSearch:{value:name},bulkCount:{value:'1'},bulkDamage:{value:String(invalid)},
            };
            window.MCBEBulkEditLogic.createBulkEditController({
                elements,
                itemCatalog:{isValidItemId:()=>true,isAddableItemId:()=>true,getMaxStack:()=>64,
                    getMaxDamage:()=>32767,hasVerifiedStackLimit:()=>true,dataValueVariantsForId:()=>variants},
                getSelectedSlots:()=>[0,1],getInventory:()=>inventory,
                getCurrentSelectionState:()=>({selectedSlots:[0,1]}),
                pushUndo:()=>{undo++;},setDirty:()=>{dirty++;},showToast:message=>messages.push(message),
            }).wire();
            click();
            assert.strictEqual(JSON.stringify(inventory), before);
            assert.strictEqual(undo, 0);
            assert.strictEqual(dirty, 0);
            assert(messages[0].includes('Datenwert'));
            elements.bulkDamage.value = String(valid);
            click();
            assert.strictEqual(undo, 1);
            assert.strictEqual(dirty, 1);
            assert(Object.values(inventory).every(item => item.name === name && item.damage === valid));
        }
        """
    )


def test_frontend_bulk_edit_controller_guards_every_mutation_entrypoint() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, console };
            vm.runInNewContext(
                fs.readFileSync("static/bulk_edit_logic.js", "utf8"),
                context,
                { filename: "static/bulk_edit_logic.js" },
            );

            function button() {
                return {
                    listener: null,
                    addEventListener(_name, handler) { this.listener = handler; },
                };
            }
            const buttons = {
                fillButton: button(),
                clearButton: button(),
                setCountButton: button(),
                repairSelectedButton: button(),
                repairAllButton: button(),
            };
            let guardCalls = 0;
            let undoWrites = 0;
            let dirtyWrites = 0;
            const controller = context.window.MCBEBulkEditLogic.createBulkEditController({
                elements: buttons,
                guardEditingAction: () => { guardCalls += 1; return true; },
                pushUndo: () => { undoWrites += 1; },
                setDirty: () => { dirtyWrites += 1; },
            });
            controller.wire();
            Object.values(buttons).forEach(control => control.listener());

            assert.strictEqual(guardCalls, 5);
            assert.strictEqual(undoWrites, 0);
            assert.strictEqual(dirtyWrites, 0);
            """
        )
    )
