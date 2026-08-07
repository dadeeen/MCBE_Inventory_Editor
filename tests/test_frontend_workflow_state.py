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


def test_frontend_workflow_state_resolves_views_and_button_models() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/workflow_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/workflow_state.js" });

            const workflow = context.window.MCBEWorkflowState;
            const emptyContext = {
                activeWorkflowView: "world",
                currentPlayer: null,
                currentPlayerKey: "",
                inventoryVisible: false,
                isDirty: false,
                worldPath: "",
            };
            assert.strictEqual(workflow.resolvedView("inventory", emptyContext), "world");
            assert.strictEqual(workflow.unavailableMessage("save"), "Lade zuerst einen bearbeitbaren Spieler.");
            assert.strictEqual(workflow.unavailableMessage("player"), "Lade zuerst eine Welt.");
            assert.strictEqual(
                JSON.stringify(workflow.appBodyClassModel(emptyContext)),
                JSON.stringify({
                    "app-world-loaded": false,
                    "app-player-loaded": false,
                    "app-dirty": false,
                }),
            );

            const worldContext = { ...emptyContext, activeWorkflowView: "player", worldPath: "C:/World" };
            assert.strictEqual(workflow.resolvedView("player", worldContext), "player");
            assert.strictEqual(
                JSON.stringify(workflow.navButtonModel("save", "player", worldContext)),
                JSON.stringify({
                    active: false,
                    ariaCurrent: "false",
                    disabled: true,
                    title: "Lade zuerst einen bearbeitbaren Spieler.",
                }),
            );

            const playerContext = {
                activeWorkflowView: "save",
                currentPlayer: { label: "Alex" },
                currentPlayerKey: "local",
                inventoryVisible: true,
                isDirty: false,
                worldPath: "C:/World",
            };
            assert.strictEqual(workflow.resolvedView("save", playerContext), "save");
            assert.strictEqual(
                JSON.stringify(workflow.appBodyClassModel({ ...playerContext, isDirty: true })),
                JSON.stringify({
                    "app-world-loaded": true,
                    "app-player-loaded": true,
                    "app-dirty": true,
                }),
            );
            assert.strictEqual(
                JSON.stringify(workflow.navButtonModel("save", "save", playerContext)),
                JSON.stringify({
                    active: true,
                    ariaCurrent: "page",
                    disabled: false,
                    title: "Keine ungespeicherten Änderungen.",
                }),
            );
            """
        )
    )


def test_responsive_panels_restore_active_panel_after_narrowing_viewport() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/workflow_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/workflow_state.js" });

            function classList(initial = []) {
                const values = new Set(initial);
                return {
                    contains: value => values.has(value),
                    remove: value => values.delete(value),
                    toggle: (value, enabled) => enabled ? values.add(value) : values.delete(value),
                };
            }

            const listeners = {};
            const win = {
                innerWidth: 1440,
                addEventListener: (name, callback) => { listeners[name] = callback; },
            };
            const leftPanel = { classList: classList(["visible"]) };
            const rightPanel = { classList: classList() };
            const toggles = [
                { dataset: { panel: "left" }, classList: classList(["active"]), style: {}, addEventListener() {} },
                { dataset: { panel: "right" }, classList: classList(), style: {}, addEventListener() {} },
            ];
            const doc = {
                querySelector: selector => selector === ".btn-toggle.active"
                    ? toggles.find(button => button.classList.contains("active"))
                    : null,
            };
            const controller = context.window.MCBEWorkflowState.createResponsivePanelController({
                win,
                doc,
                leftPanel,
                rightPanel,
                panelToggles: toggles,
            });

            controller.wire();
            assert.strictEqual(leftPanel.classList.contains("visible"), false);
            win.innerWidth = 429;
            listeners.resize();
            assert.strictEqual(leftPanel.classList.contains("visible"), true);
            assert.strictEqual(rightPanel.classList.contains("visible"), false);
            """
        )
    )


def test_main_workflow_navigation_does_not_change_scroll_position() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/workflow_state.js", "utf8");
            const context = { window: {}, setTimeout: callback => callback() };
            vm.runInNewContext(code, context, { filename: "static/workflow_state.js" });

            let activeView = "world";
            let clickHandler = null;
            let scrollCalls = 0;
            const button = {
                dataset: { workflowView: "world" },
                classList: { toggle() {} },
                setAttribute() {},
                addEventListener: (name, callback) => {
                    if (name === "click") clickHandler = callback;
                },
            };
            const controller = context.window.MCBEWorkflowState.createWorkflowShellController({
                doc: { body: {}, getElementById: () => null },
                body: { dataset: {}, classList: { toggle() {} } },
                navButtons: [button],
                getActiveView: () => activeView,
                setActiveView: value => { activeView = value; },
                getContext: () => ({ activeWorkflowView: activeView }),
                getScrollTarget: () => ({ scrollIntoView: () => { scrollCalls += 1; } }),
            });

            controller.wireNav();
            clickHandler();
            assert.strictEqual(scrollCalls, 0);

            controller.setWorkflowView("world");
            assert.strictEqual(scrollCalls, 1);
            """
        )
    )


def test_dirty_state_resolves_its_status_key_when_clean() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/workflow_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/workflow_state.js" });

            let dirty = false;
            const statuses = [];
            const cleared = [];
            const controller = context.window.MCBEWorkflowState.createDirtyStateController({
                getIsDirty: () => dirty,
                setIsDirty: value => { dirty = value; },
                effectiveWriteGate: () => ({ allowed: true }),
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
                clearStatus: key => { cleared.push(key); return true; },
                transientDirtyNoticeCategory: "dirty",
            });

            controller.setDirty(true);
            assert.strictEqual(statuses.length, 1);
            assert.strictEqual(statuses[0].options.key, "dirty");
            assert.strictEqual(statuses[0].options.active, true);
            controller.setDirty(false);
            assert.deepStrictEqual(cleared, ["dirty"]);
            """
        )
    )


def test_dirty_state_does_not_duplicate_an_existing_write_gate_error() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/workflow_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/workflow_state.js" });

            let dirty = false;
            const statuses = [];
            const controller = context.window.MCBEWorkflowState.createDirtyStateController({
                getIsDirty: () => dirty,
                setIsDirty: value => { dirty = value; },
                getWorldPath: () => "C:/World",
                effectiveWriteGate: () => ({
                    allowed: false,
                    reason: "Nur ansehen: Server online.",
                }),
                logStatus: (...args) => statuses.push(args),
            });

            controller.setDirty(true);

            assert.strictEqual(dirty, true);
            assert.deepStrictEqual(statuses, []);
            """
        )
    )


def test_dirty_state_keeps_warning_when_unknown_status_can_be_confirmed() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/workflow_state.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/workflow_state.js" });

            let dirty = false;
            const statuses = [];
            const controller = context.window.MCBEWorkflowState.createDirtyStateController({
                getIsDirty: () => dirty,
                setIsDirty: value => { dirty = value; },
                effectiveWriteGate: () => ({
                    allowed: false,
                    requires_unknown_server_confirmation: true,
                    reason: "Serverstatus unbekannt.",
                }),
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
            });

            controller.setDirty(true);

            assert.strictEqual(dirty, true);
            assert.strictEqual(statuses.length, 1);
            assert.strictEqual(statuses[0].message, "Ungespeicherte Änderungen vorhanden");
            assert.strictEqual(statuses[0].type, "warning");
            assert.strictEqual(statuses[0].options.active, true);
            """
        )
    )
