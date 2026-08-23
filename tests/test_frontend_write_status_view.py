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


def test_frontend_write_status_view_models_and_badge_applier() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/write_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/write_status_view.js" });

            const view = context.window.MCBEWriteStatusView;
            assert.ok(view.EDIT_CONTROL_SELECTOR.includes("#btnUndo"));
            assert.ok(view.EDIT_CONTROL_SELECTOR.includes("#btnRedo"));
            assert.ok(view.EDIT_CONTROL_SELECTOR.includes("#btnMountCreate"));
            assert.strictEqual(
                JSON.stringify(view.writeControlModel({ isDirty: true, blocked: false })),
                JSON.stringify({
                    saveDisabled: false,
                    restoreDisabled: false,
                    restoreTitle: "Backup wiederherstellen",
                    backupCreateDisabled: false,
                    backupCreateTitle: "Backup erstellen",
                    editDisabled: false,
                    editTitle: "",
                }),
            );
            assert.strictEqual(
                JSON.stringify(view.writeControlModel({
                    isDirty: true,
                    blocked: true,
                    blockedReason: "Server online",
                    hasEditablePlayer: true,
                })),
                JSON.stringify({
                    saveDisabled: true,
                    restoreDisabled: true,
                    restoreTitle: "Server online",
                    backupCreateDisabled: true,
                    backupCreateTitle: "Server online",
                    editDisabled: true,
                    editTitle: "Server online",
                }),
            );

            const badge = view.serverStatusBadgeModel({
                gate: { allowed: false, reason: "Server online" },
                status: { status: "online", server_name: "Bedrock", message: "läuft" },
                appConfig: {},
            });
            assert.strictEqual(badge.className, "server-status-badge online blocked");
            assert.strictEqual(badge.text, "Server: online · Schreiben gesperrt · manuell stoppen");
            assert.ok(badge.title.includes("Bedrock: läuft"));
            assert.ok(badge.title.includes("stoppt Minecraft"));

            const staleOffline = view.serverStatusBadgeModel({
                gate: {
                    allowed: false,
                    stale_loaded_player: true,
                    reason: "Spieler neu laden.",
                },
                status: { status: "offline", server_name: "Bedrock", message: "offline" },
                appConfig: {},
            });
            assert.strictEqual(staleOffline.text, "Server: offline · Schreiben gesperrt · Spieler neu laden");
            assert.ok(staleOffline.title.includes("Spieler neu laden."));
            assert.ok(!staleOffline.title.includes("stoppt Minecraft"));

            const staleOnline = view.serverStatusBadgeModel({
                gate: {
                    allowed: false,
                    stale_loaded_player: true,
                    reason: "Der Server war seit dem Laden online.",
                },
                status: { status: "online", server_name: "Bedrock", message: "online" },
                appConfig: {},
            });
            assert.strictEqual(
                staleOnline.text,
                "Server: online · Schreiben gesperrt · Server stoppen und Spieler neu laden",
            );
            assert.ok(staleOnline.title.includes("stoppt Minecraft"));

            const offline = view.serverStatusBadgeModel({
                gate: { allowed: true, reason: "Bearbeitung erlaubt." },
                status: { status: "offline", server_name: "Bedrock", message: "offline" },
                appConfig: {},
            });
            assert.strictEqual(offline.text, "Server: offline · Schreiben freigegeben");

            const localUnknown = view.serverStatusBadgeModel({
                gate: { allowed: true },
                status: { status: "unknown" },
                appConfig: { mode: "local", require_server_offline: false },
            });
            assert.strictEqual(localUnknown.text, "Server: unbekannt · manuell prüfen");
            assert.ok(localUnknown.title.includes("manuell"));

            const element = { className: "", textContent: "", title: "" };
            view.applyServerStatusBadgeModel(element, badge);
            assert.strictEqual(element.className, "server-status-badge online blocked");
            assert.strictEqual(element.textContent, "Server: online · Schreiben gesperrt · manuell stoppen");
            assert.ok(element.title.includes("stoppt Minecraft"));

            const saveButtons = [{ disabled: false }, null, { disabled: false }];
            const restoreButtons = [{ disabled: false, title: "" }];
            const backupCreateButtons = [{ disabled: false, title: "", dataset: {} }];
            view.applyWriteControlModel({ saveButtons, restoreButtons, backupCreateButtons }, {
                saveDisabled: true,
                restoreDisabled: true,
                restoreTitle: "Server online",
                backupCreateDisabled: true,
                backupCreateTitle: "Server online",
            });
            assert.strictEqual(saveButtons[0].disabled, true);
            assert.strictEqual(saveButtons[2].disabled, true);
            assert.strictEqual(restoreButtons[0].disabled, true);
            assert.strictEqual(restoreButtons[0].title, "Server online");
            assert.strictEqual(backupCreateButtons[0].disabled, true);
            assert.strictEqual(backupCreateButtons[0].title, "Server online");
            assert.strictEqual(backupCreateButtons[0].dataset.writeGateBlocked, "true");
            """
        )
    )


def test_frontend_write_status_view_exposes_shared_runtime_guards() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const listeners = {};
            const doc = {
                getElementById: () => null,
                querySelectorAll: () => [],
                addEventListener: (name, handler) => { listeners[name] = handler; },
            };
            let gate = { allowed: false, reason: "Server online" };
            const toasts = [];
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            const controller = context.window.MCBEWriteStatusView.createInventoryWriteGateController({
                doc,
                getCurrentWriteGate: () => gate,
                getCurrentPlayerKey: () => "player",
                showToast: (...args) => toasts.push(args),
            });

            assert.strictEqual(controller.guardEditingAction(), true);
            assert.strictEqual(controller.guardWorldWriteAction(), true);
            assert.strictEqual(toasts.length, 2);
            assert.strictEqual(toasts[0][0], "Server online");

            gate = { allowed: true };
            assert.strictEqual(controller.guardEditingAction(), false);
            assert.strictEqual(controller.guardWorldWriteAction(), false);
            """
        )
    )


def test_frontend_write_status_view_fallback_gate_respects_config() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/write_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/write_status_view.js" });

            const view = context.window.MCBEWriteStatusView;
            const blocked = view.fallbackWriteGate({ require_server_offline: true, server_name: "Bedrock" });
            assert.strictEqual(blocked.allowed, false);
            assert.strictEqual(blocked.requires_unknown_server_confirmation, true);
            assert.strictEqual(blocked.server_status.server_name, "Bedrock");

            // MCBE_ALLOW_EDIT_WHILE_ONLINE ist veraltet und darf keinen
            // Override mehr aktivieren.
            const deprecatedOverride = view.fallbackWriteGate({
                require_server_offline: true,
                allow_edit_while_online: true,
            });
            assert.strictEqual(deprecatedOverride.allowed, false);
            assert.strictEqual(deprecatedOverride.override_active, false);
            assert.strictEqual(deprecatedOverride.requires_unknown_server_confirmation, true);

            const confirmable = view.fallbackWriteGate({ require_server_offline: false });
            assert.strictEqual(confirmable.allowed, false);
            assert.strictEqual(confirmable.requires_unknown_server_confirmation, true);

            const confirmableController = view.createWriteGateController({
                appConfig: { require_server_offline: false },
                elements: {},
                getCurrentWriteGate: () => confirmable,
                getCurrentPlayerKey: () => "local_player",
            });
            assert.strictEqual(confirmableController.writeBlocked(), false);
            assert.strictEqual(confirmableController.editingBlocked(), false);
            assert.strictEqual(confirmableController.permissions().canWriteWorld, true);
            """
        )
    )


def test_frontend_write_status_view_keeps_one_active_player_gate_and_blocks_edit_controls() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            const view = context.window.MCBEWriteStatusView;
            const statuses = [];
            const cleared = [];
            const editControl = {
                disabled: false,
                title: "Bearbeiten",
                dataset: {},
                setAttribute(name, value) { this[name] = value; },
                removeAttribute(name) { delete this[name]; },
            };
            let staleReason = "";
            const gate = {
                allowed: false,
                reason: "Server läuft noch. Bitte Server stoppen.",
                server_status: { status: "online" },
            };
            const controller = view.createWriteGateController({
                appConfig: { require_server_offline: true },
                elements: {
                    editControls: [editControl],
                    saveButtons: [],
                    restoreButtons: [],
                    backupCreateButtons: [],
                },
                getCurrentWriteGate: () => gate,
                getCurrentPlayerKey: () => "player",
                getCurrentPlayerStaleReason: () => staleReason,
                setCurrentPlayerStaleReason: value => { staleReason = value; },
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
                clearStatus: key => { cleared.push(key); return true; },
            });

            controller.markLoadedPlayerStale("Nur ansehen: Server online.");
            controller.markLoadedPlayerStale("Darf nicht doppelt erscheinen.");

            assert.strictEqual(statuses.length, 1);
            assert.strictEqual(statuses[0].type, "error");
            assert.strictEqual(statuses[0].options.key, view.PLAYER_WRITE_GATE_NOTICE_KEY);
            assert.strictEqual(statuses[0].options.active, true);
            assert.strictEqual(editControl.disabled, true);
            assert.strictEqual(editControl.title, "Nur ansehen: Server online.");
            assert.strictEqual(editControl["aria-disabled"], "true");

            controller.clearLoadedPlayerStaleState();
            assert.strictEqual(staleReason, "");
            assert.deepStrictEqual(cleared, [view.PLAYER_WRITE_GATE_NOTICE_KEY]);
            """
        )
    )


def test_frontend_write_status_view_guards_slot_mutations_while_player_is_view_only() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const listeners = {};
            const toasts = [];
            const doc = {
                getElementById: () => null,
                querySelectorAll: () => [],
                addEventListener: (name, handler) => { listeners[name] = handler; },
            };
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            const controller = context.window.MCBEWriteStatusView.createInventoryWriteGateController({
                doc,
                appConfig: { require_server_offline: true },
                getCurrentWriteGate: () => ({
                    allowed: false,
                    reason: "Nur ansehen: Server online.",
                    server_status: { status: "online" },
                }),
                getCurrentPlayerKey: () => "player",
                showToast: (...args) => toasts.push(args),
            });

            const event = {
                type: "keydown",
                key: "v",
                ctrlKey: true,
                target: { closest: () => null },
                preventDefault() { this.prevented = true; },
                stopImmediatePropagation() { this.stopped = true; },
            };
            controller.guardEditEvent(event);

            assert.strictEqual(event.prevented, true);
            assert.strictEqual(event.stopped, true);
            assert.strictEqual(toasts.length, 1);
            assert.strictEqual(toasts[0][0], "Nur ansehen: Server online.");

            const copyEvent = {
                type: "keydown",
                key: "c",
                ctrlKey: true,
                target: { closest: () => null },
                preventDefault() { this.prevented = true; },
                stopImmediatePropagation() { this.stopped = true; },
            };
            controller.guardEditEvent(copyEvent);
            assert.strictEqual(copyEvent.prevented, undefined);
            assert.strictEqual(toasts.length, 1);
            assert.deepStrictEqual(Object.keys(listeners).sort(), ["click", "dragstart", "drop", "keydown"]);
            """
        )
    )


def test_frontend_write_status_view_localizes_backend_gate_payload() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const translations = {
                "Server läuft noch. Bitte Server stoppen.": "The server is still running. Please stop the server.",
                "Server erreichbar.": "Server reachable.",
            };
            const context = {
                window: {
                    t: text => translations[text] || text,
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            const localized = context.window.MCBEWriteStatusView.localizeServerStatusPayload({
                server_guard_epoch: 4,
                server_status: { status: "online", message: "Server erreichbar." },
                write_gate: {
                    allowed: false,
                    reason: "Server läuft noch. Bitte Server stoppen.",
                    server_status: { status: "online", message: "Server erreichbar." },
                },
            });

            assert.strictEqual(localized.write_gate.reason, "The server is still running. Please stop the server.");
            assert.strictEqual(localized.server_status.message, "Server reachable.");
            assert.strictEqual(localized.write_gate.server_status.message, "Server reachable.");
            assert.strictEqual(localized.server_guard_epoch, 4);
            """
        )
    )


def test_frontend_write_status_view_orders_responses_by_client_request() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            let revision = 50;
            let gate = {
                allowed: true,
                server_status_revision: 50,
                server_status: { status: "offline", server_status_revision: 50 },
            };
            const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                elements: { serverStatusBadge: {} },
                getCurrentWriteGate: () => gate,
                setCurrentWriteGate: value => { gate = value; },
                getCurrentServerStatusRevision: () => revision,
                setCurrentServerStatusRevision: value => { revision = value; },
            });

            const olderRequest = controller.beginServerStatusRequest();
            const newerRequest = controller.beginServerStatusRequest();
            const newestAccepted = controller.renderServerStatus({
                server_status_revision: 1,
                server_status: { status: "online", server_status_revision: 1 },
                write_gate: {
                    allowed: false,
                    server_status_revision: 1,
                    server_status: { status: "online", server_status_revision: 1 },
                },
            }, { requestOrder: newerRequest });
            const olderAccepted = controller.renderServerStatus({
                server_status_revision: 99,
                server_status: { status: "offline", server_status_revision: 99 },
                write_gate: {
                    allowed: true,
                    server_status_revision: 99,
                    server_status: { status: "offline", server_status_revision: 99 },
                },
            }, { requestOrder: olderRequest });

            assert.strictEqual(newestAccepted, true);
            assert.strictEqual(olderAccepted, false);
            assert.strictEqual(revision, 50);
            assert.strictEqual(gate.allowed, false);
            assert.strictEqual(gate.server_status.status, "online");
            """
        )
    )


def test_frontend_write_status_view_never_discards_stale_authoritative_hard_block() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            let gate = { allowed: true, server_status: { status: "offline" } };
            const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                elements: { serverStatusBadge: {} },
                getCurrentWriteGate: () => gate,
                setCurrentWriteGate: value => { gate = value; },
            });

            const slowWriteRequest = controller.beginServerStatusRequest();
            const newerPollRequest = controller.beginServerStatusRequest();
            assert.strictEqual(controller.renderServerStatus({
                server_status: { status: "offline" },
                write_gate: { allowed: true, server_status: { status: "offline" } },
            }, { requestOrder: newerPollRequest }), true);

            // Der langsame Schreibrequest beobachtet den gestarteten Server erst
            // bei seiner finalen Backend-Prüfung. Dieser harte Block ist trotz
            // älterer Request-ID sicherheitsrelevant und darf nicht verloren gehen.
            assert.strictEqual(controller.renderServerStatus({
                server_status: { status: "online" },
                write_gate: {
                    allowed: false,
                    reason: "Server läuft noch.",
                    server_status: { status: "online" },
                },
            }, { requestOrder: slowWriteRequest, authoritativeBlock: true }), true);
            assert.strictEqual(gate.allowed, false);
            assert.strictEqual(gate.server_status.status, "online");

            // Ein veralteter, nur bestätigbarer Unknown-Zustand darf dagegen
            // keinen neueren harten Block abschwächen.
            assert.strictEqual(controller.renderServerStatus({
                server_status: { status: "unknown" },
                write_gate: {
                    allowed: false,
                    requires_unknown_server_confirmation: true,
                    server_status: { status: "unknown" },
                },
            }, { requestOrder: slowWriteRequest, authoritativeBlock: true }), false);
            assert.strictEqual(gate.server_status.status, "online");

            const nextPollRequest = controller.beginServerStatusRequest();
            assert.strictEqual(controller.renderServerStatus({
                server_status: { status: "offline" },
                write_gate: { allowed: true, server_status: { status: "offline" } },
            }, { requestOrder: nextPollRequest }), true);
            assert.strictEqual(gate.allowed, true);
            """
        )
    )


def test_frontend_write_status_view_uses_generic_stale_reason_after_offline_restart() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            let gate = {
                allowed: true,
                server_guard_token: "old-token",
                server_status: { status: "offline" },
            };
            let currentToken = "old-token";
            let staleReason = "";
            const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                appConfig: { require_server_offline: true },
                elements: { serverStatusBadge: {} },
                getCurrentWriteGate: () => gate,
                setCurrentWriteGate: value => { gate = value; },
                getCurrentServerGuardToken: () => currentToken,
                setCurrentServerGuardToken: value => { currentToken = value; },
                getCurrentPlayerServerGuardToken: () => "old-token",
                getCurrentPlayerStaleReason: () => staleReason,
                setCurrentPlayerStaleReason: value => { staleReason = value; },
                getCurrentPlayerKey: () => "player",
            });

            assert.strictEqual(controller.renderServerStatus({
                server_guard_token: "new-process-token",
                server_status: { status: "offline" },
                write_gate: {
                    allowed: true,
                    server_guard_token: "new-process-token",
                    server_status: { status: "offline" },
                },
            }), true);
            assert.strictEqual(
                staleReason,
                "Nur ansehen: Der Bedrock-Serverzustand hat sich seit dem Laden dieses Spielers geändert. Lade den Spieler neu, um ihn zu bearbeiten.",
            );
            """
        )
    )


def test_frontend_write_status_view_ignores_failure_from_older_request() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            let gate = { allowed: false, server_status: { status: "unknown" } };
            const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                appConfig: { require_server_offline: true },
                elements: { serverStatusBadge: {} },
                getCurrentWriteGate: () => gate,
                setCurrentWriteGate: value => { gate = value; },
            });
            const olderRequest = controller.beginServerStatusRequest();
            const newerRequest = controller.beginServerStatusRequest();

            assert.strictEqual(controller.renderServerStatus({
                server_status: { status: "offline", message: "Server offline" },
                write_gate: {
                    allowed: true,
                    server_status: { status: "offline", message: "Server offline" },
                },
            }, { requestOrder: newerRequest }), true);
            assert.strictEqual(
                controller.renderServerStatusFailure("Netzwerkfehler", { requestOrder: olderRequest }),
                false,
            );
            assert.strictEqual(gate.allowed, true);
            assert.strictEqual(gate.server_status.status, "offline");
            assert.strictEqual(gate.status_check_failed, undefined);
            """
        )
    )


def test_frontend_write_status_view_preserves_last_observation_on_current_failure() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/write_status_view.js", "utf8"), context);

            let gate = {
                allowed: true,
                server_status: { status: "offline", message: "Server offline" },
            };
            const badge = {};
            const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                appConfig: { require_server_offline: true },
                elements: { serverStatusBadge: badge },
                getCurrentWriteGate: () => gate,
                setCurrentWriteGate: value => { gate = value; },
            });

            const requestOrder = controller.beginServerStatusRequest();
            assert.strictEqual(
                controller.renderServerStatusFailure("Netzwerkfehler", { requestOrder }),
                true,
            );
            assert.strictEqual(gate.server_status.status, "offline");
            assert.strictEqual(gate.status_check_failed, true);
            assert.strictEqual(gate.status_check_error, "Netzwerkfehler");
            assert.ok(badge.textContent.includes("Prüfung fehlgeschlagen"));
            """
        )
    )


def test_frontend_write_status_failure_does_not_downgrade_online_block() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            let gate = {
                allowed: false,
                reason: "Server läuft noch. Bitte Server stoppen.",
                requires_unknown_server_confirmation: false,
                server_status: { status: "online", message: "Server erreichbar" },
            };
            const badge = {};
            const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                appConfig: { require_server_offline: true },
                elements: { serverStatusBadge: badge },
                getCurrentWriteGate: () => gate,
                setCurrentWriteGate: value => { gate = value; },
            });

            assert.strictEqual(controller.renderServerStatusFailure("Netzwerkfehler"), true);
            assert.strictEqual(gate.server_status.status, "online");
            assert.strictEqual(gate.allowed, false);
            assert.strictEqual(gate.requires_unknown_server_confirmation, false);
            assert.strictEqual(controller.writeBlocked(), true);
            assert.ok(badge.textContent.includes("zuletzt online"));
            assert.ok(badge.textContent.includes("Prüfung fehlgeschlagen"));
            """
        )
    )


def test_frontend_write_status_refresh_renders_json_api_failure() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            (async () => {
                const context = {
                    fetch: async () => ({ ok: false }),
                    window: {},
                };
                vm.runInNewContext(
                    fs.readFileSync("static/write_status_view.js", "utf8"),
                    context,
                    { filename: "static/write_status_view.js" },
                );

                let gate = {
                    allowed: true,
                    server_status: { status: "offline", message: "Server offline" },
                };
                const badge = {};
                const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                    appConfig: { require_server_offline: true },
                    elements: { serverStatusBadge: badge },
                    parseJsonResponse: async () => ({
                        success: false,
                        error: "Statusdienst nicht verfügbar",
                    }),
                    getCurrentWriteGate: () => gate,
                    setCurrentWriteGate: value => { gate = value; },
                });

                assert.strictEqual(await controller.refreshServerStatus(), true);
                assert.strictEqual(gate.server_status.status, "offline");
                assert.strictEqual(gate.status_check_failed, true);
                assert.strictEqual(gate.status_check_error, "Statusdienst nicht verfügbar");
                assert.ok(badge.textContent.includes("Prüfung fehlgeschlagen"));
            })().catch(error => {
                console.error(error);
                process.exitCode = 1;
            });
            """
        )
    )


def test_frontend_write_status_failure_remains_visible_in_read_only_mode() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(
                fs.readFileSync("static/write_status_view.js", "utf8"),
                context,
                { filename: "static/write_status_view.js" },
            );

            let gate = {
                allowed: true,
                server_status: { status: "offline", message: "Server offline" },
            };
            const badge = {};
            const controller = context.window.MCBEWriteStatusView.createWriteGateController({
                appConfig: { read_only: true, require_server_offline: false },
                elements: { serverStatusBadge: badge },
                getCurrentWriteGate: () => gate,
                setCurrentWriteGate: value => { gate = value; },
            });

            assert.strictEqual(controller.renderServerStatusFailure("Netzwerkfehler"), true);
            assert.ok(badge.textContent.includes("Prüfung fehlgeschlagen"));
            assert.ok(badge.className.includes("blocked"));
            assert.strictEqual(controller.permissions().canWriteWorld, false);
            """
        )
    )


def test_frontend_permission_model_mirrors_backend_policy() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/write_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/write_status_view.js" });

            const view = context.window.MCBEWriteStatusView;

            // Read-Only-Modus sperrt alles.
            const readOnly = view.permissionModel({
                gate: { allowed: false, reason: "Read-Only-Modus aktiv", read_only: true },
                appConfig: { read_only: true },
            });
            assert.strictEqual(readOnly.readOnly, true);
            assert.strictEqual(readOnly.canWriteWorld, false);
            assert.strictEqual(readOnly.canWriteAppState, false);
            assert.strictEqual(readOnly.canExport, false);
            assert.strictEqual(readOnly.canImportPreview, false);
            assert.strictEqual(readOnly.canRescanIcons, false);
            assert.ok(readOnly.reason.includes("Read-Only"));

            // Server online (Gate zu, aber kein Read-Only): nur world_write gesperrt,
            // app_write-Aktionen (Export, Icons, Import-Vorschau) bleiben erlaubt.
            const gateBlocked = view.permissionModel({
                gate: { allowed: false, reason: "Server online" },
                appConfig: {},
            });
            assert.strictEqual(gateBlocked.readOnly, false);
            assert.strictEqual(gateBlocked.canWriteWorld, false);
            assert.strictEqual(gateBlocked.canWriteAppState, true);
            assert.strictEqual(gateBlocked.canExport, true);
            assert.strictEqual(gateBlocked.canImportPreview, true);
            assert.strictEqual(gateBlocked.canRescanIcons, true);
            assert.strictEqual(gateBlocked.reason, "Server online");

            // Alles offen.
            const open = view.permissionModel({ gate: { allowed: true }, appConfig: {} });
            assert.strictEqual(open.readOnly, false);
            assert.strictEqual(open.canWriteWorld, true);
            assert.strictEqual(open.canWriteAppState, true);
            assert.strictEqual(open.reason, "");
            """
        )
    )


def test_frontend_write_gate_controller_exposes_permissions() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/write_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/write_status_view.js" });

            const view = context.window.MCBEWriteStatusView;

            const readOnlyController = view.createWriteGateController({
                appConfig: { read_only: true },
                elements: {},
            });
            const readOnlyPermissions = readOnlyController.permissions();
            assert.strictEqual(readOnlyPermissions.readOnly, true);
            assert.strictEqual(readOnlyPermissions.canWriteWorld, false);
            assert.strictEqual(readOnlyPermissions.canRescanIcons, false);
            assert.strictEqual(readOnlyController.writeBlocked(), true);

            const openController = view.createWriteGateController({
                appConfig: {},
                elements: {},
                getCurrentWriteGate: () => ({ allowed: true }),
            });
            const openPermissions = openController.permissions();
            assert.strictEqual(openPermissions.readOnly, false);
            assert.strictEqual(openPermissions.canWriteWorld, true);
            assert.strictEqual(openPermissions.canExport, true);
            """
        )
    )
