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


def test_player_load_preserves_an_existing_workflow_view() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/player_view_models.js", "utf8"), context, {
                filename: "static/player_view_models.js",
            });
            vm.runInNewContext(fs.readFileSync("static/player_load_controller.js", "utf8"), context, {
                filename: "static/player_load_controller.js",
            });

            const view = context.window.MCBEPlayerLoadController.workflowViewAfterPlayerLoad;
            assert.strictEqual(view("player"), "player");
            assert.strictEqual(view("inventory"), "inventory");
            assert.strictEqual(view("mounts"), "mounts");
            assert.strictEqual(view("save"), "save");
            assert.strictEqual(view("tools"), "tools");
            assert.strictEqual(view("world"), "inventory");
            assert.strictEqual(view("unexpected"), "inventory");
            """
        )
    )


def test_recent_world_ui_is_cleared_instead_of_persisted() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/player_view_models.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/player_load_controller.js", "utf8"), context);

            const recentWorldsEl = { style: { display: "block" } };
            const recentWorldsList = { innerHTML: "stale row" };
            const workspaces = [];
            let cleared = 0;
            const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                elements: { recentWorldsEl, recentWorldsList },
                saveWorkspace: workspace => workspaces.push(workspace),
                clearRecentWorldSession: () => { cleared += 1; },
            });

            controller.saveRecentWorld("C:/World", "Test world");
            controller.renderRecentWorlds();

            assert.deepStrictEqual(JSON.parse(JSON.stringify(workspaces)), [
                { world_path: "C:/World", world_name: "Test world" },
            ]);
            assert.strictEqual(cleared, 1);
            assert.strictEqual(recentWorldsEl.style.display, "none");
            assert.strictEqual(recentWorldsList.innerHTML, "");
            """
        )
    )


def test_frontend_player_load_controller_collects_inventory_dom_elements() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            const seenIds = [];
            const doc = {
                getElementById(id) {
                    seenIds.push(id);
                    return { id };
                },
            };
            const elements = context.window.MCBEPlayerLoadController.collectPlayerLoadElements(doc);

            assert.strictEqual(elements.playersList.id, "playersList");
            assert.strictEqual(elements.worldPathInput.id, "worldPath");
            assert.ok(seenIds.includes("btnRefreshPlayers"));
            assert.ok(seenIds.includes("worldBanner"));
            """
        )
    )


def test_frontend_player_load_controller_renders_player_rows_from_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const appended = [];
            const doc = {
                createElement(tagName) {
                    const classes = new Set();
                    const el = {
                        tagName,
                        type: "",
                        className: "",
                        disabled: false,
                        innerHTML: "",
                        listeners: {},
                        classList: {
                            add(name) {
                                classes.add(name);
                                el.className = [el.className, name].filter(Boolean).join(" ");
                            },
                            contains(name) {
                                return classes.has(name);
                            },
                        },
                        addEventListener(name, fn) {
                            el.listeners[name] = fn;
                        },
                    };
                    return el;
                },
            };
            const context = { window: {}, document: doc };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            const playersList = {
                innerHTML: "stale",
                appendChild(row) {
                    appended.push(row);
                },
            };
            const state = {
                players: [
                    { player_key: "local", label: "Alex", editable: true },
                    { player_key: "remote", label: "Steve", exportable: true, reason: "readonly" },
                ],
                currentPlayerKey: "local",
            };
            const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                elements: { playersList },
                getState: () => state,
            });
            controller.renderPlayersList();

            assert.strictEqual(playersList.innerHTML, "");
            assert.strictEqual(appended.length, 2);
            assert.strictEqual(appended[0].className, "player-row active");
            assert.strictEqual(typeof appended[0].listeners.click, "function");
            assert.ok(appended[0].innerHTML.includes("Alex"));
            assert.ok(appended[1].innerHTML.includes("Nur Export"));
            """
        )
    )


def test_frontend_player_load_controller_shows_overlay_while_loading_player() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            (async () => {
                const loading = [];
                const statuses = [];
                let clearedPendingMounts = 0;
                const state = {
                    worldPath: "C:/World",
                    players: [{ player_key: "local", label: "Alex" }],
                    currentServerGuardEpoch: 0,
                    currentServerGuardToken: "new-token",
                };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: {
                        loadPlayer: async () => ({
                            success: true,
                            player: { label: "Alex", exportable: true },
                            inventory: {},
                            ender_chest: {},
                            stats: {},
                            item_availability: { schema_version: 1, classifications: { creative: ["minecraft:bedrock"] } },
                        }),
                    },
                    clearPendingMounts: () => { clearedPendingMounts += 1; },
                    showLoading: message => loading.push(message),
                    hideLoading: () => loading.push("hide"),
                    logStatus: (message, type, options) => statuses.push({ message, type, options }),
                });

                const loaded = await controller.loadPlayer("local", true);

                assert.strictEqual(loaded, true);
                assert.deepStrictEqual(loading, ["Alex wird geladen...", "hide"]);
                assert.strictEqual(state.currentPlayerKey, "local");
                assert.strictEqual(state.itemAvailability.classifications.creative[0], "minecraft:bedrock");
                assert.strictEqual(clearedPendingMounts, 1);
                assert.strictEqual(statuses[0].type, "running");
                assert.strictEqual(statuses.at(-1).type, "success");
                assert.ok(statuses.every(entry => entry.options.key === "player-load"));
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_controller_can_suppress_player_overlay_for_parent_flows() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            (async () => {
                const loading = [];
                const state = { worldPath: "C:/World", players: [], currentServerGuardEpoch: 0 };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: {
                        loadPlayer: async () => ({
                            success: true,
                            player: { label: "Fallback" },
                            inventory: {},
                            ender_chest: {},
                            stats: {},
                        }),
                    },
                    showLoading: message => loading.push(message),
                    hideLoading: () => loading.push("hide"),
                });

                await controller.loadPlayer("local", true, { showLoadingOverlay: false });

                assert.deepStrictEqual(loading, []);
                assert.strictEqual(state.currentPlayerKey, "local");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_marks_online_snapshot_stale_immediately() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/player_view_models.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/player_load_controller.js", "utf8"), context);

            (async () => {
                const staleReasons = [];
                const renderedStatuses = [];
                const state = {
                    worldPath: "C:/World",
                    players: [{ player_key: "local", label: "Alex" }],
                    currentServerGuardEpoch: 0,
                };
                const response = {
                    success: true,
                    player: { label: "Alex", exportable: true },
                    inventory: {},
                    ender_chest: {},
                    stats: {},
                    server_guard_epoch: 8,
                    server_guard_token: "new-token",
                    player_server_guard_epoch: 7,
                    player_server_guard_token: "old-token",
                    server_guard_stale: true,
                    server_guard_stale_reason: "Server war beim Laden online.",
                    write_gate: {
                        allowed: false,
                        server_status: { status: "online" },
                    },
                };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    appConfig: { require_server_offline: true },
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: { loadPlayer: async () => response },
                    markLoadedPlayerStale: reason => staleReasons.push(reason),
                    renderServerStatus: payload => renderedStatuses.push(payload),
                });

                await controller.loadPlayer("local", true, { showLoadingOverlay: false });

                assert.strictEqual(state.currentServerGuardEpoch, 8);
                assert.strictEqual(state.currentPlayerServerGuardEpoch, 7);
                assert.strictEqual(state.currentPlayerServerGuardToken, "old-token");
                assert.deepStrictEqual(staleReasons, ["Server war beim Laden online."]);
                assert.strictEqual(renderedStatuses.length, 1);
                assert.strictEqual(renderedStatuses[0], response);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_carries_client_status_request_order() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/player_view_models.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/player_load_controller.js", "utf8"), context);

            (async () => {
                const renderedStatuses = [];
                const state = {
                    worldPath: "C:/World",
                    players: [{ player_key: "local", label: "Alex" }],
                    currentServerGuardEpoch: 5,
                    currentServerStatusRevision: 12,
                };
                const response = {
                    success: true,
                    player: { label: "Alex", exportable: true },
                    inventory: {},
                    ender_chest: {},
                    stats: {},
                    server_guard_epoch: 5,
                    player_server_guard_epoch: 5,
                    server_status_revision: 11,
                    write_gate: {
                        allowed: false,
                        server_status_revision: 11,
                        server_status: { status: "online", server_status_revision: 11 },
                    },
                };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: { loadPlayer: async () => response },
                    beginServerStatusRequest: () => 7,
                    renderServerStatus: (payload, options) => renderedStatuses.push({ payload, options }),
                });

                await controller.loadPlayer("local", true, { showLoadingOverlay: false });

                assert.strictEqual(state.currentServerStatusRevision, 12);
                assert.strictEqual(renderedStatuses.length, 1);
                assert.strictEqual(renderedStatuses[0].payload, response);
                assert.strictEqual(renderedStatuses[0].options.requestOrder, 7);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_accepts_fresh_token_after_backend_epoch_reset() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/player_view_models.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/player_load_controller.js", "utf8"), context);

            (async () => {
                const staleReasons = [];
                const state = {
                    worldPath: "C:/World",
                    players: [{ player_key: "local", label: "Alex" }],
                    currentServerGuardEpoch: 50,
                    currentServerGuardToken: "old-process-token",
                };
                const response = {
                    success: true,
                    player: { label: "Alex", exportable: true },
                    inventory: {},
                    ender_chest: {},
                    stats: {},
                    server_guard_epoch: 1,
                    player_server_guard_epoch: 1,
                    server_guard_token: "new-process-token",
                    player_server_guard_token: "new-process-token",
                    write_gate: {
                        allowed: true,
                        server_guard_token: "new-process-token",
                        server_status: { status: "offline" },
                    },
                };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    appConfig: { require_server_offline: true },
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: { loadPlayer: async () => response },
                    renderServerStatus: payload => {
                        state.currentServerGuardToken = payload.server_guard_token;
                        return true;
                    },
                    markLoadedPlayerStale: reason => staleReasons.push(reason),
                });

                await controller.loadPlayer("local", true, { showLoadingOverlay: false });

                assert.strictEqual(state.currentServerGuardEpoch, 50);
                assert.strictEqual(state.currentPlayerServerGuardEpoch, 1);
                assert.strictEqual(state.currentPlayerServerGuardToken, "new-process-token");
                assert.deepStrictEqual(staleReasons, []);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_controller_ignores_out_of_order_player_response() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            (async () => {
                const requests = { a: deferred(), b: deferred() };
                const state = {
                    worldPath: "C:/World",
                    players: [
                        { player_key: "a", label: "Alex" },
                        { player_key: "b", label: "Steve" },
                    ],
                    currentServerGuardEpoch: 0,
                };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: { loadPlayer: async (_world, key) => requests[key].promise },
                });

                const loadA = controller.loadPlayer("a", true);
                const loadB = controller.loadPlayer("b", true);
                requests.b.resolve({ success: true, player: { label: "Steve" }, inventory: {}, ender_chest: {}, stats: {} });
                await loadB;
                requests.a.resolve({ success: true, player: { label: "Alex" }, inventory: {}, ender_chest: {}, stats: {} });
                await loadA;

                assert.strictEqual(state.currentPlayerKey, "b");
                assert.strictEqual(state.currentPlayer.label, "Steve");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_cancellation_replaces_superseded_running_status() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/player_view_models.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/player_load_controller.js", "utf8"), context);

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            (async () => {
                {
                    const request = deferred();
                    const statuses = [];
                    const state = {
                        worldPath: "C:/World",
                        players: [
                            { player_key: "p1", label: "P1" },
                            { player_key: "p2", label: "P2" },
                        ],
                        currentServerGuardEpoch: 0,
                        isDirty: true,
                    };
                    const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                        getState: () => state,
                        setState: patch => Object.assign(state, patch),
                        api: { loadPlayer: async () => request.promise },
                        showConfirmDialog: async () => false,
                        logStatus: (message, type, options) => statuses.push({ message, type, options }),
                    });

                    const first = controller.loadPlayer("p1", true);
                    await Promise.resolve();
                    await controller.loadPlayer("p2");
                    request.resolve({ success: true, player: { label: "P1" }, inventory: {}, ender_chest: {}, stats: {} });
                    await first;

                    assert.strictEqual(statuses[0].type, "running");
                    assert.strictEqual(statuses.at(-1).type, "warning");
                    assert.ok(statuses.at(-1).message.includes("Spielerwechsel abgebrochen"));
                    assert.strictEqual(statuses.at(-1).options.key, "player-load");
                }

                {
                    const request = deferred();
                    const statuses = [];
                    const state = { worldPath: "C:/World", players: [], isDirty: false };
                    const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                        getState: () => state,
                        setState: patch => Object.assign(state, patch),
                        api: { listPlayers: async () => request.promise },
                        showConfirmDialog: async () => false,
                        logStatus: (message, type, options) => statuses.push({ message, type, options }),
                    });

                    const first = controller.loadPlayersList(false);
                    await Promise.resolve();
                    state.isDirty = true;
                    await controller.loadPlayersList(false);
                    request.resolve({ success: true, players: [] });
                    await first;

                    assert.strictEqual(statuses[0].type, "running");
                    assert.strictEqual(statuses.at(-1).type, "warning");
                    assert.ok(statuses.at(-1).message.includes("Spielerliste abgebrochen"));
                    assert.strictEqual(statuses.at(-1).options.key, "player-load");
                }

                {
                    const statuses = [];
                    const state = { worldPath: "C:/World", players: [], isDirty: true };
                    const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                        elements: { worldPathInput: { value: "C:/OtherWorld" } },
                        getState: () => state,
                        setState: patch => Object.assign(state, patch),
                        showConfirmDialog: async () => false,
                        logStatus: (message, type, options) => statuses.push({ message, type, options }),
                    });

                    await controller.loadWorldFromInput();
                    assert.strictEqual(statuses.at(-1).type, "warning");
                    assert.ok(statuses.at(-1).message.includes("Weltwechsel abgebrochen"));
                    assert.strictEqual(statuses.at(-1).options.key, "player-load");
                }
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_list_refresh_ignores_previous_world_response() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            (async () => {
                const requests = { A: deferred(), B: deferred() };
                const state = { worldPath: "A", players: [] };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: { listPlayers: async world => requests[world].promise },
                });

                const loadA = controller.loadPlayersList(false);
                state.worldPath = "B";
                const loadB = controller.loadPlayersList(false);
                requests.B.resolve({ success: true, players: [{ player_key: "b", label: "B", editable: false }] });
                await loadB;
                requests.A.resolve({ success: true, players: [{ player_key: "a", label: "A", editable: false }] });
                await loadA;

                assert.strictEqual(state.worldPath, "B");
                assert.strictEqual(state.players.length, 1);
                assert.strictEqual(state.players[0].player_key, "b");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_controller_hides_overlay_after_load_failure() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            (async () => {
                const loading = [];
                const errors = [];
                const state = {
                    worldPath: "C:/World",
                    players: [{ player_key: "local", label: "Alex" }],
                    currentPlayerKey: "",
                    currentServerGuardEpoch: 0,
                };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: {
                        loadPlayer: async () => ({ success: false, error: "NBT zu groß" }),
                    },
                    buildErrorMessage: (data, fallback) => `${fallback}: ${data.error}`,
                    renderLoadError: (data, fallback) => errors.push({ data, fallback }),
                    showLoading: message => loading.push(message),
                    hideLoading: () => loading.push("hide"),
                });

                const loaded = await controller.loadPlayer("local", true);

                assert.strictEqual(loaded, false);
                assert.deepStrictEqual(loading, ["Alex wird geladen...", "hide"]);
                assert.strictEqual(state.currentPlayerKey, "");
                assert.strictEqual(errors[0].fallback, "Spieler konnte nicht geladen werden.");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_load_controller_does_not_rescan_icons_in_read_only_mode() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const loadControllerCode = fs.readFileSync("static/player_load_controller.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(loadControllerCode, context, { filename: "static/player_load_controller.js" });

            (async () => {
                const iconLoads = [];
                const state = {
                    worldPath: "C:/World",
                    players: [{ player_key: "local", label: "Alex" }],
                    currentServerGuardEpoch: 0,
                };
                const controller = context.window.MCBEPlayerLoadController.createPlayerLoadController({
                    appConfig: { read_only: true },
                    getState: () => state,
                    setState: patch => Object.assign(state, patch),
                    api: {
                        loadPlayer: async () => ({
                            success: true,
                            player: { label: "Alex", exportable: true },
                            inventory: {},
                            ender_chest: {},
                            stats: {},
                        }),
                    },
                    loadLocalIconIndex: options => iconLoads.push(options),
                    exportBlocked: () => true,
                });

                await controller.loadPlayer("local", true, { showLoadingOverlay: false });

                assert.deepStrictEqual(JSON.parse(JSON.stringify(iconLoads)), [{ rescan: false }]);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )
