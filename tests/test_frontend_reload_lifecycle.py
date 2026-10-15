"""Exercise write blocking across real controller boundaries, not isolated callbacks."""

import json

import pytest

from tests.node_runner import run_node


@pytest.mark.parametrize(
    "scenario",
    ["reset", "list-rejected", "list-network", "list-only", "readonly", "player-success", "world-success", "world-failed"],
)
def test_reload_lock_survives_reset_and_failed_refresh(scenario: str) -> None:
    run_node(
        f"const scenario = {json.dumps(scenario)};\n"
        + r"""
const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
const context = {window: {}, console: {error() {}}};
for (const name of ['player_view_models', 'player_load_controller', 'write_status_view']) {
    vm.runInNewContext(fs.readFileSync('static/' + name + '.js', 'utf8'), context);
}
(async () => {
    const state = {worldPath: 'world-a', currentPlayerKey: 'a', players: [], isDirty: false};
    let reason = 'Previous write outcome is unknown';
    const gate = context.window.MCBEWriteStatusView.createWriteGateController({
        getCurrentWriteGate: () => ({allowed: true}),
        getCurrentPlayerKey: () => state.currentPlayerKey,
        getCurrentPlayerStaleReason: () => reason,
        setCurrentPlayerStaleReason: value => {reason = value;},
    });
    let blockedWhileReading = null;
    const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
        getState: () => state, setState: patch => Object.assign(state, patch),
        clearLoadedPlayerStaleState: gate.clearLoadedPlayerStaleState,
        api: {
            listPlayers: async () => {
                blockedWhileReading = gate.writeBlocked();
                if (scenario === 'list-network') throw new Error('Disconnected');
                return {success: !['list-rejected', 'world-failed'].includes(scenario), players: []};
            },
            loadPlayer: async (_world, key) => ({success: true, player: {player_key: key}, inventory: {}, stats: {}}),
        },
    });
    assert.equal(gate.writeBlocked(), true);
    if (scenario === 'reset') controller.resetLoadedPlayerState();
    else if (scenario === 'readonly') await controller.selectExportOnlyPlayer({player_key: 'readonly', exportable: true});
    else if (scenario === 'player-success') assert.equal(await controller.loadPlayer('a'), true);
    else if (scenario.startsWith('world-')) await controller.loadWorldFromInput();
    else await controller.loadPlayersList(false);
    if (blockedWhileReading !== null) assert.equal(blockedWhileReading, true, 'Starting a request does not validate stored data');
    assert.equal(gate.writeBlocked(), !['player-success', 'world-success'].includes(scenario),
        'Only a successful player/world read may release the reload lock');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    )


@pytest.mark.parametrize("scenario", ["players-rejected", "players-network", "backups-network", "player-rejected", "success"])
def test_committed_restore_keeps_failed_reload_non_writable(scenario: str) -> None:
    run_node(
        f"const scenario = {json.dumps(scenario)};\n"
        + r"""
const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
let writes = 0;
const context = {window: {}, console: {error() {}}, fetch: async url => {
    if (url === '/api/restore_backup') writes++;
    return {json: async () => ({success: true, backup_token: {version: 1}})};
}};
for (const name of ['api_client', 'player_view_models', 'player_load_controller', 'write_status_view', 'backup_restore_logic']) {
    vm.runInNewContext(fs.readFileSync('static/' + name + '.js', 'utf8'), context);
}
(async () => {
    const state = {worldPath: 'world-a', currentPlayerKey: 'a', players: [], isDirty: false};
    let reason = '';
    const gate = context.window.MCBEWriteStatusView.createWriteGateController({
        getCurrentWriteGate: () => ({allowed: true}),
        getCurrentPlayerKey: () => state.currentPlayerKey,
        getCurrentPlayerStaleReason: () => reason,
        setCurrentPlayerStaleReason: value => {reason = value;},
    });
    const loader = context.window.MCBEPlayerLoadController.createPlayerLoadController({
        getState: () => state, setState: patch => Object.assign(state, patch),
        clearLoadedPlayerStaleState: gate.clearLoadedPlayerStaleState,
        api: {
            listPlayers: async () => {
                if (scenario === 'players-network') throw new Error('List disconnected');
                return {success: scenario !== 'players-rejected', players: [{player_key: 'a', editable: true}]};
            },
            loadPlayer: async (_world, key) => ({
                success: scenario !== 'player-rejected', player: {player_key: key}, inventory: {}, stats: {},
            }),
        },
    });
    const restore = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
        getWorldPath: () => state.worldPath, getCurrentPlayerKey: () => state.currentPlayerKey,
        getPlayers: () => state.players, setPlayers: players => {state.players = players;},
        resetLoadedPlayerState: loader.resetLoadedPlayerState,
        loadPlayersList: loader.loadPlayersList, loadPlayer: loader.loadPlayer,
        loadBackupsList: async () => {if (scenario === 'backups-network') throw new Error('Backups disconnected');},
        markReloadRequired: value => {reason = value;},
        guardWorldWriteAction: () => gate.writeBlocked(),
    });
    await restore.restoreBackup('backup.zip');
    assert.equal(writes, 1);
    assert.equal(gate.writeBlocked(), scenario !== 'success', 'A failed post-restore read must require an explicit reload');
    if (scenario !== 'success') {
        await restore.restoreBackup('backup.zip');
        assert.equal(writes, 1, 'Do not replay the restore while its view is stale');
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    )
