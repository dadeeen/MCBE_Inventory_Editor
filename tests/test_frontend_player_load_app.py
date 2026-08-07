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
