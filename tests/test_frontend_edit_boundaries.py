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
global.document = { getElementById: id => id === 'effectsContainer' ? container : null, createElement: () => new Element() };
for (const file of ['ability_state', 'ability_view', 'effects_view', 'effects_logic', 'undo_redo_controller']) {
    require('./static/' + file + '.js');
}
let effects = [1, 2].map(id => ({ id, amplifier: 0, duration: 200, show_particles: true }));
const clone = value => JSON.parse(JSON.stringify(value));
const undo = MCBEUndoRedoController.createUndoRedoController({ takeSnapshot: () => clone(effects), snapshotHash: JSON.stringify });
const controller = MCBEEffectsLogic.createEffectsAbilitiesController({
    getPlayerEffects: () => effects, getEffectsDb: () => ({ 1: ['A'], 2: ['B'] }), pushUndo: () => undo.pushUndo(),
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
}).wire();
elements.dimensionId.value = '1'; elements.dimensionId.emit('change');
assert.equal(elements.convertLocation.disabled, false);
elements.convertLocation.click();
assert.equal(elements.convertLocation.disabled, true);
elements.convertLocation.click(); // Still disabled until the converted form is accepted.
apply.click();
assert.equal(stats.dimension_id, 1); assert.deepEqual(stats.pos, [10, 64, 20]);
elements.dimensionId.value = '0'; elements.dimensionId.emit('change');
assert.equal(elements.convertLocation.disabled, false);
elements.convertLocation.click(); apply.click();
assert.equal(stats.dimension_id, 0); assert.deepEqual(stats.pos, [80, 64, 160]);
""")
