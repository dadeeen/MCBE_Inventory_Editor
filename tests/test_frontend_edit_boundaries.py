"""Regression checks for live editing and protected bulk operations."""

from tests.node_runner import run_node


def test_effect_undo_keeps_edits_to_other_rows_and_separates_focus_sessions():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
class Element {
    constructor() { this.dataset = {}; this.listeners = {}; this.children = []; }
    set innerHTML(html) {
        this.children = [];
        if (!html.includes('eff-level')) return;
        this.controls = {};
        for (const [name, min, max] of [['level', 1, 256], ['duration', 0, 107374182], ['particles', 0, 1]]) {
            const input = new Element();
            input.type = name === 'particles' ? 'checkbox' : 'number';
            input.min = String(min); input.max = String(max);
            input.value = html.match(new RegExp('class="eff-' + name + '"[^>]*value="([^"]+)"'))?.[1] ?? '';
            input.checked = name === 'particles' && /class="eff-particles"[^>]*checked/.test(html);
            this.controls['.eff-' + name] = input;
        }
        this.controls['.effect-remove'] = new Element();
    }
    querySelector(selector) { return this.controls?.[selector] ?? null; }
    querySelectorAll() { return Object.values(this.controls ?? {}); }
    addEventListener(type, callback) { (this.listeners[type] ??= []).push(callback); }
    emit(type) { for (const callback of this.listeners[type] ?? []) callback({ target: this }); }
    appendChild(element) { this.children.push(element); }
    getAttribute(name) { return this[name] ?? null; }
}
const container = new Element();
global.document = { getElementById: id => id === 'effectsContainer' ? container : null,
    querySelectorAll: () => container.children, createElement: () => new Element() };
for (const file of ['ability_state', 'ability_view', 'effects_view', 'effects_logic', 'undo_redo_controller']) {
    require('./static/' + file + '.js');
}
let effects = [1, 2].map(id => ({ id, amplifier: 0, duration: 200, show_particles: true }));
const clone = value => JSON.parse(JSON.stringify(value));
const undo = MCBEUndoRedoController.createUndoRedoController({ takeSnapshot: () => clone(effects), snapshotHash: JSON.stringify });
const controller = MCBEEffectsLogic.createEffectsAbilitiesController({
    getPlayerEffects: () => effects, getEffectsDb: () => ({ 1: ['A'], 2: ['B'] }),
    pushUndo: (...args) => undo.pushUndo(...args), finishUndoGroup: key => undo.finishUndoGroup(key),
});
controller.renderEffectsList();
function edit(index, seconds, blur = true) {
    const input = container.children[index].querySelector('.eff-duration');
    input.value = String(seconds); input.emit('input');
    if (blur) input.emit('blur');
}
edit(0, 20); edit(1, 30); edit(0, 40);
effects = undo.undo().snapshot;
assert.deepEqual(effects.map(effect => effect.duration), [400, 600]);
effects = undo.redo().snapshot;
assert.deepEqual(effects.map(effect => effect.duration), [800, 600]);
controller.renderEffectsList();
edit(0, 50, false); edit(0, 60); // Typing in one focused control is one action.
effects = undo.undo().snapshot;
assert.deepEqual(effects.map(effect => effect.duration), [800, 600]);
controller.renderEffectsList();
edit(0, 50); edit(0, 60); // Refocusing the same control starts another action.
effects = undo.undo().snapshot;
assert.deepEqual(effects.map(effect => effect.duration), [1000, 600]);
controller.renderEffectsList();
const particles = container.children[0].querySelector('.eff-particles');
particles.checked = false; particles.emit('change');
particles.checked = true; particles.emit('change');
effects = undo.undo().snapshot;
assert.equal(effects[0].show_particles, false);
""")


def test_repair_all_skips_protected_slots_in_the_correct_container():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/inventory_state.js');
require('./static/bulk_edit_logic.js');
const item = () => ({ name: 'minecraft:diamond_helmet', count: 1, damage: 100 });
const inventory = { 0: item(), 103: { ...item(), root_equipment_read_only: true } };
const ender = { 0: item(), 1: item() };
const button = { addEventListener(type, callback) { this.click = callback; } };
let snapshots = 0, dirty = 0;
const messages = [];
const controller = MCBEBulkEditLogic.createBulkEditController({
    elements: { repairAllButton: button }, getInventory: () => inventory, getEnderChestInventory: () => ender,
    getMaxDamage: () => ({ 'minecraft:diamond_helmet': 363 }), itemIsVisiblePresent: entry => entry?.count > 0,
    isProtectedKnownSlot: (slot, container) => container === 'inventory' ? slot === 103 : slot === 0,
    pushUndo: () => snapshots++, setDirty: () => dirty++, logStatus: message => messages.push(message),
});
controller.wire(); button.click();
assert.equal(inventory[0].damage, 0);
assert.equal(inventory[103].damage, 100);
assert.equal(ender[0].damage, 100);
assert.equal(ender[1].damage, 0);
assert.equal(snapshots, 1); assert.equal(dirty, 1);
assert.match(messages[0], /Items: 2 /);
button.click(); // Only protected damaged items remain: no change and no undo entry.
assert.equal(snapshots, 1); assert.equal(dirty, 1);
""")


def test_location_conversion_can_reverse_after_apply_without_double_conversion():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
class Element {
    constructor(type = 'number') {
        this.type = type; this.value = ''; this.disabled = false; this.listeners = {}; this.dataset = {}; this.min = ''; this.max = '';
    }
    addEventListener(type, callback) { (this.listeners[type] ??= []).push(callback); }
    emit(type) { for (const callback of this.listeners[type] ?? []) callback({ target: this }); }
    click() { if (!this.disabled) this.emit('click'); }
    getAttribute(name) { return this[name] ?? null; }
}
const elements = Object.fromEntries([
    'dimensionId', 'posX', 'posY', 'posZ', 'health', 'xpLevel', 'xpProgress', 'foodLevel', 'foodSaturation',
    'convertLocation', 'convertLocationNote',
].map(key => [key, new Element()]));
elements.dimensionId.type = 'select-one';
const apply = new Element('button');
global.document = { getElementById: id => id === 'btnApplyStats' ? apply : null, querySelectorAll: () => [] };
for (const file of ['ability_state', 'ability_view', 'effects_view', 'effects_logic']) require('./static/' + file + '.js');
let stats = { dimension_id: 0, pos: [80, 64, 160], health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 20 };
const form = MCBEEffectsLogic.createStatsFormController({ elements, getPlayerStats: () => stats });
form.wireTouchedTracking(); form.render();
MCBEEffectsLogic.createEffectsAbilitiesController({
    statsFormElements: () => elements, getTouchedStatsFields: () => form.touchedFields,
    getPlayerStats: () => stats, setPlayerStats: value => { stats = value; }, getProtectedNbt: () => ({}),
    onStatsApplied: () => form.resetConversion(),
}).wire();
const beforeConversion = { dimension: elements.dimensionId.value, x: elements.posX.value, z: elements.posZ.value };
assert.equal(elements.convertLocation.disabled, false);
elements.convertLocation.click();
assert.equal(elements.convertLocation.disabled, false);
assert.equal(elements.dimensionId.value, '1');
assert.equal(elements.posX.value, '10');
elements.convertLocation.click(); // Undo the draft, never divide it a second time.
assert.equal(elements.dimensionId.value, beforeConversion.dimension);
assert.equal(elements.posX.value, beforeConversion.x);
assert.equal(elements.posZ.value, beforeConversion.z);
elements.convertLocation.click();
apply.click();
assert.equal(stats.dimension_id, 1); assert.deepEqual(stats.pos, [10, 64, 20]);
assert.equal(elements.convertLocation.disabled, false);
elements.convertLocation.click(); apply.click();
assert.equal(stats.dimension_id, 0); assert.deepEqual(stats.pos, [80, 64, 160]);
""")


def test_modal_dialogs_keep_global_edit_shortcuts_out_of_the_editor():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/workflow_state.js');
let modalOpen = true;
let nativeDialog = true;
const calls = [];
const keyboard = MCBEWorkflowState.createAppKeyboardController({
    doc: {
        querySelector: selector => selector === 'dialog[open]' && nativeDialog && modalOpen ? {} : null,
        querySelectorAll: () => [{ getClientRects: () => !nativeDialog && modalOpen ? [{}] : [] }],
    },
    undo: () => calls.push('undo'), redo: () => calls.push('redo'),
    saveButton: { click: () => calls.push('save') },
    clearSelection: () => calls.push('clear'), hasSelection: () => true,
    inventoryClipboardController: { handleKeydown: () => { calls.push('clipboard'); return false; } },
});
const press = (key, ctrlKey = false) => {
    let prevented = false;
    keyboard.handleKeydown({ key, ctrlKey, target: { matches: () => false },
        preventDefault: () => { prevented = true; } });
    return prevented;
};
for (nativeDialog of [true, false]) {
    for (const key of ['z', 'y', 'c', 'v']) press(key, true);
    assert.equal(press('s', true), true); // Do not open the browser's Save Page dialog.
    assert.equal(press('Escape'), false); // The dialog owns Escape.
    assert.deepEqual(calls, []);
}
modalOpen = false;
press('z', true);
assert.deepEqual(calls, ['undo']);
""")


def test_workspace_shortcut_obeys_native_custom_and_loading_modals():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/workflow_state.js');
require('./static/workspace_view.js');
let nativeOpen = false, overlayOpen = false, opens = 0, handler;
const doc = {
    querySelector: () => nativeOpen ? {} : null,
    querySelectorAll: () => [{ getClientRects: () => overlayOpen ? [{}] : [] }],
    addEventListener: (name, callback) => { handler = callback; },
};
MCBEWorkspaceView.createWorkspaceController({ openWorkspaceDashboard: () => opens++ }).wireActions({ doc });
for (const flags of [{ctrlKey: true}, {metaKey: true}]) {
    const press = () => handler({ key: 'P', shiftKey: true, ...flags, preventDefault() {} });
    nativeOpen = true; press();
    nativeOpen = false; overlayOpen = true; press();
    assert.equal(opens, 0);
}
overlayOpen = false;
handler({ key: 'p', ctrlKey: true, shiftKey: true, preventDefault() {} });
assert.equal(opens, 1);
""")
