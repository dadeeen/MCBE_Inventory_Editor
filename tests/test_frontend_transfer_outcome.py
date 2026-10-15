"""Uncertain imports/migrations are not replayable; late refreshes stay scoped."""

import json

import pytest

from tests.node_runner import run_node


@pytest.mark.parametrize("action", ["import", "migration"])
@pytest.mark.parametrize(
    "scenario",
    [
        "network",
        "unreadable",
        "unknown-conflict",
        "retry-network",
        "rejected",
        "changed-world",
        "refresh-failure",
        "refresh-false",
        "changed-refresh",
        "reload-required",
    ],
)
def test_transfer_requires_reload_after_uncertain_outcomes(action: str, scenario: str) -> None:
    script = r"""
    const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
    const {action, scenario} = CONFIG;
    let world = 'world-a', writes = 0, confirms = 0, refreshes = 0;
    const reasons = [], actions = [];
    const panel = {innerHTML: '', style: {}};
    const context = {window: {}, console: {error() {}}};
    for (const file of ['api_client', 'player_view_models', 'player_tools', 'player_transfer_logic']) {
        vm.runInNewContext(fs.readFileSync('static/' + file + '.js', 'utf8'), context);
    }
    const write = async () => {
        writes++;
        if (scenario === 'changed-world') world = 'world-b';
        if (['network', 'changed-world'].includes(scenario)) throw new Error('Disconnected after POST');
        if (scenario === 'unreadable') return {success: false, response_unreadable: true, presence_conflict: true};
        if (scenario === 'unknown-conflict') return {success: false, write_outcome_unknown: true, presence_conflict: true};
        if (scenario === 'retry-network') {
            if (writes === 1) return {success: false, presence_conflict: true};
            throw new Error('Confirmed retry disconnected');
        }
        if (scenario === 'reload-required') return {success: false, reload_required: true, presence_conflict: true, error: 'Reload required'};
        if (scenario === 'rejected') return {success: false, error: 'Request rejected'};
        return {success: true};
    };
    const refresh = async () => {
        refreshes++;
        if (scenario === 'refresh-failure') throw new Error('Refresh failed');
        if (scenario === 'refresh-false') return false;
        if (scenario === 'changed-refresh') {
            world = 'world-b';
            panel.innerHTML = 'Other world';
        }
        return true;
    };
    const common = {
        getWorldPath: () => world,
        getCurrentPlayerKey: () => 'target',
        getIsDirty: () => false,
        showConfirmDialog: async () => true,
        confirmPresenceConflict: async () => { confirms++; return true; },
        markReloadRequired: reason => reasons.push(reason),
        writeBlocked: () => reasons.length > 0,
        recordAction: (...args) => actions.push(args),
    };
    (async () => {
        let run;
        if (action === 'import') {
            context.fetch = async () => ({payload: await write()});
            const controller = context.window.MCBEPlayerTransferLogic.createPlayerTransferController({
                ...common,
                elements: {importPathInput: {value: '/player.zip'}, importAsExportedCheckbox: {checked: false}},
                parseJsonResponse: async response => response.payload,
                getCurrentPlayer: () => ({editable: true}),
                getCurrentPlayerRevision: () => 'base-revision',
                getCurrentImportPreview: () => ({
                    export_path: '/player.zip', world_path: 'world-a', importable: true,
                    import_token: {version: 1}, player: {label: 'Source'},
                }),
                guardWorldWriteAction: () => reasons.length > 0,
                refreshImportedPlayer: refresh,
            });
            run = () => controller.importPlayer();
        } else {
            const controller = context.window.MCBEPlayerTools.createPlayerToolsController({
                ...common,
                elements: {
                    stateTransferSourcePlayerSelect: {value: 'source'},
                    stateTransferTargetPlayerSelect: {value: 'target'},
                    stateTransferApplyButton: {}, stateTransferPreview: panel,
                },
                refreshAfterStateTransfer: refresh,
                getPlayers: () => [
                    {player_key: 'source', label: 'Source', editable: true, kind: 'local'},
                    {player_key: 'target', label: 'Target', editable: true, kind: 'remote'},
                ],
                api: {
                    previewStateTransfer: async () => ({
                        success: true, plan: {groups: []},
                        transfer_token: {source_player_key: 'source', target_player_key: 'target'},
                    }),
                    applyStateTransfer: write,
                },
            });
            assert.equal(await controller.previewStateTransfer(), true);
            actions.length = 0;
            run = () => controller.applyStateTransfer();
        }
        await run();
        const requireReload = !['rejected', 'changed-world', 'changed-refresh'].includes(scenario);
        assert.equal(reasons.length, requireReload ? 1 : 0, 'Only an unresolved outcome in the matching world needs a reload');
        assert.equal(confirms, scenario === 'retry-network' ? 1 : 0, 'Uncertain responses cannot authorize a retry');
        assert.equal(writes, scenario === 'retry-network' ? 2 : 1);
        assert.equal(refreshes, scenario.startsWith('refresh-') || scenario === 'changed-refresh' ? 1 : 0);
        if (scenario === 'changed-refresh') {
            assert.equal(actions.length, 0, 'Do not report the old operation as success in the new world');
            assert.equal(panel.innerHTML, 'Other world');
        }
        if (requireReload) {
            const before = writes;
            await run();
            assert.equal(writes, before, 'Do not replay a write before explicitly reloading');
        }
        console.log('transfer-outcome-check-complete');
    })().catch(error => { console.error(error); process.exitCode = 1; });
    """
    result = run_node(script.replace("CONFIG", json.dumps({"action": action, "scenario": scenario})))
    assert "transfer-outcome-check-complete" in result.stdout


def test_migration_app_refresh_does_not_load_an_old_key_into_a_new_context() -> None:
    result = run_node(r"""
        const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
        const app = fs.readFileSync('static/app.js', 'utf8').replace(/\r\n/g, '\n');
        const match = app.match(/refreshAfterStateTransfer: (async [\s\S]*?\n            }),/);
        assert.ok(match, 'Migration refresh must remain wired to its guarded callback');
        (async () => {
            for (const mode of ['normal', 'list-failed', 'world-changed', 'player-changed', 'no-player']) {
                const loads = [];
                const context = {
                    worldPath: 'world-a', currentPlayerKey: mode === 'no-player' ? '' : 'player-a',
                    loadPlayersList: async () => {
                        if (mode === 'list-failed') return false;
                        context.currentPlayerKey = mode === 'player-changed' ? 'player-b' : '';
                        if (mode === 'world-changed') context.worldPath = 'world-b';
                        return true;
                    },
                    loadPlayer: async key => { loads.push({key, world: context.worldPath}); return true; },
                };
                const refresh = vm.runInNewContext('(' + match[1] + ')', context);
                assert.equal(await refresh('world-a'), ['normal', 'no-player'].includes(mode));
                assert.deepEqual(loads, mode === 'normal' ? [{key: 'player-a', world: 'world-a'}] : []);
            }
            console.log('migration-app-refresh-check-complete');
        })().catch(error => {console.error(error); process.exitCode = 1;});
    """)
    assert "migration-app-refresh-check-complete" in result.stdout
