"""Observe commits before optional UI callbacks, including after consent retries."""

import json

import pytest

from tests.node_runner import run_node


@pytest.mark.parametrize("outcome", ["success", "committed-failure"])
@pytest.mark.parametrize("callback", ["cleanup-toast", "write-gate"])
@pytest.mark.parametrize("retry", ["direct", "server", "presence", "both"])
def test_committed_response_remains_terminal_when_early_ui_callback_throws(outcome, callback, retry):
    result = run_node(
        "const config = "
        + json.dumps({"outcome": outcome, "callback": callback, "retry": retry})
        + ";\n"
        + r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const scope = {window: {}, console: {error() {}}};
for (const file of ['api_client', 'save_controller']) {
    vm.runInNewContext(fs.readFileSync(`static/${file}.js`, 'utf8'), scope);
}
(async () => {
    const noop = () => {};
    let blocked = false, posts = 0, injected = false, dialogs = 0;
    const flags = [], statuses = [], buttonStates = [];
    const responses = [];
    if (['server', 'both'].includes(config.retry)) {
        responses.push({success: false, write_gate: {requires_unknown_server_confirmation: true}});
    }
    if (['presence', 'both'].includes(config.retry)) {
        responses.push({success: false, presence_conflict: true});
    }
    responses.push({
        success: config.outcome === 'success',
        write_committed: config.outcome !== 'success',
        validation_failed: config.outcome !== 'success',
        player_revision: 'saved-revision',
        cleanup_warning: 'saved-warning',
        write_gate: {allowed: true, responseFromCommittedWrite: true},
    });
    const expectedPosts = responses.length;
    const failOnce = location => {
        if (!injected && config.callback === location) {
            injected = true;
            throw new Error(`synthetic ${location} failure`);
        }
    };
    const controller = scope.window.MCBESaveController.createSaveController({
        getWorldPath: () => 'world', getCurrentPlayerKey: () => 'player',
        getIsDirty: () => true, getPendingMounts: () => [],
        getCurrentWriteGate: () => ({}), writeBlocked: () => blocked,
        getCreateRequiresConfirmation: () => ({}),
        buildSavePayload: () => ({stats: {health: 18}, base_revision: 'loaded'}),
        payloadContainsUserChanges: () => true, buildChangeSummary: () => ({}),
        validateInventoryState: () => ({errors: 0}),
        showConfirmDialog: async () => {dialogs++; return true;},
        confirmPresenceConflict: async () => {dialogs++; return true;},
        postSavePayload: async payload => {
            flags.push({...payload});
            return responses[Math.min(posts++, responses.length - 1)];
        },
        markReloadRequired: () => {blocked = true;},
        markCleanState: noop, updateCurrentPlayerRevision: noop,
        normalizeOriginsToCurrentSavedState: noop, applyCreatedTagState: noop,
        updateWorldPresence: async () => {},
        setPrimarySaveDisabled: disabled => buttonStates.push(disabled),
        setReviewConfirmDisabled: noop, showLoading: noop, hideLoading: noop,
        renderWriteGate: gate => {if (gate.responseFromCommittedWrite) failOnce('write-gate');},
        updateWriteControls: noop, loadBackupsList: noop, recordAction: noop, flashSaveButton: noop,
        logStatus: (message, type) => statuses.push({message, type}),
        showToast: message => {if (message === 'saved-warning') failOnce('cleanup-toast');},
    });
    await controller.saveCurrentPlayer({skipReview: true});
    assert.equal(injected, true, 'The post-commit fault must actually run');
    assert.equal(posts, expectedPosts);
    assert.equal(dialogs, expectedPosts - 1);
    assert.equal(blocked, true, 'A known commit cannot become a retryable transport failure');
    assert.ok(!buttonStates.includes(false), 'A post-commit callback cannot re-enable Save');
    assert.match(statuses.at(-1).message, /wurden geschrieben/);
    if (['server', 'both'].includes(config.retry)) assert.equal(flags.at(-1).confirm_unknown_server_status, true);
    if (['presence', 'both'].includes(config.retry)) assert.equal(flags.at(-1).confirm_presence_conflict, true);
    await controller.saveCurrentPlayer({skipReview: true});
    assert.equal(posts, expectedPosts, 'A second Save must not repeat the confirmed write');
    assert.equal(controller.isSaving(), false);
    console.log('commit-observation-complete');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    )
    assert "commit-observation-complete" in result.stdout, "The asynchronous assertions did not finish"
