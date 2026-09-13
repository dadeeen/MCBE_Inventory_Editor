"""Late save completions must not mutate a newly selected player or world."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("changed_field", ["world", "player"])
@pytest.mark.parametrize("scenario", [
    "transport", "presence-error", "committed-invalid", "mount-finalization", "no-op", "success",
    "committed-invalid-presence-error", "no-op-presence-error", "no-op-with-mounts",
    "transport-after-server-confirmation", "transport-after-presence-confirmation",
])
def test_save_completion_does_not_modify_a_replaced_context(changed_field, scenario):
    script = r'''
        const fs = require("fs");
        const vm = require("vm");
        const assert = require("node:assert/strict");
        const context = {window: {}, console: {error() {}}};
        vm.runInNewContext(fs.readFileSync("static/save_controller.js", "utf8"), context);
        const {scenario, changedField} = CONFIG;
        const state = {world: "world-A", player: "player-A", changed: false};
        let started, resolve, reject;
        const ready = new Promise(done => { started = done; });
        const pending = new Promise((done, fail) => { resolve = done; reject = fail; });
        const mutations = [];
        const statuses = [];
        const noop = () => {};
        const mutation = name => () => { if (state.changed) mutations.push(name); };
        const transportFailure = scenario.startsWith("transport");
        const invalidCommit = scenario.startsWith("committed-invalid");
        const noOp = scenario.startsWith("no-op");
        const hasMounts = transportFailure || invalidCommit || ["mount-finalization", "no-op-with-mounts"].includes(scenario);
        let posts = 0;
        const controller = context.window.MCBESaveController.createSaveController({
            getWorldPath: () => state.world, getCurrentPlayerKey: () => state.player,
            getIsDirty: () => true, writeBlocked: () => false,
            getCreateRequiresConfirmation: () => ({}),
            getPendingMounts: () => hasMounts ? [{worldPath: "world-A", playerKey: "player-A"}] : [],
            buildSavePayload: () => ({stats: {health: 18}, base_revision: "original"}),
            payloadContainsUserChanges: () => true, buildChangeSummary: () => ({}),
            validateInventoryState: () => ({errors: 0}),
            setPrimarySaveDisabled: value => { if (!value && state.changed) mutations.push("save-enabled"); },
            setReviewConfirmDisabled: noop, showLoading: noop, hideLoading: noop,
            logStatus: (message, type) => statuses.push({message, type}), showToast: noop,
            showConfirmDialog: async () => true, confirmPresenceConflict: async () => true,
            updateWriteControls: noop, renderWriteGate: mutation("write-gate"),
            markReloadRequired: mutation("reload-required"),
            applyCreatedTagState: mutation("created-tags"),
            updateCurrentPlayerRevision: mutation("revision"),
            normalizeOriginsToCurrentSavedState: mutation("origins"),
            markCleanState: mutation("clean"), loadBackupsList: mutation("backups"),
            recordAction: mutation("history"), flashSaveButton: mutation("flash"),
            finalizePendingMounts: () => ({reloadRequired: scenario === "mount-finalization"}),
            postSavePayload: async () => {
                posts += 1;
                if (posts === 1 && scenario === "transport-after-server-confirmation") {
                    return {success: false, error: "Serverstatus unbekannt", write_gate: {requires_unknown_server_confirmation: true}};
                }
                if (posts === 1 && scenario === "transport-after-presence-confirmation") {
                    return {success: false, error: "Bearbeitungskonflikt", presence_conflict: true};
                }
                if (transportFailure) { started(); return pending; }
                return {
                    success: !invalidCommit,
                    write_committed: invalidCommit,
                    validation_failed: invalidCommit,
                    no_op: noOp, mounts: scenario === "no-op-with-mounts" ? [{}] : [], player_revision: "next",
                };
            },
            updateWorldPresence: async () => { started(); return pending; },
        });
        (async () => {
            const saving = controller.saveCurrentPlayer({skipReview: true});
            await ready;
            state[changedField] = "new-context";
            state.changed = true;
            if (transportFailure || scenario.endsWith("presence-error")) reject(new Error("connection interrupted"));
            else resolve();
            await saving;
            assert.deepEqual(mutations, [], `stale ${scenario} modified current ${changedField}`);
            const outcome = statuses.at(-1);
            assert.match(outcome.message, /vorherigen? Spieler|Vorheriger Spieler/);
            if (invalidCommit) {
                assert.match(outcome.message, /Nachvalidierung ist fehlgeschlagen/);
                assert.match(outcome.message, /Backup prüfen/);
                assert.equal(outcome.type, "error");
            } else if (noOp && !hasMounts) {
                assert.match(outcome.message, /nichts geschrieben/);
                assert.doesNotMatch(outcome.message, /wurde gespeichert|unklar/);
                assert.equal(outcome.type, "warning");
            } else if (transportFailure) {
                assert.match(outcome.message, /Speicherausgang.*unklar/);
                assert.equal(outcome.type, "error");
                assert.equal(posts, scenario === "transport" ? 1 : 2);
            } else if (scenario === "no-op-with-mounts") {
                assert.match(outcome.message, /wurde gespeichert/);
            }
            assert.equal(controller.isSaving(), false);
            console.log("save-context-check-passed");
        })().catch(error => {console.error = global.console.error; console.error(error); process.exitCode = 1;});
    '''
    script = script.replace("CONFIG", json.dumps({"scenario": scenario, "changedField": changed_field}))
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "save-context-check-passed" in result.stdout, "The asynchronous assertions did not complete"
