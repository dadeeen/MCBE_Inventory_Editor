import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const context = { window: {} };
for (const name of ["html_utils", "villager_model", "villager_inventory"]) {
    vm.runInNewContext(readFileSync(`static/${name}.js`, "utf8"), context, { filename: name });
}
const inventoryModel = context.window.MCBEVillagerInventory;
const plain = value => JSON.parse(JSON.stringify(value));
function inventory() {
    return { capacity: 8, present: true, editable: true,
        allowed_items: [{ name: "minecraft:bread", label: "Brot", max_count: 64 }, { name: "minecraft:carrot", label: "Karotte", max_count: 64 }],
        slots: Array.from({ length: 8 }, (_, slot) => ({ slot, item: slot === 0 ? { name: "minecraft:bread", count: 12 } : null, editable: slot !== 7 })),
    };
}

test("supply patches contain only changed editable slots and clear explicitly", () => {
    const data = inventory();
    const drafts = { 0: { name: "minecraft:bread", count: "12" }, 1: { name: "minecraft:carrot", count: "64" }, 7: { name: "minecraft:bread", count: "3" } };
    assert.deepEqual(plain(inventoryModel.changes(data, drafts)), [{ slot: 1, item: { name: "minecraft:carrot", count: 64 } }]);
    drafts[0] = { name: "", count: "0" };
    assert.deepEqual(plain(inventoryModel.changes(data, drafts)), [{ slot: 0, item: null }, { slot: 1, item: { name: "minecraft:carrot", count: 64 } }]);
    assert.equal(data.slots[0].item.count, 12);
});

test("unchanged supply forms and protected containers cannot create a preview", () => {
    const data = inventory();
    assert.throws(() => inventoryModel.changes(data, { 0: { name: "minecraft:bread", count: "12" } }), /keine Vorratsänderung/);
    assert.throws(() => inventoryModel.changes({ ...data, editable: false, reason: "Protected" }, { 0: { name: "", count: "0" } }), /Protected/);
});

for (const count of ["", "0", "-1", "65", "1.5", "Infinity", "text"]) {
    test(`supply quantity ${JSON.stringify(count)} cannot be previewed`, () => {
        assert.throws(() => inventoryModel.changes(inventory(), { 0: { name: "minecraft:bread", count } }), /Platz 1/);
    });
}

test("incomplete numbers remain dirty and unknown or unavailable items are refused", () => {
    const data = inventory();
    assert.equal(inventoryModel.slotDiffers(data.slots[0], { name: "minecraft:bread", count: "12", invalid: true }), true);
    assert.throws(() => inventoryModel.changes(data, { 0: { name: "minecraft:bread", count: "12", invalid: true } }), /Platz 1/);
    assert.throws(() => inventoryModel.changes(data, { 0: { name: "minecraft:diamond", count: "1" } }), /Platz 1/);
    data.allowed_items[0].max_count = 16;
    assert.throws(() => inventoryModel.changes(data, { 0: { name: "minecraft:bread", count: "17" } }), /16/);
});

test("inventory rendering escapes untrusted labels and protected contents", () => {
    const data = inventory();
    data.allowed_items[0].label = '<img src=x onerror="bad()">';
    data.slots[7].item = { name: "<script>bad()</script>", count: 3 };
    const html = inventoryModel.editorHtml(data);
    assert.ok(!html.includes("<img") && !html.includes("<script>"));
    assert.ok(html.includes("&lt;img"));
    assert.ok(!html.includes('id="villagerStockItem7"'));
    const preview = inventoryModel.snapshotHtml({ slots: [{ slot: 7, item: data.slots[7].item }] }, data);
    assert.ok(!preview.includes("<script>"));
    assert.ok(preview.includes("Platz 8"));
});

test("the editable filter includes independent supplies without enabling health", () => {
    const rows = [{ id: "stock", editable: false, inventory_editable: true }, { id: "protected", editable: false, inventory_editable: false }];
    assert.deepEqual(plain(context.window.MCBEVillagerModel.filterRows(rows, { editable: true })), [rows[0]]);
});
