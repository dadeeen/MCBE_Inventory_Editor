import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_player_load_app_discards_pending_mounts_on_reload_and_reset() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, document: { getElementById: () => null } };
            for (const name of ["player_view_models", "player_load_controller", "player_load_app"]) {
                vm.runInNewContext(fs.readFileSync(`static/${name}.js`, "utf8"), context);
            }

            (async () => {
                const state = { worldPath: "world-A", currentPlayerKey: "local", players: [], isDirty: true };
                let pending = [{ id: "pending-horse", worldPath: "world-A", playerKey: "local" }];
                let cleared = 0;
                const app = context.window.MCBEPlayerLoadApp.createInventoryPlayerLoadApp({
                    state: {
                        getPlayerLoadState: () => state,
                        assignAppState: patch => Object.assign(state, patch),
                    },
                    actions: {
                        clearPendingMounts: () => {
                            pending = [];
                            cleared++;
                            // The real mount callback recomputes dirty state against
                            // the previous clean snapshot before reset finishes.
                            state.isDirty = true;
                        },
                        markCleanState: () => { state.isDirty = false; },
                    },
                    controllerFactory: deps => context.window.MCBEPlayerLoadController.createInventoryPlayerLoadController({
                        ...deps,
                        api: { loadPlayer: async () => ({ success: true, player: { editable: true }, inventory: {}, stats: {} }) },
                    }),
                });

                assert.strictEqual(await app.loadPlayer("local", true), true);
                assert.strictEqual(pending.length, 0);
                assert.strictEqual(cleared, 1);
                assert.strictEqual(state.isDirty, false);

                pending = [{ id: "another-pending-horse" }];
                app.resetLoadedPlayerState();
                assert.strictEqual(pending.length, 0);
                assert.strictEqual(cleared, 2);
                assert.strictEqual(state.currentPlayerKey, "");
                assert.strictEqual(state.isDirty, false);
            })().catch(error => { console.error(error); process.exit(1); });
            """
        )
    )


def test_frontend_player_load_app_wires_app_dependencies_and_facade_methods() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_load_app.js", "utf8");
            let captured = null;
            const calls = [];
            const fakeController = {
                loadPlayer(...args) { calls.push(["loadPlayer", args]); return "loaded"; },
                loadPlayersList(...args) { calls.push(["loadPlayersList", args]); },
                loadWorldFromInput(...args) { calls.push(["loadWorldFromInput", args]); },
                renderPlayersList(...args) { calls.push(["renderPlayersList", args]); },
                renderRecentWorlds(...args) { calls.push(["renderRecentWorlds", args]); },
                resetLoadedPlayerState(...args) { calls.push(["resetLoadedPlayerState", args]); },
                wire(...args) { calls.push(["wire", args]); },
            };
            const context = {
                window: {
                    MCBEPlayerLoadController: {
                        createInventoryPlayerLoadController(deps) {
                            captured = deps;
                            return fakeController;
                        },
                    },
                },
                document: { marker: "doc" },
            };
            vm.runInNewContext(code, context, { filename: "static/player_load_app.js" });

            const bridge = context.window.MCBEPlayerLoadApp;
            const getPlayerLoadState = () => ({ worldPath: "C:/World" });
            const assignAppState = () => {};
            const withCsrf = () => ({});
            const parseJsonResponse = () => {};
            const buildErrorMessage = () => {};
            const showConfirmDialog = () => {};
            const showToast = () => {};
            const showLoading = () => {};
            const hideLoading = () => {};
            const logStatus = () => {};
            const renderLoadError = () => {};
            const clearTouchedStatsFields = () => {};
            const getActiveWorkflowView = () => "player";

            const app = bridge.createInventoryPlayerLoadApp({
                doc: context.document,
                state: { getPlayerLoadState, assignAppState },
                api: { withCsrf, parseJsonResponse, buildErrorMessage },
                feedback: { showConfirmDialog, showToast, showLoading, hideLoading },
                actions: {
                    logStatus,
                    renderLoadError,
                    buildPlayersDiagnosticsText: () => "",
                    copyTextToClipboard: () => {},
                    getActiveWorkflowView,
                },
                ui: { clearTouchedStatsFields },
                constants: { defaultMaxDamage: 123 },
            });

            assert.strictEqual(captured.doc, context.document);
            assert.strictEqual(captured.getState, getPlayerLoadState);
            assert.strictEqual(captured.setState, assignAppState);
            assert.strictEqual(captured.withCsrf, withCsrf);
            assert.strictEqual(captured.parseJsonResponse, parseJsonResponse);
            assert.strictEqual(captured.buildErrorMessage, buildErrorMessage);
            assert.strictEqual(captured.showConfirmDialog, showConfirmDialog);
            assert.strictEqual(captured.showToast, showToast);
            assert.strictEqual(captured.showLoading, showLoading);
            assert.strictEqual(captured.hideLoading, hideLoading);
            assert.strictEqual(captured.logStatus, logStatus);
            assert.strictEqual(captured.renderLoadError, renderLoadError);
            assert.strictEqual(captured.getActiveWorkflowView, getActiveWorkflowView);
            assert.strictEqual(captured.clearTouchedStatsFields, clearTouchedStatsFields);
            assert.strictEqual(captured.defaultMaxDamage, 123);
            assert.strictEqual(app.controller, fakeController);
            assert.strictEqual(app.loadPlayer("local", true), "loaded");
            app.wire();

            assert.strictEqual(
                JSON.stringify(calls),
                JSON.stringify([
                    ["loadPlayer", ["local", true]],
                    ["wire", []],
                ]),
            );
            assert.strictEqual(
                JSON.stringify(bridge.facadeMethods()),
                JSON.stringify([
                    "isLoading",
                    "loadPlayer",
                    "loadPlayersList",
                    "loadWorldFromInput",
                    "renderPlayersList",
                    "renderRecentWorlds",
                    "resetLoadedPlayerState",
                ]),
            );
            """
        )
    )
