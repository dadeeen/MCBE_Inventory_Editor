import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../../static/workflow_state.js", import.meta.url), "utf8");
const context = { window: { t: (text) => text } };
vm.runInNewContext(source, context);
const navigation = context.window.MCBEWorkflowState;

const noWorld = {};
const worldOnly = { worldPath: "/worlds/survival" };
const mountReference = { ...worldOnly, currentPlayerKey: "local", currentPlayer: { name: "Alex" } };
const editable = { ...mountReference, inventoryVisible: true };

test("world/player are context prerequisites, not sequential edit steps", () => {
    assert.equal(navigation.viewAllowed("world", noWorld), true);
    assert.equal(navigation.viewAllowed("tools", noWorld), true);
    for (const area of ["player", "inventory", "player-edit", "mounts", "save"]) {
        assert.equal(navigation.viewAllowed(area, noWorld), false, `${area} is unavailable without a world`);
    }
    assert.equal(navigation.viewAllowed("player", worldOnly), true);
    for (const area of ["inventory", "player-edit", "mounts", "save"]) {
        assert.equal(navigation.viewAllowed(area, worldOnly), false, `${area} needs a player`);
    }
});

test("experimental mounts only require a reference player; editing requires editable player", () => {
    assert.equal(navigation.viewAllowed("mounts", mountReference), true);
    assert.equal(navigation.viewAllowed("inventory", mountReference), false);
    assert.equal(navigation.viewAllowed("player-edit", mountReference), false);
    for (const area of ["inventory", "player-edit", "mounts", "save", "player", "world", "tools"]) {
        assert.equal(navigation.viewAllowed(area, editable), true, `${area} is available`);
    }
});

test("editing destinations are independent and save does not require dirty edits", () => {
    for (const requested of ["inventory", "player-edit", "mounts", "tools", "player", "save"]) {
        assert.equal(navigation.resolvedView(requested, editable), requested);
    }
    assert.equal(navigation.resolvedView("player-edit", worldOnly), "player");
    assert.equal(navigation.resolvedView("inventory", noWorld), "world");
    assert.equal(navigation.viewAllowed("save", { ...editable, isDirty: false }), true);
    assert.equal(navigation.disabledReason("save", { ...editable, isDirty: false }), "Keine ungespeicherten Änderungen.");
});
