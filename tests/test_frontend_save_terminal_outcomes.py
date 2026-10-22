"""A server reload requirement or confirmed commit must never be replayed."""

import json

import pytest

from tests.node_runner import run_node


@pytest.mark.parametrize("with_mounts", [False, True])
@pytest.mark.parametrize("confirmation", ["none", "server", "presence", "both"])
@pytest.mark.parametrize("outcome", ["reload", "committed", "committed-reload", "success-reload"])
def test_terminal_save_outcomes_block_retries_and_preserve_the_known_result(with_mounts, confirmation, outcome):
    result = run_node(
        f"const config = {json.dumps({'mounts': with_mounts, 'confirmation': confirmation, 'outcome': outcome})};\n"
        + r"""
const assert = require('node:assert/strict'), fs = require('fs'), vm = require('vm');
const context = {window: {}, console: {error() {}}};
for (const name of ['api_client', 'save_controller']) {
    vm.runInNewContext(fs.readFileSync('static/' + name + '.js', 'utf8'), context);
}
(async () => {
    const committed = config.outcome !== 'reload';
    const body = {
        success: config.outcome === 'success-reload',
        error: committed ? 'Written, but this player must be reloaded' : 'Player snapshot is stale; reload required',
        backup_file: 'retained.zip', player_revision: 'written-revision',
        ...(config.outcome.includes('committed') ? {write_committed: true, validation_failed: true} : {}),
        ...(config.outcome.includes('reload') ? {reload_required: true} : {}),
        ...(['server', 'both'].includes(config.confirmation)
            ? {write_gate: {requires_unknown_server_confirmation: true}} : {}),
        ...(['presence', 'both'].includes(config.confirmation) ? {presence_conflict: true} : {}),
        mounts: config.mounts && committed ? [{actor_id: 'written-actor'}] : [],
    };
    const noop = () => {};
    let posts = 0, dialogs = 0, dirty = true, reason = '', revision = 'loaded-revision';
    let cleaned = 0, normalized = 0, finalized = 0;
    let pendingMounts = config.mounts ? [{id: 'draft-horse', worldPath: 'world', playerKey: 'player'}] : [];
    const statuses = [], buttonStates = [];
    const controller = context.window.MCBESaveController.createSaveController({
        getWorldPath: () => 'world', getCurrentPlayerKey: () => 'player',
        getIsDirty: () => dirty, getPendingMounts: () => pendingMounts,
        getCurrentWriteGate: () => ({}), writeBlocked: () => Boolean(reason),
        getCreateRequiresConfirmation: () => ({}),
        buildSavePayload: () => ({stats: {health: 18}, base_revision: 'loaded-revision'}),
        payloadContainsUserChanges: () => true, buildChangeSummary: () => ({}),
        validateInventoryState: () => ({errors: 0}),
        showConfirmDialog: async () => {dialogs++; return true;},
        confirmPresenceConflict: async () => {dialogs++; return true;},
        postSavePayload: async () => {posts++; return body;},
        markReloadRequired: value => {reason = value;},
        markCleanState: () => {cleaned++; dirty = false;},
        updateCurrentPlayerRevision: value => {revision = value;},
        normalizeOriginsToCurrentSavedState: () => {normalized++;},
        finalizePendingMounts: () => {finalized++; pendingMounts = []; return {complete: true};},
        applyCreatedTagState: noop, updateWorldPresence: async () => {},
        setPrimarySaveDisabled: disabled => buttonStates.push(disabled),
        setReviewConfirmDisabled: noop, showLoading: noop, hideLoading: noop,
        renderWriteGate: noop, updateWriteControls: noop, loadBackupsList: noop,
        logStatus: (message, type) => statuses.push({message, type}),
        showToast: noop, recordAction: noop, flashSaveButton: noop,
    });
    await controller.saveCurrentPlayer({skipReview: true});
    assert.equal(posts, 1, 'A terminal response must never cause a second POST');
    assert.equal(dialogs, 0, 'Consent cannot settle an already written or stale operation');
    assert.ok(reason, 'Further writes stay blocked until a fresh player read');
    assert.equal(revision, committed ? 'written-revision' : 'loaded-revision');
    assert.equal(cleaned, committed ? 1 : 0);
    assert.equal(normalized, committed ? 1 : 0);
    assert.equal(finalized, config.mounts && committed ? 1 : 0);
    assert.equal(pendingMounts.length, config.mounts && !committed ? 1 : 0);
    assert.equal(statuses.at(-1).type, 'error');
    assert.ok(!buttonStates.includes(false), 'Do not briefly offer an unsafe retry');
    await controller.saveCurrentPlayer({skipReview: true});
    assert.equal(posts, 1, 'Clicking Save again cannot replay the request');
    assert.equal(controller.isSaving(), false);
    console.log('terminal-save-outcomes-complete');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    )
    assert "terminal-save-outcomes-complete" in result.stdout, "The asynchronous assertions did not finish"
