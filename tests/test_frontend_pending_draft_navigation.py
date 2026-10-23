"""Replacing a loaded player must account for forms not yet applied to state."""

import json

import pytest

from tests.node_runner import run_node


@pytest.mark.parametrize("operation", ["player", "reload", "world", "list", "readonly", "diagnostic"])
@pytest.mark.parametrize("accept", [False, True])
def test_navigation_confirms_pending_forms_and_discards_only_after_acceptance(operation, accept):
    run_node(
        f"const operation = {json.dumps(operation)}, accept = {json.dumps(accept)};\n"
        + r"""
const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
const context = { AbortController, setTimeout, clearTimeout,window: {}, document: {getElementById: () => null}, console,
    localStorage: {getItem: () => null, setItem() {}}};
for (const name of ['player_view_models', 'player_load_controller', 'player_load_app']) {
    vm.runInNewContext(fs.readFileSync('static/' + name + '.js', 'utf8'), context);
}
(async () => {
    const originalInventory = {0: {name: 'minecraft:diamond', count: 3}};
    const state = {worldPath: 'world-a', currentPlayerKey: 'a', currentPlayer: {player_key: 'a'},
        inventory: originalInventory, players: [], isDirty: false};
    let pendingForm = true, confirmations = 0, reads = 0, discarded = 0;
    const app = context.window.MCBEPlayerLoadApp.createInventoryPlayerLoadApp({
        state: {getPlayerLoadState: () => state, assignAppState: patch => Object.assign(state, patch)},
        actions: {
            hasUnsavedChanges: () => state.isDirty || pendingForm,
            discardEditorDrafts: () => {discarded++; pendingForm = false;},
        },
        feedback: {showConfirmDialog: async () => {
            confirmations++;
            assert.equal(reads, 0, 'Ask before replacing or reading a new player context');
            assert.equal(state.inventory, originalInventory, 'The current inventory survives the question');
            assert.equal(pendingForm, true, 'The form remains available if the user cancels');
            return accept;
        }},
        controllerFactory: deps => context.window.MCBEPlayerLoadController.createPlayerLoadController({
            ...deps, elements: {worldPathInput: {value: 'world-b'}},
            api: {
                listPlayers: async () => {reads++; return {success: true, players: []};},
                loadPlayer: async (_world, key) => {
                    reads++; return {success: true, player: {player_key: key}, inventory: {}, stats: {}};
                },
            },
        }),
    });
    const result = operation === 'world' ? await app.loadWorldFromInput()
        : operation === 'list' ? await app.loadPlayersList(false)
        : ['readonly', 'diagnostic'].includes(operation) ? await app.controller.selectReadOnlyPlayer({
            player_key: 'readonly', exportable: operation === 'readonly', reason: 'Not editable',
        }) : await app.loadPlayer(operation === 'reload' ? 'a' : 'b');
    assert.equal(confirmations, 1, 'An unapplied form is an unsaved change');
    assert.equal(result, accept);
    if (!accept) {
        assert.equal(reads, 0);
        assert.equal(discarded, 0);
        assert.equal(pendingForm, true);
        assert.equal(state.inventory, originalInventory);
        assert.equal(state.currentPlayerKey, 'a');
        assert.equal(state.worldPath, 'world-a');
    } else {
        assert.equal(discarded, 1, 'Accepted replacement closes the old nested editor too');
        assert.equal(pendingForm, false);
        assert.notEqual(state.inventory, originalInventory);
    }
    assert.equal(app.isLoading(), false);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    )


def test_failed_player_read_keeps_the_confirmed_form_draft_available():
    run_node(r"""
const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
const context = { AbortController, setTimeout, clearTimeout,window: {}, console: {error() {}}};
for (const name of ['player_view_models', 'player_load_controller']) {
    vm.runInNewContext(fs.readFileSync('static/' + name + '.js', 'utf8'), context);
}
(async () => {
    for (const networkFailure of [false, true]) {
        const state = {worldPath: 'world-a', currentPlayerKey: 'a', isDirty: false};
        let pendingForm = true, confirmations = 0;
        const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
            getState: () => state, setState: patch => Object.assign(state, patch),
            hasUnsavedChanges: () => pendingForm,
            discardEditorDrafts: () => {pendingForm = false;},
            showConfirmDialog: async () => {confirmations++; return true;},
            api: {loadPlayer: async () => {
                if (networkFailure) throw new Error('Disconnected');
                return {success: false, error: 'Player could not be read'};
            }},
        });
        assert.equal(await controller.loadPlayer('b'), false);
        assert.equal(confirmations, 1);
        assert.equal(pendingForm, true, 'A failed read has not replaced the outgoing player');
        assert.equal(state.currentPlayerKey, 'a');
        assert.equal(controller.isLoading(), false);
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
""")
