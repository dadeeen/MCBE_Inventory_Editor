"""Regression coverage for import, restore and asynchronous editor workflows."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _node(source, **params):
    result = subprocess.run(
        ["node", "-e", "const params = " + json.dumps(params) + ";\n" + source],
        cwd=ROOT, text=True, capture_output=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'workflow-check-complete' in result.stdout, 'Asynchronous assertions did not finish'


@pytest.mark.parametrize("phase", ["confirm", "response", "conflict", "retry"])
@pytest.mark.parametrize("change", ["world", "player", "dirty", "revision"])
def test_import_does_not_use_an_outdated_editor_context(phase, change):
    _node(r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const state = { world: 'world-A', player: 'player-A', dirty: false, revision: 'a'.repeat(64) };
const calls = [];
let changed = false;
const change = () => {
    changed = true;
    if (params.change === 'dirty') state.dirty = true;
    else state[params.change] = params.change === 'revision' ? 'b'.repeat(64) : 'B';
};
const ctx = { window: {}, console, fetch: async (url, options) => {
    calls.push('request');
    if (params.phase === 'response') change();
    if (params.phase === 'retry' && calls.filter(x => x === 'request').length === 2) change();
    const conflict = ['conflict', 'retry'].includes(params.phase) && calls.filter(x => x === 'request').length === 1;
    return { data: conflict ? { success: false, presence_conflict: true } : {
        success: true, write_gate: { allowed: false }, write_committed: true,
    } };
} };
vm.runInNewContext(fs.readFileSync('static/player_transfer_logic.js', 'utf8'), ctx);
const forbidden = name => { calls.push(name); };
const controller = ctx.window.MCBEPlayerTransferLogic.createPlayerTransferController({
    elements: { importPathInput: { value: 'export.zip' }, importAsExportedCheckbox: { checked: false } },
    parseJsonResponse: async r => r.data,
    getWorldPath: () => state.world,
    getCurrentPlayerKey: () => state.player,
    getCurrentPlayer: () => ({ editable: true }),
    getCurrentPlayerRevision: () => state.revision,
    getIsDirty: () => state.dirty,
    getCurrentImportPreview: () => ({
        export_path: 'export.zip', world_path: 'world-A', importable: true, import_token: { version: 1 },
    }),
    showConfirmDialog: async () => { if (params.phase === 'confirm') change(); return true; },
    confirmPresenceConflict: async () => { if (params.phase === 'conflict') change(); return true; },
    renderServerStatus: () => forbidden('render-status'),
    refreshImportedPlayer: async () => forbidden('reload'),
    recordAction: () => forbidden('record'),
});
(async () => {
    await controller.importPlayer();
    assert.ok(changed, 'test did not reach the intended asynchronous boundary');
    const expectedRequests = params.phase === 'confirm' && params.change === 'dirty' ? 0 : params.phase === 'retry' ? 2 : 1;
    assert.strictEqual(calls.filter(x => x === 'request').length, expectedRequests);
    assert.ok(!calls.includes('render-status'), 'stale write gate was applied');
    assert.ok(!calls.includes('reload'), 'stale import reloaded the player');
    assert.ok(!calls.includes('record'), 'stale import changed the action history');
})().then(() => console.log('workflow-check-complete')).catch(e => { console.error(e); process.exit(1); });
''', phase=phase, change=change)


@pytest.mark.parametrize("phase", ["response", "conflict", "retry", "players", "backups", "presence", "player_load"])
@pytest.mark.parametrize("change", ["world", "player"])
def test_restore_does_not_update_a_different_context(phase, change):
    _node(r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let world = 'world-A';
let player = 'player-A';
let changed = false;
let restoreRequests = 0;
const calls = [];
const change = () => { if (params.change === 'world') world = 'world-B'; player = 'player-B'; changed = true; };
const record = name => { calls.push([name, changed]); };
const ctx = { window: {}, console, fetch: async url => {
    if (url.includes('restore_preview')) return { data: { success: true, backup_token: { version: 1 } } };
    restoreRequests += 1;
    if (params.phase === 'response' || (params.phase === 'retry' && restoreRequests === 2)) change();
    const conflict = ['conflict', 'retry'].includes(params.phase) && restoreRequests === 1;
    return { data: conflict ? { success: false, presence_conflict: true } : { success: true, write_gate: { allowed: false } } };
} };
vm.runInNewContext(fs.readFileSync('static/backup_restore_logic.js', 'utf8'), ctx);
const controller = ctx.window.MCBEBackupRestoreLogic.createBackupRestoreController({
    parseJsonResponse: async r => r.data,
    getWorldPath: () => world,
    getCurrentPlayerKey: () => player,
    getPlayers: () => params.phase === 'presence' ? [] : [{ player_key: 'player-A', editable: true }],
    resetLoadedPlayerState: () => { record('reset'); player = ''; },
    setPlayers: () => record('set-players'),
    renderWriteGate: () => record('gate'),
    confirmPresenceConflict: async () => { if (params.phase === 'conflict') change(); return true; },
    loadPlayersList: async () => { record('players'); if (params.phase === 'players') change(); return true; },
    loadBackupsList: async () => { record('backups'); if (params.phase === 'backups') change(); },
    updateWorldPresence: async () => { record('presence'); if (params.phase === 'presence') change(); },
    loadPlayer: async key => { record('player-load'); player = key; if (params.phase === 'player_load') change(); },
    setWorkflowView: () => record('workflow'),
    showToast: (message, type) => { if (type === 'success') record('success-toast'); },
});
(async () => {
    await controller.restoreBackup('selected.zip');
    assert.ok(changed, 'test did not reach the intended asynchronous boundary');
    assert.deepStrictEqual(calls.filter(([name, afterChange]) => afterChange), []);
    assert.strictEqual(restoreRequests, params.phase === 'retry' ? 2 : 1);
})().then(() => console.log('workflow-check-complete')).catch(e => { console.error(e); process.exit(1); });
''', phase=phase, change=change)


@pytest.mark.parametrize("phase", ["list_failure", "context_change", "player_failure", "success"])
def test_import_refresh_wiring_stops_on_failed_or_outdated_player_list(phase):
    _node(r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/app.js', 'utf8');
const match = source.match(/refreshImportedPlayer: (async [\s\S]*?\n        }),\n/);
assert.ok(match, 'production refresh callback missing');
let current = true;
let loads = 0;
const refresh = vm.runInNewContext('(' + match[1] + ')', {
    loadPlayersList: async () => {
        if (params.phase === 'context_change') current = false;
        return params.phase !== 'list_failure';
    },
    loadPlayer: async () => { loads += 1; return params.phase !== 'player_failure'; },
});
(async () => {
    const result = await refresh('player-A', () => current);
    assert.strictEqual(loads, ['list_failure', 'context_change'].includes(params.phase) ? 0 : 1);
    if (params.phase === 'success') assert.notStrictEqual(result, false);
    else assert.strictEqual(result, false);
})().then(() => console.log('workflow-check-complete')).catch(e => { console.error(e); process.exit(1); });
''', phase=phase)


@pytest.mark.parametrize("action", ["browse", "manual", "toggle", "remove"])
@pytest.mark.parametrize("failure", ["server", "transport"])
def test_scan_path_failures_are_visible_without_success_refresh(action, failure):
    _node(r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const context = { window: {}, console, fetch: () => {} };
vm.runInNewContext(fs.readFileSync('static/scan_paths_controller.js', 'utf8'), context);
const button = () => ({ listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } });
const browseButton = button();
const confirmButton = button();
const toggle = Object.assign(button(), { checked: true, dataset: { path: 'world-A' } });
const remove = Object.assign(button(), { dataset: { path: 'world-A' } });
const status = { textContent: '' };
let refreshes = 0;
const controller = context.window.MCBEScanPathsController.createScanPathsController({
    elements: {
        browseButton, confirmButton, status,
        textInput: { value: 'world-A' }, manualInput: { style: {} },
        list: { innerHTML: '', querySelectorAll: s => s.includes('toggle') ? [toggle] : [remove] },
    },
    fetchImpl: async url => {
        if (url.includes('pick_folder')) return { data: { success: true, path: 'world-A' } };
        if (url === '/api/scan_paths') return { data: { success: true, scan_roots: [] } };
        if (params.failure === 'transport') throw new Error('network offline');
        return { data: { success: false, error: 'permission denied' } };
    },
    parseJsonResponse: async r => r.data,
    withCsrf: () => ({}), scanPathsHtml: () => '',
    consoleObj: { error() {} },
    scanWorlds: async () => { refreshes += 1; },
});
controller.wire();
controller.renderScanPaths({});
(async () => {
    if (params.action === 'browse') await browseButton.listeners.click();
    if (params.action === 'manual') await confirmButton.listeners.click();
    if (params.action === 'toggle') await toggle.listeners.change();
    if (params.action === 'remove') await remove.listeners.click();
    assert.ok(status.textContent.length > 0, 'failure hidden from the user');
    assert.strictEqual(refreshes, 0, 'failed operation triggered success refresh');
    if (params.action === 'toggle') assert.strictEqual(toggle.checked, false);
})().then(() => console.log('workflow-check-complete')).catch(e => { console.error(e); process.exit(1); });
''', action=action, failure=failure)


@pytest.mark.parametrize("new_player", [False, True])
@pytest.mark.parametrize("refresh", ["failure", "world_change", "dirty_change", "success"])
def test_import_refresh_outcome_is_not_reported_as_a_different_result(new_player, refresh):
    _node(r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const state = { world: 'world-A', player: 'player-A', revision: 'a'.repeat(64), dirty: false };
const statuses = [];
const actions = [];
const ctx = { window: {}, console, fetch: async () => ({ data: { success: true, write_committed: true } }) };
vm.runInNewContext(fs.readFileSync('static/player_transfer_logic.js', 'utf8'), ctx);
const controller = ctx.window.MCBEPlayerTransferLogic.createPlayerTransferController({
    elements: { importPathInput: { value: 'export.zip' }, importAsExportedCheckbox: { checked: params.new_player } },
    parseJsonResponse: async r => r.data,
    getWorldPath: () => state.world, getCurrentPlayerKey: () => state.player,
    getCurrentPlayer: () => ({ editable: true }), getCurrentPlayerRevision: () => state.revision,
    getIsDirty: () => state.dirty,
    getCurrentImportPreview: () => ({
        export_path: 'export.zip', world_path: 'world-A', importable: true, import_token: { version: 1 },
        player: { player_key: 'exported-player' },
    }),
    showConfirmDialog: async () => true,
    refreshImportedPlayer: async (key, contextIsCurrent) => {
        if (params.refresh === 'world_change') { state.world = 'world-B'; return false; }
        if (params.refresh === 'dirty_change') { state.dirty = true; return false; }
        if (params.refresh === 'failure') return false;
        if (typeof contextIsCurrent === 'function') assert.strictEqual(contextIsCurrent(), true);
        state.player = key;
        state.revision = 'b'.repeat(64);
        return true;
    },
    logStatus: (message, type) => statuses.push({ message, type }),
    recordAction: (...args) => actions.push(args),
});
(async () => {
    await controller.importPlayer();
    if (params.refresh === 'failure') {
        assert.ok(statuses.some(s => s.type === 'warning' && s.message.includes('Spieleransicht')),
            'a failed reload was silently presented as complete success');
    } else if (params.refresh.endsWith('change')) {
        assert.deepStrictEqual(actions, [], 'a different view received the old import history');
        assert.ok(!statuses.some(s => s.type === 'success'));
    } else {
        assert.strictEqual(actions.length, 1);
        assert.ok(statuses.some(s => s.type === 'success'));
    }
})().then(() => console.log('workflow-check-complete')).catch(e => { console.error(e); process.exit(1); });
''', new_player=new_player, refresh=refresh)


@pytest.mark.parametrize("new_player", [False, True])
@pytest.mark.parametrize("phase", [
    "success", "list_failure", "player_failure", "world_change", "player_change", "dirty_change", "revision_change", "selection_change",
])
def test_import_refresh_uses_real_loader_reset_and_preserves_new_context(new_player, phase):
    _node(r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const state = {worldPath: 'world-A', currentPlayerKey: 'player-A', currentPlayerRevision: 'a'.repeat(64),
    currentPlayer: {editable: true}, isDirty: false, players: []};
const pathInput = {value: 'export.zip'};
const calls = [], messages = [], actions = [];
const target = params.new_player ? 'player-B' : 'player-A';
const context = {window: {}, console, fetch: async () => {
    calls.push('import');
    return {data: {success: true, write_committed: true}};
}};
for (const name of ['player_view_models', 'player_load_controller', 'player_transfer_logic']) {
    vm.runInNewContext(fs.readFileSync(`static/${name}.js`, 'utf8'), context);
}
const loader = context.window.MCBEPlayerLoadController.createPlayerLoadController({
    getState: () => state, setState: patch => Object.assign(state, patch),
    api: {
        listPlayers: async () => {
            calls.push('list');
            assert.equal(state.currentPlayerKey, '', 'real list refresh must reset the old selection');
            assert.equal(state.currentPlayerRevision, '');
            if (params.phase === 'world_change') state.worldPath = 'world-B';
            if (params.phase === 'player_change') state.currentPlayerKey = 'other-player';
            if (params.phase === 'dirty_change') { state.isDirty = true; state.inventory = {draft: 'keep'}; }
            if (params.phase === 'revision_change') state.currentPlayerRevision = 'c'.repeat(64);
            if (params.phase === 'selection_change') pathInput.value = 'another-export.zip';
            return {success: params.phase !== 'list_failure', players: [{player_key: target, editable: true}]};
        },
        loadPlayer: async (_world, key) => {
            calls.push('load');
            return {success: params.phase !== 'player_failure', player: {player_key: key, editable: true},
                player_revision: 'b'.repeat(64), inventory: {}, stats: {}};
        },
    },
});
const callback = fs.readFileSync('static/app.js', 'utf8').match(/refreshImportedPlayer: (async [\s\S]*?\n        }),\n/);
assert.ok(callback);
const refresh = vm.runInNewContext('(' + callback[1] + ')', {
    loadPlayersList: (...args) => loader.loadPlayersList(...args), loadPlayer: (...args) => loader.loadPlayer(...args),
});
const importer = context.window.MCBEPlayerTransferLogic.createPlayerTransferController({
    elements: {importPathInput: pathInput, importAsExportedCheckbox: {checked: params.new_player}},
    parseJsonResponse: async response => response.data,
    getWorldPath: () => state.worldPath, getCurrentPlayerKey: () => state.currentPlayerKey,
    getCurrentPlayerRevision: () => state.currentPlayerRevision, getCurrentPlayer: () => state.currentPlayer,
    getIsDirty: () => state.isDirty,
    getCurrentImportPreview: () => ({export_path: 'export.zip', world_path: 'world-A', importable: true,
        import_token: {version: 1}, player: {player_key: 'player-B'}}),
    showConfirmDialog: async () => true, refreshImportedPlayer: refresh,
    logStatus: (message, type) => messages.push({message, type}), recordAction: message => actions.push(message),
});
(async () => {
    await importer.importPlayer();
    const shouldLoad = ['success', 'player_failure'].includes(params.phase);
    assert.deepEqual(calls, shouldLoad ? ['import', 'list', 'load'] : ['import', 'list']);
    if (params.phase === 'success') {
        assert.equal(state.currentPlayerKey, target);
        assert.equal(state.currentPlayerRevision, 'b'.repeat(64));
        assert.equal(messages.at(-1).type, 'success');
        assert.equal(actions.length, 1);
    } else if (params.phase.endsWith('failure')) {
        assert.equal(state.currentPlayerKey, '');
        assert.match(messages.at(-1).message, /Import wurde gespeichert, aber die Spieleransicht/);
        assert.equal(messages.at(-1).type, 'warning');
    } else {
        assert.deepEqual(actions, []);
        assert.ok(!messages.some(entry => entry.type === 'success'));
        if (params.phase === 'world_change') assert.equal(state.worldPath, 'world-B');
        if (params.phase === 'player_change') assert.equal(state.currentPlayerKey, 'other-player');
        if (params.phase === 'dirty_change') { assert.equal(state.isDirty, true); assert.deepEqual(state.inventory, {draft: 'keep'}); }
        if (params.phase === 'revision_change') assert.equal(state.currentPlayerRevision, 'c'.repeat(64));
        if (params.phase === 'selection_change') assert.equal(pathInput.value, 'another-export.zip');
    }
})().then(() => console.log('workflow-check-complete')).catch(error => {console.error(error); process.exitCode = 1;});
''', new_player=new_player, phase=phase)


@pytest.mark.parametrize("change", ["world", "player"])
def test_import_failed_rollback_keeps_error_and_backup_after_context_change(change):
    _node(r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const state = {world: 'world-A', player: 'player-A'};
const messages = [], mutations = [];
const context = {window: {}, console, fetch: async () => {
    state[params.change] = 'new-context';
    return {data: {success: false, write_committed: true, error: 'Import validation failed',
        rollback_warning: 'Import-Rollback unvollständig: Datenbank gesperrt', backup_file: 'world_before_import.zip'}};
}};
vm.runInNewContext(fs.readFileSync('static/player_transfer_logic.js', 'utf8'), context);
const controller = context.window.MCBEPlayerTransferLogic.createPlayerTransferController({
    elements: {importPathInput: {value: 'export.zip'}, importAsExportedCheckbox: {checked: false}},
    parseJsonResponse: async response => response.data,
    getWorldPath: () => state.world, getCurrentPlayerKey: () => state.player,
    getCurrentPlayerRevision: () => 'a'.repeat(64), getCurrentPlayer: () => ({editable: true}), getIsDirty: () => false,
    getCurrentImportPreview: () => ({export_path: 'export.zip', world_path: 'world-A', importable: true, import_token: {version: 1}}),
    showConfirmDialog: async () => true,
    refreshImportedPlayer: async () => mutations.push('reload'), recordAction: () => mutations.push('history'),
    renderServerStatus: () => mutations.push('status'), logStatus: (message, type) => messages.push({message, type}),
});
(async () => {
    await controller.importPlayer();
    const outcome = messages.at(-1);
    assert.equal(outcome.type, 'error');
    assert.match(outcome.message, /ursprünglichen Zielspieler/);
    assert.match(outcome.message, /Import validation failed/);
    assert.match(outcome.message, /Rollback unvollständig/);
    assert.match(outcome.message, /world_before_import\.zip/);
    assert.deepEqual(mutations, []);
    assert.equal(state[params.change], 'new-context');
})().then(() => console.log('workflow-check-complete')).catch(error => {console.error(error); process.exitCode = 1;});
''', change=change)
