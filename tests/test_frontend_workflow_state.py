import textwrap

from tests.node_runner import run_node


def test_lifecycle_heartbeat_only_runs_with_explicit_local_shutdown():
    run_node(r"""
        const assert = require("assert"), fs = require("fs"), vm = require("vm");
        const requests = [], timers = [];
        const context = { window: {}, fetch: async (...args) => requests.push(args) };
        vm.runInNewContext(fs.readFileSync("static/workflow_state.js", "utf8"), context);
        for (const appConfig of [
            {}, {mode: "local"}, {mode: "local", heartbeat_enabled: false},
            {mode: "docker", heartbeat_enabled: true}, {mode: "local", heartbeat_enabled: "true"},
        ]) {
            context.window.MCBEWorkflowState.createAppLifecycleController({
                appConfig, win: {setInterval: (...args) => timers.push(args)},
            }).startHeartbeat();
        }
        assert.equal(timers.length, 0);
        assert.equal(requests.length, 0);
        context.window.MCBEWorkflowState.createAppLifecycleController({
            appConfig: {mode: "local", heartbeat_enabled: true},
            win: {setInterval: (...args) => timers.push(args)},
            withCsrf: () => ({"X-CSRF-Token": "test-token"}),
        }).startHeartbeat();
        assert.equal(timers.length, 1);
        const [tick, delay] = timers[0];
        assert.equal(delay, 2000);
        tick();
        assert.equal(requests.length, 1);
        assert.equal(requests[0][0], "/api/heartbeat");
        assert.equal(requests[0][1].headers["X-CSRF-Token"], "test-token");
    """)


def test_frontend_workflow_state_resolves_views_and_button_models() -> None:
    run_node(
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
            assert.strictEqual(workflow.resolvedView("player-edit", emptyContext), "world");
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
            assert.strictEqual(workflow.resolvedView("player-edit", playerContext), "player-edit");
            assert.strictEqual(workflow.viewTitle("player-edit"), "Spielerdaten bearbeiten");
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
    run_node(
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
    run_node(
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


def test_review_navigation_keeps_unaccepted_editor_input_in_place() -> None:
    run_node(r"""
        const assert = require("assert"), fs = require("fs"), vm = require("vm");
        const context = { window: {}, setTimeout: callback => callback() };
        vm.runInNewContext(fs.readFileSync("static/workflow_state.js", "utf8"), context);
        let activeView = "inventory", pending = true, rendered = 0, click;
        const button = {
            dataset: { workflowView: "save" }, classList: { toggle() {} },
            setAttribute() {}, addEventListener(name, handler) { click = handler; },
        };
        const controller = context.window.MCBEWorkflowState.createWorkflowShellController({
            doc: { body: {}, getElementById: () => null },
            body: { dataset: {}, classList: { toggle() {} } }, navButtons: [button],
            getActiveView: () => activeView, setActiveView: value => { activeView = value; },
            getContext: () => ({ currentPlayer: {}, currentPlayerKey: "fixture", worldPath: "fixture",
                inventoryVisible: true, isDirty: true, hasPendingSlotDraft: pending }),
            guardSaveView: () => pending, renderSaveWorkflowPanel: () => { rendered += 1; },
        });
        controller.wireNav();
        controller.refreshNavigation();
        assert.equal(button.disabled, true);
        click();
        controller.setWorkflowView("save", { scroll: false, user: true });
        assert.equal(activeView, "inventory");
        assert.equal(rendered, 0);
        pending = false;
        controller.refreshNavigation();
        assert.equal(button.disabled, false);
        click();
        assert.equal(activeView, "save");
        assert.equal(rendered, 1);
    """)


def test_dirty_state_resolves_its_status_key_when_clean() -> None:
    run_node(
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
    run_node(
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
    run_node(
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
