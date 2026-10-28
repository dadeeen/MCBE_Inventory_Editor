from __future__ import annotations

from tests.node_runner import run_node


_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const appSource = fs.readFileSync("static/app.js", "utf8");

function createHarness() {
    const context = { AbortController, setTimeout, clearTimeout,window: {}, console};
    for (const name of ["player_view_models", "player_load_controller", "update_db_view"]) {
        vm.runInNewContext(fs.readFileSync(`static/${name}.js`, "utf8"), context);
    }
    const pending = {slot: false, special: false, stats: false, effects: false};
    const calls = {reads: 0, confirmations: 0, discarded: 0, catalogUpdates: 0, iconReads: 0, iconChecksInvalidated: 0};
    const state = {
        worldPath: "world-a", currentPlayerKey: "a", currentPlayer: {player_key: "a"},
        inventory: {0: {name: "minecraft:diamond", count: 1}}, players: [], isDirty: false,
    };
    Object.assign(context, {
        document: {}, apiClient: {},
        showLoading() {}, hideLoading() {}, logStatus() {}, showToast() {},
        showConfirmDialog: async () => {calls.confirmations++; return false;},
        dataSourceController: {applyItemDbStatus() {calls.catalogUpdates++;}},
        loadItemDbStatus: async () => {calls.catalogUpdates++;},
        iconSourcesController: {invalidateUpdateCheck() {calls.iconChecksInvalidated++;}},
        loadLocalIconIndex: async options => {
            assert.equal(options.rescan, false);
            calls.iconReads++;
        },
        specialItemEditor: {hasPendingChanges: () => pending.special},
        slotDetailController: {hasPendingChanges: () => pending.slot},
        statsFormController: {hasPendingChanges: () => pending.stats},
        effectsAbilitiesController: {hasPendingChanges: () => pending.effects},
    });
    Object.defineProperties(context, {
        isDirty: {get: () => state.isDirty},
        currentPlayerKey: {get: () => state.currentPlayerKey},
    });

    const guardStart = appSource.indexOf("function hasUnsavedChanges() {");
    const guardEnd = appSource.indexOf("\nfunction guardPendingEditorChanges", guardStart);
    assert.ok(guardStart >= 0 && guardEnd > guardStart);
    vm.runInNewContext(appSource.slice(guardStart, guardEnd), context);
    const playerController = context.window.MCBEPlayerLoadController.createPlayerLoadController({
        getState: () => state,
        setState: patch => Object.assign(state, patch),
        hasUnsavedChanges: () => context.hasUnsavedChanges(),
        discardEditorDrafts: () => {
            calls.discarded++;
            for (const kind of Object.keys(pending)) pending[kind] = false;
        },
        showConfirmDialog: context.showConfirmDialog,
        api: {loadPlayer: async (_world, playerKey) => {
            calls.reads++;
            return {success: true, player: {player_key: playerKey}, inventory: {}, stats: {}};
        }},
    });
    context.loadPlayer = (...args) => playerController.loadPlayer(...args);

    // Execute the real app wiring, rather than duplicating its dirty-state guard.
    context.window.MCBEUpdateDbView.createInventoryUpdateDbController = options => {
        context.updateFinished = options.onReloaded;
        return {};
    };
    const wiringStart = appSource.indexOf("const updateDbController = ");
    const wiringEnd = appSource.indexOf("\nfirstRunSetupController = ", wiringStart);
    assert.ok(wiringStart >= 0 && wiringEnd > wiringStart);
    vm.runInNewContext(appSource.slice(wiringStart, wiringEnd), context);
    return {context, pending, calls, state};
}
"""


def test_database_update_preserves_every_kind_of_unapplied_form() -> None:
    run_node(
        _HARNESS
        + r"""
        (async () => {
            for (const kind of ["slot", "special", "stats", "effects"]) {
                const {context, pending, calls, state} = createHarness();
                pending[kind] = true;
                assert.equal(state.isDirty, false);
                const result = await context.updateFinished({item_db: {status: "ok"}});
                assert.equal(calls.catalogUpdates, 1, kind);
                assert.equal(calls.iconReads, 1, kind);
                assert.equal(calls.iconChecksInvalidated, 1, kind);
                assert.equal(calls.reads, 0, kind);
                assert.equal(calls.confirmations, 0, kind);
                assert.equal(calls.discarded, 0, kind);
                assert.equal(pending[kind], true, kind);
                assert.ok(result.warning, kind);
            }
        })().catch(error => {console.error(error); process.exitCode = 1;});
        """
    )


def test_database_update_reads_live_changes_and_reloads_a_clean_player() -> None:
    run_node(
        _HARNESS
        + r"""
        (async () => {
            const {context, pending, calls, state} = createHarness();
            // Changes made after the controller was created must still protect the player.
            state.isDirty = true;
            assert.ok((await context.updateFinished({item_db: {status: "ok"}})).warning);
            assert.equal(calls.reads, 0);
            state.isDirty = false;
            pending.slot = true;
            assert.ok((await context.updateFinished({item_db: {status: "ok"}})).warning);
            assert.equal(calls.reads, 0);
            pending.slot = false;
            state.currentPlayerKey = "new-player";
            const result = await context.updateFinished({item_db: {status: "ok"}});
            assert.equal(result.warning, undefined);
            assert.equal(calls.reads, 1);
            assert.equal(calls.iconReads, 3);
            assert.equal(calls.iconChecksInvalidated, 3);
            assert.equal(calls.confirmations, 0);
            assert.equal(calls.discarded, 1);
            assert.equal(state.currentPlayerKey, "new-player");
        })().catch(error => {console.error(error); process.exitCode = 1;});
        """
    )
